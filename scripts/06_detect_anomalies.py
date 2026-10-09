"""Step 06 - anomaly detection on the exported feature snapshot.

Compares a statistical baseline with Isolation Forest, Local Outlier Factor and
One-Class SVM on identical preprocessing, and stores per-tender scores in
MongoDB (``anomaly_scores``) plus tables in ``results/tables/``.

An anomaly is a statistical outlier in procurement data, not evidence of
corruption; the wording of every output column reflects that.

Usage:
    .venv/bin/python scripts/06_detect_anomalies.py
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.feature_selection import f_classif
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, FIGURES, MODELS, RESULTS, TABLES  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS  # noqa: E402
from src.mtender.mongo_client import connect, make_run_id, utcnow_iso  # noqa: E402
from src.mtender.mongo_schema import ANOMALY_SCORES  # noqa: E402

RANDOM_STATE = 42
OUTLIER_RATE = 0.05  # contamination assumption, stated explicitly in the thesis

#: Neighbourhood methods (LOF, One-Class SVM) are O(n^2) in memory, so they are
#: fitted on a bounded random sample and then used in novelty mode to score every
#: row. Isolation Forest and the MAD baseline are linear in n and always see the
#: whole corpus.
NEIGHBOURHOOD_FIT_CAP = 20000


def fit_sample(n_rows: int, cap: int, seed: int) -> np.ndarray:
    """Row indices a neighbourhood model is fitted on.

    Deliberately a random sample and never a prefix: the exported snapshot is
    sorted by ``ocid``, and an MTender OCID embeds its publication timestamp, so
    the first rows are the *oldest* procurements in the history. A prefix would
    fit the model on 2018 and score 2026, which is a temporal extrapolation
    rather than an outlier search.
    """
    if cap >= n_rows:
        return np.arange(n_rows)
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(n_rows, size=cap, replace=False))


def statistical_baseline(df: pd.DataFrame, cols: list[str], z_threshold: float = 5.0) -> pd.DataFrame:
    """Robust z-score (median / MAD) per feature, then the max |z| per tender.

    Chosen over a plain z-score because award values are heavily right-skewed,
    so mean/std would be dominated by a few very large contracts.

    Two classes of feature are excluded from the score, both listed in the run
    parameters so the choice is auditable:

    * binary indicators - a rare flag such as ``short_deadline`` has MAD 0, so its
      scale falls back to the standard deviation and one set bit gives |z| > 10.
    * spike-like bounded features - ``value_vs_cpv_median`` sits on 1.0 for most
      rows (MAD 0.038 against a tail reaching 20), which produced |z| up to 335
      and flagged 46% of tenders purely because of the feature's shape. The MAD
      is not a meaningful scale for these; the tree-based models handle them.

    Constant columns are dropped as well: they cannot deviate from anything.
    """
    binary: list[str] = []
    spiked: list[str] = []
    z = pd.DataFrame(index=df.index)

    for col in cols:
        values = pd.to_numeric(df[col], errors="coerce")
        if set(values.dropna().unique()) <= {0.0, 1.0}:
            binary.append(col)
            continue
        median = values.median()
        mad = (values - median).abs().median()
        spread = values.quantile(0.95) - values.quantile(0.05)
        if not np.isfinite(mad) or mad <= 0:
            continue
        if spread and mad < 0.05 * abs(spread):
            spiked.append(col)
            continue
        z[col] = (values - median).abs() / (1.4826 * mad)

    if z.empty:
        score = pd.Series(0.0, index=df.index)
    else:
        score = z.max(axis=1).fillna(0.0)

    if binary:
        n_red_flags = (
            df[binary].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int).sum(axis=1)
        )
    else:
        n_red_flags = pd.Series(0, index=df.index)
    out = pd.DataFrame(
        {
            "score": score,
            "n_red_flags": n_red_flags,
            "is_anomaly": (score > z_threshold).astype(int),
        },
        index=df.index,
    )
    # Kept out of the frame itself so the returned columns stay numeric.
    out.attrs["binary_features"] = binary
    out.attrs["spiked_features"] = spiked
    out.attrs["scored_features"] = list(z.columns)
    return out


def main() -> int:
    warnings.filterwarnings("ignore")
    path = DATA_FEATURES / "features.csv"
    if not path.exists() or path.stat().st_size == 0:
        print(f"ERROR: {path} is empty. Run 04_export_snapshot.py first.")
        return 1

    df = pd.read_csv(path, low_memory=False)
    print(f"loaded {len(df):,} rows x {df.shape[1]} columns from {path}")
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    print(f"using {len(cols)} feature columns")

    X = df[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X.values)

    run_id = make_run_id("detect")
    results: dict[str, dict] = {}

    # -- 1. statistical baseline ------------------------------------------
    stat = statistical_baseline(df, cols)
    results["statistical_mad_zscore"] = {
        "score": stat["score"].to_numpy(),
        "is_anomaly": stat["is_anomaly"].to_numpy(),
        "params": {
            "z_threshold": 5.0,
            "scored_features": stat.attrs["scored_features"],
            "binary_features_excluded": stat.attrs["binary_features"],
            "spike_like_features_excluded": stat.attrs["spiked_features"],
            "note": (
                "binary indicators are reported as red flags rather than z-scores; "
                "spike-like bounded ratios are left to the tree-based models"
            ),
        },
    }

    # -- 2. Isolation Forest ----------------------------------------------
    iso = IsolationForest(
        n_estimators=300, contamination=OUTLIER_RATE, random_state=RANDOM_STATE, n_jobs=-1
    )
    iso.fit(Xs)
    results["isolation_forest"] = {
        "score": -iso.score_samples(Xs),
        "is_anomaly": (iso.predict(Xs) == -1).astype(int),
        "params": {
            "n_estimators": 300,
            "contamination": OUTLIER_RATE,
            "random_state": RANDOM_STATE,
        },
    }

    # -- 3. Local Outlier Factor ------------------------------------------
    # novelty=True is what allows the model to score rows it was not fitted on,
    # so the full corpus is still ranked while the quadratic fit stays bounded.
    lof_rows = fit_sample(len(Xs), NEIGHBOURHOOD_FIT_CAP, RANDOM_STATE)
    lof = LocalOutlierFactor(
        n_neighbors=20, contamination=OUTLIER_RATE, novelty=True
    )
    lof.fit(Xs[lof_rows])
    results["local_outlier_factor"] = {
        "score": -lof.score_samples(Xs),
        "is_anomaly": (lof.predict(Xs) == -1).astype(int),
        "params": {
            "n_neighbors": 20,
            "contamination": OUTLIER_RATE,
            "novelty": True,
            "fitted_on": int(lof_rows.size),
            "fit_sample": "uniform random without replacement, seeded",
        },
    }

    # -- 4. One-Class SVM --------------------------------------------------
    svm_rows = fit_sample(len(Xs), NEIGHBOURHOOD_FIT_CAP, RANDOM_STATE)
    svm = OneClassSVM(kernel="rbf", nu=OUTLIER_RATE, gamma="scale")
    svm.fit(Xs[svm_rows])
    svm_scores = -svm.decision_function(Xs)
    results["one_class_svm"] = {
        "score": svm_scores,
        "is_anomaly": (svm.predict(Xs) == -1).astype(int),
        "params": {
            "kernel": "rbf",
            "nu": OUTLIER_RATE,
            "gamma": "scale",
            "fitted_on": int(svm_rows.size),
            "fit_sample": "uniform random without replacement, seeded",
        },
    }

    # -- comparison ---------------------------------------------------------
    comparison = []
    for name, res in results.items():
        flags = res["is_anomaly"]
        comparison.append(
            {
                "model": name,
                "n_flagged": int(flags.sum()),
                "pct_flagged": round(float(flags.mean() * 100), 3),
                "params": json.dumps(res["params"], ensure_ascii=False),
                "mean_score": round(float(np.mean(res["score"])), 6),
                "median_score": round(float(np.median(res["score"])), 6),
            }
        )

    flag_matrix = np.column_stack([results[n]["is_anomaly"] for n in results])
    agreement = float((flag_matrix.sum(axis=1) >= 3).mean())
    comparison.append(
        {
            "model": "consensus_flagged_by_3_or_more",
            "n_flagged": int((flag_matrix.sum(axis=1) >= 3).sum()),
            "pct_flagged": round(agreement * 100, 3),
            "params": "{}",
            "mean_score": None,
            "median_score": None,
        }
    )

    comp_df = pd.DataFrame(comparison)
    comp_df.to_csv(TABLES / "model_comparison.csv", index=False)
    print("\n" + comp_df.to_string(index=False))

    # -- consensus score per tender ----------------------------------------
    score_cols = {f"score_{n}": results[n]["score"] for n in results}
    scores = pd.DataFrame(score_cols, index=df.index)
    flag_cols = {f"flag_{n}": results[n]["is_anomaly"] for n in results}
    flags = pd.DataFrame(flag_cols, index=df.index)
    ranks = scores.rank(pct=True)
    scores["max_score"] = ranks.max(axis=1)
    scores["n_models_flagging"] = flags.sum(axis=1)
    scores["consensus"] = (scores["n_models_flagging"] >= 3).astype(int)

    out_cols = [
        "ocid", "title", "status", "procurement_method_details", "buyer_name",
        "buyer_identifier", "winner_name", "winner_identifier", "cpv_primary",
        "estimated_value", "award_value", "n_bidders", "tender_start", "award_date",
    ]
    export = pd.concat([df.reindex(columns=out_cols), scores, flags], axis=1)
    export = export.sort_values(["n_models_flagging", "max_score"], ascending=False)
    export.to_csv(TABLES / "tender_anomaly_scores.csv", index=False)
    export.head(200).to_csv(TABLES / "top_200_flagged_tenders.csv", index=False)
    print(f"\ntop 200 flagged written to {TABLES/'top_200_flagged_tenders.csv'}")

    # -- univariate significance of each indicator -------------------------
    f_values, p_values = f_classif(Xs, scores["consensus"])
    sig = pd.DataFrame(
        {
            "feature": cols,
            "f_statistic": np.nan_to_num(f_values, nan=0.0, posinf=0.0),
            "p_value": np.nan_to_num(p_values, nan=1.0, posinf=1.0),
        }
    ).sort_values("p_value")
    sig["significant_at_0.01"] = sig["p_value"] < 0.01
    sig.to_csv(TABLES / "feature_significance.csv", index=False)
    print("\nfeature significance (ANOVA vs consensus flag):")
    print(sig.head(10).to_string(index=False))

    # -- PCA projection for visualisation ----------------------------------
    pca = PCA(n_components=2, random_state=RANDOM_STATE)
    coords = pca.fit_transform(Xs)
    pca_df = pd.DataFrame(
        {
            "ocid": df["ocid"].to_numpy(),
            "pc1": coords[:, 0],
            "pc2": coords[:, 1],
            "consensus": scores["consensus"].to_numpy(),
        }
    )
    pca_df["pc1_explained_variance"] = float(pca.explained_variance_ratio_[0])
    pca_df["pc2_explained_variance"] = float(pca.explained_variance_ratio_[1])
    pca_df.to_csv(TABLES / "pca_projection.csv", index=False)

    import joblib

    joblib.dump(
        {
            "scaler": scaler,
            "isolation_forest": iso,
            "pca": pca,
            "feature_columns": cols,
            "contamination": OUTLIER_RATE,
            "run_id": run_id,
        },
        MODELS / "anomaly_models.joblib",
    )

    # -- persist scores in MongoDB ----------------------------------------
    client, db = connect()
    db[ANOMALY_SCORES].delete_many({"run_id": run_id})
    docs = []
    for i in range(0, len(df), 1000):
        chunk = scores.iloc[i : i + 1000]
        flags_chunk = flags.iloc[i : i + 1000]
        for idx, row in chunk.iterrows():
            doc = {
                "ocid": df.at[idx, "ocid"],
                "run_id": run_id,
                "consensus": int(row["consensus"]),
                "n_models_flagging": int(row["n_models_flagging"]),
                "max_score": float(row["max_score"]),
            }
            for name in results:
                doc[f"score_{name}"] = float(row[f"score_{name}"])
                doc[f"flag_{name}"] = int(flags_chunk.at[idx, f"flag_{name}"])
            docs.append(doc)
    if docs:
        db[ANOMALY_SCORES].insert_many(docs, ordered=False)

    summary = {
        "run_id": run_id,
        "stage": "anomaly_detection",
        "generated_at": utcnow_iso(),
        "n_rows": len(df),
        "feature_columns": cols,
        "contamination_assumption": OUTLIER_RATE,
        "random_state": RANDOM_STATE,
        "preprocessing": "StandardScaler on numeric features, missing -> 0",
        "models": comparison,
        "pca_explained_variance": [float(x) for x in pca.explained_variance_ratio_],
        "significant_features_at_0.01": int(sig["significant_at_0.01"].sum()),
        "scores_stored_in_mongo": len(docs),
    }
    (RESULTS / "mongo" / "detection_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        for name, res in results.items():
            axes[0].hist(res["score"], bins=60, histtype="step", label=name)
        axes[0].set_xlabel("anomaly score (higher = more unusual)")
        axes[0].set_ylabel("tenders")
        axes[0].legend(fontsize=8)
        axes[0].set_title("Anomaly score distributions")
        sc = axes[1].scatter(coords[:, 0], coords[:, 1], c=scores["consensus"], s=4, alpha=0.5)
        axes[1].set_title(f"PCA projection (explained {pca.explained_variance_ratio_[0]:.1%} + "
                          f"{pca.explained_variance_ratio_[1]:.1%})")
        axes[1].set_xlabel("PC1")
        axes[1].set_ylabel("PC2")
        fig.colorbar(sc, ax=axes[1], label="consensus anomaly flag")
        fig.tight_layout()
        fig.savefig(FIGURES / "anomaly_overview.png", dpi=140)
        print(f"\nfigure -> {FIGURES/'anomaly_overview.png'}")
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")

    print(f"\nsummary -> {RESULTS/'mongo'/'detection_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
