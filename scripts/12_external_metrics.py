"""Step 12 (methodology cycle, step 2) - external validation metrics on raw data.

Takes **all 22 AAP interdiction entries**, finds every procedure of their matched
suppliers in the *full* 152,378-procedure corpus (not the historical 1,500-row
slice), and evaluates the current ranking against that weak external label:

* per entry - best / median rank, percentile, band, share of its procedures in
  ``medium+`` and ``high+``;
* per ranking rule - precision@k, recall@k, lift@k, ROC-AUC, PR-AUC, each with a
  bootstrap 95% confidence interval, resampled at the *supplier* level as well as
  at the procedure level (600 procedures from one supplier are not 600 facts).

Nothing here is evidence of wrongdoing by a supplier; the label means "the
supplier appears on the official AAP interdiction list", nothing more.

Usage:
    .venv/bin/python scripts/12_external_metrics.py [--boot 1000]
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import FIGURES, RESULTS, TABLES  # noqa: E402
from src.mtender.eval_metrics import (  # noqa: E402
    bootstrap_ci,
    lift_at_k,
    precision_at_k,
    pr_auc,
    recall_at_k,
    roc_auc,
)
from src.mtender.external_labels import build_label_table  # noqa: E402

SCORES_CSV = TABLES / "tender_anomaly_scores.csv"
#: Review budgets an auditor could plausibly be given, in procedures.
K_VALUES = (50, 100, 200, 500, 1000, 2000, 3031, 7662)

#: Only the headline budgets get a bootstrap CI; the rest are point estimates
#: (a bootstrap pass over 152k rows costs ~10 s per replication set).
BOOT_K_VALUES = (200, 1000)

#: Year of publication used for the temporal split (tune 2018-2021, check 2022-2024).
SPLIT_YEAR = 2022


def band_of(n_models: int) -> str:
    """The dashboard's band rule (0 low, 1 medium, 2 high, 3+ critical)."""
    if n_models >= 3:
        return "critical"
    if n_models == 2:
        return "high"
    if n_models == 1:
        return "medium"
    return "low"


def mean_rank_percentile(scores: pd.DataFrame, score_cols: list[str]) -> pd.Series:
    """Ensemble candidate: mean of the four per-detector percentile ranks."""
    return scores[score_cols].rank(pct=True).mean(axis=1)


def add_ranking_columns(df: pd.DataFrame, score_cols: list[str]) -> pd.DataFrame:
    """Attach ``rank_*`` / ``pct_*`` columns for every ranking rule compared."""
    n = len(df)
    df = df.copy()
    df["rank_production"] = df["max_score"].rank(ascending=False, method="average")
    df["pct_production"] = 1.0 - (df["rank_production"] - 1) / max(n - 1, 1)
    mean_pct = mean_rank_percentile(df, score_cols)
    df["score_mean_rank"] = mean_pct
    df["rank_mean_rank"] = mean_pct.rank(ascending=False, method="average")
    df["pct_mean_rank"] = 1.0 - (df["rank_mean_rank"] - 1) / max(n - 1, 1)
    # votes as a ranking: votes dominate, max_score only breaks ties (it is < 1)
    vote_key = df["n_models_flagging"].astype(float) * 10.0 + df["max_score"]
    df["rank_votes"] = vote_key.rank(ascending=False, method="average")
    df["pct_votes"] = 1.0 - (df["rank_votes"] - 1) / max(n - 1, 1)
    return df


def entry_rankings(df: pd.DataFrame, per_entry: list[dict]) -> pd.DataFrame:
    """One row per AAP entry: where its procedures sit in the ranking."""
    scored = df[df["is_aap_positive"] == 1]
    rows = []
    for rec in per_entry:
        nrs = {int(rec["blacklist_nr"])}
        subset = scored[scored["blacklist_nrs"].fillna("").map(
            lambda v: bool(v) and nrs.issubset({int(x) for x in v.split(";")})
        )]
        out = {
            "blacklist_nr": rec["blacklist_nr"],
            "blacklist_name": rec["blacklist_name"],
            "ground": rec["ground"],
            "decision_date": rec["decision_date"],
            "suspended": rec["suspended"],
            "match_level": rec["match_level"],
            "n_procedures": int(len(subset)),
        }
        if len(subset):
            n = len(df)
            best_rank = int(subset["rank_production"].min())
            out.update(
                best_rank=best_rank,
                best_percentile=round(float(1 - (best_rank - 1) / max(n - 1, 1)) * 100, 2),
                median_percentile=round(float(subset["pct_production"].median() * 100), 2),
                max_percentile=round(float(subset["pct_production"].max() * 100), 2),
                band_counts=json.dumps(
                    {b: int(c) for b, c in
                     subset["band"].value_counts().sort_index().items()},
                    ensure_ascii=False,
                ),
                share_medium_plus=round(float((subset["band"] != "low").mean()), 4),
                share_high_plus=round(float(subset["band"].isin(["high", "critical"]).mean()), 4),
                share_consensus=round(float((subset["n_models_flagging"] >= 3).mean()), 4),
            )
        else:
            out.update(
                best_rank=None, best_percentile=None, median_percentile=None,
                max_percentile=None, band_counts="{}",
                share_medium_plus=None, share_high_plus=None, share_consensus=None,
            )
        rows.append(out)
    return pd.DataFrame(rows)


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--boot", type=int, default=1000, help="bootstrap replications")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    labels, label_summary = build_label_table()
    scores = pd.read_csv(SCORES_CSV, low_memory=False)
    score_cols = [c for c in scores.columns if c.startswith("score_")]

    df = scores.merge(
        labels[["ocid", "winner_key", "match_level", "blacklist_nrs", "is_aap_positive",
                "published_date", "tender_start"]],
        on="ocid",
        how="left",
    )
    df["is_aap_positive"] = df["is_aap_positive"].fillna(0).astype(int)
    df = add_ranking_columns(df, score_cols)
    df["band"] = df["n_models_flagging"].map(lambda n: band_of(int(n)))
    pub = pd.to_datetime(df["published_date"], errors="coerce", utc=True, format="mixed")
    df["year"] = pub.dt.year.fillna(0).astype(int)
    df["period"] = np.where(df["year"] <= 2021, "2018-2021", "2022-2024")

    y = df["is_aap_positive"].to_numpy()
    # Guard against exactly the class of silent-corruption bug this cycle keeps
    # finding: a labelling bug would inflate the base rate to tens of percent,
    # and every "precision" computed from it would look impressive while meaning
    # nothing. 22 suppliers cannot plausibly hold a fifth of the corpus.
    if y.mean() > 0.05:
        raise SystemExit(
            f"sanity check failed: {int(y.sum()):,} procedures labelled positive "
            f"({y.mean():.1%}). The AAP list covers a few dozen suppliers; a base "
            "rate that high means the label join is broken."
        )
    print(f"procedures: {len(df):,}   positive: {int(y.sum()):,}   "
          f"base rate: {y.mean():.5f}")

    rankings = {
        "production_max_score": "pct_production",
        "mean_rank_ensemble": "pct_mean_rank",
        "votes_then_score": "pct_votes",
    }

    # ---- per-entry table -------------------------------------------------
    entries = entry_rankings(df, label_summary["per_entry"])
    entries.to_csv(TABLES / "aap_entry_rankings.csv", index=False)

    # ---- matched procedures ---------------------------------------------
    matched = df[df["match_level"].notna()].copy()
    matched_cols = [
        "ocid", "blacklist_nrs", "match_level", "winner_name", "winner_identifier",
        "buyer_name", "published_date", "award_value", "max_score", "score_mean_rank",
        "n_models_flagging", "band", "rank_production", "pct_production", "year", "period",
    ]
    matched.reindex(columns=matched_cols).to_csv(
        TABLES / "aap_procedure_matches.csv", index=False
    )

    # ---- metrics ---------------------------------------------------------
    metric_rows: list[dict] = []

    def record(rule: str, period: str, name: str, value: float,
               ci: dict | None = None, note: str = "") -> None:
        row = {
            "ranking_rule": rule,
            "period": period,
            "metric": name,
            "value": None if value != value else round(float(value), 6),
            "ci_lo": None if not ci else round(ci["lo"], 6),
            "ci_hi": None if not ci else round(ci["hi"], 6),
            "n_boot": None if not ci else ci["n_boot"],
            "resample_unit": None if not ci else ci.get("unit", ""),
            "n_rows": int(len(_mask(period))),
            "n_positive": int(_mask(period)["is_aap_positive"].sum()),
            "note": note,
        }
        metric_rows.append(row)

    def _mask(period: str) -> pd.DataFrame:
        return df if period == "all" else df[df["period"] == period]

    supplier_cluster = df["winner_key"].fillna("<no winner name>").to_numpy()

    for period in ("all", "2018-2021", "2022-2024"):
        sub = _mask(period)
        y_p = sub["is_aap_positive"].to_numpy()
        if y_p.sum() == 0:
            print(f"[{period}] no positive labels - metrics skipped")
            continue
        for rule, col in rankings.items():
            s = sub[col].to_numpy()
            record(rule, period, "roc_auc", roc_auc(y_p, s),
                   bootstrap_ci(y_p, s, roc_auc, args.boot, args.seed),
                   "weak supplier-level label")
            record(rule, period, "pr_auc", pr_auc(y_p, s),
                   bootstrap_ci(y_p, s, pr_auc, args.boot, args.seed),
                   "weak supplier-level label")
            record(rule, period, "pr_auc_base_rate", float(y_p.mean()), None,
                   "share of positive procedures; PR-AUC must be read against this")
            for k in K_VALUES:
                if k > len(sub):
                    continue
                ci = None
                if k in BOOT_K_VALUES:
                    ci = bootstrap_ci(y_p, s, lambda a, b, _k=k: precision_at_k(a, b, _k),
                                      args.boot, args.seed)
                record(rule, period, f"precision@{k}", precision_at_k(y_p, s, k), ci, "")
                if period == "all":
                    record(rule, period, f"recall@{k}", recall_at_k(y_p, s, k))
                    record(rule, period, f"lift@{k}", lift_at_k(y_p, s, k))
            # supplier-level resampling for the headline numbers
            record(rule, period, "roc_auc", roc_auc(y_p, s),
                   bootstrap_ci(y_p, s, roc_auc, args.boot, args.seed,
                                cluster=sub["winner_key"].fillna("<none>").to_numpy()),
                   "supplier-level cluster bootstrap")
            record(rule, period, "pr_auc", pr_auc(y_p, s),
                   bootstrap_ci(y_p, s, pr_auc, args.boot, args.seed,
                                cluster=sub["winner_key"].fillna("<none>").to_numpy()),
                   "supplier-level cluster bootstrap")

    # ---- vote rules (decision rules, not rankings) -----------------------
    rule_rows = []
    for votes in (1, 2, 3, 4):
        pred = (df["n_models_flagging"] >= votes).to_numpy()
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / (tp + fn) if tp + fn else float("nan")
        rule_rows.append({
            "rule": f"votes>={votes}",
            "n_flagged": int(pred.sum()),
            "pct_flagged": round(float(pred.mean() * 100), 4),
            "tp": tp, "fp": fp, "fn": fn,
            "precision_vs_aap": round(prec, 6),
            "recall_vs_aap": round(rec, 6),
            "lift_vs_aap": round(prec / float(y.mean()), 3) if prec == prec and y.mean() else None,
        })
    pd.DataFrame(rule_rows).to_csv(TABLES / "external_rule_metrics.csv", index=False)

    metrics_df = pd.DataFrame(metric_rows)
    metrics_df.to_csv(TABLES / "external_metrics.csv", index=False)

    # ---- AAP label distribution over bands/periods -----------------------
    pos = df[df["is_aap_positive"] == 1]
    band_dist = (
        df.groupby("band")["is_aap_positive"]
        .agg(n="size", n_positive="sum")
        .reindex(["low", "medium", "high", "critical"])
        .reset_index()
    )
    band_dist["share_positive"] = (band_dist["n_positive"] / band_dist["n"]).round(6)
    band_dist.to_csv(TABLES / "aap_label_by_band.csv", index=False)

    summary = {
        **label_summary,
        "corpus_rows": int(len(df)),
        "positive_procedures": int(y.sum()),
        "positive_share": round(float(y.mean()), 6),
        "positive_by_period": {
            p: int(df.loc[df["period"] == p, "is_aap_positive"].sum())
            for p in ("2018-2021", "2022-2024")
        },
        "positive_by_year": {
            str(k): int(v) for k, v in sorted(df.groupby("year")["is_aap_positive"].sum().items())
        },
        "median_best_percentile_of_entries": float(
            entries["best_percentile"].median()
        ) if entries["best_percentile"].notna().any() else None,
        "entries_with_procedures": int(entries["n_procedures"].gt(0).sum()),
        "boot_replications": args.boot,
        "split_rule": f"tune on published year <= {SPLIT_YEAR - 1}, check on >= {SPLIT_YEAR}",
        "disclaimer": (
            "Indicators of potential risk, not evidence of corruption. The external label "
            "is the official AAP interdiction list, matched on company name only."
        ),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_json = RESULTS / "methodology"
    out_json.mkdir(exist_ok=True)
    (out_json / "external_validation_metrics.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---- console report --------------------------------------------------
    print("\nper-entry ranking (AAP -> corpus):")
    show = entries[["blacklist_nr", "blacklist_name", "match_level", "n_procedures",
                    "best_percentile", "median_percentile", "share_medium_plus",
                    "share_high_plus"]]
    print(show.to_string(index=False))

    print("\nheadline metrics (period=all, production ranking):")
    head = metrics_df[
        (metrics_df["period"] == "all")
        & (metrics_df["ranking_rule"] == "production_max_score")
        & (metrics_df["metric"].isin(["roc_auc", "pr_auc", "pr_auc_base_rate",
                                      "precision@200", "precision@1000",
                                      "recall@1000", "lift@1000"]))
    ]
    print(head[["metric", "value", "ci_lo", "ci_hi", "resample_unit"]].to_string(index=False))

    print("\nvote rules vs AAP label:")
    print(pd.DataFrame(rule_rows).to_string(index=False))

    print(f"\ntable  -> {TABLES / 'external_metrics.csv'}")
    print(f"table  -> {TABLES / 'aap_entry_rankings.csv'}")
    print(f"table  -> {TABLES / 'aap_procedure_matches.csv'}")
    print(f"report -> {out_json / 'external_validation_metrics.json'}")
    _plot(metrics_df, y, df)
    return 0


def _plot(metrics_df: pd.DataFrame, y: np.ndarray, df: pd.DataFrame) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")
        return
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    ks = [k for k in K_VALUES]
    ax = axes[0]
    for rule, col in (("production_max_score", "tab:blue"),
                      ("mean_rank_ensemble", "tab:orange"),
                      ("votes_then_score", "tab:green")):
        sub = metrics_df[(metrics_df["ranking_rule"] == rule)
                         & (metrics_df["period"] == "all")
                         & (metrics_df["metric"].str.startswith("precision@"))].copy()
        sub["k"] = sub["metric"].str.split("@").str[1].astype(int)
        sub = sub.sort_values("k")
        ax.plot(sub["k"], sub["value"], marker="o", label=rule, color=col)
        ok = sub.dropna(subset=["ci_lo"])
        if len(ok):
            ax.fill_between(ok["k"], ok["ci_lo"], ok["ci_hi"], color=col, alpha=0.15)
    ax.axhline(float(y.mean()), color="grey", ls="--", lw=1,
               label=f"base rate {y.mean():.4f}")
    ax.set_xscale("log")
    ax.set_xlabel("k (review budget, procedures)")
    ax.set_ylabel("precision@k vs AAP label")
    ax.set_title("Precision@k with 95% bootstrap CI")
    ax.legend(fontsize=8)

    ax = axes[1]
    for rule, col in (("production_max_score", "tab:blue"),
                      ("mean_rank_ensemble", "tab:orange")):
        sub = metrics_df[(metrics_df["ranking_rule"] == rule)
                         & (metrics_df["metric"].isin(["roc_auc", "pr_auc"]))
                         & (metrics_df["metric"].str.startswith(("roc", "pr_auc")))
                         & (metrics_df["resample_unit"] != "supplier-level cluster bootstrap")
                         ].copy()
        sub = sub[sub["metric"].isin(["roc_auc", "pr_auc"])]
        for period, marker in (("2018-2021", "o"), ("2022-2024", "s")):
            s2 = sub[sub["period"] == period]
            xs = np.arange(len(s2)) + (0.0 if rule == "production_max_score" else 0.25)
            ax.errorbar(xs, s2["value"],
                        yerr=[np.array(s2["value"]) - np.array(s2["ci_lo"]),
                              np.array(s2["ci_hi"]) - np.array(s2["value"])],
                        fmt=marker, color=col, capsize=3,
                        label=f"{rule} / {period}")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["ROC-AUC", "PR-AUC"])
    ax.set_ylim(0, 1.05)
    ax.set_title("AUC by period (procedure-level bootstrap)")
    ax.legend(fontsize=7)

    fig.suptitle("External validation on the AAP interdiction list "
                 "(weak supplier-level label, not ground truth)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "external_validation.png", dpi=140)
    print(f"figure -> {FIGURES / 'external_validation.png'}")


if __name__ == "__main__":
    raise SystemExit(main())
