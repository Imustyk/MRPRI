"""Step 32 (audit 2026-10, measurement) - noise / input-perturbation sensitivity.

Research question: is the **fixed production v0 ranking** stable when the input
data carry small, realistic errors - misreported amounts, counts, dates,
missing publications, rounding?

This is an *inference* robustness experiment and complements step 15, which
measures *training* (seed/refit) robustness. Nothing here retrains, re-tunes or
replaces anything: production stays v0, votes/bands/thresholds are untouched,
and no cycle is opened (this is a measurement, like MTA-0009/0012/0013).

Design (pre-registered in reports/audit_2026-10/AUDIT_REPORT.md §6):

* models are frozen - IsolationForest + StandardScaler from the production
  joblib; LOF and One-Class SVM are reconstructed exactly as production built
  them (seed 42, deterministic ``fit_sample``) because step 06 does not persist
  them; the reconstruction is *verified* against the published score table by
  fidelity gates before any perturbation is scored;
* perturbations act on the **source columns** of ``data/features/features.csv``
  and all 22 features are re-derived by the production ``engineer_features()``,
  so derived features stay consistent with their sources (monetary block,
  CPV medians, ratios, deadline flags);
* identifiers (ocid, buyer/supplier ids), CPV codes, statuses, procedure types
  and behavioural relationship shares are never perturbed - numerical noise
  there would be meaningless;
* regimes: ``round`` (deterministic rounding), ``noise_small``, ``noise_moderate``
  (10 seeds each), ``missing_1pct``, ``missing_5pct`` (5 seeds each).

An anomaly score is a statistical outlier indicator, not evidence of
corruption; this script measures stability only and never labels anyone.

Usage:
    .venv/bin/python scripts/32_noise_sensitivity.py [--seeds-noise 10]
        [--seeds-missing 5] [--bootstrap 200] [--only REGIME]
        [--allow-low-fidelity]
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

from src.mtender.config import (  # noqa: E402
    DATA_FEATURES,
    FIGURES,
    MODELS,
    RESULTS,
    TABLES,
)
from src.mtender.features import FEATURE_COLUMNS, engineer_features  # noqa: E402

BASELINE_SEED = 42
OUTLIER_RATE = 0.05
NEIGHBOURHOOD_FIT_CAP = 20000
PRODUCTION_CSV = TABLES / "tender_anomaly_scores.csv"

#: top-K cuts whose overlap is reported (production review loads).
TOP_K = (50, 100, 200, 500)

#: The four production detector names, in vote order.
DETECTOR_NAMES = (
    "statistical_mad_zscore",
    "isolation_forest",
    "local_outlier_factor",
    "one_class_svm",
)

#: Pre-registered stability hypotheses (H1-H4, written before the run).
HYPOTHESES = {
    "H1_noise_small_rho": 0.99,
    "H2_noise_moderate_rho": 0.97,
    "H2_noise_moderate_top200": 0.80,
}

#: Source columns each regime is allowed to touch. Everything else - ids, CPV,
#: status, procedure type, behavioural shares - is invariant by design.
MONETARY_SOURCES = ("award_value", "award_total", "estimated_value")
COUNT_SOURCES = ("n_bidders", "n_suppliers")
DATE_SOURCES = ("tender_end",)
AMEND_SOURCES = ("n_amendments",)


def _load_stage06():
    """Import scripts/06 so the MAD baseline is literally the production code."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "06_detect_anomalies.py"
    spec = importlib.util.spec_from_file_location("stage06_detect_noise32", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def band_of(n_models_flagging: np.ndarray) -> np.ndarray:
    """Production bands: 0/1/2/3+ votes -> low/medium/high/critical (0..3)."""
    return np.clip(np.asarray(n_models_flagging, dtype=int), 0, 3)


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman rank correlation (average ranks for ties), no scipy dependency."""
    ra = pd.Series(a).rank(method="average").to_numpy()
    rb = pd.Series(b).rank(method="average").to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def spearman_bootstrap_ci(
    a: np.ndarray, b: np.ndarray, reps: int, seed: int
) -> tuple[float, float]:
    """Percentile bootstrap CI for Spearman (procedure-level resampling)."""
    rng = np.random.default_rng(seed)
    n = len(a)
    vals = np.empty(reps)
    for i in range(reps):
        idx = rng.integers(0, n, n)
        vals[i] = spearman(a[idx], b[idx])
    return float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))


def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    """Jaccard index of two boolean masks over the same population."""
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(a, b).sum() / union)


def topk_overlap(rank_orig: np.ndarray, rank_pert: np.ndarray, k: int) -> float:
    """Share of the original top-K (by rank position) that survives in the perturbed top-K."""
    orig = set(np.argsort(rank_orig, kind="stable")[-k:])
    pert = set(np.argsort(rank_pert, kind="stable")[-k:])
    return float(len(orig & pert) / k)


def transition_matrix(band_orig: np.ndarray, band_pert: np.ndarray) -> np.ndarray:
    """4x4 counts of original band (rows) -> perturbed band (columns)."""
    m = np.zeros((4, 4), dtype=np.int64)
    np.add.at(m, (band_orig, band_pert), 1)
    return m


def ks_statistic(a: np.ndarray, b: np.ndarray) -> float:
    """Two-sample Kolmogorov-Smirnov statistic (sup CDF distance), no scipy."""
    a = np.sort(np.asarray(a, dtype=float))
    b = np.sort(np.asarray(b, dtype=float))
    all_vals = np.sort(np.concatenate([a, b]))
    cdf_a = np.searchsorted(a, all_vals, side="right") / len(a)
    cdf_b = np.searchsorted(b, all_vals, side="right") / len(b)
    return float(np.max(np.abs(cdf_a - cdf_b)))


# ---------------------------------------------------------------------------
# perturbations
# ---------------------------------------------------------------------------


def perturb_sources(df: pd.DataFrame, regime: str, seed: int) -> pd.DataFrame:
    """Return a copy of ``df`` with only the regime's source columns changed.

    All edits are semantically valid for the field: monetary amounts get
    multiplicative error (log-domain jitter), counts get small integer jitter
    and stay non-negative integers, a date window gets day-level jitter, and
    the missing regimes delete whole publication blocks (which the ETL
    convention then turns into its documented fill values on re-derivation).
    """
    if regime == "original":
        return df.copy()

    out = df.copy()
    rng = np.random.default_rng(seed)

    if regime == "round":
        # Reporting/precision change: money rounded to the nearest 10k MDL.
        for col in MONETARY_SOURCES:
            v = pd.to_numeric(out[col], errors="coerce")
            out[col] = (np.round(v / 1e4) * 1e4).where(v.notna(), np.nan)
        return out

    if regime in ("noise_small", "noise_moderate"):
        sigma, p_count, date_days, p_date, p_amend = {
            "noise_small": (np.log(1.01), 0.02, 1.0, 0.05, 0.02),
            "noise_moderate": (np.log(1.05), 0.15, 3.0, 0.15, 0.10),
        }[regime]
        for col in MONETARY_SOURCES:
            v = pd.to_numeric(out[col], errors="coerce")
            scale = np.exp(rng.normal(0.0, sigma, size=len(out)))
            out[col] = (v * scale).where(v.notna(), np.nan)
        for col in COUNT_SOURCES:
            v = pd.to_numeric(out[col], errors="coerce")
            flip = rng.random(len(out)) < p_count
            jitter = np.where(flip, rng.choice([-1, 1], size=len(out)), 0)
            out[col] = np.clip(v.fillna(0).to_numpy() + jitter, 0, None)
        v = pd.to_numeric(out["n_amendments"], errors="coerce")
        flip = rng.random(len(out)) < p_amend
        jitter = np.where(flip, rng.choice([-1, 1], size=len(out)), 0)
        out["n_amendments"] = np.clip(v.fillna(0).to_numpy() + jitter, 0, None)
        # day-level jitter of the end date; start date is the anchor and stays
        end = pd.to_datetime(out["tender_end"], errors="coerce", utc=True)
        flip = (rng.random(len(out)) < p_date) & end.notna()
        delta = pd.to_timedelta(
            np.where(flip, rng.integers(-date_days, date_days + 1, size=len(out)), 0),
            unit="D",
        )
        out["tender_end"] = (end + delta).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return out

    if regime in ("missing_1pct", "missing_5pct"):
        p = {"missing_1pct": 0.01, "missing_5pct": 0.05}[regime]
        # Publication blocks are masked independently: if a block is not
        # published, every feature derived from it follows the ETL convention
        # when engineer_features() re-derives the table.
        award_block = ["award_value", "award_total", "estimated_value", "n_awards_with_value"]
        mask = rng.random(len(out)) < p
        for col in award_block:
            out.loc[mask, col] = np.nan
        mask = rng.random(len(out)) < p
        for col in COUNT_SOURCES:
            out.loc[mask, col] = np.nan
        mask = rng.random(len(out)) < p
        out.loc[mask, "tender_end"] = np.nan
        return out

    raise ValueError(f"unknown regime: {regime}")


# ---------------------------------------------------------------------------
# scoring (frozen models, production code paths)
# ---------------------------------------------------------------------------


def recompute_features(source_df: pd.DataFrame) -> pd.DataFrame:
    """Re-derive all 22 features from (possibly perturbed) sources.

    Uses the single shared production implementation, so binary flags,
    clips and fill conventions are identical to the ETL. Behavioural columns
    are carried through untouched (they are aggregates over many procedures;
    per-procedure source noise moves them by O(1/n) and is out of scope here).
    """
    return engineer_features(source_df.copy())


def score_frozen(
    features: pd.DataFrame,
    stage06,
    scaler,
    iso,
    lof,
    svm,
) -> pd.DataFrame:
    """Score the (perturbed) feature table with frozen components.

    Mirrors scripts/06 exactly: numeric -> fill 0 -> scaler.transform, four
    detector votes, percentile ranks, ``max_score`` = max percentile rank.
    The MAD robust statistics are recomputed by the production function on the
    scored population (documented deviation from strict frozen inference -
    at n = 152 378 the sampling error of median/MAD is negligible next to the
    injected noise, and this keeps the production code as the single source).
    """
    cols = [c for c in FEATURE_COLUMNS if c in features.columns]
    X = features[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    Xs = scaler.transform(X.values)

    scores: dict[str, np.ndarray] = {}
    flags: dict[str, np.ndarray] = {}

    stat = stage06.statistical_baseline(features, cols)
    scores["statistical_mad_zscore"] = stat["score"].to_numpy()
    flags["statistical_mad_zscore"] = stat["is_anomaly"].to_numpy()

    scores["isolation_forest"] = -iso.score_samples(Xs)
    flags["isolation_forest"] = (iso.predict(Xs) == -1).astype(int)
    scores["local_outlier_factor"] = -lof.score_samples(Xs)
    flags["local_outlier_factor"] = (lof.predict(Xs) == -1).astype(int)
    scores["one_class_svm"] = -svm.decision_function(Xs)
    flags["one_class_svm"] = (svm.predict(Xs) == -1).astype(int)

    scores_df = pd.DataFrame(scores)
    ranks = scores_df.rank(pct=True)
    out = pd.DataFrame(
        {
            "max_score": ranks.max(axis=1).to_numpy(),
            "n_models_flagging": np.sum(
                np.column_stack([flags[n] for n in flags]), axis=1
            ),
        }
    )
    out["band"] = band_of(out["n_models_flagging"].to_numpy())
    for name in scores:
        out[f"score_{name}"] = scores[name]
    return out


def build_frozen_models(df: pd.DataFrame, stage06, artifacts: dict):
    """Frozen scaler/IF from the production joblib; LOF/OCSVM rebuilt as in 06."""
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    X = df[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    Xs = artifacts["scaler"].transform(X.values)

    from sklearn.neighbors import LocalOutlierFactor  # noqa: PLC0415
    from sklearn.svm import OneClassSVM  # noqa: PLC0415

    lof_rows = stage06.fit_sample(len(Xs), NEIGHBOURHOOD_FIT_CAP, BASELINE_SEED)
    lof = LocalOutlierFactor(n_neighbors=20, contamination=OUTLIER_RATE, novelty=True)
    lof.fit(Xs[lof_rows])

    svm_rows = stage06.fit_sample(len(Xs), NEIGHBOURHOOD_FIT_CAP, BASELINE_SEED)
    svm = OneClassSVM(kernel="rbf", nu=OUTLIER_RATE, gamma="scale")
    svm.fit(Xs[svm_rows])
    return Xs, artifacts["scaler"], artifacts["isolation_forest"], lof, svm


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def run_metrics(
    ref: pd.DataFrame,
    pert: pd.DataFrame,
    bootstrap_reps: int,
    seed: int,
    value_edges: list[float],
    type_labels: np.ndarray,
    award_values: np.ndarray,
) -> tuple[dict, list[dict], np.ndarray]:
    """All stability metrics of one perturbed scoring against the reference."""
    m: dict[str, float] = {}
    transitions: list[dict] = []

    ref_score = ref["max_score"].to_numpy()
    pert_score = pert["max_score"].to_numpy()
    ref_band = ref["band"].to_numpy()
    pert_band = pert["band"].to_numpy()

    m["spearman_max_score"] = spearman(ref_score, pert_score)
    lo, hi = spearman_bootstrap_ci(ref_score, pert_score, bootstrap_reps, seed)
    m["spearman_ci_low"], m["spearman_ci_high"] = lo, hi

    for name in ("statistical_mad_zscore", "isolation_forest", "local_outlier_factor",
                 "one_class_svm"):
        m[f"spearman_{name}"] = spearman(
            ref[f"score_{name}"].to_numpy(), pert[f"score_{name}"].to_numpy()
        )

    ref_high = ref["n_models_flagging"].to_numpy() >= 2
    pert_high = pert["n_models_flagging"].to_numpy() >= 2
    ref_crit = ref["n_models_flagging"].to_numpy() >= 3
    pert_crit = pert["n_models_flagging"].to_numpy() >= 3
    m["jaccard_high_plus"] = jaccard(ref_high, pert_high)
    m["jaccard_critical"] = jaccard(ref_crit, pert_crit)
    m["jaccard_top200_score"] = jaccard(
        ref_score >= np.quantile(ref_score, 1 - 200 / len(ref_score)),
        pert_score >= np.quantile(pert_score, 1 - 200 / len(pert_score)),
    )

    for k in TOP_K:
        m[f"topk_overlap_{k}"] = topk_overlap(ref_score, pert_score, k)

    tm = transition_matrix(ref_band, pert_band)
    m["band_change_pct"] = float(
        100.0 * (1.0 - np.trace(tm) / tm.sum())
    )
    for i in range(4):
        for j in range(4):
            transitions.append(
                {"orig_band": i, "pert_band": j, "count": int(tm[i, j])}
            )

    for q in (0.5, 0.9, 0.99):
        m[f"max_score_q{int(q * 100)}_orig"] = float(np.quantile(ref_score, q))
        m[f"max_score_q{int(q * 100)}_pert"] = float(np.quantile(pert_score, q))
    m["ks_max_score"] = ks_statistic(ref_score, pert_score)

    # sensitivity by contract-value band and by procedure type
    award = np.asarray(award_values, dtype=float)
    value_group = np.digitize(award, value_edges, right=True)
    value_group = np.where(np.isnan(award) | (award <= 0), len(value_edges), value_group)
    for g in range(len(value_edges) + 1):
        sel = value_group == g
        if sel.sum() >= 500:
            m[f"spearman_value_band_{g}"] = spearman(ref_score[sel], pert_score[sel])
            m[f"band_change_pct_value_band_{g}"] = float(
                100.0 * (ref_band[sel] != pert_band[sel]).mean()
            )
    for t in np.unique(type_labels):
        sel = type_labels == t
        if sel.sum() >= 500:
            key = str(t).replace(" ", "_").replace("/", "_")[:40]
            m[f"spearman_type_{key}"] = spearman(ref_score[sel], pert_score[sel])
            m[f"band_change_pct_type_{key}"] = float(
                100.0 * (ref_band[sel] != pert_band[sel]).mean()
            )
    return m, transitions, tm


def aggregate(runs: pd.DataFrame, metric_cols: list[str]) -> dict:
    """Mean/sd/min/max of each metric across seeds within a regime."""
    out: dict[str, dict] = {}
    for regime, grp in runs.groupby("regime", sort=False):
        out[regime] = {"n_runs": int(len(grp))}
        for col in metric_cols:
            if col in grp.columns:
                vals = grp[col].dropna()
                if len(vals):
                    out[regime][col] = {
                        "mean": float(vals.mean()),
                        "sd": float(vals.std(ddof=1)) if len(vals) > 1 else 0.0,
                        "min": float(vals.min()),
                        "max": float(vals.max()),
                    }
    return out


def make_figures(runs: pd.DataFrame, ref: pd.DataFrame | None,
                 pert_example: pd.DataFrame | None, tm_example: np.ndarray,
                 example_label: str, rng_sample: np.ndarray | None) -> None:
    """Six required figures; best-effort (a missing display never fails the run).

    ``--report-only`` passes ``ref=None``/``pert_example=None`` and the
    original-vs-perturbed scatter is skipped (it needs a scoring pass).
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"figures skipped: {exc}")
        return

    order = ["round", "noise_small", "noise_moderate", "missing_1pct", "missing_5pct"]
    regimes = [r for r in order if r in set(runs["regime"])]

    # 1. noise level vs ranking stability
    fig, ax = plt.subplots(figsize=(8, 5))
    means = [runs.loc[runs["regime"] == r, "spearman_max_score"].mean() for r in regimes]
    mins = [runs.loc[runs["regime"] == r, "spearman_max_score"].min() for r in regimes]
    maxs = [runs.loc[runs["regime"] == r, "spearman_max_score"].max() for r in regimes]
    ax.errorbar(range(len(regimes)), means,
                yerr=[np.array(means) - np.array(mins), np.array(maxs) - np.array(means)],
                fmt="o-", capsize=4)
    ax.set_xticks(range(len(regimes)), regimes, rotation=15)
    ax.set_ylabel("Spearman ρ of max_score vs original")
    ax.set_title("Ranking stability under input perturbation (frozen v0)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "noise_sensitivity_stability.png", dpi=140)
    plt.close(fig)

    # 2. noise level vs top-K overlap
    fig, ax = plt.subplots(figsize=(8, 5))
    for k in TOP_K:
        col = f"topk_overlap_{k}"
        means = [runs.loc[runs["regime"] == r, col].mean() for r in regimes]
        ax.plot(range(len(regimes)), means, "o-", label=f"K={k}")
    ax.set_xticks(range(len(regimes)), regimes, rotation=15)
    ax.set_ylabel("Top-K overlap with original")
    ax.set_ylim(0, 1.05)
    ax.legend()
    ax.set_title("Top-K survival under input perturbation")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "noise_sensitivity_topk.png", dpi=140)
    plt.close(fig)

    # 3. band transition heatmap (example run)
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(np.log10(tm_example + 1), cmap="Blues")
    labels = ["low", "medium", "high", "critical"]
    ax.set_xticks(range(4), labels)
    ax.set_yticks(range(4), labels)
    ax.set_xlabel("perturbed band")
    ax.set_ylabel("original band")
    for i in range(4):
        for j in range(4):
            ax.text(j, i, f"{tm_example[i, j]:,}", ha="center", va="center", fontsize=8)
    ax.set_title(f"Band transitions ({example_label}); log10 colour")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(FIGURES / "noise_sensitivity_transitions.png", dpi=140)
    plt.close(fig)

    # 4. original vs perturbed scores (sampled; needs a scoring pass)
    if ref is not None and pert_example is not None and rng_sample is not None:
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(ref["max_score"].to_numpy()[rng_sample],
                   pert_example["max_score"].to_numpy()[rng_sample], s=4, alpha=0.4)
        lim_min = min(ref["max_score"].min(), pert_example["max_score"].min())
        lim_max = max(ref["max_score"].max(), pert_example["max_score"].max())
        ax.plot([lim_min, lim_max], [lim_min, lim_max], "r--", lw=1)
        ax.set_xlabel("original max_score")
        ax.set_ylabel("perturbed max_score")
        ax.set_title(f"Original vs perturbed ranking score ({example_label})")
        fig.tight_layout()
        fig.savefig(FIGURES / "noise_sensitivity_scatter.png", dpi=140)
        plt.close(fig)

    # 5. stability distributions across seeds
    fig, ax = plt.subplots(figsize=(8, 5))
    data = [runs.loc[runs["regime"] == r, "spearman_max_score"].dropna().to_numpy()
            for r in regimes]
    ax.boxplot(data, tick_labels=regimes)
    ax.set_ylabel("Spearman ρ of max_score")
    ax.set_title("Seed-to-seed distribution of ranking stability")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGURES / "noise_sensitivity_seeds.png", dpi=140)
    plt.close(fig)

    # 6. sensitivity by group (worst regime with group columns)
    group_rows = [c for c in runs.columns
                  if c.startswith("band_change_pct_value_band_")
                  or c.startswith("band_change_pct_type_")]
    if group_rows:
        worst = regimes[-1]
        grp = runs[runs["regime"] == worst]
        names, vals = [], []
        for c in group_rows:
            v = grp[c].dropna()
            if len(v):
                names.append(c.replace("band_change_pct_", ""))
                vals.append(float(v.mean()))
        if names:
            fig, ax = plt.subplots(figsize=(9, 5))
            ax.bar(range(len(vals)), vals)
            ax.set_xticks(range(len(vals)), names, rotation=45, ha="right", fontsize=8)
            ax.set_ylabel("% procedures changing band")
            ax.set_title(f"Group-wise band sensitivity, worst regime ({worst})")
            ax.grid(alpha=0.3, axis="y")
            fig.tight_layout()
            fig.savefig(FIGURES / "noise_sensitivity_groups.png", dpi=140)
            plt.close(fig)


def procedure_type_labels(types: pd.Series, top_n: int = 8) -> tuple[np.ndarray, list[str]]:
    """Top-N procedure types kept as labels, everything else folded into 'other'."""
    types = types.astype(str).fillna("unknown")
    top = types.value_counts().head(top_n).index.tolist()
    labels = np.where(types.isin(top), types, "other")
    return np.asarray(labels), top


def emit_outputs(
    runs: list[dict],
    all_transitions: list[dict],
    config: dict,
    fidelity: dict,
    progress: dict,
    args,
    example: tuple[pd.DataFrame | None, np.ndarray, str] | None = None,
    ref: pd.DataFrame | None = None,
    t0: float | None = None,
) -> int:
    """Tables, figures, aggregates, pre-registered verdicts and the JSON payload.

    Shared by the live run and ``--report-only`` (which passes ``ref=None``).
    """
    runs_df = pd.DataFrame(runs)
    metric_cols = [c for c in runs_df.columns if c not in ("regime", "seed")]
    TABLES.mkdir(parents=True, exist_ok=True)
    runs_df.to_csv(TABLES / "noise_sensitivity_runs.csv", index=False)
    pd.DataFrame(all_transitions).to_csv(
        TABLES / "noise_sensitivity_transitions.csv", index=False)

    agg = aggregate(runs_df, metric_cols)

    # pre-registered hypotheses
    verdicts: dict[str, dict] = {}

    def _min_over(regime: str, col: str) -> float | None:
        vals = runs_df.loc[runs_df["regime"] == regime, col].dropna()
        return float(vals.min()) if len(vals) else None

    v = _min_over("noise_small", "spearman_max_score")
    verdicts["H1_noise_small_rho"] = {
        "threshold": HYPOTHESES["H1_noise_small_rho"], "observed_min": v,
        "passed": bool(v is not None and v >= HYPOTHESES["H1_noise_small_rho"]),
    }
    v_rho = _min_over("noise_moderate", "spearman_max_score")
    v_top = _min_over("noise_moderate", "topk_overlap_200")
    verdicts["H2_noise_moderate"] = {
        "rho_threshold": HYPOTHESES["H2_noise_moderate_rho"], "rho_observed_min": v_rho,
        "top200_threshold": HYPOTHESES["H2_noise_moderate_top200"],
        "top200_observed_min": v_top,
        "passed": bool(v_rho is not None and v_top is not None
                       and v_rho >= HYPOTHESES["H2_noise_moderate_rho"]
                       and v_top >= HYPOTHESES["H2_noise_moderate_top200"]),
    }
    miss = runs_df.loc[runs_df["regime"] == "missing_5pct", "band_change_pct"].mean() \
        if "missing_5pct" in set(runs_df["regime"]) else None
    noise = runs_df.loc[runs_df["regime"] == "noise_moderate", "band_change_pct"].mean() \
        if "noise_moderate" in set(runs_df["regime"]) else None
    verdicts["H3_missing_vs_noise_band_change"] = {
        "missing_5pct_mean_pct": None if miss is None else float(miss),
        "noise_moderate_mean_pct": None if noise is None else float(noise),
        "passed": bool(miss is not None and noise is not None and miss >= noise),
        "note": "descriptive comparison, no threshold pre-registered",
    }
    noise_mask = runs_df["regime"].isin(["noise_small", "noise_moderate"])
    verdicts["H4_detector_driver"] = {
        name: float(runs_df.loc[noise_mask, f"spearman_{name}"].mean())
        for name in DETECTOR_NAMES
    }

    if example is not None:
        pert_example, tm_example, example_label = example
    else:
        pert_example, tm_example, example_label = None, None, ""
    rng_sample = None if ref is None else np.random.default_rng(BASELINE_SEED).choice(
        len(ref), size=min(20000, len(ref)), replace=False)
    make_figures(runs_df, ref, pert_example, tm_example, example_label, rng_sample)

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "experiment": "noise_input_perturbation_sensitivity",
        "measurement_not_cycle": True,
        "production_unchanged": "v0",
        "budget_note": "measurement only: no v7, no retraining, votes/bands/thresholds untouched",
        "config": config,
        "fidelity": fidelity,
        "hypotheses": HYPOTHESES,
        "verdicts": verdicts,
        "aggregate": agg,
        "runtime_seconds": round((time.time() - t0) if t0 else 0.0, 1),
        "disclaimer": "Anomaly scores are statistical outlier indicators, not "
                      "evidence of corruption or violations; review by a competent "
                      "authority is required.",
    }
    (RESULTS / "methodology" / "noise_sensitivity.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(verdicts, indent=2))
    print(f"\ndone in {payload['runtime_seconds']}s -> "
          f"{RESULTS/'methodology'/'noise_sensitivity.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Noise/input-perturbation sensitivity of v0")
    parser.add_argument("--seeds-noise", type=int, default=10)
    parser.add_argument("--seeds-missing", type=int, default=5)
    parser.add_argument("--bootstrap", type=int, default=200)
    parser.add_argument("--only", type=str, default=None,
                        help="run a single regime (for debugging)")
    parser.add_argument("--allow-low-fidelity", action="store_true",
                        help="proceed even if the frozen reconstruction does not "
                             "reproduce the published production scores")
    parser.add_argument("--report-only", action="store_true",
                        help="rebuild tables/figures/JSON from the progress file "
                             "without rescoring (used after a cosmetic fix)")
    args = parser.parse_args()
    warnings.filterwarnings("ignore")

    t0 = time.time()

    if args.report_only:
        progress_path = RESULTS / "methodology" / "noise_sensitivity_progress.json"
        payload_path = RESULTS / "methodology" / "noise_sensitivity.json"
        if not progress_path.exists() or not payload_path.exists():
            print("ERROR: --report-only needs noise_sensitivity_progress.json "
                  "and a previous noise_sensitivity.json")
            return 1
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        previous = json.loads(payload_path.read_text(encoding="utf-8"))
        runs = [v["metrics"] for v in progress.values()]
        all_transitions = [
            dict(regime=k.split(":")[0], seed=int(k.split(":")[1]), **t)
            for k, v in progress.items() for t in v["transitions"]
        ]
        config = dict(previous["config"])
        config["regenerated_via"] = "report-only (no rescoring)"
        example_key = "noise_moderate:0" if "noise_moderate:0" in progress else next(iter(progress))
        tm_example = np.zeros((4, 4), dtype=np.int64)
        for t in progress[example_key]["transitions"]:
            tm_example[t["orig_band"], t["pert_band"]] = t["count"]
        return emit_outputs(runs, all_transitions, config, previous["fidelity"],
                            progress, args, example=(None, tm_example, example_key),
                            ref=None, t0=t0)

    stage06 = _load_stage06()
    import joblib  # noqa: PLC0415

    artifacts = joblib.load(MODELS / "anomaly_models.joblib")
    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    print(f"loaded features.csv: {len(df):,} rows x {df.shape[1]} cols")
    missing_src = [c for c in
                   (*MONETARY_SOURCES, *COUNT_SOURCES, *DATE_SOURCES, *AMEND_SOURCES,
                    "n_awards_with_value", "cpv_primary", "status",
                    "procurement_method_details", "tender_start")
                   if c not in df.columns]
    if missing_src:
        print(f"ERROR: source columns missing from features.csv: {missing_src}")
        return 1

    # -- fidelity gates -----------------------------------------------------
    print("building frozen models (IF+scaler from joblib; LOF/OCSVM rebuilt) ...")
    Xs, scaler, iso, lof, svm = build_frozen_models(df, stage06, artifacts)
    del Xs

    print("scoring the untouched table (fidelity reference) ...")
    ref_features = recompute_features(df)
    fidelity_features = float(max(
        np.max(np.abs(
            pd.to_numeric(ref_features[c], errors="coerce").fillna(0).to_numpy()
            - pd.to_numeric(df[c], errors="coerce").fillna(0).to_numpy()
        )) for c in FEATURE_COLUMNS
    ))
    ref = score_frozen(ref_features, stage06, scaler, iso, lof, svm)

    published = pd.read_csv(PRODUCTION_CSV, usecols=["ocid", "max_score",
                                                     "n_models_flagging"]
                            + [f"score_{n}" for n in (
                                "statistical_mad_zscore", "isolation_forest",
                                "local_outlier_factor", "one_class_svm")])
    merged = df[["ocid"]].merge(published, on="ocid", how="left")
    fidelity: dict[str, float] = {
        "features_rederived_max_abs_diff": fidelity_features,
    }
    ok = fidelity_features <= 1e-5
    for name in ("statistical_mad_zscore", "isolation_forest", "local_outlier_factor",
                 "one_class_svm"):
        rho = spearman(merged[f"score_{name}"].to_numpy(),
                       ref[f"score_{name}"].to_numpy())
        fidelity[f"spearman_{name}"] = rho
        ok = ok and rho >= 0.99999
    fidelity["spearman_max_score"] = spearman(
        merged["max_score"].to_numpy(), ref["max_score"].to_numpy())
    fidelity["band_agreement_pct"] = float(100.0 * np.mean(
        band_of(merged["n_models_flagging"].to_numpy()) == ref["band"].to_numpy()))
    ok = ok and fidelity["spearman_max_score"] >= 0.99999 and fidelity["band_agreement_pct"] >= 99.9
    fidelity["passed"] = bool(ok)
    print("fidelity gates:", json.dumps(fidelity, indent=2))
    if not ok and not args.allow_low_fidelity:
        print("ERROR: frozen reconstruction does not reproduce production scores; "
              "rerun with --allow-low-fidelity to proceed anyway (documented).")
        (RESULTS / "methodology" / "noise_sensitivity.json").write_text(
            json.dumps({"fidelity": fidelity, "aborted": True}, indent=2),
            encoding="utf-8")
        return 1

    # -- grouping anchors ---------------------------------------------------
    award = pd.to_numeric(df["award_value"], errors="coerce")
    positive = award[award > 0]
    value_edges = [float(positive.quantile(q)) for q in (0.25, 0.5, 0.75)]
    types = df["procurement_method_details"].astype(str).fillna("unknown")
    type_labels, top_types = procedure_type_labels(types)
    award_values = pd.to_numeric(df["award_value"], errors="coerce").to_numpy()

    regime_seeds: list[tuple[str, int]] = []
    if args.only in (None, "round"):
        regime_seeds.append(("round", BASELINE_SEED))
    if args.only in (None, "noise_small"):
        regime_seeds += [("noise_small", s) for s in range(args.seeds_noise)]
    if args.only in (None, "noise_moderate"):
        regime_seeds += [("noise_moderate", s) for s in range(args.seeds_noise)]
    if args.only in (None, "missing_1pct"):
        regime_seeds += [("missing_1pct", s) for s in range(args.seeds_missing)]
    if args.only in (None, "missing_5pct"):
        regime_seeds += [("missing_5pct", s) for s in range(args.seeds_missing)]

    progress_path = RESULTS / "methodology" / "noise_sensitivity_progress.json"
    progress: dict[str, dict] = {}
    if progress_path.exists() and args.only is None:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        print(f"resuming: {len(progress)} passes already completed")

    runs: list[dict] = []
    all_transitions: list[dict] = []
    metric_cols: list[str] = []
    example_pert: pd.DataFrame | None = None
    example_tm: np.ndarray | None = None
    example_label = ""

    for regime, seed in regime_seeds:
        key = f"{regime}:{seed}"
        if key in progress:
            runs.append(progress[key]["metrics"])
            all_transitions.extend(progress[key]["transitions"])
            continue
        t_pass = time.time()
        pert_sources = perturb_sources(df, regime, seed)
        pert_features = recompute_features(pert_sources)
        pert = score_frozen(pert_features, stage06, scaler, iso, lof, svm)
        metrics, transitions, tm = run_metrics(
            ref, pert, args.bootstrap, BASELINE_SEED + seed, value_edges, type_labels,
            award_values,
        )
        entry = {"regime": regime, "seed": seed, **metrics}
        runs.append(entry)
        all_transitions.extend(
            {"regime": regime, "seed": seed, **t} for t in transitions
        )
        progress[key] = {"metrics": entry, "transitions": transitions}
        progress_path.write_text(json.dumps(progress), encoding="utf-8")
        if example_pert is None and regime == "noise_moderate":
            example_pert, example_tm, example_label = pert, tm, f"{regime}, seed {seed}"
        print(f"[{regime} seed={seed}] rho={metrics['spearman_max_score']:.4f} "
              f"top200={metrics['topk_overlap_200']:.3f} "
              f"band_change={metrics['band_change_pct']:.2f}% "
              f"({time.time() - t_pass:.0f}s)", flush=True)
        del pert, pert_features, pert_sources

    config = {
        "seeds_noise": args.seeds_noise, "seeds_missing": args.seeds_missing,
        "bootstrap_reps": args.bootstrap, "baseline_seed": BASELINE_SEED,
        "fit_cap": NEIGHBOURHOOD_FIT_CAP, "outlier_rate": OUTLIER_RATE,
        "value_edges": value_edges, "top_types": top_types,
        "regimes": {
            "round": "money rounded to 10k MDL (deterministic)",
            "noise_small": "monetary lognormal sigma=ln(1.01); count +-1 p=0.02; "
                           "end date +-1 day p=0.05; amendments +-1 p=0.02",
            "noise_moderate": "monetary lognormal sigma=ln(1.05); count +-1 p=0.15; "
                              "end date +-3 days p=0.15; amendments +-1 p=0.10",
            "missing_1pct": "award/bids/date publication blocks masked with p=0.01, "
                            "re-derived via ETL conventions",
            "missing_5pct": "same with p=0.05",
        },
        "invariants": ["ocid", "buyer/supplier ids", "cpv_primary", "status",
                       "procurement_method_details", "tender_start",
                       "behavioural relationship shares"],
    }
    if example_pert is None:  # --only without noise_moderate: use the last pass
        example_pert, example_tm = pert, tm
        example_label = f"{regime}, seed {seed}"
    return emit_outputs(
        runs, all_transitions, config, fidelity, progress, args,
        example=(example_pert, example_tm, example_label), ref=ref, t0=t0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
