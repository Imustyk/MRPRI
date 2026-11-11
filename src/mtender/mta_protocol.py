"""Fixed comparison protocol for MTA-0024 / MTA-0025.

The detector constants repeat ``scripts/06_detect_anomalies.py`` in the
read-only Diplom tree. This module does not import that tree and does not
open MongoDB.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "log_award_value",
    "value_vs_cpv_median",
    "value_zscore_cpv",
    "estimate_to_award_ratio",
    "log_award_total",
    "multi_award_tender",
    "n_bidders_log",
    "single_bidder",
    "no_bid_data",
    "multi_supplier_award",
    "bid_window_days",
    "short_deadline",
    "long_deadline",
    "n_amendments",
    "amended",
    "accelerated_like",
    "cancelled",
    "no_award_after_tender",
    "buyer_supplier_repeat_share",
    "winner_share_of_buyer_awards",
    "supplier_win_concentration",
    "supplier_award_count_log",
]

PERIOD_COLUMNS = ("bid_window_days", "short_deadline", "long_deadline")

#: Binary columns counted by the simple-indicator score.
#: ``submission_window_missing`` is deliberately absent: it records a gap,
#: it is not treated as a procurement red flag.
SIMPLE_INDICATOR_COLUMNS = (
    "multi_award_tender",
    "single_bidder",
    "no_bid_data",
    "multi_supplier_award",
    "short_deadline",
    "long_deadline",
    "amended",
    "accelerated_like",
    "cancelled",
    "no_award_after_tender",
)

RANDOM_STATE = 42
OUTLIER_RATE = 0.05
NEIGHBOURHOOD_FIT_CAP = 20_000
Z_THRESHOLD = 5.0
WINDOW_CLIP = 3650
TOP_KS = (50, 100, 200, 500, 1000)
ISO_ESTIMATORS = 300
LOF_NEIGHBORS = 20
SIMPLE_FLAG_RATE = 0.05

ARMS = ("legacy", "stage_consistent", "ablation")
METHODS = (
    "mad",
    "isolation_forest",
    "lof",
    "one_class_svm",
    "ensemble",
    "simple_indicators",
)

DIPLOM_ROOT = Path("/Users/imustyk/Diplom")


def assert_outside_diplom(path: Path, diplom: Path = DIPLOM_ROOT) -> Path:
    """Refuse any output path inside the read-only source tree."""
    resolved = path.expanduser().resolve()
    source = diplom.expanduser().resolve()
    if resolved == source or source in resolved.parents:
        raise SystemExit(f"refusing to write into the read-only source tree: {resolved}")
    return resolved


def fit_sample(n_rows: int, cap: int, seed: int) -> np.ndarray:
    """Seeded uniform sample. A prefix would be the oldest OCIDs."""
    if cap >= n_rows:
        return np.arange(n_rows)
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(n_rows, size=cap, replace=False))


def statistical_baseline(
    df: pd.DataFrame, cols: list[str], z_threshold: float = Z_THRESHOLD
) -> dict:
    """Robust z-score per column, then the max |z| per row.

    Binary columns and spike-like columns are excluded from the z-score, as
    in ``scripts/06_detect_anomalies.py``. Constant columns are dropped.
    """
    binary: list[str] = []
    spiked: list[str] = []
    dropped_constant: list[str] = []
    used: list[str] = []
    z_cols: list[np.ndarray] = []

    for col in cols:
        values = pd.to_numeric(df[col], errors="coerce")
        observed = values.dropna()
        if set(observed.unique()) <= {0.0, 1.0}:
            binary.append(col)
            continue
        median = float(values.median())
        mad = float((values - median).abs().median())
        spread = float(values.quantile(0.95) - values.quantile(0.05))
        if not np.isfinite(mad) or mad <= 0:
            dropped_constant.append(col)
            continue
        if spread and mad < 0.05 * abs(spread):
            spiked.append(col)
            continue
        z_cols.append(((values - median).abs() / (1.4826 * mad)).to_numpy(dtype=float))
        used.append(col)

    if not z_cols:
        score = np.zeros(len(df), dtype=float)
    else:
        score = np.nanmax(np.column_stack(z_cols), axis=1)
        score = np.nan_to_num(score, nan=0.0)

    if binary:
        flags = df[binary].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        n_red = (flags >= 0.5).sum(axis=1).to_numpy(dtype=int)
    else:
        n_red = np.zeros(len(df), dtype=int)

    return {
        "score": score,
        "is_anomaly": (score > z_threshold).astype(int),
        "n_red_flags": n_red,
        "binary_features": binary,
        "spiked_features": spiked,
        "dropped_constant": dropped_constant,
        "scored_features": used,
    }
