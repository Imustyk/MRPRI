#!/usr/bin/env python3
"""Blind manual-review package for the 50-document ANSC sample
(MTA-0019, step 2-3).

MEASUREMENT ONLY - no training, production stays v0, ``data/raw/**`` is
untouched. The script never touches the network and NEVER fills a single
``reviewer_*`` cell: the manual review is performed by the author alone.

BLINDNESS CONTRACT: the machine side of the extraction
(``extracted_outcome``, ``extraction_method``, ``confidence``) is NOT
written into the review files - the reviewer must decide the outcome before
seeing what the rule predicted. The prediction stays only in
``data/external/ansc_review_sample_50.csv`` (scripts/44), which is the
machine-side join key used later by scripts/45.

Outputs:
  data/external/ansc_manual_review_50.csv        - all 50 documents
  data/external/ansc_manual_review_pilot10.csv   - deterministic pilot group
  results/methodology/ansc_review_package.json   - coverage artefact

Reference columns (filled by this script): document number, OCID, source
URL, local PDF path, page of the expected resolutory part, evidence quote
(if extracted). Reviewer columns (ALWAYS written empty):

  reviewer_outcome       admitted | partially_admitted | rejected |
                         inadmissible | withdrawn | terminated | unknown
  reviewer_document_type ansc_decision | other_document | uncertain
  reviewer_link_verified confirmed | rejected | uncertain
  reviewer_evidence_page page actually holding the resolutory text
  reviewer_evidence_quote quote actually found on that page
  reviewer_notes         free text (markers: ``mislink:``, ``multiple:``,
                         ``quote page N``, ``quote not found``)

Pilot selection (step 3) uses the machine side ONLY for selection - the
files still contain no prediction:

  * one row per each of the four classified outcomes present in the sample
    (admitted as text-layer AND as scan, partially_admitted, rejected,
    withdrawn preferring the ``low``-confidence row);
  * five ``unknown`` rows: three text-layer (at least one carrying a
    decision number) and two scans;
  * rows are chosen in (year, url) order - fully deterministic, and the
    final pilot is sorted chronologically.

Usage:
    .venv/bin/python scripts/46_ansc_review_package.py [build|validate]
        [--sandbox DIR] [--pilot-size 10] [--quiet]

Exit codes: build: 0 = ok, 4 = inputs/sandbox missing, 6 = source sample
broken (reviewer cells not empty / wrong columns). validate: 0 = review
complete and valid, 4 = file missing, 5 = fields still empty (progress),
6 = invalid values.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IN_SAMPLE = ROOT / "data" / "external" / "ansc_review_sample_50.csv"
IN_OUTCOMES = ROOT / "results" / "tables" / "ansc_outcomes.csv"
INV_JSON = ROOT / "results" / "methodology" / "ansc_decision_inventory.json"
OUT_REVIEW = ROOT / "data" / "external" / "ansc_manual_review_50.csv"
OUT_PILOT = ROOT / "data" / "external" / "ansc_manual_review_pilot10.csv"
OUT_JSON = ROOT / "results" / "methodology" / "ansc_review_package.json"

PILOT_SIZE = 10

# machine-side columns that must NEVER enter the review files
FORBIDDEN_COLUMNS = ("extracted_outcome", "extraction_method", "confidence")

REVIEWER_OUTCOMES = ("admitted", "partially_admitted", "rejected",
                     "inadmissible", "withdrawn", "terminated", "unknown")
REVIEWER_DOC_TYPES = ("ansc_decision", "other_document", "uncertain")
REVIEWER_LINK = ("confirmed", "rejected", "uncertain")

REVIEW_FIELDS = [
    "ocid", "decision_id", "document_url", "local_pdf_path",
    "page_number", "evidence_quote",
    "reviewer_outcome", "reviewer_document_type", "reviewer_link_verified",
    "reviewer_evidence_page", "reviewer_evidence_quote", "reviewer_notes",
]

REQUIRED_ENUMS = {
    "reviewer_outcome": REVIEWER_OUTCOMES,
    "reviewer_document_type": REVIEWER_DOC_TYPES,
    "reviewer_link_verified": REVIEWER_LINK,
}

DISCLAIMER_RU = ("Индикатор потенциального риска, а не доказательство "
                 "коррупции/нарушения. Требуется проверка компетентным "
                 "органом.")
DISCLAIMER_EN = ("An upheld ANSC complaint indicates an administrative "
                 "procurement dispute outcome and does not constitute proof "
                 "of corruption.")


def _shown(path: Path) -> str:
    """Repo-relative path when possible (tmp paths stay absolute)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --- inputs -----------------------------------------------------------------
def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing {path}")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def machine_index() -> dict[str, dict]:
    """url -> {year, text_layer, confidence, outcome} (machine side only)."""
    out: dict[str, dict] = {}
    for r in load_rows(IN_OUTCOMES):
        out.setdefault(r.get("url", ""), {
            "year": r.get("year", ""),
            "text_layer": r.get("text_layer", ""),
            "confidence": r.get("confidence", ""),
            "outcome": r.get("outcome", "unknown"),
        })
    return out


def resolve_sandbox(explicit: str = "") -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_dir() else None
    if not INV_JSON.exists():
        return None
    meta = json.loads(INV_JSON.read_text(encoding="utf-8"))
    p = Path(meta.get("sandbox_dir") or "")
    return p if p.is_dir() else None


def pdf_path(url: str, sandbox: Path) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return str(sandbox / f"{digest}.pdf")


# --- package rows -----------------------------------------------------------
def build_rows(sample: list[dict], meta: dict[str, dict], sandbox: Path
               ) -> tuple[list[dict], list[dict]]:
    """Review rows (blind) + machine-side annotations for pilot selection."""
    rows: list[dict] = []
    machine: list[dict] = []
    for r in sample:
        url = r.get("document_url", "")
        m = meta.get(url, {})
        rows.append({
            "ocid": r.get("ocid", ""),
            "decision_id": r.get("decision_id", ""),
            "document_url": url,
            "local_pdf_path": pdf_path(url, sandbox),
            "page_number": r.get("page_number", ""),
            "evidence_quote": r.get("evidence_quote", ""),
            # reviewer columns - ALWAYS empty, never imitated:
            "reviewer_outcome": "",
            "reviewer_document_type": "",
            "reviewer_link_verified": "",
            "reviewer_evidence_page": "",
            "reviewer_evidence_quote": "",
            "reviewer_notes": "",
        })
        machine.append({
            "year": m.get("year", ""),
            "text_layer": m.get("text_layer", ""),
            "confidence": m.get("confidence", ""),
            "outcome": (r.get("extracted_outcome") or "unknown"),
            "decision_id": r.get("decision_id", ""),
        })
    return rows, machine


# --- pilot selection (uses machine side; never writes it) -------------------
# ordered strata: (predicted outcome, predicate over the machine side)
def _specs() -> list[tuple[str, callable]]:
    return [
        ("admitted", lambda m: m["text_layer"] == "1"),
        ("admitted", lambda m: m["text_layer"] == "0"),
        ("partially_admitted", lambda m: True),
        ("rejected", lambda m: True),
        ("withdrawn", lambda m: m["confidence"] == "low"),
        ("unknown", lambda m: m["text_layer"] == "1" and m["decision_id"]),
        ("unknown", lambda m: m["text_layer"] == "1"),
        ("unknown", lambda m: m["text_layer"] == "1"),
        ("unknown", lambda m: m["text_layer"] == "0"),
        ("unknown", lambda m: m["text_layer"] == "0"),
    ]


def pick_pilot(rows: list[dict], machine: list[dict],
               size: int = PILOT_SIZE) -> list[int]:
    """Deterministic indices of the pilot rows (never writes predictions)."""
    order = sorted(range(len(rows)),
                   key=lambda i: (machine[i]["year"] or "0000",
                                  rows[i]["document_url"]))
    used: set[int] = set()
    picked: list[int] = []

    def take(outcome: str, want) -> bool:
        for pass_no in (1, 0):        # 1 = with predicate, 0 = fallback
            for i in order:
                if i in used:
                    continue
                if machine[i]["outcome"] != outcome:
                    continue
                if pass_no == 1 and not want(machine[i]):
                    continue
                used.add(i)
                picked.append(i)
                return True
        return False

    for outcome, want in _specs()[:size]:
        take(outcome, want)
    # fill any shortfall from the pool (chronological)
    for i in order:
        if len(picked) >= size:
            break
        if i not in used:
            used.add(i)
            picked.append(i)
    return sorted(picked[:size])


def pilot_coverage(rows: list[dict], machine: list[dict],
                   idx: list[int]) -> dict:
    return {
        "outcomes": dict(Counter(machine[i]["outcome"] for i in idx)),
        "text_layer": dict(Counter(machine[i]["text_layer"] or "?"
                                   for i in idx)),
        "confidence": dict(Counter(machine[i]["confidence"] or "?"
                                   for i in idx)),
        "years": dict(sorted(Counter(machine[i]["year"] or "" for i in idx
                                     ).items())),
        "with_decision_id": sum(1 for i in idx if machine[i]["decision_id"]),
    }


# --- io ---------------------------------------------------------------------
def write_review_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def check_source(sample: list[dict]) -> list[str]:
    """The source sample must be blind-safe: no filled reviewer cells and
    no missing reference data."""
    errors: list[str] = []
    for i, r in enumerate(sample, start=2):
        for field in ("reviewer_outcome", "reviewer_notes"):
            if (r.get(field) or "").strip():
                errors.append(f"line {i}: source sample already has "
                              f"{field}={r[field]!r} - refusing to copy a "
                              f"possibly human/machine-filled label")
        if not (r.get("document_url") or "").strip():
            errors.append(f"line {i}: empty document_url")
    return errors


def validate_review(path: Path) -> dict:
    """Validate entered labels; returns a status dict (exit code inside)."""
    if not path.exists():
        return {"exit": 4, "status": "missing", "error": f"missing {path}"}
    rows = load_rows(path)
    if not rows:
        return {"exit": 4, "status": "missing", "error": "empty file"}
    header = list(rows[0])
    missing: list[dict] = []
    invalid: list[dict] = []
    complete = 0
    required = [f for f in REQUIRED_ENUMS if f in header]
    for i, row in enumerate(rows, start=2):
        row_bad = False
        for field in required:
            raw = (row.get(field) or "").strip()
            if not raw:
                missing.append({"line": i, "field": field,
                                "document_url": row.get("document_url", "")})
                row_bad = True
            elif raw not in REQUIRED_ENUMS[field]:
                invalid.append({"line": i, "field": field, "value": raw,
                                "document_url": row.get("document_url", "")})
                row_bad = True
        page = (row.get("reviewer_evidence_page") or "").strip()
        if page and not page.isdigit():
            invalid.append({"line": i, "field": "reviewer_evidence_page",
                            "value": page,
                            "document_url": row.get("document_url", "")})
            row_bad = True
        if not row_bad:
            complete += 1
    if invalid:
        status = "invalid_values"
        code = 6
    elif missing:
        status = "in_progress"
        code = 5
    else:
        status = "review_complete"
        code = 0
    return {"exit": code, "status": status, "total": len(rows),
            "complete": complete, "missing": missing, "invalid": invalid,
            "required_fields": required}


# --- main -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("build", "validate"),
                        default="build")
    parser.add_argument("--file", default=str(OUT_REVIEW),
                        help="validate: which review file to check")
    parser.add_argument("--sandbox", default="")
    parser.add_argument("--pilot-size", type=int, default=PILOT_SIZE)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "validate":
        rep = validate_review(Path(args.file))
        if not args.quiet:
            print(json.dumps({k: rep[k] for k in
                              ("status", "total", "complete",
                               "required_fields") if k in rep}
                             | {"n_missing": len(rep.get("missing", [])),
                                "n_invalid": len(rep.get("invalid", []))},
                             ensure_ascii=False, indent=1))
            for bad in rep.get("invalid", [])[:20]:
                print(f"  INVALID line {bad['line']} {bad['field']}="
                      f"{bad['value']!r}", file=sys.stderr)
        if rep["exit"] != 0 and not args.quiet:
            print(f"status: {rep['status']}", file=sys.stderr)
        return rep["exit"]

    # build ---------------------------------------------------------------
    if OUT_REVIEW.exists():
        # never clobber a file the reviewer may already be filling in
        existing = load_rows(OUT_REVIEW)
        filled = [r for r in existing
                  if any((r.get(f) or "").strip()
                         for f in REVIEW_FIELDS if f.startswith("reviewer_"))]
        if filled:
            print(f"refusing to overwrite {OUT_REVIEW}: "
                  f"{len(filled)} row(s) already contain reviewer data",
                  file=sys.stderr)
            return 6
    try:
        sample = load_rows(IN_SAMPLE)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 4
    if not sample:
        print("empty source sample", file=sys.stderr)
        return 4
    errors = check_source(sample)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 6

    sandbox = resolve_sandbox(args.sandbox)
    if sandbox is None:
        print("sandbox directory unknown/missing: local PDF paths cannot "
              "be written (pass --sandbox or restore "
              "ansc_decision_inventory.json)", file=sys.stderr)
        return 4

    rows, machine = build_rows(sample, machine_index(), sandbox)
    missing_files = [r["document_url"] for r in rows
                     if not Path(r["local_pdf_path"]).exists()]
    idx = pick_pilot(rows, machine, args.pilot_size)
    if len(rows) >= args.pilot_size and len(idx) < args.pilot_size:
        print("pilot selection shortfall", file=sys.stderr)
        return 4

    write_review_csv(rows, OUT_REVIEW)
    write_review_csv([rows[i] for i in idx], OUT_PILOT)
    coverage = pilot_coverage(rows, machine, idx)

    payload = {
        "task": "MTA-0019",
        "part": "2-3 - blind manual-review package",
        "generated": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "review_csv": _shown(OUT_REVIEW),
        "pilot_csv": _shown(OUT_PILOT),
        "documents_prepared": len(rows),
        "pilot_size": len(idx),
        "reviewer_fields": "empty - filled ONLY by the human reviewer; this "
                           "script never imitates the review",
        "blindness": "extracted_outcome / extraction_method / confidence "
                     "are NOT in the review files (join key: "
                     "ansc_review_sample_50.csv)",
        "pilot_coverage": coverage,
        "missing_local_pdfs": missing_files,
        "enums": {k: list(v) for k, v in REQUIRED_ENUMS.items()},
        "machine_review_status": "not started - awaiting the human reviewer",
        "disclaimer_ru": DISCLAIMER_RU,
        "disclaimer_en": DISCLAIMER_EN,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    if not args.quiet:
        print(json.dumps({"documents_prepared": len(rows),
                          "pilot_size": len(idx),
                          "pilot_coverage": coverage,
                          "missing_local_pdfs": len(missing_files)},
                         ensure_ascii=False, indent=1))
        print(f"written {_shown(OUT_REVIEW)}, {_shown(OUT_PILOT)}, "
              f"{_shown(OUT_JSON)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
