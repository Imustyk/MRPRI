"""The stage-consistent table must not invent a 30-day submission window."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.stage_feature_table import (
    ablation_model_frame,
    apply_stage_period_features,
    stage_model_frame,
    stage_period_feature_row,
)


def test_missing_status_does_not_become_thirty_even_if_a_number_is_passed():
    row = stage_period_feature_row(30, "no_evaluation_record")
    assert row["bid_window_days"] is None
    assert row["short_deadline"] is None
    assert row["long_deadline"] is None
    assert row["historically_certified"] == 0
    assert row["submission_window_observed"] == 0


def test_a_real_thirty_day_evaluation_window_is_kept():
    row = stage_period_feature_row(30, "evaluation_complete")
    assert row["bid_window_days"] == 30
    assert row["short_deadline"] == 0
    assert row["long_deadline"] == 0
    assert row["submission_window_observed"] == 1
    assert row["historically_certified"] == 0


def test_short_and_long_follow_the_observed_window_only():
    short = stage_period_feature_row(3, "evaluation_complete")
    long = stage_period_feature_row(120, "evaluation_complete")
    assert short["short_deadline"] == 1 and short["long_deadline"] == 0
    assert long["short_deadline"] == 0 and long["long_deadline"] == 1
    conflict = stage_period_feature_row(3, "evaluation_conflict")
    assert conflict["short_deadline"] is None


def test_vector_form_matches_the_row_form_and_clips_without_filling():
    status = pd.Series(
        ["evaluation_complete", "evaluation_incomplete", "evaluation_complete", "inverted"]
    )
    days = pd.Series([12, 30, 4000, 5])
    frame = apply_stage_period_features(status, days, clip=3650)
    for index in range(len(status)):
        row = stage_period_feature_row(days.iloc[index], status.iloc[index], clip=3650)
        assert frame.iloc[index]["submission_window_observed"] == row["submission_window_observed"]
        assert frame.iloc[index]["historically_certified"] == 0
        if row["bid_window_days"] is None:
            assert pd.isna(frame.iloc[index]["bid_window_days"])
        else:
            assert frame.iloc[index]["bid_window_days"] == row["bid_window_days"]
    assert frame.iloc[2]["bid_window_days"] == 3650
    assert frame.iloc[2]["submission_window_days_unclipped"] == 4000
    assert frame.iloc[2]["window_clipped"] == 1
    assert pd.isna(frame.iloc[1]["bid_window_days"])


def test_stage_model_matrix_uses_the_observed_median_and_a_missing_indicator():
    frame = pd.DataFrame(
        {
            "bid_window_days": [10.0, None, 20.0],
            "short_deadline": [0.0, None, 0.0],
            "long_deadline": [0.0, None, 0.0],
            "single_bidder": [1.0, 0.0, 0.0],
        }
    )
    matrix, info = stage_model_frame(
        frame, ["bid_window_days", "short_deadline", "long_deadline", "single_bidder"]
    )
    assert info["median_observed_window"] == 15
    assert info["constant_30_fill"] is False
    assert matrix.loc[1, "bid_window_days"] == 15
    assert matrix.loc[1, "submission_window_missing"] == 1
    assert matrix.loc[1, "short_deadline"] == 0
    assert 30 not in set(matrix["bid_window_days"])


def test_ablation_drops_only_the_period_columns():
    frame = pd.DataFrame(
        {
            "bid_window_days": [30.0, 30.0],
            "short_deadline": [0.0, 1.0],
            "long_deadline": [0.0, 0.0],
            "single_bidder": [1.0, 0.0],
        }
    )
    matrix, info = ablation_model_frame(
        frame, ["bid_window_days", "short_deadline", "long_deadline", "single_bidder"]
    )
    assert list(matrix.columns) == ["single_bidder"]
    assert info["dropped"] == ["bid_window_days", "short_deadline", "long_deadline"]
