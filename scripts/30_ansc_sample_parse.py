#!/usr/bin/env python3
"""ANSC sample download + PDF parse (MTA-0012, part B).

Part A (``scripts/29``) found ANSC candidate documents referenced by the raw
OCDS; this script takes at most ``--max-docs`` of them (stratified by year,
strong candidates preferred), downloads them from ``storage.mtender.gov.md``
AND NOWHERE ELSE, sequentially, with at least ``--sleep`` seconds between
requests and a User-Agent that states the academic purpose. No circumvention:
on HTTP 403/429, or on a redirect leaving the storage host (an anti-automation
block), the script stops immediately and records the reason - it never tries
to retry, rotate or bypass.

Security posture: downloaded files are UNTRUSTED.
* every document gets its own fresh, empty folder OUTSIDE the repository
  (the script refuses a ``--dest`` inside the git worktree);
* nothing downloaded is ever executed; text extraction uses ``pypdf`` only;
* this script is meant to be run with ``python -I`` (isolated mode);
* the repository artefacts store ONLY parsed numbers (decision / complaint
  numbers, dates, procurement ids, outcome) - never full texts, so no
  personal data of individuals is persisted in the repo.

The script refuses to run at all without the explicit ``--allow-network``
flag (regression-tested in ``tests/test_ansc_parser.py``).

Outcomes (``admis`` / ``respins`` / ``admis_partial``) are HEURISTIC regex
readouts of Romanian decision text, useful as a feasibility signal only -
"жалоба удовлетворена" is not a proven violation (see the report).

Usage:
    .venv/bin/python -I scripts/30_ansc_sample_parse.py \
        --candidates results/tables/ansc_candidates.csv \
        [--max-docs 50] [--sleep 2] --allow-network \
        [--dest DIR] [--out results/methodology/ansc_sample_parse.json]

Exit codes: 0 = ok, 2 = missing --allow-network, 3 = blocked by the server.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ROOT / "results" / "tables" / "ansc_candidates.csv"
DEFAULT_OUT = ROOT / "results" / "methodology" / "ansc_sample_parse.json"
STORAGE_HOST = "storage.mtender.gov.md"
USER_AGENT = ("MoldovaProcurementThesis/1.0 (student research, educational "
              "purpose; single-pass sample for a diploma thesis; "
              "contact via github.com/Imustyk)")
MIN_TEXT_CHARS = 50          # fewer letters than this => "требует OCR"
STRONG_PREFERENCE = 1000     # large per-row weight for strong candidates

# --- regexes (pure functions; tested on synthetic strings only) -------------
RE_DECISION = re.compile(r"\b0[0-9]D-\d{1,5}-\d{2}\b", re.IGNORECASE)
RE_REGISTER = re.compile(r"\b0\d-\d{2}-\d{2}/\d{2}/\d{2,5}/\d{2}\b")
RE_COMPLAINT = re.compile(r"\b\d{1,5}[a-zа-я]?/\d{2}\.\d{2}\.(?:19|20)\d{2}\b",
                          re.IGNORECASE)
RE_DATE = re.compile(r"\b\d{2}\.\d{2}\.(?:19|20)\d{2}\b")
RE_PROCUREMENT = re.compile(r"\bMD-\d{9,16}\b", re.IGNORECASE)
RE_PARTIAL = re.compile(
    r"(?:admis|admit)\w*[^.]{0,40}partial|partial[^.]{0,40}(?:admis|admit)\w*")
RE_ADMIS = re.compile(r"\badmis\w*|\badmit\w*", re.IGNORECASE)
RE_RESPINS = re.compile(r"\bresping\w*|\brespins\w*", re.IGNORECASE)


def parse_decision_number(text: str) -> list[str]:
    """ANSC decision numbers like ``03D-159-26``."""
    return sorted({m.upper() for m in RE_DECISION.findall(text)})


def parse_register_numbers(text: str) -> list[str]:
    """ANSC incoming-letter register numbers like ``01-02-01/05/933/26``."""
    return sorted(set(RE_REGISTER.findall(text)))


def parse_complaint_numbers(text: str) -> list[str]:
    """Complaint registration numbers like ``1234b/05.04.2026``."""
    return sorted({m for m in RE_COMPLAINT.findall(text)})


def parse_dates(text: str) -> list[str]:
    return sorted(set(RE_DATE.findall(text)))


def parse_procurement_ids(text: str) -> list[str]:
    """Tender ids like ``MD-1771250199749``."""
    return sorted({m.upper() for m in RE_PROCUREMENT.findall(text)})


def _deaccent(text: str) -> str:
    """Lowercase and strip combining marks (``parţial`` -> ``partial``)."""
    import unicodedata

    norm = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


def parse_outcome(text: str) -> str | None:
    """Heuristic outcome of a Romanian decision: admis / respins / partial."""
    flat = _deaccent(text)
    if RE_PARTIAL.search(flat):
        return "admis_partial"
    if RE_ADMIS.search(flat):
        return "admis"
    if RE_RESPINS.search(flat):
        return "respins"
    return None


def allocate_stratified(rows: list[dict], max_docs: int) -> list[dict]:
    """Deterministic year-stratified sample; strong candidates win ties.

    Allocation is proportional to the per-year candidate count (largest
    remainder), then rows are taken in (strong desc, year, ocid, url) order
    so the same input always yields the same sample.
    """
    if len(rows) <= max_docs:
        return sorted(rows, key=_row_key)
    years = sorted({r["year"] for r in rows})
    counts = {y: sum(1 for r in rows if r["year"] == y) for y in years}
    total = sum(counts.values())
    quota = {y: max_docs * counts[y] / total for y in years}
    base = {y: int(quota[y]) for y in years}
    remainders = sorted(years, key=lambda y: (-(quota[y] - base[y]), y))
    leftover = max_docs - sum(base.values())
    for y in remainders[:leftover]:
        base[y] += 1
    picked: list[dict] = []
    for y in years:
        group = sorted((r for r in rows if r["year"] == y), key=_row_key)
        picked.extend(group[: base[y]])
    return sorted(picked, key=_row_key)


def _row_key(row: dict) -> tuple:
    return (0 if row.get("strong") == "1" else 1,
            row.get("year", ""), row.get("ocid", ""), row.get("url", ""))


def url_host(url: str) -> str:
    try:
        return (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def extract_text(pdf_bytes: bytes) -> dict:
    """Text of a PDF via pypdf; never executes anything from the file."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = len(reader.pages)
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:            # corrupt page: keep going, count below
            parts.append("")
    text = "\n".join(parts)
    letters = sum(1 for ch in text if ch.isalpha())
    return {"text": text, "pages": pages, "chars": len(text),
            "letters": letters, "needs_ocr": letters < MIN_TEXT_CHARS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default=str(DEFAULT_CANDIDATES))
    parser.add_argument("--max-docs", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=2.0,
                        help="minimum seconds between requests")
    parser.add_argument("--dest", default="",
                        help="sandbox dir OUTSIDE the repo "
                             "(default: $TMPDIR/mtender_ansc_sample_<ts>)")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--allow-network", action="store_true",
                        help="explicit opt-in; without it the script exits 2")
    args = parser.parse_args()

    if not args.allow_network:
        print("refusing to touch the network: pass --allow-network to run "
              "part B (MTA-0012)", file=sys.stderr)
        return 2

    import os
    import tempfile

    import requests

    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_root = Path(args.dest) if args.dest else \
        Path(tempfile.gettempdir()) / f"mtender_ansc_sample_{started}"
    repo_root = ROOT.resolve()
    try:
        dest_root.resolve().relative_to(repo_root)
        print(f"refusing: --dest {dest_root} is inside the repository; "
              "downloaded files must stay outside it", file=sys.stderr)
        return 2
    except ValueError:
        pass
    dest_root.mkdir(parents=True, exist_ok=True)

    with open(args.candidates, newline="", encoding="utf-8") as fh:
        all_rows = list(csv.DictReader(fh))
    rows = [r for r in all_rows if url_host(r.get("url", "")) == STORAGE_HOST]
    skipped_non_storage = len(all_rows) - len(rows)

    sample = allocate_stratified(rows, args.max_docs)
    records: list[dict] = []
    stopped_reason = ""
    n_downloaded = 0
    for idx, row in enumerate(sample):
        if idx:
            time.sleep(max(2.0, args.sleep))
        url = row["url"]
        entry = {"ocid": row["ocid"], "year": row["year"],
                 "level": row["level"], "title": row["title"][:120],
                 "keywords": row.get("keywords", ""),
                 "strong": row.get("strong", "0"), "url": url}
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                                timeout=30)
        except requests.RequestException as exc:
            entry["error"] = f"{type(exc).__name__}"
            records.append(entry)
            stopped_reason = f"network error: {type(exc).__name__}"
            break
        entry["http"] = resp.status_code
        if resp.status_code in (403, 429) or \
                url_host(resp.url) != STORAGE_HOST:
            stopped_reason = (f"blocked: http {resp.status_code}, final host "
                              f"{url_host(resp.url) or '-'}")
            records.append(entry)
            break
        if resp.status_code != 200:
            records.append(entry)
            continue
        n_downloaded += 1
        doc_dir = dest_root / f"doc_{idx + 1:03d}_{row['ocid'][-13:]}"
        doc_dir.mkdir(parents=True, exist_ok=False)
        ctype = resp.headers.get("Content-Type", "")
        entry["content_type"] = ctype
        entry["bytes"] = len(resp.content)
        if "pdf" in ctype.lower() or resp.content[:5] == b"%PDF-":
            pdf_path = doc_dir / "raw.pdf"
            pdf_path.write_bytes(resp.content)
            try:
                extracted = extract_text(resp.content)
                (doc_dir / "extracted.txt").write_text(
                    extracted["text"], encoding="utf-8")
                entry.update({k: v for k, v in extracted.items()
                              if k != "text"})
                text = extracted["text"]
                entry["decision_numbers"] = parse_decision_number(text)
                entry["register_numbers"] = parse_register_numbers(text)
                entry["complaint_numbers"] = parse_complaint_numbers(text)
                entry["dates"] = parse_dates(text)[:5]
                entry["procurement_ids"] = parse_procurement_ids(text)
                entry["outcome"] = parse_outcome(text)
            except Exception as exc:
                entry["pdf_error"] = f"{type(exc).__name__}"
                entry["needs_ocr"] = True
        else:
            (doc_dir / "raw.bin").write_bytes(resp.content)
            entry["needs_ocr"] = True
            entry["pdf_error"] = "not a PDF"
        records.append(entry)

    outcomes = Counter(r.get("outcome") for r in records
                       if r.get("outcome"))
    with_ocr = sum(1 for r in records if r.get("needs_ocr"))
    text_ok = sum(1 for r in records if r.get("chars", 0) >= MIN_TEXT_CHARS)
    summary = {
        "task": "MTA-0012",
        "part": "B - sample download + parse",
        "generated": started,
        "candidates_file": str(Path(args.candidates).resolve()),
        "candidates_rows_storage_host": len(rows),
        "candidates_rows_other_hosts": skipped_non_storage,
        "max_docs": args.max_docs,
        "sleep_seconds": max(2.0, args.sleep),
        "sampled": len(sample),
        "downloaded": n_downloaded,
        "text_extracted": text_ok,
        "needs_ocr": with_ocr,
        "extraction_success_share": round(text_ok / len(sample), 3)
        if sample else None,
        "outcomes": dict(outcomes),
        "stopped_reason": stopped_reason,
        "sandbox_dir": str(dest_root),
        "records": records,
        "disclaimer": ("Индикатор потенциального риска, а не доказательство "
                       "коррупции/нарушения. Требуется проверка компетентным "
                       "органом."),
        "user_agent": USER_AGENT,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "sampled", "downloaded", "text_extracted", "needs_ocr",
        "extraction_success_share", "outcomes", "stopped_reason",
        "sandbox_dir")}, ensure_ascii=False, indent=1))
    return 3 if stopped_reason.startswith("blocked") else 0


if __name__ == "__main__":
    sys.exit(main())
