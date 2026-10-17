"""Step 15 (methodology cycle, step 7) - seed robustness of the detectors.

Isolation Forest (tree bootstrap), the LOF fit sample and the One-Class SVM fit
sample are stochastic; the production run fixes ``random_state=42`` once and
never asks what a different seed would have done. This stage reruns the three
stochastic detectors for ``--runs`` seeds (>= 20) and measures:

* per-run counts (detector flags, consensus size, band shares);
* set stability: Jaccard of each run's consensus set and top-200 set against the
  production run (seed 42);
* per-procedure stability: how often a procedure is flagged by >= 3 detectors
  across runs, and how often its *band* changes - the number an analyst would
  see in the dashboard.

The MAD baseline is deterministic (median / MAD of fixed data) and is computed
once; it participates in the vote but is never re-seeded.

Progress is written after every seed so an interrupted run keeps its work.

Usage:
    .venv/bin/python scripts/15_robustness_seeds.py --runs 20 [--seed0 42]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, FIGURES, RESULTS, TABLES  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS  # noqa: E402

BASELINE_SEED = 42
OUTLIER_RATE = 0.05
NEIGHBOURHOOD_FIT_CAP = 20000
PRODUCTION_CSV = TABLES / "tender_anomaly_scores.csv"


def _load_stage06():
    """Import scripts/06 so the MAD baseline is literally the production code."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "06_detect_anomalies.py"
    spec = importlib.util.spec_from_file_location("stage06_detect", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def fit_sample(n_rows: int, cap: int, seed: int) -> np.ndarray:
    if cap >= n_rows:
        return np.arange(n_rows)
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(n_rows, size=cap, replace=False))


def band_vector(votes: np.ndarray) -> np.ndarray:
    """0 low / 1 medium / 2 high / 3 critical, same rule as the dashboard."""
    return np.minimum(votes, 3)


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--seed0", type=int, default=BASELINE_SEED)
    args = ap.parse_args()

    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    X = df[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    from sklearn.preprocessing import StandardScaler

    Xs = StandardScaler().fit_transform(X.values)
    n = len(Xs)
    print(f"{n:,} rows x {len(cols)} features", flush=True)

    stage06 = _load_stage06()
    mad = stage06.statistical_baseline(df, cols)
    mad_flag = mad["is_anomaly"].to_numpy().astype(int)
    print(f"MAD baseline (deterministic): {int(mad_flag.sum()):,} flagged", flush=True)

    seeds = [args.seed0 + i for i in range(args.runs)]
    runs: list[dict] = []
    consensus_sets: dict[int, np.ndarray] = {}
    top200_sets: dict[int, np.ndarray] = {}
    vote_matrix = np.zeros((n, len(seeds)), dtype=np.uint8)
    band_matrix = np.zeros((n, len(seeds)), dtype=np.uint8)
    max_score_matrix = np.zeros((n, len(seeds)), dtype=np.float32)

    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.svm import OneClassSVM

    out_dir = RESULTS / "methodology"
    out_dir.mkdir(exist_ok=True)

    for i, seed in enumerate(seeds):
        t0 = time.time()
        iso = IsolationForest(
            n_estimators=300, contamination=OUTLIER_RATE, random_state=seed, n_jobs=-1
        )
        iso.fit(Xs)
        iso_flag = (iso.predict(Xs) == -1).astype(int)

        rows = fit_sample(n, NEIGHBOURHOOD_FIT_CAP, seed)
        lof = LocalOutlierFactor(n_neighbors=20, contamination=OUTLIER_RATE, novelty=True)
        lof.fit(Xs[rows])
        lof_flag = (lof.predict(Xs) == -1).astype(int)

        svm = OneClassSVM(kernel="rbf", nu=OUTLIER_RATE, gamma="scale")
        svm.fit(Xs[rows])
        svm_flag = (svm.predict(Xs) == -1).astype(int)

        votes = mad_flag + iso_flag + lof_flag + svm_flag
        consensus = (votes >= 3).astype(np.uint8)

        # production ranking = max per-detector percentile rank (same as script 06)
        det_scores = pd.DataFrame({
            "mad": mad["score"].to_numpy(),
            "if": -iso.score_samples(Xs),
            "lof": -lof.score_samples(Xs),
            "svm": -svm.decision_function(Xs),
        })
        max_score = det_scores.rank(pct=True).max(axis=1).to_numpy().astype(np.float32)
        top200 = np.zeros(n, dtype=bool)
        top200[np.argsort(-max_score, kind="stable")[:200]] = True

        vote_matrix[:, i] = votes
        band_matrix[:, i] = band_vector(votes)
        consensus_sets[seed] = consensus.astype(bool)
        top200_sets[seed] = top200
        max_score_matrix[:, i] = max_score

        runs.append({
            "seed": seed,
            "n_mad": int(mad_flag.sum()),
            "n_if": int(iso_flag.sum()),
            "n_lof": int(lof_flag.sum()),
            "n_svm": int(svm_flag.sum()),
            "n_consensus_ge3": int(consensus.sum()),
            "n_votes_ge2": int((votes >= 2).sum()),
            "n_votes_ge1": int((votes >= 1).sum()),
            "seconds": round(time.time() - t0, 1),
        })
        # checkpoint after every seed: an interrupted run keeps its work
        pd.DataFrame(runs).to_csv(TABLES / "seed_stability_runs.csv", index=False)
        print(f"seed {seed}: consensus {int(consensus.sum()):,} "
              f"({runs[-1]['seconds']}s)", flush=True)

    # ---- stability against the production seed ---------------------------
    from src.mtender.eval_metrics import jaccard

    base = consensus_sets[args.seed0]
    top_base = top200_sets[args.seed0]
    for r in runs:
        s = r["seed"]
        r["jaccard_consensus_vs_seed42"] = round(jaccard(base, consensus_sets[s]), 6)
        r["jaccard_top200_vs_seed42"] = round(jaccard(top_base, top200_sets[s]), 6)
    pd.DataFrame(runs).to_csv(TABLES / "seed_stability_runs.csv", index=False)

    # ---- per-procedure stability ----------------------------------------
    consensus_freq = np.mean(
        np.vstack([consensus_sets[s].astype(float) for s in seeds]), axis=0
    )
    votes_min = vote_matrix.min(axis=1)
    votes_max = vote_matrix.max(axis=1)
    votes_mean = vote_matrix.mean(axis=1)
    band_min = band_matrix.min(axis=1)
    band_max = band_matrix.max(axis=1)

    proc = pd.DataFrame({
        "ocid": df["ocid"].to_numpy(),
        "consensus_freq": np.round(consensus_freq, 4),
        "votes_min": votes_min,
        "votes_max": votes_max,
        "votes_mean": np.round(votes_mean, 4),
        "band_min": band_min,
        "band_max": band_max,
        "band_always_same": (band_min == band_max).astype(int),
    })
    proc.to_csv(TABLES / "seed_stability_procedures.csv", index=False)

    run_df = pd.DataFrame(runs)
    summary = {
        "runs": args.runs,
        "seeds": seeds,
        "baseline_seed": args.seed0,
        "detector_params": {
            "isolation_forest": "n_estimators=300, contamination=0.05, random_state=seed",
            "lof": "n_neighbors=20, contamination=0.05, novelty=True, fit on 20k seeded sample",
            "one_class_svm": "rbf, nu=0.05, gamma=scale, fit on 20k seeded sample",
            "mad": "deterministic, computed once",
        },
        "consensus_count": {
            "mean": round(float(run_df["n_consensus_ge3"].mean()), 1),
            "std": round(float(run_df["n_consensus_ge3"].std(ddof=1)), 1),
            "min": int(run_df["n_consensus_ge3"].min()),
            "max": int(run_df["n_consensus_ge3"].max()),
            "cv_pct": round(float(run_df["n_consensus_ge3"].std(ddof=1)
                                  / run_df["n_consensus_ge3"].mean() * 100), 3),
        },
        "jaccard_consensus_vs_baseline": {
            "mean": round(float(run_df["jaccard_consensus_vs_seed42"].mean()), 4),
            "min": round(float(run_df["jaccard_consensus_vs_seed42"].min()), 4),
        },
        "jaccard_top200_vs_baseline": {
            "mean": round(float(run_df["jaccard_top200_vs_seed42"].mean()), 4),
            "min": round(float(run_df["jaccard_top200_vs_seed42"].min()), 4),
        },
        "per_procedure": {
            "share_always_consensus": round(float((consensus_freq == 1.0).mean()), 6),
            "share_never_consensus": round(float((consensus_freq == 0.0).mean()), 6),
            "share_partial_consensus_0_1": round(
                float(((consensus_freq > 0) & (consensus_freq < 1)).mean()), 6),
            "share_band_always_same": round(float((band_min == band_max).mean()), 6),
            "share_band_spans_2_or_more": round(float((band_max - band_min >= 2).mean()), 6),
            "share_ever_consensus": round(float((consensus_freq > 0).mean()), 6),
        },
        "total_seconds": round(float(run_df["seconds"].sum()), 1),
        "disclaimer": (
            "Seed stability measures reproducibility of a statistical indicator, not "
            "correctness. A stable flag is still an indicator of potential risk, not "
            "evidence of corruption."
        ),
    }
    (out_dir / "robustness_seeds.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\nper-run summary:")
    print(run_df.to_string(index=False))
    print("\nsummary:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\ntable  -> {TABLES / 'seed_stability_runs.csv'}")
    print(f"table  -> {TABLES / 'seed_stability_procedures.csv'}")
    print(f"report -> {out_dir / 'robustness_seeds.json'}")
    _plot(run_df, consensus_freq, votes_mean)
    return 0


def _plot(run_df: pd.DataFrame, consensus_freq: np.ndarray, votes_mean: np.ndarray) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")
        return
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))

    ax = axes[0]
    ax.plot(run_df["seed"], run_df["n_consensus_ge3"], marker="o", label="consensus >=3")
    ax.plot(run_df["seed"], run_df["n_votes_ge2"], marker="s", label="votes >=2")
    ax.set_xlabel("seed")
    ax.set_ylabel("procedures flagged")
    ax.set_title("Flagged counts across seeds")
    ax.legend(fontsize=8)

    ax = axes[1]
    ax.hist(consensus_freq, bins=np.linspace(0, 1, 21), color="tab:blue")
    ax.set_xlabel("share of runs in which the procedure has >=3 votes")
    ax.set_ylabel("procedures")
    ax.set_title("Per-procedure consensus stability")

    ax = axes[2]
    ax.hist(run_df["jaccard_consensus_vs_seed42"], bins=10, color="tab:orange")
    ax.set_xlabel("Jaccard vs seed 42")
    ax.set_ylabel("runs")
    ax.set_title("Consensus-set overlap with the production run")

    fig.suptitle("Seed robustness (>=20 runs) - reproducibility, not validity",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "seed_robustness.png", dpi=140)
    print(f"figure -> {FIGURES / 'seed_robustness.png'}")


if __name__ == "__main__":
    raise SystemExit(main())
