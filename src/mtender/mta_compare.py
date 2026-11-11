"""Agreement, rank stability and top-K overlap on one OCID population."""

from __future__ import annotations

import numpy as np
import pandas as pd


def jaccard(left: np.ndarray, right: np.ndarray) -> float:
    a = np.asarray(left).astype(bool)
    b = np.asarray(right).astype(bool)
    union = int(np.logical_or(a, b).sum())
    if union == 0:
        return 1.0
    inter = int(np.logical_and(a, b).sum())
    return inter / union


def flag_counts(left: np.ndarray, right: np.ndarray) -> dict:
    a = np.asarray(left).astype(bool)
    b = np.asarray(right).astype(bool)
    both = int(np.logical_and(a, b).sum())
    only_left = int(np.logical_and(a, ~b).sum())
    only_right = int(np.logical_and(~a, b).sum())
    neither = int(np.logical_and(~a, ~b).sum())
    return {
        "both": both,
        "only_left": only_left,
        "only_right": only_right,
        "neither": neither,
        "jaccard": jaccard(a, b),
    }


def spearman(left: np.ndarray, right: np.ndarray) -> float | None:
    sx = pd.Series(np.asarray(left, dtype=float))
    sy = pd.Series(np.asarray(right, dtype=float))
    if sx.nunique(dropna=True) < 2 or sy.nunique(dropna=True) < 2:
        return None
    value = sx.corr(sy, method="spearman")
    if pd.isna(value):
        return None
    return float(value)


def top_positions(scores: np.ndarray, ocids: np.ndarray, k: int) -> np.ndarray:
    """Positions of the top k scores. Ties break by OCID ascending."""
    scores = np.asarray(scores, dtype=float)
    ocids = np.asarray(ocids)
    k = min(int(k), len(scores))
    order = np.lexsort((ocids, -scores))
    return order[:k]


def top_ocids(scores: np.ndarray, ocids: np.ndarray, k: int) -> list[str]:
    positions = top_positions(scores, ocids, k)
    return [str(item) for item in np.asarray(ocids)[positions]]


def topk_overlap(left: np.ndarray, right: np.ndarray, ocids: np.ndarray, k: int) -> dict:
    a = set(top_ocids(left, ocids, k))
    b = set(top_ocids(right, ocids, k))
    inter = len(a & b)
    return {
        "k": int(min(k, len(ocids))),
        "intersection": inter,
        "overlap": inter / min(k, len(ocids)) if len(ocids) else None,
        "only_left": len(a - b),
        "only_right": len(b - a),
    }


def percentile_ranks(scores: np.ndarray) -> np.ndarray:
    return pd.Series(np.asarray(scores, dtype=float)).rank(method="average", pct=True).to_numpy()


def exact_top_fraction_flag(scores: np.ndarray, ocids: np.ndarray, rate: float) -> tuple[np.ndarray, int]:
    """Flag exactly round(n * rate) rows, ties broken by OCID.

    This is a reporting convention aligned with the 0.05 contamination
    assumption. It is not a validated decision threshold.
    """
    n = len(scores)
    k = max(1, int(round(n * rate))) if n else 0
    flag = np.zeros(n, dtype=int)
    if k:
        flag[top_positions(scores, ocids, k)] = 1
    return flag, k
