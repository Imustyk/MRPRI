"""Step 13 (methodology cycle, step 4) - detector agreement matrix.

Four detectors vote; the production band rule counts the votes (>= 3 is
"critical"). This stage answers, with numbers rather than adjectives:

* how much the detectors actually agree - pairwise Cohen's kappa and Jaccard on
  the binary flags, plus rank agreement (Spearman on percentile ranks and
  Jaccard of the top-k ranked sets, since two detectors can flag different rows
  yet rank them identically);
* how the votes distribute and what share of procedures the detectors disagree
  on;
* whether an alternative to plain voting does better - mean-percentile rank
  averaging and a weighted ensemble - compared at the *same review load* on the
  external AAP label and on agreement with the individual detectors.

Usage:
    .venv/bin/python scripts/13_agreement_matrix.py
"""

from __future__ import annotations

import json
import sys
import warnings
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import FIGURES, RESULTS, TABLES  # noqa: E402
from src.mtender.eval_metrics import cohen_kappa, jaccard, precision_at_k, recall_at_k  # noqa: E402
from src.mtender.external_labels import build_label_table  # noqa: E402

SCORES_CSV = TABLES / "tender_anomaly_scores.csv"

#: Review loads at which the alternative rules are compared with plain voting.
LOADS = (500, 2000, 3031, 7662)
#: Top-k sets used for rank-overlap Jaccard between detectors.
RANK_KS = (200, 1000, 3031)


def percentile_ranks(df: pd.DataFrame, score_cols: list[str]) -> pd.DataFrame:
    """Per-detector percentile rank (0-1, higher = more unusual)."""
    return df[score_cols].rank(pct=True)


def topk_mask(values: np.ndarray, k: int) -> np.ndarray:
    """Boolean mask of the ``k`` largest values (ties broken by position)."""
    k = min(int(k), len(values))
    if k <= 0:
        return np.zeros(len(values), dtype=bool)
    order = np.argsort(-values, kind="stable")[:k]
    mask = np.zeros(len(values), dtype=bool)
    mask[order] = True
    return mask


def main() -> int:
    warnings.filterwarnings("ignore")
    df = pd.read_csv(SCORES_CSV, low_memory=False)
    score_cols = [c for c in df.columns if c.startswith("score_")]
    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    detectors = [c[len("flag_"):] for c in flag_cols]
    n = len(df)

    ranks = percentile_ranks(df, score_cols)
    flags = {d: df[f"flag_{d}"].fillna(0).astype(int).to_numpy() for d in detectors}
    rank_values = {d: ranks[f"score_{d}"].to_numpy() for d in detectors}

    # ---- pairwise agreement ---------------------------------------------
    rows = []
    for a, b in combinations(detectors, 2):
        fa, fb = flags[a], flags[b]
        both = int(((fa == 1) & (fb == 1)).sum())
        either = int(((fa == 1) | (fb == 1)).sum())
        row = {
            "detector_a": a,
            "detector_b": b,
            "observed_agreement": round(float(np.mean(fa == fb)), 6),
            "cohen_kappa": round(cohen_kappa(fa, fb), 6),
            "jaccard_flags": round(jaccard(fa, fb), 6),
            "n_flags_a": int(fa.sum()),
            "n_flags_b": int(fb.sum()),
            "n_both": both,
            "n_either": either,
            "spearman_rank": round(float(pd.Series(rank_values[a]).corr(
                pd.Series(rank_values[b]), method="spearman")), 6),
        }
        for k in RANK_KS:
            ma, mb = topk_mask(rank_values[a], k), topk_mask(rank_values[b], k)
            row[f"jaccard_top{k}"] = round(jaccard(ma, mb), 6)
        rows.append(row)
    pairwise = pd.DataFrame(rows)
    pairwise.to_csv(TABLES / "agreement_pairwise.csv", index=False)

    # ---- vote distribution ----------------------------------------------
    votes = df["n_models_flagging"].fillna(0).astype(int)
    vote_dist = (
        votes.value_counts().sort_index().rename_axis("n_models_flagging")
        .to_frame("n_procedures")
        .reset_index()
    )
    vote_dist["share"] = (vote_dist["n_procedures"] / n).round(6)
    vote_dist["cum_share"] = vote_dist["share"].cumsum().round(6)
    vote_dist["band"] = vote_dist["n_models_flagging"].map(
        lambda v: "critical" if v >= 3 else "high" if v == 2 else "medium" if v == 1 else "low"
    )
    vote_dist.to_csv(TABLES / "agreement_vote_distribution.csv", index=False)

    unanimous = float((votes.isin([0, 4])).mean())
    any_flag = int((votes > 0).sum())
    disagreement = {
        "n_procedures": n,
        "share_unanimous_all_clear_or_all_flag": round(unanimous, 6),
        "share_partial_agreement_1_to_3": round(1.0 - unanimous, 6),
        "n_flagged_by_any": any_flag,
        "share_disagreement_among_flagged": round(
            float(votes.between(1, 3).sum()) / any_flag, 6
        ) if any_flag else None,
        "mean_pairwise_kappa": round(float(pairwise["cohen_kappa"].mean()), 6),
        "min_pairwise_kappa": round(float(pairwise["cohen_kappa"].min()), 6),
        "mean_pairwise_jaccard_flags": round(float(pairwise["jaccard_flags"].mean()), 6),
        "mean_pairwise_spearman_rank": round(float(pairwise["spearman_rank"].mean()), 6),
    }

    # ---- alternatives to plain voting ------------------------------------
    labels, label_summary = build_label_table()
    y = (
        df[["ocid"]].merge(labels[["ocid", "is_aap_positive"]], on="ocid", how="left")
        ["is_aap_positive"].fillna(0).astype(int).to_numpy()
    )

    mean_rank = ranks.mean(axis=1).to_numpy()
    # weights: proportional to each detector's own lift@3031 on the external
    # label, floored at 0 so a detector with no signal cannot receive negative
    # weight. Equal weights are kept as the neutral baseline.
    raw_weights = {}
    for d in detectors:
        s = ranks[f"score_{d}"].to_numpy()
        p = precision_at_k(y, s, 3031)
        raw_weights[d] = max(p - float(y.mean()), 0.0)
    total = sum(raw_weights.values())
    w_learned = {d: (raw_weights[d] / total if total > 0 else 1 / len(detectors))
                 for d in detectors}
    weighted = sum(w_learned[d] * ranks[f"score_{d}"].to_numpy() for d in detectors)

    rule_scores = {
        "votes_majority_3_of_4": df["n_models_flagging"].fillna(0).astype(int).to_numpy()
        * 10.0 + df["max_score"].to_numpy(),          # production rule, as a ranking
        "production_max_score": df["max_score"].to_numpy(),
        "mean_percentile_rank": mean_rank,
        "weighted_percentile_rank": weighted,
    }

    ens_rows = []
    prod_mask = topk_mask(df["max_score"].to_numpy(), 3031)
    for name, values in rule_scores.items():
        for load in LOADS:
            mask = topk_mask(values, load)
            ens_rows.append({
                "rule": name,
                "review_load": load,
                "n_selected": int(mask.sum()),
                "precision_vs_aap": round(float(y[mask].mean()), 6) if mask.any() else None,
                "recall_vs_aap": round(float(y[mask].sum() / max(y.sum(), 1)), 6),
                "lift_vs_aap": round(float(y[mask].mean() / y.mean()), 3)
                if mask.any() and y.mean() else None,
                "jaccard_vs_production_top3031": round(jaccard(mask, prod_mask), 6),
                "share_with_consensus_votes_ge3": round(
                    float((df.loc[mask, "n_models_flagging"] >= 3).mean()), 6
                ) if mask.any() else None,
            })
    ensembles = pd.DataFrame(ens_rows)
    ensembles.to_csv(TABLES / "ensemble_comparison.csv", index=False)

    learned_weights = {d: round(v, 6) for d, v in w_learned.items()}
    summary = {
        "detectors": detectors,
        "n_procedures": n,
        "vote_distribution": {
            str(int(r["n_models_flagging"])): int(r["n_procedures"])
            for _, r in vote_dist.iterrows()
        },
        **disagreement,
        "ensemble_weight_source": (
            "per-detector lift@3031 against the AAP label, floored at 0; equal weights "
            "kept as the neutral baseline because the label is weak (18 suppliers)"
        ),
        "ensemble_learned_weights": learned_weights,
        "circularity_note": (
            "Detector agreement is measured against the detectors themselves. It is a "
            "reliability statement (do the methods repeat each other?), never a validity "
            "statement (is the flagged row actually problematic?). Validity evidence is "
            "the external AAP comparison in scripts/12, and it is weak by construction."
        ),
    }
    out_dir = RESULTS / "methodology"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "agreement_matrix.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("pairwise agreement:")
    print(pairwise.to_string(index=False))
    print("\nvote distribution:")
    print(vote_dist.to_string(index=False))
    print("\nalternatives at matched review load:")
    print(ensembles.to_string(index=False))
    print(f"\ntable  -> {TABLES / 'agreement_pairwise.csv'}")
    print(f"table  -> {TABLES / 'agreement_vote_distribution.csv'}")
    print(f"table  -> {TABLES / 'ensemble_comparison.csv'}")
    print(f"report -> {out_dir / 'agreement_matrix.json'}")
    _plot(pairwise, vote_dist, ranks, detectors, y)
    return 0


def _plot(pairwise: pd.DataFrame, vote_dist: pd.DataFrame, ranks: pd.DataFrame,
          detectors: list[str], y: np.ndarray) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")
        return
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))

    # matrix of kappa
    ax = axes[0]
    size = len(detectors)
    mat = np.eye(size)
    for i, a in enumerate(detectors):
        for j, b in enumerate(detectors):
            if i == j:
                continue
            hit = pairwise[
                ((pairwise["detector_a"] == a) & (pairwise["detector_b"] == b))
                | ((pairwise["detector_a"] == b) & (pairwise["detector_b"] == a))
            ]
            mat[i, j] = float(hit["cohen_kappa"].iloc[0]) if len(hit) else np.nan
    im = ax.imshow(mat, vmin=0, vmax=1, cmap="Blues")
    for i in range(size):
        for j in range(size):
            ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=9,
                    color="white" if mat[i, j] > 0.6 else "black")
    ax.set_xticks(range(size), [d.replace("_", "\n") for d in detectors], fontsize=7)
    ax.set_yticks(range(size), [d.replace("_", "\n") for d in detectors], fontsize=7)
    ax.set_title("Cohen's kappa (binary flags)")
    fig.colorbar(im, ax=ax, fraction=0.046)

    ax = axes[1]
    ax.bar(vote_dist["n_models_flagging"].astype(str), vote_dist["n_procedures"],
           color=["#9ecae1", "#c6dbef", "#fdae6b", "#f16913", "#a50f15"])
    ax.set_xlabel("number of detectors flagging")
    ax.set_ylabel("procedures")
    ax.set_title("Vote distribution (bands = vote counts)")
    for i, row in vote_dist.iterrows():
        ax.text(i, row["n_procedures"], f"{row['share']:.1%}", ha="center",
                va="bottom", fontsize=8)

    ax = axes[2]
    for d in detectors:
        r = ranks[f"score_{d}"].to_numpy()
        pos = np.sort(r[y == 1])
        ax.hist(pos, bins=20, histtype="step", density=True, label=d.replace("_", " "))
    ax.set_xlabel("detector percentile rank")
    ax.set_ylabel("density")
    ax.set_title("AAP-positive procedures across detectors' ranks")
    ax.legend(fontsize=6)

    fig.suptitle("Detector agreement: reliability, not validity "
                 "(an indicator of potential risk, not evidence of corruption)",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "agreement_matrix.png", dpi=140)
    print(f"figure -> {FIGURES / 'agreement_matrix.png'}")


if __name__ == "__main__":
    raise SystemExit(main())
