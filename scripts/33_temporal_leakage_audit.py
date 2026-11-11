#!/usr/bin/env python3
"""Export and cross-check the temporal feature-availability matrix (2026-10-20).

Machine-readable half of ``docs/TEMPORAL_LEAKAGE_AUDIT.md``. For each of the 22
production features the matrix records the procurement event after which its
inputs exist (publication / bid close / award decision / terminal state),
whether the value requires events after publication, and whether the
*as-implemented* computation is point-in-time safe (corpus-reference features
- CPV medians and behavioural shares - use the full corpus window and are
therefore only valid for retrospective as-of-now scoring).

Cross-checks (guards, not assumptions):

* ``src/mtender/features.py::FEATURE_COLUMNS`` must equal
  ``results/mongo/detection_summary.json::feature_columns`` - the matrix
  describes exactly what production v0 ran (exit 1 on mismatch when the
  artefact exists);
* the same columns must appear in the ``data/features/features.csv`` header;
* label fields (AAP/ANSC/synthetic ground truth) must never be features.

This is a **measurement, not a cycle**: no model, band, vote or threshold is
touched; the v0-v6 budget stays 6 of 10; no v7 exists.

Usage:
    .venv/bin/python scripts/33_temporal_leakage_audit.py

Output:
    results/methodology/temporal_feature_matrix.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from src.mtender.features import FEATURE_COLUMNS            # noqa: E402
from src.mtender.stage_features import (                    # noqa: E402
    LABEL_ONLY_FIELDS,
    STAGES,
    feature_matrix,
)

DETECTION_SUMMARY = RESULTS / "mongo" / "detection_summary.json"
FEATURES_CSV = ROOT / "data" / "features" / "features.csv"
OUT_PATH = RESULTS / "methodology" / "temporal_feature_matrix.json"


def _read_detection_columns() -> list[str] | None:
    if not DETECTION_SUMMARY.exists():
        return None
    try:
        data = json.loads(DETECTION_SUMMARY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cols = data.get("feature_columns")
    return list(cols) if isinstance(cols, list) else None


def _read_features_csv_header() -> list[str] | None:
    if not FEATURES_CSV.exists():
        return None
    try:
        with FEATURES_CSV.open(encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh), None)
    except (OSError, csv.Error):
        return None
    return list(header) if header else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()

    matrix = feature_matrix()
    checks: dict[str, dict] = {}

    detection_cols = _read_detection_columns()
    if detection_cols is None:
        checks["detection_summary"] = {
            "status": "absent",
            "note": "regenerable artefact not present - check skipped",
        }
    else:
        ok = detection_cols == FEATURE_COLUMNS
        checks["detection_summary"] = {
            "status": "match" if ok else "MISMATCH",
            "n": len(detection_cols),
            "only_in_detection": sorted(set(detection_cols) - set(FEATURE_COLUMNS)),
            "only_in_module": sorted(set(FEATURE_COLUMNS) - set(detection_cols)),
        }

    csv_header = _read_features_csv_header()
    if csv_header is None:
        checks["features_csv"] = {
            "status": "absent",
            "note": "data/features/features.csv not present - check skipped",
        }
    else:
        missing = [c for c in FEATURE_COLUMNS if c not in csv_header]
        checks["features_csv"] = {
            "status": "match" if not missing else "MISMATCH",
            "missing_from_csv": missing,
        }

    label_hits = sorted(set(LABEL_ONLY_FIELDS) & set(FEATURE_COLUMNS))
    checks["labels_never_features"] = {
        "status": "match" if not label_hits else "MISMATCH",
        "label_fields_checked": list(LABEL_ONLY_FIELDS),
        "hits": label_hits,
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "measurement_not_cycle": (
            "diagnostic export; production v0 unchanged, no v7, budget 6/10"
        ),
        "matrix": matrix,
        "stage_order": list(STAGES),
        "cross_checks": checks,
        "disclaimer": (
            "Feature timing validity, not a corruption finding: an anomaly "
            "score is a potential risk indicator; verification by a competent "
            "authority is required."
        ),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"stages ({len(STAGES)}):")
    for stage in STAGES:
        entry = matrix["stages"][stage]
        print(
            f"  {stage:<15} inputs={entry['n_features']:>2}  "
            f"point-in-time={entry['n_features_point_in_time']:>2}"
        )
    print(
        "not point-in-time safe:",
        ", ".join(matrix["not_point_in_time_safe"]),
    )
    print("MTA-0013 leak suspects:", len(matrix["leak_suspect_features"]))
    mismatches = [
        name
        for name, check in checks.items()
        if str(check.get("status", "")).upper() == "MISMATCH"
    ]
    for name, check in checks.items():
        print(f"check {name}: {check['status']}")
    print(f"written: {OUT_PATH.relative_to(ROOT)}")

    if mismatches:
        print("FAILED cross-checks:", ", ".join(mismatches), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
