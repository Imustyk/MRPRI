"""Unsupervised anomaly detection + hybrid risk score."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import RobustScaler

from .features import FEATURE_COLUMNS, rule_based_score


def fit_detectors(X: np.ndarray, random_state: int = 1312015) -> dict:
    scaler = RobustScaler()
    Xs = scaler.fit_transform(X)

    iso = IsolationForest(
        n_estimators=400,
        contamination=0.12,
        max_samples="auto",
        random_state=random_state,
        n_jobs=-1,
    )
    iso.fit(Xs)

    lof = LocalOutlierFactor(
        n_neighbors=35,
        contamination=0.12,
        novelty=True,
        n_jobs=-1,
    )
    lof.fit(Xs)

    return {"scaler": scaler, "isolation_forest": iso, "lof": lof}


def _minmax(arr: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(arr)), float(np.max(arr))
    if hi - lo < 1e-9:
        return np.zeros_like(arr, dtype=float)
    return (arr - lo) / (hi - lo)


def score_frame(df: pd.DataFrame, models: dict) -> pd.DataFrame:
    X = df[FEATURE_COLUMNS].to_numpy(dtype=float)
    Xs = models["scaler"].transform(X)

    iso = models["isolation_forest"]
    lof = models["lof"]

    iso_raw = -iso.score_samples(Xs)  # higher = more anomalous
    lof_raw = -lof.score_samples(Xs)
    iso_pred = iso.predict(Xs)  # -1 anomaly
    lof_pred = lof.predict(Xs)

    iso_n = _minmax(iso_raw)
    lof_n = _minmax(lof_raw)

    rule_scores = []
    flag_lists = []
    for _, row in df.iterrows():
        s, flags = rule_based_score(row)
        rule_scores.append(s)
        flag_lists.append(flags)
    rule = np.array(rule_scores, dtype=float)
    rule_n = rule / 100.0

    hybrid = 100.0 * (0.40 * iso_n + 0.15 * lof_n + 0.45 * rule_n)

    out = df.copy()
    out["iso_score"] = iso_n
    out["lof_score"] = lof_n
    out["rule_score"] = rule
    out["risk_score"] = np.round(hybrid, 1)
    out["iso_anomaly"] = (iso_pred == -1).astype(int)
    out["lof_anomaly"] = (lof_pred == -1).astype(int)
    out["flags"] = [json.dumps(f, ensure_ascii=False) for f in flag_lists]
    out["risk_level"] = pd.cut(
        out["risk_score"],
        bins=[-0.1, 35, 55, 75, 100.1],
        labels=["low", "medium", "high", "critical"],
    ).astype(str)
    return out


def evaluate_against_planted(df: pd.DataFrame) -> dict:
    if "is_planted_anomaly" not in df.columns:
        return {"available": False}
    y = df["is_planted_anomaly"].astype(bool)
    pred = df["risk_score"] >= 40
    tp = int((pred & y).sum())
    fp = int((pred & ~y).sum())
    fn = int((~pred & y).sum())
    tn = int((~pred & ~y).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    ranked = df.sort_values("risk_score", ascending=False)
    k_values = [20, 50, 100]
    precision_at_k = {}
    for k in k_values:
        top = ranked.head(k)
        precision_at_k[f"P@{k}"] = float(top["is_planted_anomaly"].mean())

    return {
        "available": True,
        "n": int(len(df)),
        "planted": int(y.sum()),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "precision_at_k": precision_at_k,
        "threshold": 40,
    }


def save_models(models: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(models, path)
