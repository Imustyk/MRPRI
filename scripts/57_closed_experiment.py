"""Closed comparison of legacy, stage-consistent and ablated features.

Same OCID population, same seed, same detector settings as
``scripts/06_detect_anomalies.py``. Writes only inside the workspace.
Does not open MongoDB and does not update production scores.

    .venv/bin/python scripts/57_closed_experiment.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.detectors import run_detectors  # noqa: E402
from src.mtender.mta_compare import flag_counts, spearman, top_ocids, topk_overlap  # noqa: E402
from src.mtender.mta_protocol import (  # noqa: E402
    ARMS,
    FEATURE_COLUMNS,
    METHODS,
    OUTLIER_RATE,
    PERIOD_COLUMNS,
    RANDOM_STATE,
    TOP_KS,
    assert_outside_diplom,
)
from src.mtender.stage_feature_table import (  # noqa: E402
    ablation_model_frame,
    legacy_model_frame,
    stage_model_frame,
)

ROOT = Path(__file__).resolve().parents[1]


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _method_summary(payload: dict, seconds: float) -> dict:
    score = payload["score"]
    flag = payload["flag"]
    return {
        "n_flagged": int(flag.sum()),
        "pct_flagged": round(float(flag.mean() * 100), 4),
        "mean_score": round(float(np.mean(score)), 6),
        "median_score": round(float(np.median(score)), 6),
        "p95_score": round(float(np.quantile(score, 0.95)), 6),
        "seconds": round(float(seconds), 3),
        "params": payload["params"],
    }


def _write_scores(path: Path, ocids: np.ndarray, result: dict) -> None:
    frame = pd.DataFrame({"ocid": ocids})
    for name, payload in result["methods"].items():
        frame[f"score_{name}"] = payload["score"]
        frame[f"flag_{name}"] = payload["flag"]
    frame.to_csv(path, index=False, compression="gzip")


def _window_stats(series: pd.Series) -> dict:
    number = pd.to_numeric(series, errors="coerce")
    observed = number.dropna()
    if observed.empty:
        return {"n": 0, "median": None, "mad": None, "std": None}
    median = float(observed.median())
    mad = float((observed - median).abs().median())
    return {
        "n": int(observed.size),
        "median": median,
        "mad": mad,
        "std": float(observed.std(ddof=0)),
    }


def run(table_path: Path, out_dir: Path) -> dict:
    out_dir = assert_outside_diplom(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pd.read_csv(table_path, low_memory=False)
    table = table.sort_values("ocid").reset_index(drop=True)
    if table["ocid"].duplicated().any():
        raise SystemExit("duplicate ocid in the stage feature table")
    ocids = table["ocid"].astype(str).to_numpy()

    legacy_columns = table[list(FEATURE_COLUMNS)].copy()
    legacy_columns["bid_window_days"] = table["legacy_bid_window_days"]
    legacy_columns["short_deadline"] = table["legacy_short_deadline"]
    legacy_columns["long_deadline"] = table["legacy_long_deadline"]
    stage_columns = table[list(FEATURE_COLUMNS)].copy()
    observed = table["submission_window_observed"].eq(1)
    changed = (~observed) | ~table["bid_window_days"].eq(table["legacy_bid_window_days"])

    matrices = {}
    raw_indicators = {}
    matrices["legacy"], legacy_info = legacy_model_frame(legacy_columns, FEATURE_COLUMNS)
    raw_indicators["legacy"] = legacy_columns
    matrices["stage_consistent"], stage_info = stage_model_frame(stage_columns, FEATURE_COLUMNS)
    raw_indicators["stage_consistent"] = stage_columns
    matrices["ablation"], ablation_info = ablation_model_frame(legacy_columns, FEATURE_COLUMNS)
    raw_ablation = legacy_columns.drop(columns=list(PERIOD_COLUMNS))
    raw_indicators["ablation"] = raw_ablation
    preprocess = {
        "legacy": legacy_info,
        "stage_consistent": stage_info,
        "ablation": ablation_info,
    }

    stored = {}
    arms = {}
    wall_started = time.perf_counter()
    for arm in ARMS:
        print(f"fitting {arm} on {len(ocids):,} rows x {matrices[arm].shape[1]} columns", flush=True)
        result = run_detectors(raw_indicators[arm], matrices[arm], ocids)
        score_path = out_dir / f"scores_{arm}.csv.gz"
        _write_scores(score_path, ocids, result)
        digest = hashlib.sha256(score_path.read_bytes()).hexdigest()
        stored[arm] = result
        arms[arm] = {
            "columns": preprocess[arm]["columns"],
            "n_columns": len(preprocess[arm]["columns"]),
            "preprocess": preprocess[arm],
            "seconds": {name: round(value, 3) for name, value in result["seconds"].items()},
            "seconds_total": round(sum(result["seconds"].values()), 3),
            "fit_rows": result["fit_rows"],
            "bid_window_observed_stats": _window_stats(
                stage_columns["bid_window_days"] if arm == "stage_consistent" else legacy_columns["bid_window_days"]
            ) if arm != "ablation" else None,
            "methods": {
                name: _method_summary(result["methods"][name], result["seconds"][name])
                for name in METHODS
            },
            "scores_file": score_path.name,
            "scores_sha256": digest,
        }
        print(
            f"  done {arm} in {arms[arm]['seconds_total']:.1f}s "
            f"consensus={arms[arm]['methods']['ensemble']['n_flagged']}",
            flush=True,
        )

    pairwise = []
    sensitivity = []
    top_lists = []
    for left_name, right_name in (
        ("legacy", "stage_consistent"),
        ("legacy", "ablation"),
        ("stage_consistent", "ablation"),
    ):
        left = stored[left_name]
        right = stored[right_name]
        for method in METHODS:
            left_score = left["methods"][method]["score"]
            right_score = right["methods"][method]["score"]
            left_flag = left["methods"][method]["flag"]
            right_flag = right["methods"][method]["flag"]
            counts = flag_counts(left_flag, right_flag)
            rank_gap = np.abs(left["percentile_ready"][method] - right["percentile_ready"][method])
            changed_np = changed.to_numpy()
            unchanged_np = ~changed_np
            topk = {str(k): topk_overlap(left_score, right_score, ocids, k) for k in TOP_KS}
            pairwise.append(
                {
                    "left": left_name,
                    "right": right_name,
                    "method": method,
                    "spearman": spearman(left_score, right_score),
                    "spearman_where_period_changed": spearman(left_score[changed_np], right_score[changed_np]),
                    "spearman_where_period_unchanged": spearman(
                        left_score[unchanged_np], right_score[unchanged_np]
                    ),
                    **counts,
                    "median_abs_percentile_gap": float(np.median(rank_gap)),
                    "median_abs_percentile_gap_changed": float(np.median(rank_gap[changed_np])),
                    "median_abs_percentile_gap_unchanged": float(np.median(rank_gap[unchanged_np]))
                    if int(unchanged_np.sum())
                    else None,
                    "topk": topk,
                }
            )
            if method == "ensemble":
                for k in TOP_KS:
                    lost = set(top_ocids(left_score, ocids, k)) - set(top_ocids(right_score, ocids, k))
                    gained = set(top_ocids(right_score, ocids, k)) - set(top_ocids(left_score, ocids, k))
                    sensitivity.append(
                        {
                            "left": left_name,
                            "right": right_name,
                            "k": k,
                            "left_only": len(lost),
                            "right_only": len(gained),
                            "intersection": k - len(lost),
                        }
                    )

    for arm_name, arm_result in stored.items():
        for method in METHODS:
            chosen = top_ocids(arm_result["methods"][method]["score"], ocids, 100)
            for rank, ocid in enumerate(chosen, start=1):
                top_lists.append({"arm": arm_name, "method": method, "rank": rank, "ocid": ocid})

    within = []
    for arm_name, arm_result in stored.items():
        names = ["mad", "isolation_forest", "lof", "one_class_svm"]
        for i, left_method in enumerate(names):
            for right_method in names[i + 1 :]:
                counts = flag_counts(
                    arm_result["methods"][left_method]["flag"],
                    arm_result["methods"][right_method]["flag"],
                )
                within.append(
                    {
                        "arm": arm_name,
                        "left": left_method,
                        "right": right_method,
                        "spearman": spearman(
                            arm_result["methods"][left_method]["score"],
                            arm_result["methods"][right_method]["score"],
                        ),
                        **counts,
                    }
                )

    summary = {
        "protocol": {
            "population": "inner join of features.csv and the stage-period export, sorted by ocid",
            "n_ocids": int(len(ocids)),
            "period_values_changed": int(changed.sum()),
            "period_values_unchanged": int((~changed).sum()),
            "random_state": RANDOM_STATE,
            "outlier_rate": OUTLIER_RATE,
            "neighbourhood_fit_cap": int(stored["legacy"]["fit_rows"]),
            "methods": list(METHODS),
            "arms": {
                "legacy": "production feature snapshot, including the filled bid window",
                "stage_consistent": "same non-period features; period features from one evaluation release; missing stays missing in the table",
                "ablation": "same rows without bid_window_days, short_deadline and long_deadline",
            },
            "ensemble_flag": "at least 3 of mad, isolation forest, lof and one-class svm",
            "simple_indicator_flag": "exact top 5 percent of the binary count, ties broken by ocid",
            "external_labels_used": False,
            "superiority_claim": False,
            "historically_certified": False,
        },
        "preprocess": preprocess,
        "arms": arms,
        "pairwise": pairwise,
        "ensemble_topk_movement": sensitivity,
        "within_arm": within,
        "seconds_total": round(time.perf_counter() - wall_started, 3),
    }
    (out_dir / "experiment_summary.json").write_text(
        json.dumps(_jsonable(summary), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(top_lists).to_csv(out_dir / "top100.csv", index=False)
    pd.DataFrame(pairwise).drop(columns=["topk"]).to_csv(out_dir / "pairwise.csv", index=False)
    flat_topk = []
    for row in pairwise:
        for k, payload in row["topk"].items():
            flat_topk.append(
                {
                    "left": row["left"],
                    "right": row["right"],
                    "method": row["method"],
                    **payload,
                }
            )
    pd.DataFrame(flat_topk).to_csv(out_dir / "topk_overlap.csv", index=False)
    pd.DataFrame(within).to_csv(out_dir / "within_arm_agreement.csv", index=False)
    print(json.dumps({"n_ocids": int(len(ocids)), "seconds_total": summary["seconds_total"]}, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--table",
        default=str(ROOT / "results" / "mta0024_stage_periods" / "stage_feature_table.csv.gz"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "results" / "mta0025_closed_experiment"),
    )
    args = parser.parse_args()
    run(Path(args.table), Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
