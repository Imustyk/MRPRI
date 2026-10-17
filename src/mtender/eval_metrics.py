"""Ranking / classification metrics with bootstrap confidence intervals.

Why this module exists
----------------------
The real MTender corpus carries no ground-truth anomaly labels, so precision
and recall *against a truth of "this contract is corrupt"* are not computable
(see ``backend/app/model_kpis.py``). What **is** computable is performance
against the one external signal that exists: the AAP interdiction list
(``data/raw/blacklist/*.json``), which yields a procedure-level label of the
form "this procedure was awarded to a supplier that AAP has interdicted".

That label is weak and its limits are stated wherever it is used (supplier-level
attribution, name-based matching, decisions that postdate some procedures), so
every metric here is reported with a bootstrap confidence interval rather than
as a point number, and the resampling unit can be set to the *supplier* to avoid
pretending that 600 procedures from one company are 600 independent facts.

Nothing in this module interprets a high score as evidence of wrongdoing.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

#: Percentile ranks / scores are higher = more unusual everywhere in the repo.
SCORE_DIRECTION = 1.0


def _as_float_array(values: Sequence[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return arr


def precision_at_k(y_true: Sequence[int], score: Sequence[float], k: int) -> float:
    """Share of true positives in the top ``k`` ranked rows."""
    y = np.asarray(y_true, dtype=int)
    s = _as_float_array(score)
    if k <= 0 or y.size == 0:
        return float("nan")
    k = min(int(k), y.size)
    order = np.argsort(-s, kind="stable")[:k]
    return float(y[order].sum() / k)


def recall_at_k(y_true: Sequence[int], score: Sequence[float], k: int) -> float:
    """Share of all true positives captured in the top ``k`` ranked rows."""
    y = np.asarray(y_true, dtype=int)
    total = int(y.sum())
    if total == 0:
        return float("nan")
    return float(precision_at_k(y, score, k) * min(int(k), y.size) / total)


def lift_at_k(y_true: Sequence[int], score: Sequence[float], k: int) -> float:
    """precision@k divided by base rate; 1.0 means "no better than random"."""
    y = np.asarray(y_true, dtype=int)
    base = float(y.mean()) if y.size else float("nan")
    if not base or base != base:
        return float("nan")
    return float(precision_at_k(y, score, k) / base)


def roc_auc(y_true: Sequence[int], score: Sequence[float]) -> float:
    """ROC-AUC; NaN when only one class is present (undefined, not 0.5)."""
    y = np.asarray(y_true, dtype=int)
    if np.unique(y).size < 2:
        return float("nan")
    return float(roc_auc_score(y, _as_float_array(score)))


def pr_auc(y_true: Sequence[int], score: Sequence[float]) -> float:
    """Average precision (PR-AUC); NaN when only one class is present."""
    y = np.asarray(y_true, dtype=int)
    if np.unique(y).size < 2:
        return float("nan")
    return float(average_precision_score(y, _as_float_array(score)))


#: name -> function, in the order they are written to the metrics table.
METRICS: dict[str, Callable[[Sequence[int], Sequence[float]], float]] = {
    "roc_auc": roc_auc,
    "pr_auc": pr_auc,
}


def bootstrap_ci(
    y_true: Sequence[int],
    score: Sequence[float],
    metric: Callable[[Sequence[int], Sequence[float]], float],
    n_boot: int = 1000,
    seed: int = 42,
    cluster: Sequence[str | int] | None = None,
    alpha: float = 0.05,
    k: int | None = None,
) -> dict[str, float]:
    """Percentile bootstrap CI for a metric.

    ``cluster`` switches the resampling unit: when the label was assigned at
    the *supplier* level (all procedures of an interdicted supplier are
    positive), resampling individual procedures would understate the
    uncertainty because procedures from one supplier are not independent.
    Passing supplier keys resamples suppliers with replacement and keeps every
    procedure of each drawn supplier, which is the honest interval for that
    labelling.

    ``k`` is only used by the @k metrics, which need the two-argument
    ``metric(y, score)`` shape; pass a closure or use ``bootstrap_precision``
    for clarity.
    """
    y = np.asarray(y_true, dtype=int)
    s = _as_float_array(score)
    if y.size == 0:
        return {"point": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "se": float("nan"), "n_boot": 0, "n_units": 0}

    point = float(metric(y, s))

    if cluster is None:
        units = np.arange(y.size)
        members: dict[object, np.ndarray] = {}
        unit_arr = units
    else:
        unit_arr = np.asarray(cluster)
        keys = {v: i for i, v in enumerate(dict.fromkeys(unit_arr.tolist()))}
        encoded = np.array([keys[v] for v in unit_arr.tolist()])
        members = {}
        for u in np.unique(encoded):
            members[u] = np.flatnonzero(encoded == u)
        units = np.unique(encoded)

    rng = np.random.default_rng(seed)
    draws: list[float] = []
    n_units = int(units.size)
    for _ in range(int(n_boot)):
        picked = rng.choice(units, size=n_units, replace=True)
        if cluster is None:
            idx = picked
        else:
            idx = np.concatenate([members[u] for u in picked])
        value = float(metric(y[idx], s[idx]))
        if value == value:  # drop NaN draws (single-class resamples)
            draws.append(value)

    if not draws:
        return {"point": point, "lo": float("nan"), "hi": float("nan"),
                "se": float("nan"), "n_boot": 0, "n_units": n_units}

    arr = np.asarray(draws, dtype=float)
    lo = float(np.quantile(arr, alpha / 2))
    hi = float(np.quantile(arr, 1 - alpha / 2))
    return {
        "point": point,
        "lo": lo,
        "hi": hi,
        "se": float(arr.std(ddof=1)) if arr.size > 1 else float("nan"),
        "n_boot": int(arr.size),
        "n_units": n_units,
    }


def cohen_kappa(flag_a: Sequence[int], flag_b: Sequence[int]) -> float:
    """Cohen's kappa for two binary flags (NaN if both are constant)."""
    a = np.asarray(flag_a, dtype=int)
    b = np.asarray(flag_b, dtype=int)
    if a.size == 0:
        return float("nan")
    p_yes = float(np.mean(a == b))
    pa = float(np.mean(a))
    pb = float(np.mean(b))
    p_e = pa * pb + (1 - pa) * (1 - pb)
    if p_e == 1.0:
        return float("nan")
    return float((p_yes - p_e) / (1 - p_e))


def jaccard(flag_a: Sequence[int], flag_b: Sequence[int]) -> float:
    """Jaccard similarity of two binary flags over rows flagged by either."""
    a = np.asarray(flag_a, dtype=bool)
    b = np.asarray(flag_b, dtype=bool)
    union = np.logical_or(a, b).sum()
    if union == 0:
        return float("nan")
    return float(np.logical_and(a, b).sum() / union)


def wilson_ci(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Used for the precision of a *decision rule* (how many of the flagged rows
    carry the external label), where a normal approximation collapses at the
    single-digit hit counts this evaluation produces.
    """
    if trials <= 0:
        return float("nan"), float("nan")
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = (z / denom) * np.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return float(max(centre - half, 0.0)), float(min(centre + half, 1.0))
