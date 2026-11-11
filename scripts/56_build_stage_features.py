"""Build the stage-consistent feature table and the data-quality report.

Reads the period export and the legacy ``features.csv``. Writes only inside
the workspace. Does not modify Diplom, does not fill a missing window with
30 days, and does not mark any row as historically certified.

    .venv/bin/python scripts/56_build_stage_features.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.audit_expectations import AUDIT_PACKAGES
from src.mtender.mta_protocol import (  # noqa: E402
    DIPLOM_ROOT,
    FEATURE_COLUMNS,
    assert_outside_diplom,
)
from src.mtender.stage_feature_table import apply_stage_period_features  # noqa: E402
from src.mtender.stage_periods import stage_period_view  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bins(values: pd.Series) -> dict:
    number = pd.to_numeric(values, errors="coerce")
    cuts = {
        "missing": number.isna(),
        "0": number.eq(0),
        "1_to_6": number.between(1, 6, inclusive="both"),
        "7_to_14": number.between(7, 14, inclusive="both"),
        "15_to_29": number.between(15, 29, inclusive="both"),
        "30": number.eq(30),
        "31_to_90": number.between(31, 90, inclusive="both"),
        "91_to_365": number.between(91, 365, inclusive="both"),
        "366_to_3650": number.between(366, 3650, inclusive="both"),
        "above_3650": number.gt(3650),
    }
    return {name: int(mask.sum()) for name, mask in cuts.items()}


def _blank_to_na(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return text.mask(text.isin(["", "<NA>", "nan", "None"]))


def _audit_real_packages(package_dir: Path) -> list[dict]:
    import gzip

    rows = []
    for expected in AUDIT_PACKAGES:
        path = package_dir / f"{expected['ocid']}.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            view = stage_period_view(json.load(handle))
        rows.append(
            {
                "ocid": expected["ocid"],
                "matches_mta0022": bool(
                    view["legacy_cross_stage"] == 1
                    and view["legacy_start_stage"] == "planning"
                    and view["legacy_end_stage"] == "evaluation"
                    and view["legacy_merged_start"] == expected["pn_start"]
                    and view["legacy_merged_end"] == expected["ev_end"]
                    and view["legacy_window_days"] == expected["legacy_days"]
                    and view["evaluation_start"] == expected["ev_start"]
                    and view["evaluation_end"] == expected["ev_end"]
                    and view["submission_window_days"] == expected["evaluation_days"]
                    and view["submission_window_status"] == "evaluation_complete"
                    and view["historically_certified"] == 0
                ),
                "legacy_window_days": view["legacy_window_days"],
                "submission_window_days": view["submission_window_days"],
                "submission_window_status": view["submission_window_status"],
            }
        )
    return rows


def build(periods_csv: Path, features_csv: Path, package_dir: Path, out_dir: Path) -> dict:
    out_dir = assert_outside_diplom(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    periods = pd.read_csv(periods_csv, low_memory=False)
    feature_cols = ["ocid", "tender_start", "tender_end", *FEATURE_COLUMNS]
    features = pd.read_csv(features_csv, usecols=feature_cols, low_memory=False)
    if periods["ocid"].duplicated().any() or features["ocid"].duplicated().any():
        raise SystemExit("duplicate ocid in an input table")

    merged = features.merge(periods, on="ocid", how="outer", indicator=True, validate="one_to_one")
    features_only = int((merged["_merge"] == "left_only").sum())
    periods_only = int((merged["_merge"] == "right_only").sum())
    both = merged[merged["_merge"] == "both"].drop(columns=["_merge"]).copy()
    both = both.sort_values("ocid").reset_index(drop=True)

    stage = apply_stage_period_features(
        both["submission_window_status"].astype("string"),
        both["submission_window_days"],
    )
    # The legacy snapshot keeps its own period columns. Stage values replace
    # them only in the new table, under the same names the detectors expect.
    table = both[["ocid", *[column for column in FEATURE_COLUMNS if column not in ("bid_window_days", "short_deadline", "long_deadline")]]].copy()
    table["bid_window_days"] = stage["bid_window_days"]
    table["short_deadline"] = stage["short_deadline"]
    table["long_deadline"] = stage["long_deadline"]
    table["submission_window_days_unclipped"] = stage["submission_window_days_unclipped"]
    table["submission_window_observed"] = stage["submission_window_observed"]
    table["historically_certified"] = stage["historically_certified"]
    table["window_clipped"] = stage["window_clipped"]
    table["submission_window_status"] = both["submission_window_status"]
    table["legacy_bid_window_days"] = pd.to_numeric(both["bid_window_days"], errors="coerce")
    table["legacy_short_deadline"] = pd.to_numeric(both["short_deadline"], errors="coerce")
    table["legacy_long_deadline"] = pd.to_numeric(both["long_deadline"], errors="coerce")
    table["legacy_window_days_reproduced"] = pd.to_numeric(both["legacy_window_days"], errors="coerce")
    table["legacy_cross_stage"] = pd.to_numeric(both["legacy_cross_stage"], errors="coerce").fillna(0).astype(int)
    table["legacy_start_stage"] = both["legacy_start_stage"]
    table["legacy_end_stage"] = both["legacy_end_stage"]
    table["evaluation_start"] = _blank_to_na(both["evaluation_start"])
    table["evaluation_end"] = _blank_to_na(both["evaluation_end"])
    table["n_evaluation_complete_pairs"] = pd.to_numeric(both["n_evaluation_complete_pairs"], errors="coerce")

    forbidden = (
        (table["submission_window_observed"] == 0)
        & table["bid_window_days"].notna()
    )
    if int(forbidden.sum()):
        raise SystemExit("a missing evaluation window was written as a number")
    if int((table["historically_certified"] != 0).sum()):
        raise SystemExit("a snapshot row was marked historically certified")

    feature_start = pd.to_datetime(both["tender_start"], utc=True, errors="coerce")
    feature_end = pd.to_datetime(both["tender_end"], utc=True, errors="coerce")
    reproduced_start = pd.to_datetime(_blank_to_na(both["legacy_merged_start"]), utc=True, errors="coerce")
    reproduced_end = pd.to_datetime(_blank_to_na(both["legacy_merged_end"]), utc=True, errors="coerce")

    legacy_days = table["legacy_bid_window_days"]
    stage_days = table["bid_window_days"]
    observed = table["submission_window_observed"].eq(1)
    is_30 = legacy_days.eq(30)
    status_counts = both["submission_window_status"].value_counts(dropna=False).to_dict()

    legacy_numeric = table["legacy_window_days_reproduced"].notna()
    equal_reproduced = legacy_numeric & table["legacy_window_days_reproduced"].eq(legacy_days)
    stage_equal_legacy_feature = observed & stage_days.eq(legacy_days)
    observed_days = stage_days[observed]
    end_equal = feature_end.eq(reproduced_end) | (feature_end.isna() & reproduced_end.isna())
    start_equal = feature_start.eq(reproduced_start) | (feature_start.isna() & reproduced_start.isna())
    non_cross = table.loc[
        observed & table["legacy_cross_stage"].eq(0),
        ["ocid", "bid_window_days", "legacy_bid_window_days", "legacy_start_stage", "legacy_end_stage"],
    ]
    legacy_30_other = table.loc[is_30 & observed & ~stage_days.eq(30), "bid_window_days"]
    stage_30_legacy = table.loc[stage_days.eq(30), "legacy_bid_window_days"]

    quality = {
        "features_csv": str(features_csv),
        "features_sha256": _sha256(features_csv),
        "features_rows": int(len(features)),
        "periods_csv": str(periods_csv),
        "periods_rows": int(len(periods)),
        "package_dir": str(package_dir),
        "join": {
            "comparable_ocids": int(len(table)),
            "features_only": features_only,
            "periods_only": periods_only,
        },
        "submission_window_status": {str(key): int(value) for key, value in status_counts.items()},
        "legacy_cross_stage": int(table["legacy_cross_stage"].sum()),
        "evaluation_window_observed": int(observed.sum()),
        "evaluation_window_missing": int((~observed).sum()),
        "historically_certified_rows": int(table["historically_certified"].sum()),
        "windows_clipped_at_3650": int(table["window_clipped"].sum()),
        "missing_window_stored_as_number": 0,
        "bins_legacy_feature_bid_window": _bins(legacy_days),
        "bins_stage_clipped_window": _bins(stage_days),
        "bins_stage_unclipped_window": _bins(table["submission_window_days_unclipped"]),
        "bins_reproduced_legacy_merge": _bins(table["legacy_window_days_reproduced"]),
        "deadline_flags": {
            "legacy_short": int(table["legacy_short_deadline"].eq(1).sum()),
            "legacy_long": int(table["legacy_long_deadline"].eq(1).sum()),
            "stage_short_among_observed": int((observed & table["short_deadline"].eq(1)).sum()),
            "stage_long_among_observed": int((observed & table["long_deadline"].eq(1)).sum()),
            "stage_short_missing": int(table["short_deadline"].isna().sum()),
            "stage_long_missing": int(table["long_deadline"].isna().sum()),
        },
        "value_30_in_legacy_feature": {
            "rows": int(is_30.sum()),
            "stage_missing": int((is_30 & ~observed).sum()),
            "stage_also_30": int((is_30 & stage_days.eq(30)).sum()),
            "stage_other_observed_value": int((is_30 & observed & ~stage_days.eq(30)).sum()),
        },
        "reproduced_merge_versus_features": {
            "start_dates_equal": int((feature_start.eq(reproduced_start) | (feature_start.isna() & reproduced_start.isna())).sum()),
            "end_dates_equal": int((feature_end.eq(reproduced_end) | (feature_end.isna() & reproduced_end.isna())).sum()),
            "legacy_days_equal_where_reproduced_numeric": int(equal_reproduced.sum()),
            "reproduced_numeric": int(legacy_numeric.sum()),
            "stage_days_equal_legacy_feature_where_observed": int(stage_equal_legacy_feature.sum()),
        },
        "period_value_differs_from_legacy_feature": int((~observed | ~stage_days.eq(legacy_days)).sum()),
        "observed_stage_window": {
            "n": int(observed_days.size),
            "min": None if observed_days.empty else float(observed_days.min()),
            "median": None if observed_days.empty else float(observed_days.median()),
            "mean": None if observed_days.empty else float(observed_days.mean()),
            "p25": None if observed_days.empty else float(observed_days.quantile(0.25)),
            "p75": None if observed_days.empty else float(observed_days.quantile(0.75)),
            "max": None if observed_days.empty else float(observed_days.max()),
        },
        "evaluation_complete_not_cross_stage": non_cross.to_dict(orient="records"),
        "legacy_30_but_stage_other_bins": _bins(legacy_30_other),
        "stage_30_legacy_feature_bins": _bins(stage_30_legacy),
        "blank_legacy_days_among_evaluation_complete": int(
            (observed & table["legacy_window_days_reproduced"].isna()).sum()
        ),
        "cross_stage_without_evaluation_window": table.loc[
            table["legacy_cross_stage"].eq(1) & ~observed,
            [
                "ocid",
                "submission_window_status",
                "legacy_start_stage",
                "legacy_end_stage",
                "legacy_bid_window_days",
                "bid_window_days",
            ],
        ].to_dict(orient="records"),
        "date_mismatch": {
            "start_mismatch": int((~start_equal).sum()),
            "end_mismatch": int((~end_equal).sum()),
            "end_mismatch_and_no_evaluation_record": int(
                ((~end_equal) & both["submission_window_status"].eq("no_evaluation_record")).sum()
            ),
            "end_mismatch_and_evaluation_complete": int(
                ((~end_equal) & both["submission_window_status"].eq("evaluation_complete")).sum()
            ),
            "end_mismatch_reproduced_missing": int(((~end_equal) & reproduced_end.isna()).sum()),
            "end_mismatch_features_missing": int(((~end_equal) & feature_end.isna()).sum()),
        },
        "audit_packages": _audit_real_packages(package_dir),
        "snapshot_note": (
            "Stage-consistent columns describe the current compiled releases. "
            "historically_certified is 0 on every row. The legacy columns are "
            "copies of the production feature snapshot, which MTA-0022 also "
            "did not certify as publication-time values."
        ),
    }
    if not all(row["matches_mta0022"] for row in quality["audit_packages"]):
        raise SystemExit("real audit packages diverged from the MTA-0022 snapshot")

    table_path = out_dir / "stage_feature_table.csv.gz"
    quality_path = out_dir / "quality.json"
    table.to_csv(table_path, index=False, compression="gzip")
    quality["stage_feature_table"] = str(table_path)
    quality["stage_feature_table_sha256"] = _sha256(table_path)
    def _clean(value):
        if isinstance(value, dict):
            return {key: _clean(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_clean(item) for item in value]
        if isinstance(value, float) and value != value:
            return None
        return value

    quality_path.write_text(
        json.dumps(_clean(quality), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return quality


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--periods",
        default=str(ROOT / "results" / "mta0024_stage_periods" / "stage_periods.csv"),
    )
    parser.add_argument(
        "--features",
        default=str(DIPLOM_ROOT / "data" / "features" / "features.csv"),
    )
    parser.add_argument(
        "--packages",
        default=str(DIPLOM_ROOT / "data" / "raw" / "ocds_packages"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "results" / "mta0024_stage_periods"),
    )
    args = parser.parse_args()
    quality = build(Path(args.periods), Path(args.features), Path(args.packages), Path(args.out))
    printable = {
        "comparable_ocids": quality["join"]["comparable_ocids"],
        "evaluation_window_observed": quality["evaluation_window_observed"],
        "evaluation_window_missing": quality["evaluation_window_missing"],
        "legacy_cross_stage": quality["legacy_cross_stage"],
        "value_30_in_legacy_feature": quality["value_30_in_legacy_feature"],
        "historically_certified_rows": quality["historically_certified_rows"],
        "audit_matches": sum(row["matches_mta0022"] for row in quality["audit_packages"]),
    }
    print(json.dumps(printable, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
