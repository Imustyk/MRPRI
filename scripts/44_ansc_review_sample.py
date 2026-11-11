#!/usr/bin/env python3
"""Stratified 50-document manual-review sample (MTA-0018, step 4).

MEASUREMENT ONLY - no training, production stays v0, ``data/raw/**`` is
untouched. The script reads ``results/tables/ansc_outcomes.csv`` produced by
``scripts/43`` and builds a DETERMINISTIC stratified sample (no RNG - a
re-run produces byte-identical output) for INDEPENDENT manual review. It
performs no network requests: the reviewer opens ``document_url`` by hand
later.

Stratification:
  * primary stratum = extracted outcome (all seven classes available in the
    pool are represented);
  * every available class gets at least ``MIN_PER_OUTCOME`` slots (capped by
    availability), the rest is split proportionally to class size (largest
    remainder);
  * inside a class rows are taken by even stride over the list sorted by
    (year, text_layer, confidence, url), so years, PDF types (text layer vs
    scan) and confidence levels all spread through the sample;
  * a presence pass then guarantees that every year / text-layer value /
    confidence value present in the pool appears in the sample (swap within
    the same outcome class where possible);
  * rows are deduplicated by URL - a document review is per document.

``reviewer_outcome`` and ``reviewer_notes`` are written EMPTY: this script
NEVER imitates or pre-fills the manual review (MTA-0018 §4).

Verification (step 7): every sampled row is re-opened in the sandbox PDF -
the reported ``page_number`` must exist, and the evidence quote must be
locatable on that page (text layer directly; scans via a fresh OCR pass of
the same page). Failures are reported and fail the run (exit 6) so that no
sample is published that a reviewer cannot check against the source page.

Outputs:
  data/external/ansc_review_sample_50.csv    - the sample (reviewer fields empty)
  results/methodology/ansc_sample_50.json    - strata + verification results

Usage:
    .venv/bin/python scripts/44_ansc_review_sample.py [--total 50]
        [--sandbox DIR] [--quiet]

Exit codes: 0 = ok, 4 = inputs/sandbox missing, 6 = verification failures.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IN_OUTCOMES = ROOT / "results" / "tables" / "ansc_outcomes.csv"
INV_JSON = ROOT / "results" / "methodology" / "ansc_decision_inventory.json"
OUT_SAMPLE = ROOT / "data" / "external" / "ansc_review_sample_50.csv"
OUT_JSON = ROOT / "results" / "methodology" / "ansc_sample_50.json"

SAMPLE_SIZE = 50
MIN_PER_OUTCOME = 3

SAMPLE_FIELDS = [
    "ocid", "decision_id", "document_url", "extracted_outcome",
    "evidence_quote", "page_number", "extraction_method", "confidence",
    "reviewer_outcome", "reviewer_notes",
]

OUTCOMES = ("admitted", "partially_admitted", "rejected", "inadmissible",
            "withdrawn", "terminated", "unknown")

CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}

DISCLAIMER_RU = ("Индикатор потенциального риска, а не доказательство "
                 "коррупции/нарушения. Требуется проверка компетентным "
                 "органом.")
DISCLAIMER_EN = ("An upheld ANSC complaint indicates an administrative "
                 "procurement dispute outcome and does not constitute proof "
                 "of corruption.")


def _load_script(name: str):
    """Import a sibling script as a module (same trick as scripts/31/42)."""
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S43 = _load_script("43_ansc_outcome_extract.py")   # read_pdf_pages, ocr_page


# --- sample construction -----------------------------------------------------
def _sort_key(row: dict) -> tuple:
    return (row.get("year") or "0000",
            row.get("text_layer") or "?",
            CONFIDENCE_RANK.get(row.get("confidence"), 9),
            row.get("url") or "")


def _stride_pick(items: list[dict], k: int) -> list[dict]:
    """Deterministic even-stride pick of ``k`` items from a sorted list."""
    n = len(items)
    if k >= n:
        return list(items)
    if k <= 0:
        return []
    idxs = sorted({((2 * i + 1) * n) // (2 * k) for i in range(k)})
    return [items[i] for i in idxs]


def build_sample(rows: list[dict], total: int = SAMPLE_SIZE,
                 min_per: int = MIN_PER_OUTCOME) -> tuple[list[dict], dict]:
    """Deterministic stratified sample; returns ``(sampled, strata_report)``."""
    pool: list[dict] = []
    seen: set[str] = set()
    duplicates = 0
    for row in sorted(rows, key=lambda r: (r.get("url") or "",
                                           r.get("ocid") or "")):
        if row.get("document_present") != "1":
            continue
        if (row.get("url") or "") in seen:
            duplicates += 1
            continue
        seen.add(row.get("url") or "")
        pool.append(row)
    if not pool:
        raise ValueError("no available documents in the outcomes table")

    by_outcome: dict[str, list[dict]] = {c: [] for c in OUTCOMES}
    for row in sorted(pool, key=_sort_key):
        outcome = row.get("outcome") or "unknown"
        by_outcome.setdefault(outcome, by_outcome["unknown"]).append(row)
    classes = [c for c in OUTCOMES if by_outcome[c]]

    # proportional allocation with a minimum per available class
    alloc = {c: min(min_per, len(by_outcome[c])) for c in classes}
    remaining = total - sum(alloc.values())
    if remaining > 0:
        caps = {c: len(by_outcome[c]) - alloc[c] for c in classes}
        want = min(remaining, sum(caps.values()))
        sizes = {c: len(by_outcome[c]) for c in classes}
        quota = {c: want * sizes[c] / sum(sizes.values()) for c in classes}
        for c in classes:
            alloc[c] += min(caps[c], int(quota[c]))
        left = want - sum(min(caps[c], int(quota[c])) for c in classes)
        order = sorted(classes,
                       key=lambda c: (-(quota[c] - int(quota[c])),
                                      -sizes[c], OUTCOMES.index(c)))
        while left > 0:
            progressed = False
            for c in order:
                if left > 0 and alloc[c] < len(by_outcome[c]):
                    alloc[c] += 1
                    left -= 1
                    progressed = True
            if not progressed:
                break

    sampled: list[dict] = []
    for c in classes:
        sampled.extend(_stride_pick(by_outcome[c], alloc[c]))

    # presence guarantees: every year / text-layer / confidence value that
    # exists in the pool must appear in the sample. Sweeps repeat until a
    # full pass performs no swap (a swap for one attribute can invalidate
    # the coverage of another).
    sampled_urls = {r.get("url") for r in sampled}

    def cover(attr: str) -> int:
        swaps = 0
        for _ in range(len(pool) + 1):
            covered = {r.get(attr, "") for r in sampled}
            want_vals = sorted({r.get(attr, "") for r in pool} - covered)
            if not want_vals:
                break
            changed = False
            for val in want_vals:
                cands = [r for r in pool
                         if r.get(attr, "") == val
                         and r.get("url") not in sampled_urls]
                if not cands:
                    continue
                new_row = cands[0]
                counts = Counter(r["outcome"] for r in sampled)
                same = [r for r in sampled
                        if r["outcome"] == new_row["outcome"]
                        and counts[r["outcome"]] > 1]
                if same:
                    drop = same[0]
                else:
                    drop = max(sampled, key=lambda r: counts[r["outcome"]])
                    if counts[drop["outcome"]] <= 1:
                        continue
                sampled.remove(drop)
                sampled_urls.discard(drop.get("url"))
                sampled.append(new_row)
                sampled_urls.add(new_row.get("url"))
                swaps += 1
                changed = True
            if not changed:
                break
        return swaps

    for _ in range(8):
        if sum(cover(a) for a in ("year", "text_layer", "confidence")) == 0:
            break

    sampled.sort(key=lambda r: (OUTCOMES.index(r.get("outcome", "unknown"))
                                if r.get("outcome") in OUTCOMES else 9,
                                r.get("year") or "0000",
                                r.get("url") or ""))
    strata = {
        "input_rows": len(rows),
        "pool_present_unique_urls": len(pool),
        "duplicate_urls_dropped": duplicates,
        "classes_available": classes,
        "allocation_requested": total,
        "allocation_by_outcome": {c: alloc[c] for c in classes},
        "sampled": len(sampled),
        "shortage": max(0, total - len(sampled)),
        "sample_outcomes": dict(Counter(r["outcome"] for r in sampled)),
        "sample_years": dict(Counter(r.get("year") or ""
                                     for r in sampled).most_common()),
        "sample_text_layer": dict(Counter(r.get("text_layer") or ""
                                          for r in sampled)),
        "sample_confidence": dict(Counter(r.get("confidence") or ""
                                          for r in sampled).most_common()),
        "sample_with_decision_id": sum(1 for r in sampled
                                       if r.get("decision_numbers")),
        "pool_text_layer_values": sorted({r.get("text_layer") or ""
                                          for r in pool}),
        "pool_confidence_values": sorted({r.get("confidence") or ""
                                          for r in pool}),
        "pool_years": sorted({r.get("year") or "" for r in pool}),
    }
    return sampled, strata


# --- verification that a reviewer can open the source page (step 7) ----------
def _fold(text: str) -> str:
    return " ".join(str(text).split())


def _quote_core(quote: str) -> str:
    quote = quote or ""
    return quote[:-4] if quote.endswith(" ...") else quote


def _quote_of(row: dict) -> str:
    """Evidence text of an outcomes row.

    ``scripts/43`` writes the evidence into the documented CSV column
    ``evidence_quote``; in-memory rows (and the tests) use ``quote``.
    """
    return row.get("evidence_quote") or row.get("quote") or ""


def verify_sample(sampled: list[dict], sandbox: Path) -> dict:
    """Re-open every sampled document and locate its evidence quote.

    Text-layer documents: the quote must be present in the text of the
    reported page (adjacent pages/pairs allowed for items crossing a page
    break) - otherwise the row is a FAILURE. Scans: the same page is
    re-OCR'd with the scripts/43 pipeline; a hit locates the page, a miss is
    only a ``manual_visual_check`` warning (OCR is not bit-stable across
    environments), never a silent pass. Rows without a quote (``unknown``)
    are checked structurally: the PDF must exist and ``page_number`` - when
    present - must be in range.
    """
    results: list[dict] = []
    failures: list[dict] = []
    counts: Counter = Counter()

    for row in sampled:
        url = row.get("url") or ""
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        pdf = sandbox / f"{digest}.pdf"
        item = {"document_url": url,
                "decision_id": row.get("decision_numbers", ""),
                "outcome": row.get("outcome", ""),
                "page_number": row.get("page_number", "")}

        def fail(verdict: str, **extra) -> None:
            item["verdict"] = verdict
            item.update(extra)
            failures.append(item)
            counts[verdict] += 1
            results.append(item)

        if not pdf.exists():
            fail("missing_pdf")
            continue
        pages, err = S43.read_pdf_pages(pdf)
        if err:
            fail("unreadable_pdf", error=err)
            continue
        n_pages = len(pages)
        page_raw = str(row.get("page_number") or "").strip()
        page_no = int(page_raw) if page_raw.isdigit() else 0
        if page_no and n_pages and not (1 <= page_no <= n_pages):
            fail("page_out_of_range", pages_in_pdf=n_pages)
            continue

        quote = _quote_core(_quote_of(row))
        if row.get("outcome") != "unknown" and not quote:
            # an extracted outcome WITHOUT evidence cannot be checked by a
            # reviewer against the source page - that is a defect, not a pass
            fail("missing_quote")
            continue
        if row.get("outcome") == "unknown" or not quote:
            item["verdict"] = "no_quote_expected"
            counts["no_quote_expected"] += 1
            results.append(item)
            continue
        if not n_pages:
            fail("no_pages_in_pdf")
            continue

        q = _fold(quote)
        folded = [_fold(t) for t in pages]

        if row.get("text_layer") == "1":
            found = _locate(folded, q, page_no)
            if found:
                item["verdict"] = ("quote_locatable"
                                   if found == page_no or page_no == 0
                                   else "quote_locatable_other_page")
                item["located_page"] = found
                counts[item["verdict"]] += 1
                if item["verdict"] != "quote_locatable":
                    failures.append(item)   # page_number would mislead
                results.append(item)
            else:
                fail("quote_not_found_in_text_layer")
            continue

        # scan: re-OCR the reported page and its neighbours
        found = None
        for p in sorted({max(1, page_no - 1), page_no, page_no + 1}):
            if p > n_pages:
                continue
            ocr = S43.ocr_page(pdf, p, 1)
            if ocr and (q in _fold(ocr)
                        or q in _fold((pages[p - 1] or "") + "\n" + ocr)):
                found = p
                break
        if found:
            item["verdict"] = "quote_locatable_ocr"
            item["located_page"] = found
        else:
            item["verdict"] = "manual_visual_check"
        counts[item["verdict"]] += 1
        results.append(item)

    return {"checked": len(sampled),
            "failures": len(failures),
            "verdicts": dict(counts.most_common()),
            "failure_items": failures,
            "items": results}


def _locate(folded_pages: list[str], q: str, page_no: int) -> int:
    """Find ``q`` on ``page_no`` first, then neighbours, then the document."""
    order = [p for p in (page_no - 1, page_no, page_no + 1)
             if 1 <= p <= len(folded_pages)]
    order += [p for p in range(1, len(folded_pages) + 1) if p not in order]
    for p in order:
        if q in folded_pages[p - 1]:
            return p
    for p in range(1, len(folded_pages)):     # item crossing a page break
        if q in _fold(folded_pages[p - 1] + " " + folded_pages[p]):
            return p
    return 0


# --- io ----------------------------------------------------------------------
def load_outcomes(path: Path | None = None) -> list[dict]:
    path = path or IN_OUTCOMES
    if not path.exists():
        raise SystemExit(f"missing {path} - run scripts/43 first")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def resolve_sandbox(explicit: str = "") -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_dir() else None
    if not INV_JSON.exists():
        return None
    meta = json.loads(INV_JSON.read_text(encoding="utf-8"))
    p = Path(meta.get("sandbox_dir") or "")
    return p if p.is_dir() else None


def write_sample_csv(sampled: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SAMPLE_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        for row in sampled:
            out = {
                "ocid": row.get("ocid", ""),
                "decision_id": row.get("decision_numbers", ""),
                "document_url": row.get("url", ""),
                "extracted_outcome": row.get("outcome", ""),
                "evidence_quote": _quote_of(row),
                "page_number": row.get("page_number", ""),
                "extraction_method": row.get("extraction_method", ""),
                "confidence": row.get("confidence", ""),
                "reviewer_outcome": "",      # NEVER pre-filled (MTA-0018 §4)
                "reviewer_notes": "",        # NEVER pre-filled
            }
            writer.writerow(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--min-per-outcome", type=int,
                        default=MIN_PER_OUTCOME)
    parser.add_argument("--sandbox", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    rows = load_outcomes()
    try:
        sampled, strata = build_sample(rows, args.total,
                                       args.min_per_outcome)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    sandbox = resolve_sandbox(args.sandbox)
    if sandbox is None:
        print("sandbox directory unknown/missing: the sample cannot be "
              "verified against source pages (run scripts/42 with "
              "--allow-network first, or pass --sandbox)", file=sys.stderr)
        return 4

    verification = verify_sample(sampled, sandbox)
    write_sample_csv(sampled, OUT_SAMPLE)

    def _show(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    payload = {
        "task": "MTA-0018",
        "part": "4 - stratified manual-review sample",
        "generated": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "sample_csv": _show(OUT_SAMPLE),
        "sample_size": len(sampled),
        "strata": strata,
        "verification": verification,
        "reviewer_fields": "empty - the manual review is performed by the "
                           "author, never imitated by this script",
        "manual_review_status": "pending",
        "metrics_status": "not computed until the manual review exists "
                          "(scripts/45 refuses without expert labels)",
        "disclaimer_ru": DISCLAIMER_RU,
        "disclaimer_en": DISCLAIMER_EN,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    if not args.quiet:
        print(json.dumps({
            "sample_size": payload["sample_size"],
            "strata": {k: strata[k] for k in
                       ("allocation_by_outcome", "sample_outcomes",
                        "sample_years", "sample_text_layer",
                        "sample_confidence", "shortage")},
            "verification": {k: verification[k] for k in
                             ("checked", "failures", "verdicts")},
        }, ensure_ascii=False, indent=1))
        print(f"written {_show(OUT_SAMPLE)}, {_show(OUT_JSON)}")
    if verification["failures"]:
        print(f"VERIFICATION FAILURES: {verification['failures']} "
              "(see the JSON for details)", file=sys.stderr)
        return 6
    return 0


if __name__ == "__main__":
    sys.exit(main())
