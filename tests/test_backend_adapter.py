"""Regression tests for the backend adapter.

The dashboard originally read a synthetic dataset whose column names did not
exist in the real feed. These tests pin the mapping so a real field can never be
silently reported as 0 or as a fabricated indicator.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.adapter import (  # noqa: E402
    UNAVAILABLE,
    _num,
    build_graph,
    build_stats,
    project_tender,
    risk_level,
)

REAL_ROW = {
    "ocid": "ocds-x-MD-1",
    "tender_id": "ocds-x-MD-1",
    "title": "Pharmaceutical supplies",
    "buyer_id": "MD-IDNO-1",
    "buyer_name": "IMSP",
    "buyer_identifier": "1",
    "buyer_locality": "mun.Chisinau",
    "procurement_method_details": "licitatie_deschisa",
    "status": "active",
    "cpv_primary": "33100000-1",
    "published_date": "2019-02-01T00:00:00Z",
    "list_date": "2019-06-11T00:00:00Z",
    "tender_start": "2019-02-01T00:00:00Z",
    "tender_end": "2019-03-22T00:00:00Z",
    "award_date": "2019-03-22T00:00:00Z",
    "bid_window_days": 49.0,
    "estimated_value": 2_687_373.09,
    "award_value": 27_025.0,
    "award_total": 7_992_807.28,
    "currency": "MDL",
    "winner_name": "SOGNO",
    "winner_identifier": None,
    "winner_id": "MD-IDNO-2",
    "n_bids": 503,
    "n_bidders": 28,
    "n_lots": 202,
    "n_awards": 210,
    "single_bidder": 0,
    "short_deadline": 0,
    "value_vs_cpv_median": 0.4,
    "winner_share_of_buyer_awards": 0.25,
    "buyer_supplier_repeat_share": 0.1,
    "estimate_to_award_ratio": 0.34,
    "has_bid_data": True,
    "has_award_data": True,
}

REAL_SCORE = {
    "ocid": "ocds-x-MD-1",
    "max_score": 0.81,
    "n_models_flagging": 2,
    "score_isolation_forest": 0.46,
    "score_local_outlier_factor": 490.0,
    "score_one_class_svm": -0.2,
    "score_statistical_mad_zscore": 3.1,
}


# -- numeric hygiene --------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_num_drops_non_finite(bad):
    """NaN/inf have no JSON encoding; FastAPI rejects the whole response.

    They must become None, not 0: a 0 would read as a measured zero.
    """
    assert _num(bad) is None


def test_num_rejects_bool_and_strings():
    assert _num(True) is None
    assert _num("3") is None
    assert _num(None) is None
    assert _num(3) == 3.0


def test_num_keeps_finite_values():
    assert _num(0) == 0.0
    assert _num(-2.5) == -2.5
    assert not math.isnan(_num(1.5))


# -- risk banding -----------------------------------------------------------

@pytest.mark.parametrize(
    "n_models,expected",
    [
        (0, "low"),
        (1, "medium"),
        (2, "high"),
        (3, "critical"),
        (4, "critical"),
        (None, "low"),
    ],
)
def test_risk_level_bands_on_model_agreement(n_models, expected):
    assert risk_level(n_models) == expected


def test_risk_level_tolerates_string_counts():
    assert risk_level("2") == "high"


# -- field mapping ----------------------------------------------------------

def test_project_tender_maps_real_field_names():
    t = project_tender(REAL_ROW, REAL_SCORE)
    # the real ETL names, not the synthetic ones
    assert t["procedure"] == "licitatie_deschisa"
    assert t["cpv_code"] == "33100000-1"
    assert t["published_at"] == "2019-02-01T00:00:00Z"
    assert t["bid_deadline"] == "2019-03-22T00:00:00Z"
    assert t["estimated_value_mdl"] == 2_687_373.09
    assert t["winner_idno"] is None


def test_project_tender_keeps_lot_summed_total():
    t = project_tender(REAL_ROW, REAL_SCORE)
    assert t["award_total_mdl"] == 7_992_807.28
    assert t["award_total_mdl"] > t["award_value_mdl"]


def test_project_tender_exposes_bid_records_separately():
    """bids.details is per lot, so n_bids must not be presented as bidders."""
    t = project_tender(REAL_ROW, REAL_SCORE)
    assert t["n_bidders"] == 28
    assert t["n_bid_records"] == 503
    assert "n_bids" in UNAVAILABLE


def test_project_tender_never_fabricates_unavailable_fields():
    t = project_tender(REAL_ROW, REAL_SCORE)
    for field in ("cpv_label", "bids", "planted_pattern", "is_planted_anomaly"):
        assert t[field] is None, f"{field} must be null, not a placeholder value"
    for field in ("round_price", "near_threshold", "bid_spread",
                  "negotiated_flag", "supplier_company_age"):
        assert field in UNAVAILABLE
        assert field not in t


def test_project_tender_scales_percentile_to_0_100():
    t = project_tender(REAL_ROW, REAL_SCORE)
    assert t["risk_score"] == 81.0
    assert 0 <= t["risk_score"] <= 100


def test_project_tender_without_scores_is_still_valid():
    t = project_tender(REAL_ROW, None)
    assert t["risk_score"] is None
    assert t["risk_level"] == "low"
    assert t["n_models_flagging"] is None


def test_flags_come_from_real_boolean_features():
    row = dict(REAL_ROW, single_bidder=1, short_deadline=1)
    flags = project_tender(row, REAL_SCORE)["flags"]
    assert "Single bidder" in flags
    assert "Short bidding window" in flags
    assert all(isinstance(f, str) and f for f in flags)


def test_flags_empty_when_nothing_triggered():
    assert project_tender(REAL_ROW, REAL_SCORE)["flags"] == []


# -- aggregates -------------------------------------------------------------

def test_build_stats_uses_all_lot_totals():
    rows = [project_tender(REAL_ROW, REAL_SCORE)]
    s = build_stats(rows, ["single_bidder"])
    assert s["total_award_mdl"] == 7_992_807.28
    assert s["n_tenders"] == 1
    assert s["n_buyers"] == 1
    assert s["n_winners"] == 1


def test_build_stats_reports_bidders_not_bid_records():
    s = build_stats([project_tender(REAL_ROW, REAL_SCORE)], [])
    assert s["mean_n_bidders"] == 28
    assert s["mean_n_bid_records"] == 503
    assert "mean_n_bids" not in s


def test_build_stats_handles_empty_input():
    s = build_stats([], [])
    assert s["n_tenders"] == 0
    assert s["mean_risk"] is None
    assert s["single_bidder_share"] is None
    assert s["total_award_mdl"] == 0


def test_build_stats_marks_metrics_unavailable():
    s = build_stats([project_tender(REAL_ROW, REAL_SCORE)], [])
    assert s["metrics"]["available"] is False
    assert s["metrics"]["reason"]


def test_build_stats_handles_non_finite_features():
    row = dict(REAL_ROW, value_vs_cpv_median=float("inf"))
    s = build_stats([project_tender(row, REAL_SCORE)], [])
    assert s["mean_risk"] == 81.0


def test_build_graph_links_buyer_to_winner():
    g = build_graph([project_tender(REAL_ROW, REAL_SCORE)])
    assert len(g["nodes"]) == 2
    assert len(g["links"]) == 1
    assert g["links"][0]["value"] == 7_992_807.28
    assert g["links"][0]["max_risk"] == 81.0


def test_build_graph_skips_rows_without_both_parties():
    g = build_graph([project_tender(dict(REAL_ROW, winner_id=None), REAL_SCORE)])
    assert g["links"] == []


def test_build_stats_counts_int_flags_as_set():
    """single_bidder_share was 0.0 because the ETL writes 1, not True."""
    row = dict(REAL_ROW, single_bidder=1)
    other = dict(REAL_ROW, ocid="ocds-y-MD-2", single_bidder=0)
    s = build_stats([project_tender(row, REAL_SCORE), project_tender(other, REAL_SCORE)], [])
    assert s["single_bidder_share"] == 0.5


def test_flag_rejects_strings_and_non_unit_numbers():
    from backend.app.adapter import _flag

    assert _flag(1) is True
    assert _flag(1.0) is True
    assert _flag(True) is True
    assert _flag(0) is False
    assert _flag(2) is False
    assert _flag("1") is False
    assert _flag(None) is False


def test_build_stats_excludes_rows_without_published_bidders():
    """n_bidders == 0 is missing data, not zero competition.

    Counting those rows made n_with_bid_data equal the whole dataset, which
    understated the single-bidder share by dividing by records that published no
    participant list at all.
    """
    published = dict(REAL_ROW, single_bidder=1, n_bidders=1)
    unpublished = dict(REAL_ROW, ocid="ocds-y-MD-2", single_bidder=0, n_bidders=0)
    s = build_stats(
        [project_tender(published, REAL_SCORE), project_tender(unpublished, REAL_SCORE)], []
    )
    assert s["n_with_bid_data"] == 1
    # 1 of the 1 procedures that published a list had a single bidder, not
    # 1 of the 2 rows in the dataset.
    assert s["single_bidder_share"] == 1.0
    assert s["mean_n_bidders"] == 1.0


def test_build_stats_reports_no_share_when_nothing_published_bidders():
    rows = [project_tender(dict(REAL_ROW, n_bidders=0), REAL_SCORE)]
    s = build_stats(rows, [])
    assert s["n_with_bid_data"] == 0
    assert s["single_bidder_share"] is None
    assert s["mean_n_bidders"] is None
