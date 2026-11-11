"""A tiny seeded run returns one row per OCID and repeats itself."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.detectors import run_detectors


def _frame(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 80
    window = rng.integers(5, 40, size=n).astype(float)
    window[:10] = np.nan
    return pd.DataFrame(
        {
            "bid_window_days": window,
            "short_deadline": np.where(np.isnan(window), np.nan, (window < 7).astype(float)),
            "long_deadline": np.where(np.isnan(window), np.nan, (window > 90).astype(float)),
            "single_bidder": rng.integers(0, 2, size=n).astype(float),
            "log_award_value": rng.normal(size=n),
        }
    )


def test_tiny_protocol_is_reproducible_and_covers_every_method():
    frame = _frame(1)
    ocids = np.array([f"ocds-{i:03d}" for i in range(len(frame))])
    matrix = frame.fillna(frame.median(numeric_only=True)).fillna(0.0)
    first = run_detectors(
        frame, matrix, ocids, iso_estimators=30, fit_cap=40, lof_neighbors=5
    )
    second = run_detectors(
        frame, matrix, ocids, iso_estimators=30, fit_cap=40, lof_neighbors=5
    )
    assert set(first["methods"]) == {
        "mad",
        "isolation_forest",
        "lof",
        "one_class_svm",
        "ensemble",
        "simple_indicators",
    }
    for name, payload in first["methods"].items():
        assert len(payload["score"]) == len(ocids)
        assert len(payload["flag"]) == len(ocids)
        assert np.array_equal(payload["flag"], second["methods"][name]["flag"])
        assert np.allclose(payload["score"], second["methods"][name]["score"])
    assert int(first["methods"]["simple_indicators"]["flag"].sum()) == 4
