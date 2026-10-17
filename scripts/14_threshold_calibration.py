"""Step 14 (methodology cycle, step 6) - decision boundary calibration.

The production decision boundary is a *vote count*: 3 of 4 detectors (bands
0/1/2/3+ = low/medium/high/critical). This stage treats it as the parameter it
really is and sweeps alternatives:

* rules and thresholds: votes >= 1..4, top-N cuts of ``max_score`` (the
  production percentile), of the mean-percentile ensemble and of the weighted
  ensemble, plus round score cuts (0.95 / 0.97 / 0.98 / 0.99 / 0.995);
* evaluation: review load, precision/recall/lift against the external AAP label
  with Wilson intervals, and an explicit business cost
  ``cost = FP * c_review + FN * c_miss`` over a range of miss prices;
* temporal split, as required: thresholds are *chosen on 2018-2021* and then
  applied unchanged to 2022-2024, so a boundary that only works in the period
  it was fitted on is visible;
* drift: per-year score distributions, PSI and a KS test between the periods.

The external label has 633 procedures from 17 suppliers, so every threshold
chosen here carries a real overfitting risk on a small sample; the report and
the JSON state that explicitly rather than presenting a tuned number as a
discovery.

Usage:
    .venv/bin/python scripts/14_threshold_calibration.py
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import FIGURES, RESULTS, TABLES  # noqa: E402
from src.mtender.eval_metrics import wilson_ci  # noqa: E402
from src.mtender.external_labels import build_label_table  # noqa: E402

SCORES_CSV = TABLES / "tender_anomaly_scores.csv"
TUNE_PERIOD, TEST_PERIOD = "2018-2021", "2022-2024"
#: Review loads at which a threshold is estimated on the *tune* period.
TARGET_LOADS = (300, 500, 1000, 2000, 3031, 5000, 7662, 15000)
#: Prices of a missed positive, in multiples of the cost of one review.
MISS_PRICES = (10, 50, 200)
#: Price of reviewing one flagged procedure (hours of auditor attention = 1 unit).
C_REVIEW = 1.0
ROUND_CUTS = (0.95, 0.97, 0.98, 0.99, 0.995)


def top_threshold(values: np.ndarray, load: int) -> float:
    """Score cut that selects (approximately) the ``load`` largest values."""
    if load >= len(values):
        return float(np.min(values))
    return float(np.sort(values)[-int(load)])


def rule_metrics(y: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    tp = int(((mask == 1) & (y == 1)).sum())
    fp = int(((mask == 1) & (y == 0)).sum())
    fn = int(((mask == 0) & (y == 1)).sum())
    n_flag = int(mask.sum())
    precision = tp / n_flag if n_flag else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    lo, hi = wilson_ci(tp, n_flag)
    base = float(y.mean()) if len(y) else float("nan")
    return {
        "n_flagged": n_flag,
        "pct_flagged": round(n_flag / len(y) * 100, 4) if len(y) else None,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 6) if precision == precision else None,
        "precision_ci_lo": round(lo, 6) if lo == lo else None,
        "precision_ci_hi": round(hi, 6) if hi == hi else None,
        "recall": round(recall, 6) if recall == recall else None,
        "lift": round(precision / base, 3) if base and precision == precision else None,
        "positives_in_period": int(y.sum()),
    }


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Population stability index of ``actual`` against ``expected`` deciles."""
    if len(expected) == 0 or len(actual) == 0:
        return float("nan")
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return float("nan")
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(expected, bins=edges)[0] / len(expected)
    a = np.histogram(actual, bins=edges)[0] / len(actual)
    e = np.clip(e, 1e-6, None)
    a = np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


def main() -> int:
    warnings.filterwarnings("ignore")
    labels, label_summary = build_label_table()
    df = pd.read_csv(SCORES_CSV, low_memory=False)
    score_cols = [c for c in df.columns if c.startswith("score_")]

    df = df.merge(
        labels[["ocid", "is_aap_positive", "winner_key", "published_date"]],
        on="ocid", how="left",
    )
    df["is_aap_positive"] = df["is_aap_positive"].fillna(0).astype(int)

    ranks = df[score_cols].rank(pct=True)
    df["score_mean_rank"] = ranks.mean(axis=1)
    w = json.loads(
        (RESULTS / "methodology" / "agreement_matrix.json").read_text(encoding="utf-8")
    ).get("ensemble_learned_weights") if (RESULTS / "methodology" / "agreement_matrix.json").exists() else {}
    if w:
        df["score_weighted_rank"] = sum(
            float(w.get(c[len("score_"):], 1 / len(score_cols))) * ranks[c] for c in score_cols
        )
    else:  # neutral weights if 13 has not run yet
        df["score_weighted_rank"] = df["score_mean_rank"]

    pub = pd.to_datetime(df["published_date"], errors="coerce", utc=True, format="mixed")
    df["year"] = pub.dt.year.fillna(0).astype(int)
    df["period"] = np.where(df["year"] <= 2021, TUNE_PERIOD, TEST_PERIOD)

    y = df["is_aap_positive"].to_numpy()
    votes = df["n_models_flagging"].fillna(0).astype(int).to_numpy()

    # ------------------------------------------------------------------
    # candidate thresholds: numeric cuts estimated on the TUNE period only
    # ------------------------------------------------------------------
    tune_mask = (df["period"] == TUNE_PERIOD).to_numpy()
    candidates: list[dict] = [
        # reference rules: what a "do nothing" / "flag everything" policy costs,
        # so the cost minimiser can never look better than it is by construction
        {"rule": "baseline:no_flag", "score_col": "baseline_no_flag",
         "threshold": float("inf"), "selection": "reference: flag nothing"},
        {"rule": "baseline:flag_all", "score_col": "baseline_flag_all",
         "threshold": -float("inf"), "selection": "reference: flag everything"},
    ]

    for k in (1, 2, 3, 4):
        candidates.append({
            "rule": f"votes>={k}",
            "score_col": "votes",
            "threshold": float(k),
            "selection": "structural (vote count), not fitted",
        })

    for col in ("max_score", "score_mean_rank", "score_weighted_rank"):
        vals = df.loc[tune_mask, col].to_numpy()
        for load in TARGET_LOADS:
            if load > tune_mask.sum():
                continue
            thr = top_threshold(vals, load)
            candidates.append({
                "rule": f"{col}@top{load}_of_tune",
                "score_col": col,
                "threshold": round(thr, 6),
                "selection": f"top-{load} quantile of {col} on {TUNE_PERIOD}",
            })
        for cut in ROUND_CUTS:
            candidates.append({
                "rule": f"{col}>={cut}",
                "score_col": col,
                "threshold": cut,
                "selection": "round cut, not fitted",
            })

    # evaluate every candidate on both periods with the *same* numeric cut
    sweep_rows = []
    for cand in candidates:
        col = cand["score_col"]
        if col == "votes":
            full_mask = votes >= cand["threshold"]
        elif col == "baseline_no_flag":
            full_mask = np.zeros(len(df), dtype=bool)
        elif col == "baseline_flag_all":
            full_mask = np.ones(len(df), dtype=bool)
        else:
            full_mask = df[col].to_numpy() >= cand["threshold"]
        for period in ("all", TUNE_PERIOD, TEST_PERIOD):
            sel = np.ones(len(df), dtype=bool) if period == "all" else (
                df["period"] == period).to_numpy()
            sub_y = y[sel]
            sub_m = full_mask[sel]
            row = {
                "rule": cand["rule"],
                "score_col": col,
                "threshold": cand["threshold"],
                "selection": cand["selection"],
                "period": period,
                **rule_metrics(sub_y, sub_m),
            }
            for miss in MISS_PRICES:
                row[f"cost_miss_{miss}"] = int(row["fp"]) * C_REVIEW + int(row["fn"]) * miss
            sweep_rows.append(row)

    sweep = pd.DataFrame(sweep_rows)
    sweep.to_csv(TABLES / "threshold_sweep.csv", index=False)

    # ------------------------------------------------------------------
    # choose the boundary on the tune period, report it on the test period
    # ------------------------------------------------------------------
    pick_rows = []
    for miss in MISS_PRICES:
        cost_col = f"cost_miss_{miss}"
        tune = sweep[(sweep["period"] == TUNE_PERIOD)
                     & (~sweep["rule"].str.startswith("baseline:"))]
        best = tune.loc[tune[cost_col].idxmin()]

        def _ref(rule: str, period: str) -> int | None:
            hit = sweep[(sweep["period"] == period) & (sweep["rule"] == rule)]
            return int(hit.iloc[0][cost_col]) if len(hit) else None

        row = {
            "c_miss": miss,
            "chosen_rule": best["rule"],
            "threshold": best["threshold"],
            "tune_n_flagged": int(best["n_flagged"]),
            "tune_precision": best["precision"],
            "tune_recall": best["recall"],
            "tune_cost": int(best[cost_col]),
            "tune_cost_if_no_flag": _ref("baseline:no_flag", TUNE_PERIOD),
            "tune_cost_flag_all": _ref("baseline:flag_all", TUNE_PERIOD),
        }
        test = sweep[(sweep["period"] == TEST_PERIOD) & (sweep["rule"] == best["rule"])]
        if len(test):
            t = test.iloc[0]
            row.update(
                test_n_flagged=int(t["n_flagged"]),
                test_precision=t["precision"],
                test_recall=t["recall"],
                test_cost=int(t[cost_col]),
            )
        row["test_cost_if_no_flag"] = _ref("baseline:no_flag", TEST_PERIOD)
        row["test_cost_flag_all"] = _ref("baseline:flag_all", TEST_PERIOD)
        row["chosen_beats_no_flag_on_test"] = (
            row.get("test_cost") is not None
            and row["test_cost_if_no_flag"] is not None
            and row["test_cost"] < row["test_cost_if_no_flag"]
        )
        baseline = sweep[(sweep["period"] == TEST_PERIOD) & (sweep["rule"] == "votes>=3")]
        if len(baseline):
            b = baseline.iloc[0]
            row.update(
                production_votes_ge_3_test_precision=b["precision"],
                production_votes_ge_3_test_recall=b["recall"],
                production_votes_ge_3_test_cost=int(b[cost_col]),
            )
        pick_rows.append(row)
    picks = pd.DataFrame(pick_rows)
    picks.to_csv(TABLES / "threshold_temporal_split.csv", index=False)

    # ------------------------------------------------------------------
    # drift
    # ------------------------------------------------------------------
    drift_rows = []
    try:
        from scipy.stats import ks_2samp
    except Exception:  # noqa: BLE001
        ks_2samp = None

    for col in ("max_score", "score_mean_rank", "score_weighted_rank"):
        a = df.loc[df["period"] == TUNE_PERIOD, col].to_numpy()
        b = df.loc[df["period"] == TEST_PERIOD, col].to_numpy()
        stat, pvalue = (ks_2samp(a, b).statistic, ks_2samp(a, b).pvalue) if ks_2samp else (None, None)
        drift_rows.append({
            "measure": col,
            "tune_median": round(float(np.median(a)), 6),
            "test_median": round(float(np.median(b)), 6),
            "tune_p95": round(float(np.quantile(a, 0.95)), 6),
            "test_p95": round(float(np.quantile(b, 0.95)), 6),
            "ks_statistic": round(float(stat), 6) if stat == stat else None,
            "ks_pvalue": float(f"{pvalue:.3g}") if pvalue == pvalue else None,
            "psi": round(psi(a, b), 6),
        })

    by_year = (
        df.groupby("year")
        .agg(
            n=("ocid", "size"),
            median_max_score=("max_score", "median"),
            p95_max_score=("max_score", lambda s: float(np.quantile(s, 0.95))),
            share_votes_ge_1=("n_models_flagging", lambda s: float((s >= 1).mean())),
            share_votes_ge_3=("n_models_flagging", lambda s: float((s >= 3).mean())),
            share_mad_flag=("flag_statistical_mad_zscore", "mean"),
            share_if_flag=("flag_isolation_forest", "mean"),
            share_lof_flag=("flag_local_outlier_factor", "mean"),
            share_svm_flag=("flag_one_class_svm", "mean"),
            n_positive=("is_aap_positive", "sum"),
        )
        .reset_index()
    )
    for c in ("share_votes_ge_1", "share_votes_ge_3", "share_mad_flag", "share_if_flag",
              "share_lof_flag", "share_svm_flag"):
        by_year[c] = by_year[c].round(6)
    by_year.to_csv(TABLES / "drift_by_year.csv", index=False)
    pd.DataFrame(drift_rows).to_csv(TABLES / "drift_periods.csv", index=False)

    summary = {
        "production_boundary": "votes >= 3 of 4 detectors (bands low/medium/high/critical)",
        "tune_period": TUNE_PERIOD,
        "test_period": TEST_PERIOD,
        "external_label": {
            "positive_procedures": int(y.sum()),
            "distinct_suppliers": label_summary["n_distinct_matched_suppliers"],
            "positive_tune": int(y[tune_mask].sum()),
            "positive_test": int((~tune_mask & (y == 1)).sum()),
        },
        "cost_model": {
            "c_review": C_REVIEW,
            "miss_prices_tested": list(MISS_PRICES),
            "formula": "cost = FP * c_review + FN * c_miss, computed against the weak AAP label",
        },
        "chosen_on_tune": pick_rows,
        "drift": drift_rows,
        "overfitting_warning": (
            "Threshold selection uses 194 positive procedures from 17 suppliers in the tune "
            "period. The chosen cut is a candidate for review, not a discovered optimum; the "
            "test-period columns are the honest check and the Wilson intervals are wide."
        ),
        "disclaimer": "Indicators of potential risk, not evidence of corruption.",
    }
    out_dir = RESULTS / "methodology"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "threshold_calibration.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("temporal split: threshold chosen on tune period, applied unchanged to test")
    print(picks.to_string(index=False))
    print("\ndrift between periods:")
    print(pd.DataFrame(drift_rows).to_string(index=False))
    print("\nby year:")
    print(by_year.to_string(index=False))
    print(f"\ntable  -> {TABLES / 'threshold_sweep.csv'}")
    print(f"table  -> {TABLES / 'threshold_temporal_split.csv'}")
    print(f"table  -> {TABLES / 'drift_by_year.csv'}")
    print(f"report -> {out_dir / 'threshold_calibration.json'}")
    _plot(sweep, by_year, df, y)
    return 0


def _plot(sweep: pd.DataFrame, by_year: pd.DataFrame, df: pd.DataFrame, y: np.ndarray) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")
        return

    fig, axes = plt.subplots(1, 3, figsize=(17, 5))

    # precision vs review load, tune vs test
    ax = axes[0]
    for col, color in (("max_score", "tab:blue"), ("score_mean_rank", "tab:orange"),
                       ("score_weighted_rank", "tab:green")):
        sub = sweep[(sweep["score_col"] == col) & (sweep["rule"].str.startswith(f"{col}@top"))]
        for period, ls in ((TUNE_PERIOD, "-"), (TEST_PERIOD, "--")):
            s2 = sub[sub["period"] == period].sort_values("n_flagged")
            ax.plot(s2["n_flagged"], s2["precision"], marker="o", ls=ls, color=color,
                    label=f"{col} / {period}")
    votes3 = sweep[sweep["rule"] == "votes>=3"]
    for period, ls in ((TUNE_PERIOD, "-"), (TEST_PERIOD, "--")):
        s2 = votes3[votes3["period"] == period]
        if len(s2):
            ax.plot([s2.iloc[0]["n_flagged"]], [s2.iloc[0]["precision"]], marker="*",
                    ms=15, color="black", ls=ls)
    ax.axhline(float(y.mean()), color="grey", ls=":", label="base rate")
    ax.set_xscale("log")
    ax.set_xlabel("review load (procedures flagged)")
    ax.set_ylabel("precision vs AAP label")
    ax.set_title("Boundary sweep: precision vs load\n(solid = tune, dashed = test)")
    ax.legend(fontsize=6)

    # cost curves
    ax = axes[1]
    miss = 50
    for rule in ("votes>=3", "max_score@top3031_of_tune", "score_weighted_rank@top3031_of_tune"):
        s2 = sweep[(sweep["rule"] == rule)]
        if not len(s2):
            continue
        xs = []
        ys = []
        for period in ("all", TUNE_PERIOD, TEST_PERIOD):
            r = s2[s2["period"] == period]
            if len(r):
                xs.append(period)
                ys.append(r.iloc[0][f"cost_miss_{miss}"])
        ax.plot(xs, ys, marker="o", label=rule)
    ax.set_title(f"Business cost, c_miss = {miss} x review cost")
    ax.set_ylabel("cost (FP*1 + FN*50)")
    ax.legend(fontsize=7)

    # drift of the production score
    ax = axes[2]
    for period, color in ((TUNE_PERIOD, "tab:blue"), (TEST_PERIOD, "tab:red")):
        vals = df.loc[df["period"] == period, "max_score"]
        ax.hist(vals, bins=60, histtype="step", density=True, color=color, label=period)
    ax2 = ax.twinx()
    ax2.plot(by_year["year"], by_year["share_votes_ge_3"], marker="s", color="black",
             label="share votes>=3")
    ax2.set_ylabel("share flagged by consensus")
    ax.set_xlabel("max_score (production percentile)")
    ax.set_ylabel("density")
    ax.set_title("Score drift by period + consensus share by year")
    ax.legend(fontsize=8, loc="upper left")
    ax2.legend(fontsize=8, loc="upper right")

    fig.suptitle("Decision boundary calibration - indicator of potential risk, "
                 "not evidence of corruption", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "threshold_calibration.png", dpi=140)
    print(f"figure -> {FIGURES / 'threshold_calibration.png'}")


if __name__ == "__main__":
    raise SystemExit(main())
