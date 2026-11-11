"""Four detectors, the production ensemble, and a simple indicator count.

Hyperparameters match ``scripts/06_detect_anomalies.py``. Neighbourhood models
are fitted on a seeded sample and then score every row.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

from src.mtender.mta_compare import exact_top_fraction_flag, percentile_ranks
from src.mtender.mta_protocol import (
    ISO_ESTIMATORS,
    LOF_NEIGHBORS,
    NEIGHBOURHOOD_FIT_CAP,
    OUTLIER_RATE,
    RANDOM_STATE,
    SIMPLE_FLAG_RATE,
    Z_THRESHOLD,
    fit_sample,
    statistical_baseline,
)
from src.mtender.stage_feature_table import simple_indicator_score


def _round_scores(scores: np.ndarray) -> np.ndarray:
    return np.round(np.asarray(scores, dtype=float), 6)


def run_detectors(
    raw_for_indicators: pd.DataFrame,
    model_matrix: pd.DataFrame,
    ocids: np.ndarray,
    *,
    seed: int = RANDOM_STATE,
    outlier_rate: float = OUTLIER_RATE,
    fit_cap: int = NEIGHBOURHOOD_FIT_CAP,
    z_threshold: float = Z_THRESHOLD,
    iso_estimators: int = ISO_ESTIMATORS,
    lof_neighbors: int = LOF_NEIGHBORS,
    simple_flag_rate: float = SIMPLE_FLAG_RATE,
) -> dict:
    """Fit every method on one arm.

    ``raw_for_indicators`` is the pre-imputation frame used for the simple
    count, so a missing deadline is not counted as a normal deadline.
    ``model_matrix`` is what MAD and the geometric models see.
    """
    if len(model_matrix) != len(ocids) or len(raw_for_indicators) != len(ocids):
        raise ValueError("scores and OCIDs must have the same length")

    timings: dict[str, float] = {}
    Xs = StandardScaler().fit_transform(model_matrix.to_numpy(dtype=float))
    rows = fit_sample(len(Xs), fit_cap, seed)

    started = time.perf_counter()
    mad = statistical_baseline(model_matrix, list(model_matrix.columns), z_threshold)
    timings["mad"] = time.perf_counter() - started

    started = time.perf_counter()
    iso = IsolationForest(
        n_estimators=iso_estimators,
        contamination=outlier_rate,
        random_state=seed,
        n_jobs=-1,
    )
    iso.fit(Xs)
    iso_score = -iso.score_samples(Xs)
    iso_flag = (iso.predict(Xs) == -1).astype(int)
    timings["isolation_forest"] = time.perf_counter() - started

    started = time.perf_counter()
    lof = LocalOutlierFactor(
        n_neighbors=lof_neighbors, contamination=outlier_rate, novelty=True
    )
    lof.fit(Xs[rows])
    lof_score = -lof.score_samples(Xs)
    lof_flag = (lof.predict(Xs) == -1).astype(int)
    timings["lof"] = time.perf_counter() - started

    started = time.perf_counter()
    svm = OneClassSVM(kernel="rbf", nu=outlier_rate, gamma="scale")
    svm.fit(Xs[rows])
    svm_score = -svm.decision_function(Xs)
    svm_flag = (svm.predict(Xs) == -1).astype(int)
    timings["one_class_svm"] = time.perf_counter() - started

    started = time.perf_counter()
    rank_frame = pd.DataFrame(
        {
            "mad": mad["score"],
            "isolation_forest": iso_score,
            "lof": lof_score,
            "one_class_svm": svm_score,
        }
    )
    ensemble_score = rank_frame.rank(method="average", pct=True).mean(axis=1).to_numpy()
    votes = (
        mad["is_anomaly"].astype(int)
        + iso_flag
        + lof_flag
        + svm_flag
    )
    ensemble_flag = (votes >= 3).astype(int)
    timings["ensemble"] = time.perf_counter() - started

    started = time.perf_counter()
    simple_score = simple_indicator_score(raw_for_indicators).to_numpy(dtype=float)
    simple_flag, simple_k = exact_top_fraction_flag(simple_score, ocids, simple_flag_rate)
    timings["simple_indicators"] = time.perf_counter() - started

    methods = {
        "mad": {
            "score": _round_scores(mad["score"]),
            "flag": mad["is_anomaly"].astype(int),
            "params": {
                "z_threshold": z_threshold,
                "scored_features": mad["scored_features"],
                "binary_features_excluded": mad["binary_features"],
                "spike_like_features_excluded": mad["spiked_features"],
                "constant_features_excluded": mad["dropped_constant"],
            },
        },
        "isolation_forest": {
            "score": _round_scores(iso_score),
            "flag": iso_flag,
            "params": {
                "n_estimators": iso_estimators,
                "contamination": outlier_rate,
                "random_state": seed,
            },
        },
        "lof": {
            "score": _round_scores(lof_score),
            "flag": lof_flag,
            "params": {
                "n_neighbors": lof_neighbors,
                "contamination": outlier_rate,
                "novelty": True,
                "fitted_on": int(rows.size),
                "fit_sample": "uniform random without replacement, seeded, after sorting by ocid",
            },
        },
        "one_class_svm": {
            "score": _round_scores(svm_score),
            "flag": svm_flag,
            "params": {
                "kernel": "rbf",
                "nu": outlier_rate,
                "gamma": "scale",
                "fitted_on": int(rows.size),
                "fit_sample": "uniform random without replacement, seeded, after sorting by ocid",
            },
        },
        "ensemble": {
            "score": _round_scores(ensemble_score),
            "flag": ensemble_flag,
            "params": {
                "score": "mean of within-arm percentile ranks of mad, isolation_forest, lof, one_class_svm",
                "flag": "at least 3 of the 4 detector flags",
                "votes_mean": float(np.mean(votes)),
            },
        },
        "simple_indicators": {
            "score": _round_scores(simple_score),
            "flag": simple_flag,
            "params": {
                "score": "count of listed binary indicators equal to 1; missing period flags do not count",
                "flag": "exact top fraction after OCID tie-break",
                "rate": simple_flag_rate,
                "n_flagged_by_construction": int(simple_k),
                "note": "a reporting convention aligned with contamination 0.05, not a validated threshold",
            },
        },
    }
    return {
        "methods": methods,
        "seconds": timings,
        "n_rows": int(len(ocids)),
        "fit_rows": int(rows.size),
        "votes": votes.astype(int),
        "percentile_ready": {
            name: percentile_ranks(payload["score"]) for name, payload in methods.items()
        },
    }
