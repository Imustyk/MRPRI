#!/usr/bin/env python3
"""External label ``ansc_upheld`` from the COMPLETED manual review
(MTA-0019, step 6). MEASUREMENT ONLY - no training, production stays v0,
``data/raw/**`` untouched.

THE GATE: this script refuses to create a single label while the manual
review of ``data/external/ansc_manual_review_50.csv`` is incomplete or
contains invalid values - it then writes only PROGRESS to the JSON artefact
and exits 5 (invalid -> exit 6). No label CSV exists before a human has
reviewed every document; the review is never imitated.

LABEL RULES (document/decision level, never collapsed to a procedure):
  ansc_upheld = 1  reviewer_outcome in {admitted, partially_admitted}
                   (complaint fully or partially upheld)
  ansc_upheld = 0  reviewer_outcome == rejected (rejected ON THE MERITS)
  ansc_upheld = NULL  everything else: inadmissible / withdrawn /
                   terminated / unknown, a document that is not a confirmed
                   ANSC decision (reviewer_document_type != ansc_decision),
                   an UNCONFIRMED procedure link (reviewer_link_verified !=
                   confirmed), or a row whose notes carry the ``multiple:``
                   marker (several complaints with different outcomes stay
                   at their own complaint/decision level and are NEVER
                   collapsed into one binary label).
  Rows are emitted one per reviewed document: several documents/complaints
  of ONE procedure each keep their own label; procedure-level conflicts are
  REPORTED, not resolved.

FUTURE LEAKAGE: decision dates are summarised from the extraction table -
labels may only be used by a model as of a date AFTER the decision date of
the document they derive from; dates after the generation moment are
flagged as leakage candidates.

FEATURE LEAKAGE SCAN: before anything else the script scans the feature
pipeline (scripts 00-15) and ``backend/`` for the literal ``ansc_upheld`` -
if the label has leaked into model features/production code the script
exits 7 without writing labels (regression-tested).

UPHELD IS NOT PROOF: an upheld ANSC complaint indicates an administrative
procurement dispute outcome and does not constitute proof of corruption.

Usage:
    .venv/bin/python scripts/47_ansc_upheld_labels.py
        [--review FILE] [--outcomes FILE] [--out FILE] [--quiet]

Exit codes: 0 = labels written (review complete & valid, no leakage);
4 = input missing/structurally wrong; 5 = review incomplete (progress
only, NO label file); 6 = invalid reviewer values; 7 = ``ansc_upheld``
found in the feature pipeline (leakage).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, date, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IN_REVIEW = ROOT / "data" / "external" / "ansc_manual_review_50.csv"
IN_OUTCOMES = ROOT / "results" / "tables" / "ansc_outcomes.csv"
OUT_LABELS = ROOT / "data" / "external" / "ansc_upheld_labels.csv"
OUT_JSON = ROOT / "results" / "methodology" / "ansc_upheld_labels.json"

OUTCOMES = ("admitted", "partially_admitted", "rejected", "inadmissible",
            "withdrawn", "terminated", "unknown")
DOC_TYPES = ("ansc_decision", "other_document", "uncertain")
LINK_VALUES = ("confirmed", "rejected", "uncertain")
REQUIRED_COLUMNS = ("ocid", "document_url", "reviewer_outcome",
                    "reviewer_document_type", "reviewer_link_verified")

LABEL_CSV_FIELDS = [
    "ocid", "decision_id", "document_url", "reviewer_outcome",
    "reviewer_document_type", "reviewer_link_verified", "ansc_upheld",
    "label_reason", "multi_complaint", "decision_date", "reviewer_notes",
]

RE_MULTI = re.compile(r"\bmultiple:", re.IGNORECASE)
RE_SCRIPT_NUM = re.compile(r"^(\d{2})")

# feature pipeline that must never see the label (MTA-0019 §6/§8)
SCAN_SUFFIXES = (".py", ".json", ".yaml", ".yml")

DISCLAIMER_RU = ("Индикатор потенциального риска, а не доказательство "
                 "коррупции/нарушения. Требуется проверка компетентным "
                 "органом. Удовлетворённая жалоба ANSC не является "
                 "доказательством коррупции.")
DISCLAIMER_EN = ("An upheld ANSC complaint indicates an administrative "
                 "procurement dispute outcome and does not constitute proof "
                 "of corruption.")


def scan_targets() -> list[Path]:
    """Feature-pipeline files: scripts/00..15 and backend/ (by constant)."""
    targets: list[Path] = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        m = RE_SCRIPT_NUM.match(p.name)
        if m and int(m.group(1)) <= 15:
            targets.append(p)
    backend = ROOT / "backend"
    if backend.is_dir():
        targets.extend(sorted(p for p in backend.rglob("*")
                              if p.is_file() and p.suffix in SCAN_SUFFIXES))
    return targets


def scan_feature_leakage(targets: list[Path]) -> list[dict]:
    """Occurrences of the literal label name in the feature pipeline."""
    hits: list[dict] = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "ansc_upheld" in text:
            lines = [i for i, line in enumerate(text.splitlines(), 1)
                     if "ansc_upheld" in line]
            hits.append({"file": str(path), "lines": lines[:10]})
    return hits


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing {path}")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --- validation (review must be COMPLETE and VALID) -------------------------
def validate_review(rows: list[dict], header: list[str]) -> dict:
    """Complete / missing / invalid over the required enum columns."""
    missing: list[dict] = []
    invalid: list[dict] = []
    required = [f for f in ("reviewer_outcome", "reviewer_document_type",
                            "reviewer_link_verified") if f in header]
    enums = {"reviewer_outcome": OUTCOMES,
             "reviewer_document_type": DOC_TYPES,
             "reviewer_link_verified": LINK_VALUES}
    complete = 0
    for i, row in enumerate(rows, start=2):
        row_ok = True
        for field in required:
            raw = (row.get(field) or "").strip()
            if not raw:
                missing.append({"line": i, "field": field,
                                "document_url": row.get("document_url", "")})
                row_ok = False
            elif raw not in enums[field]:
                invalid.append({"line": i, "field": field, "value": raw,
                                "document_url": row.get("document_url", "")})
                row_ok = False
        if row_ok:
            complete += 1
    return {"required_fields": required, "complete": complete,
            "missing": missing, "invalid": invalid}


# --- label derivation (pure) ------------------------------------------------
def derive_label(row: dict) -> tuple[int | None, str, bool]:
    """``(ansc_upheld, reason, multi_complaint)`` for one reviewed document.

    NULL whenever the document is not a CONFIRMED ANSC decision or the
    outcome is not a merits decision; ``multiple:`` rows are never
    collapsed (MTA-0019 §6).
    """
    doc_type = (row.get("reviewer_document_type") or "").strip()
    link = (row.get("reviewer_link_verified") or "").strip()
    outcome = (row.get("reviewer_outcome") or "").strip()
    notes = row.get("reviewer_notes") or ""
    multi = bool(RE_MULTI.search(notes))

    if doc_type != "ansc_decision":
        return None, f"document type is {doc_type or 'unfilled'}: outcome " \
                     f"quality excludes it, no binary label", multi
    if link != "confirmed":
        return None, f"procedure link not confirmed ({link})", multi
    if multi:
        return None, "several complaints with different outcomes: kept at " \
                     "complaint/decision level, NOT collapsed", multi
    if outcome in ("admitted", "partially_admitted"):
        return 1, f"complaint upheld ({outcome})", multi
    if outcome == "rejected":
        return 0, "complaint rejected on the merits", multi
    return None, f"outcome {outcome} is not a merits upholding/rejection", \
        multi


# --- decision dates / future leakage ---------------------------------------
def decision_dates(rows: list[dict], outcomes_path: Path
                   ) -> dict:
    """Decision dates of the labelled documents (from the extraction table).

    A label may only be used as of a date AFTER its decision date; any date
    later than the generation moment is a leakage candidate.
    """
    dates_by_url: dict[str, str] = {}
    if outcomes_path.exists():
        for r in load_rows(outcomes_path):
            dates_by_url.setdefault(r.get("url", ""),
                                    r.get("decision_date", ""))
    today = datetime.now(timezone.utc).date()
    parsed: list[date] = []
    without = 0
    unparsed = 0
    future: list[dict] = []
    for row in rows:
        raw = (dates_by_url.get(row.get("document_url", "")) or "").strip()
        if not raw:
            without += 1
            continue
        try:
            d = datetime.strptime(raw, "%d.%m.%Y").date()
        except ValueError:
            unparsed += 1
            continue
        parsed.append(d)
        if d > today:
            future.append({"document_url": row.get("document_url", ""),
                           "decision_date": raw})
    return {
        "source": str(outcomes_path) if outcomes_path.exists() else None,
        "with_date": len(parsed),
        "without_date": without,
        "unparsed_date": unparsed,
        "min_date": min(parsed).isoformat() if parsed else None,
        "max_date": max(parsed).isoformat() if parsed else None,
        "dates_after_generation": future,
        "rule": "a label may only enter a model as of a date AFTER the "
                "decision date of its document; features dated before the "
                "decision would be future leakage",
    }


def procedure_level_summary(rows: list[dict]) -> dict:
    """Several reviewed documents of ONE procedure keep their own labels;
    conflicting binary labels are reported, never collapsed."""
    by_ocid: dict[str, list[int | None]] = defaultdict(list)
    for row in rows:
        label, _, _ = derive_label(row)
        by_ocid[(row.get("ocid") or "").strip()].append(label)
    multi_doc = {k: v for k, v in by_ocid.items() if len(v) > 1}
    conflicts = {k: v for k, v in multi_doc.items()
                 if len({x for x in v if x is not None}) > 1}
    return {
        "procedures_reviewed": len(by_ocid),
        "procedures_with_several_reviewed_documents": len(multi_doc),
        "procedures_with_conflicting_binary_labels": len(conflicts),
        "conflicting_ocids": sorted(conflicts),
        "rule": "labels stay at document/complaint level; no procedure "
                "collapses them into one binary value",
    }


def write_labels_csv(rows: list[dict], dates_by_url: dict[str, str],
                     path: Path) -> tuple[int, int]:
    """Write the label artefact; returns (n_labels, n_null)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n1 = n0 = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LABEL_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            label, reason, multi = derive_label(row)
            if label == 1:
                n1 += 1
            elif label == 0:
                n0 += 1
            writer.writerow({
                "ocid": row.get("ocid", ""),
                "decision_id": row.get("decision_id", ""),
                "document_url": row.get("document_url", ""),
                "reviewer_outcome": row.get("reviewer_outcome", ""),
                "reviewer_document_type": row.get("reviewer_document_type",
                                                  ""),
                "reviewer_link_verified": row.get("reviewer_link_verified",
                                                  ""),
                "ansc_upheld": "" if label is None else str(label),
                "label_reason": reason,
                "multi_complaint": "1" if multi else "",
                "decision_date": dates_by_url.get(
                    row.get("document_url", ""), ""),
                "reviewer_notes": row.get("reviewer_notes", ""),
            })
    return n1, n0


def write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", default=str(IN_REVIEW))
    parser.add_argument("--outcomes", default=str(IN_OUTCOMES))
    parser.add_argument("--out", default=str(OUT_LABELS))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    base = {
        "task": "MTA-0019",
        "part": "6 - external label ansc_upheld from the manual review",
        "generated": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "disclaimer_ru": DISCLAIMER_RU,
        "disclaimer_en": DISCLAIMER_EN,
    }

    # 1) leakage scan FIRST: no labels if the name is in the pipeline
    hits = scan_feature_leakage(scan_targets())
    if hits:
        write_json(base | {"status": "feature_leakage_detected",
                           "leakage": hits, "labels": None,
                           "note": "ansc_upheld must never appear in the "
                                   "feature pipeline (scripts 00-15, "
                                   "backend); fix the leak before labeling"},
                   OUT_JSON)
        print("LEAKAGE: ansc_upheld found in the feature pipeline:",
              file=sys.stderr)
        for h in hits:
            print(f"  {h['file']}: lines {h['lines']}", file=sys.stderr)
        return 7

    # 2) inputs
    review_path = Path(args.review)
    try:
        rows = load_rows(review_path)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 4
    if not rows:
        print(f"empty review file: {review_path}", file=sys.stderr)
        return 4
    header = list(rows[0])
    absent = [c for c in REQUIRED_COLUMNS if c not in header]
    if absent:
        print(f"review file lacks required columns: {', '.join(absent)}",
              file=sys.stderr)
        return 4

    # 3) the gate: complete + valid human labels only
    rep = validate_review(rows, header)
    if rep["invalid"]:
        payload = base | {"status": "invalid_labels", "labels": None,
                          "n_total": len(rows), "n_complete": rep["complete"],
                          "invalid_rows": rep["invalid"],
                          "missing_rows": rep["missing"],
                          "note": "invalid reviewer values - no label file "
                                  "is written"}
        write_json(payload, OUT_JSON)
        print("invalid reviewer values - refusing to label:", file=sys.stderr)
        for bad in rep["invalid"][:20]:
            print(f"  line {bad['line']} {bad['field']}={bad['value']!r}",
                  file=sys.stderr)
        return 6
    if rep["missing"]:
        payload = base | {"status": "awaiting_manual_review",
                          "labels": None, "n_total": len(rows),
                          "n_complete": rep["complete"],
                          "n_missing": len(rep["missing"]),
                          "missing_rows": rep["missing"],
                          "required_fields": rep["required_fields"],
                          "label_file_written": False,
                          "note": "the manual review is incomplete: NO "
                                  "ansc_upheld labels exist (MTA-0019 §6); "
                                  "progress only, no metrics"}
        write_json(payload, OUT_JSON)
        print(json.dumps({"status": "awaiting_manual_review",
                          "n_complete": rep["complete"],
                          "n_total": len(rows),
                          "n_missing": len(rep["missing"]),
                          "labels": None}, ensure_ascii=False, indent=1))
        print("refusing to create ansc_upheld: the manual review is "
              "incomplete (no label file written).", file=sys.stderr)
        return 5

    # 4) review complete -> derive labels
    outcomes_path = Path(args.outcomes)
    dates_by_url: dict[str, str] = {}
    if outcomes_path.exists():
        for r in load_rows(outcomes_path):
            dates_by_url.setdefault(r.get("url", ""),
                                    r.get("decision_date", ""))
    out_path = Path(args.out)
    n1, n0 = write_labels_csv(rows, dates_by_url, out_path)
    nulls = len(rows) - n1 - n0
    multi_rows = sum(1 for r in rows if RE_MULTI.search(
        r.get("reviewer_notes") or ""))

    payload = base | {
        "status": "labels_written",
        "review_file": str(review_path),
        "label_file": str(out_path),
        "n_documents": len(rows),
        "n_upheld_1": n1,
        "n_rejected_0": n0,
        "n_null": nulls,
        "n_multi_complaint_rows": multi_rows,
        "outcome_distribution_manual": dict(Counter(
            (r.get("reviewer_outcome") or "").strip() for r in rows)),
        "document_type_distribution_manual": dict(Counter(
            (r.get("reviewer_document_type") or "").strip() for r in rows)),
        "procedure_level": procedure_level_summary(rows),
        "decision_dates": decision_dates(rows, outcomes_path),
        "feature_leakage_scan": {"targets": len(scan_targets()),
                                 "occurrences": 0},
        "note": "labels derive from the human review only; upheld != "
                "proof of corruption; ansc_upheld is an EXTERNAL label "
                "and must never become a model feature",
    }
    write_json(payload, OUT_JSON)
    if not args.quiet:
        print(json.dumps({k: payload[k] for k in
                          ("status", "n_documents", "n_upheld_1", "n_rejected_0",
                           "n_null", "n_multi_complaint_rows")},
                         ensure_ascii=False, indent=1))
        print(f"written {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
