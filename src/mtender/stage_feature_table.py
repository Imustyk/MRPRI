"""Stage-consistent period features.

The stored value is missing whenever the evaluation release does not contain
one non-negative closed period. Nothing in this module writes the constant 30.
``historically_certified`` is always 0: a current snapshot is not a
publication-time certificate.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.mtender.mta_protocol import PERIOD_COLUMNS, SIMPLE_INDICATOR_COLUMNS, WINDOW_CLIP


def stage_period_feature_row(
    submission_window_days: Any,
    submission_window_status: str,
    clip: int = WINDOW_CLIP,
) -> dict:
    """One procedure. Days are kept only for ``evaluation_complete``."""
    empty = {
        "bid_window_days": None,
        "short_deadline": None,
        "long_deadline": None,
        "submission_window_days_unclipped": None,
        "submission_window_observed": 0,
        "historically_certified": 0,
        "window_clipped": 0,
    }
    if submission_window_status != "evaluation_complete":
        return empty
    if submission_window_days is None or submission_window_days == "":
        return empty
    days = int(submission_window_days)
    if days < 0:
        return empty
    clipped = min(days, clip)
    return {
        "bid_window_days": clipped,
        "short_deadline": int(clipped < 7),
        "long_deadline": int(clipped > 90),
        "submission_window_days_unclipped": days,
        "submission_window_observed": 1,
        "historically_certified": 0,
        "window_clipped": int(clipped != days),
    }


def apply_stage_period_features(
    status: pd.Series,
    days: pd.Series,
    clip: int = WINDOW_CLIP,
) -> pd.DataFrame:
    """Vector form of :func:`stage_period_feature_row`."""
    raw = pd.to_numeric(days, errors="coerce")
    observed = status.eq("evaluation_complete") & raw.notna() & raw.ge(0)
    clipped = raw.clip(upper=clip)
    out = pd.DataFrame(index=status.index)
    out["bid_window_days"] = clipped.where(observed)
    out["short_deadline"] = (clipped < 7).astype(float).where(observed)
    out["long_deadline"] = (clipped > 90).astype(float).where(observed)
    out["submission_window_days_unclipped"] = raw.where(observed)
    out["submission_window_observed"] = observed.astype(int)
    out["historically_certified"] = 0
    out["window_clipped"] = (observed & raw.gt(clip)).astype(int)
    return out


def stage_model_frame(features: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, dict]:
    """Detector matrix for the stage-consistent arm.

    The feature table itself is not filled. Inside this matrix only, a missing
    window becomes the median of the observed windows, and a missing indicator
    is added. Short and long flags that were missing become 0 next to that
    indicator. The median is an input to the detector. It is not recorded as
    a measured duration, and the fill is not the constant 30 unless the
    observed median itself is 30.
    """
    X = features.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce").copy()
    missing = X["bid_window_days"].isna()
    observed = X.loc[~missing, "bid_window_days"]
    if observed.empty:
        median = 0.0
        median_defined = False
    else:
        median = float(observed.median())
        median_defined = True
    X["bid_window_days"] = X["bid_window_days"].fillna(median)
    X["short_deadline"] = X["short_deadline"].fillna(0.0)
    X["long_deadline"] = X["long_deadline"].fillna(0.0)
    X["submission_window_missing"] = missing.astype(float)
    X = X.fillna(0.0)
    info = {
        "policy": "median_of_observed_windows_plus_missing_indicator",
        "constant_30_fill": False,
        "median_defined": median_defined,
        "median_observed_window": median if median_defined else None,
        "median_equals_legacy_constant_30": bool(median_defined and median == 30),
        "n_missing_window": int(missing.sum()),
        "n_observed_window": int((~missing).sum()),
        "columns": list(X.columns),
    }
    return X, info


def legacy_model_frame(features: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, dict]:
    """Production matrix: numeric coercion and missing values set to 0.

    ``bid_window_days`` in the legacy snapshot was already filled with 30
    before this step. This function does not apply that fill again.
    """
    X = features.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    info = {
        "policy": "production_fillna_0_on_already_filled_snapshot",
        "constant_30_fill_applied_here": False,
        "columns": list(X.columns),
    }
    return X, info


def ablation_model_frame(features: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, dict]:
    """Same rows, without the three period-derived columns."""
    keep = [column for column in columns if column not in PERIOD_COLUMNS]
    X = features.loc[:, keep].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    info = {
        "policy": "drop_period_columns_fillna_0",
        "dropped": list(PERIOD_COLUMNS),
        "columns": list(X.columns),
    }
    return X, info


def simple_indicator_score(frame: pd.DataFrame) -> pd.Series:
    """Count of listed binary indicators equal to 1. Missing is not a flag."""
    cols = [column for column in SIMPLE_INDICATOR_COLUMNS if column in frame.columns]
    if not cols:
        return pd.Series(0.0, index=frame.index)
    values = frame[cols].apply(pd.to_numeric, errors="coerce")
    return values.eq(1).sum(axis=1).astype(float)
