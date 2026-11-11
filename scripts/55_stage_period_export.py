"""Export stage-pure submission windows without replacing the current features.

Reads archived OCDS packages and writes a new table. It does not open
MongoDB, does not score procedures, and does not write ``features.csv``,
``tenders.json``, or ``anomaly_scores``.

    .venv/bin/python scripts/55_stage_period_export.py
    .venv/bin/python scripts/55_stage_period_export.py --limit 20

``historically_certified`` is 0 on every row.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.stage_periods import stage_period_view

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGES = ROOT / "data" / "raw" / "ocds_packages"
DEFAULT_OUT = ROOT / "results" / "mta0024_stage_periods"
PROTECTED = {
    (ROOT / "data" / "processed" / "features.csv").resolve(),
    (ROOT / "data" / "processed" / "tenders.json").resolve(),
    (ROOT / "results" / "tables").resolve(),
}

COLUMNS = [
    "ocid",
    "n_compiled_releases",
    "has_planning_record",
    "has_evaluation_record",
    "legacy_merged_start",
    "legacy_merged_end",
    "legacy_start_stage",
    "legacy_end_stage",
    "legacy_cross_stage",
    "legacy_window_days",
    "n_evaluation_complete_pairs",
    "n_planning_complete_pairs",
    "evaluation_start",
    "evaluation_end",
    "submission_window_days",
    "submission_window_status",
    "historically_certified",
]


def _ocid_from_name(path: Path) -> str:
    name = path.name
    if name.endswith(".json.gz"):
        return name[: -len(".json.gz")]
    return path.stem


def export(package_dir: Path, out_dir: Path, limit: int | None) -> dict:
    resolved = out_dir.resolve()
    if resolved in PROTECTED or any(resolved == protected or protected in resolved.parents for protected in PROTECTED):
        raise SystemExit(f"refusing to write over a protected path: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(package_dir.glob("*.json.gz"))
    if limit is not None:
        paths = paths[:limit]
    table_path = out_dir / "stage_periods.csv"
    summary_path = out_dir / "summary.json"
    status_counts: Counter[str] = Counter()
    cross = 0
    comparable = 0
    legacy_longer = 0
    legacy_shorter = 0
    equal_when_both = 0
    read_errors = 0
    written = 0
    with table_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for path in paths:
            try:
                with gzip.open(path, "rt", encoding="utf-8") as raw:
                    package = json.load(raw)
            except (OSError, json.JSONDecodeError):
                read_errors += 1
                continue
            if not isinstance(package, dict):
                read_errors += 1
                continue
            view = stage_period_view(package)
            view["ocid"] = _ocid_from_name(path)
            writer.writerow({column: view.get(column, "") for column in COLUMNS})
            written += 1
            status_counts[str(view["submission_window_status"])] += 1
            cross += int(view["legacy_cross_stage"])
            legacy = view["legacy_window_days"]
            submission = view["submission_window_days"]
            if legacy != "" and submission != "":
                comparable += 1
                legacy_value = int(legacy)
                submission_value = int(submission)
                if legacy_value > submission_value:
                    legacy_longer += 1
                elif legacy_value < submission_value:
                    legacy_shorter += 1
                else:
                    equal_when_both += 1
    summary = {
        "package_dir": str(package_dir),
        "rows_written": written,
        "read_errors": read_errors,
        "legacy_cross_stage": cross,
        "both_windows_observed": comparable,
        "legacy_longer_than_evaluation": legacy_longer,
        "legacy_shorter_than_evaluation": legacy_shorter,
        "windows_equal": equal_when_both,
        "submission_window_status": dict(status_counts),
        "historically_certified_rows": 0,
        "replaces_features_csv": False,
        "corruption_detection_claim": False,
        "table": str(table_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packages", default=str(DEFAULT_PACKAGES))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    summary = export(Path(args.packages), Path(args.out), args.limit)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
