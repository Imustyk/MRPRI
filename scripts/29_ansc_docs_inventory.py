#!/usr/bin/env python3
"""ANSC document inventory inside the raw MTender OCDS (MTA-0012, part A).

Local-only reconnaissance (no network, no training, no new cycle): every
document referenced by the raw OCDS packages under ``data/raw/ocds_packages``
(read-only) is inventoried at all four OCDS levels (tender, award, contract,
planning), then searched for ANSC candidates with a fixed keyword list
(ro/ru, case- and diacritic-insensitive). The question is whether a weak
independent label ``procedure contested, complaint upheld`` can be built from
documents the raw OCDS already points to - a feasibility study, not a label
for the model (production stays v0, budget stays 6 of 10).

Outputs:
  results/methodology/ansc_docs_inventory.json   - full summary
  results/tables/ansc_docs_inventory.csv         - document table (all docs)
  results/tables/ansc_candidates.csv             - keyword-matched candidates

Usage:
    .venv/bin/python scripts/29_ansc_docs_inventory.py [--limit N] [--quiet]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mtender.ocds import merge_compiled_releases  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "ocds_packages"
OUT_JSON = ROOT / "results" / "methodology" / "ansc_docs_inventory.json"
OUT_DOCS = ROOT / "results" / "tables" / "ansc_docs_inventory.csv"
OUT_CAND = ROOT / "results" / "tables" / "ansc_candidates.csv"

# Author's fixed keyword list (MTA-0012), matched case-insensitively after
# diacritic stripping so "contestați" also matches "contestaţi"/"contestație".
KEYWORDS = [
    "ansc",
    "autoritatea nationala pentru solutionarea contestatiilor",
    "agentia nationala pentru solutionarea contestatiilor",
    "contestati",
    "decizi",
    "03d-",
    "hotarare ansc",
    "жалоб",
    "решение анск",
]
YEARS = [str(y) for y in range(2018, 2025)]
DOC_CSV_FIELDS = [
    "ocid", "year", "level", "documentType", "title",
    "description", "url", "date", "format",
]
CAND_CSV_FIELDS = DOC_CSV_FIELDS + ["keywords", "strong"]
STRUCT_FIELDS = ("complaints", "enquiries", "amendments")
# The author's known ANSC pair, probed in the candidates as a parser sanity
# signal (letter 01-02-01/05/933/26 of 07.04.2026, decision 03D-159-26).
PROBE_STRINGS = ("03d-159-26", "md-1771250199749", "md-1772439133346")
# Beyond the author's list the OCDS documentType ``complaints`` is a
# structural ANSC signal; "decizi" is deliberately NOT strong (it matches
# routine award decisions - "decizia de atribuire" - by the thousand).
WEAK_KEYWORDS = ("decizi",)
STRONG_KEYWORDS = [kw for kw in KEYWORDS if kw not in WEAK_KEYWORDS]
DOCTYPE_COMPLAINT = "doctype:complaints"


def strip_diacritics(text: str) -> str:
    """Lowercase and remove combining marks (``contestaţi`` ~ ``contestație``)."""
    norm = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


def procedure_year(compiled: dict) -> str:
    """Year bucket of the procedure, first non-empty of the usual dates."""
    tender = compiled.get("tender") or {}
    contracts = compiled.get("contracts") or []
    candidates = [
        (tender.get("datePublished") or ""),
        ((tender.get("period") or {}).get("startDate") or ""),
        ((contracts[0].get("datePublished") or "") if contracts else ""),
        (compiled.get("date") or ""),
    ]
    for value in candidates:
        m = re.match(r"^(\d{4})", str(value))
        if m:
            return m.group(1)
    return "unknown"


def iter_documents(compiled: dict):
    """Yield ``(level, document)`` for every document in the package."""
    for level, container in (
        ("tender", compiled.get("tender")),
        ("planning", compiled.get("planning")),
    ):
        if isinstance(container, dict):
            for doc in container.get("documents") or []:
                if isinstance(doc, dict):
                    yield level, doc
    for kind in ("awards", "contracts"):
        for item in compiled.get(kind) or []:
            if isinstance(item, dict):
                for doc in item.get("documents") or []:
                    if isinstance(doc, dict):
                        yield kind[:-1], doc


def matched_keywords(text: str) -> list[str]:
    haystack = strip_diacritics(text)
    return [kw for kw in KEYWORDS if kw in haystack]


def url_host(url: str) -> str:
    try:
        return (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def _year_bucket(counter: Counter, year: str) -> None:
    counter[year if year in YEARS else "other"] += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="scan only the first N packages (development)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    t0 = time.time()
    files = sorted(RAW_DIR.glob("*.json.gz"))
    if args.limit:
        files = files[: args.limit]

    docs_total = 0
    packages_with_docs = 0
    by_level: Counter = Counter()
    type_counts: Counter = Counter()
    title_counts: Counter = Counter()
    host_counts: Counter = Counter()
    proc_years: Counter = Counter()
    struct_present: dict = {f: Counter() for f in STRUCT_FIELDS}
    kw_docs: dict = {kw: 0 for kw in KEYWORDS}
    kw_procs: dict = {kw: set() for kw in KEYWORDS}
    kw_years: dict = {kw: Counter() for kw in KEYWORDS}
    doctype_complaint_docs = 0
    doctype_complaint_procs: set = set()
    doctype_complaint_years: Counter = Counter()
    strong_years: Counter = Counter()
    strong_procs: set = set()
    # ocid -> year, for honest PROCEDURE-level per-year tables
    cand_proc_year: dict = {}
    strong_proc_year: dict = {}
    comp_proc_year: dict = {}
    cand_years: Counter = Counter()
    cand_procs: set = set()
    candidates: list[dict] = []
    probes: dict = {p: [] for p in PROBE_STRINGS}

    with open(OUT_DOCS, "w", newline="", encoding="utf-8") as fh_docs, \
            open(OUT_CAND, "w", newline="", encoding="utf-8") as fh_cand:
        w_docs = csv.DictWriter(fh_docs, fieldnames=DOC_CSV_FIELDS)
        w_cand = csv.DictWriter(fh_cand, fieldnames=CAND_CSV_FIELDS)
        w_docs.writeheader()
        w_cand.writeheader()

        for i, path in enumerate(files):
            try:
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    package = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            compiled = merge_compiled_releases(package)
            if not compiled:
                continue
            ocid = compiled.get("ocid") or path.name[:-8]
            year = procedure_year(compiled)
            _year_bucket(proc_years, year)

            for field in STRUCT_FIELDS:
                for level, container in (
                    ("tender", compiled.get("tender")),
                    ("planning", compiled.get("planning")),
                ):
                    if isinstance(container, dict) and container.get(field):
                        struct_present[field][level] += 1
                for kind in ("awards", "contracts"):
                    for item in compiled.get(kind) or []:
                        if isinstance(item, dict) and item.get(field):
                            struct_present[field][kind[:-1]] += 1

            package_docs = 0
            for level, doc in iter_documents(compiled):
                package_docs += 1
                docs_total += 1
                title = str(doc.get("title") or "")[:300]
                desc = str(doc.get("description") or "")[:300]
                url = str(doc.get("url") or "")
                row = {
                    "ocid": ocid,
                    "year": year,
                    "level": level,
                    "documentType": str(doc.get("documentType") or ""),
                    "title": title,
                    "description": desc,
                    "url": url,
                    "date": str(doc.get("date") or ""),
                    "format": str(doc.get("format") or ""),
                }
                w_docs.writerow(row)
                by_level[level] += 1
                type_counts[row["documentType"]] += 1
                if title:
                    title_counts[title] += 1
                host = url_host(url)
                if host:
                    host_counts[host] += 1

                hits = matched_keywords(f"{title} {desc} {url}")
                is_complaint_type = (row["documentType"] == "complaints")
                if hits or is_complaint_type:
                    tags = list(hits)
                    if is_complaint_type:
                        tags.append(DOCTYPE_COMPLAINT)
                        doctype_complaint_docs += 1
                        doctype_complaint_procs.add(ocid)
                        _year_bucket(doctype_complaint_years, year)
                    is_strong = any(kw in STRONG_KEYWORDS for kw in hits) \
                        or is_complaint_type
                    if is_strong:
                        strong_procs.add(ocid)
                        strong_proc_year[ocid] = year
                        _year_bucket(strong_years, year)
                    if is_complaint_type:
                        comp_proc_year[ocid] = year
                    cand_proc_year[ocid] = year
                    cand_procs.add(ocid)
                    _year_bucket(cand_years, year)
                    crow = dict(row, keywords="; ".join(tags),
                                strong="1" if is_strong else "0")
                    w_cand.writerow(crow)
                    candidates.append(crow)
                    blob = strip_diacritics(f"{title} {desc} {url}")
                    for probe in PROBE_STRINGS:
                        if probe in blob:
                            probes[probe].append(ocid)
                    for kw in hits:
                        kw_docs[kw] += 1
                        kw_procs[kw].add(ocid)
                        _year_bucket(kw_years[kw], year)
            if package_docs:
                packages_with_docs += 1
            if not args.quiet and (i + 1) % 20000 == 0:
                print(f"  scanned {i + 1}/{len(files)} packages, "
                      f"{docs_total} documents", flush=True)

    summary = {
        "task": "MTA-0012",
        "part": "A - local inventory over raw OCDS packages",
        "raw_dir": str(RAW_DIR.relative_to(ROOT)),
        "packages_total": len(files),
        "packages_with_documents": packages_with_docs,
        "documents_total": docs_total,
        "documents_by_level": dict(by_level.most_common()),
        "document_type_counts": dict(type_counts.most_common(25)),
        "top_titles": [[t, c] for t, c in title_counts.most_common(25)],
        "url_hosts": dict(host_counts.most_common()),
        "procedure_years": {k: proc_years[k] for k in YEARS
                            if k in proc_years},
        "procedure_years_other": proc_years.get("other", 0),
        "procedure_years_unknown": proc_years.get("unknown", 0),
        "structure_fields_present": {
            f: dict(struct_present[f]) for f in STRUCT_FIELDS},
        "keywords": {
            kw: {
                "documents": kw_docs[kw],
                "procedures": len(kw_procs[kw]),
                "by_year": {y: kw_years[kw].get(y, 0) for y in YEARS},
            } for kw in KEYWORDS},
        "candidates_documents_total": len(candidates),
        "candidates_procedures_total": len(cand_procs),
        "candidates_documents_by_year": {y: cand_years.get(y, 0)
                                         for y in YEARS},
        "candidates_procedures_by_year": {
            y: sum(1 for v in cand_proc_year.values() if v == y)
            for y in YEARS},
        "candidates_by_year_other": cand_years.get("other", 0)
        + cand_years.get("unknown", 0),
        "candidates_strong_procedures_total": len(strong_procs),
        "candidates_strong_documents_by_year": {y: strong_years.get(y, 0)
                                                for y in YEARS},
        "candidates_strong_procedures_by_year": {
            y: sum(1 for v in strong_proc_year.values() if v == y)
            for y in YEARS},
        "complaint_doctype_documents": doctype_complaint_docs,
        "complaint_doctype_procedures": len(doctype_complaint_procs),
        "complaint_doctype_documents_by_year": {
            y: doctype_complaint_years.get(y, 0) for y in YEARS},
        "complaint_doctype_procedures_by_year": {
            y: sum(1 for v in comp_proc_year.values() if v == y)
            for y in YEARS},
        "known_pair_probe": {p: sorted(set(v)) for p, v in probes.items()},
        "outputs": {
            "documents_csv": str(OUT_DOCS.relative_to(ROOT)),
            "candidates_csv": str(OUT_CAND.relative_to(ROOT)),
        },
        "disclaimer": ("Индикатор потенциального риска, а не доказательство "
                       "коррупции/нарушения. Требуется проверка компетентным "
                       "органом."),
        "seconds": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "packages_total", "documents_total", "documents_by_level",
        "candidates_documents_total", "candidates_procedures_total",
        "candidates_procedures_by_year", "candidates_strong_procedures_total",
        "seconds")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
