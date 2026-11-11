"""Automated temporal-leakage tests (added 2026-10-20).

Two kinds of guarantee:

1. **Matrix invariants** - the availability matrix covers exactly the 22
   production features, stage sets are monotone, MTA-0013 post-decision
   suspects are unavailable before the award stage, labels are never features,
   corpus-reference features are excluded from point-in-time sets.
2. **Functional invariance** - a feature must not change when only *later*
   procurement events are perturbed. ``engineer_features`` is run on frames
   that differ solely in future columns and the earlier-stage outputs are
   asserted identical (with non-vacuous checks that later features *do*
   change).

These tests evaluate feature timing only; they never retrain or re-band
production v0.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.mtender.features import FEATURE_COLUMNS
from src.mtender.stage_features import (
    FEATURE_AVAILABILITY,
    LABEL_ONLY_FIELDS,
    LEAK_SUSPECT_FEATURES,
    STAGES,
    STAGE_ORDER,
    availability,
    feature_matrix,
    stage_columns,
    strict_stage_columns,
)

PUBLICATION_FEATURES = {"bid_window_days", "short_deadline", "long_deadline", "accelerated_like"}
BID_FEATURES = {"n_bidders_log", "single_bidder", "no_bid_data"}
BEHAVIOURAL = {
    "buyer_supplier_repeat_share",
    "winner_share_of_buyer_awards",
    "supplier_win_concentration",
    "supplier_award_count_log",
}
NOT_POINT_IN_TIME = BEHAVIOURAL | {"value_vs_cpv_median", "value_zscore_cpv"}

REQUIRED_META_KEYS = {
    "stage",
    "inputs",
    "calculation",
    "earliest_availability",
    "future_event_info",
    "point_in_time_safe",
    "notes",
}


# --------------------------------------------------------------------------- #
# matrix invariants
# --------------------------------------------------------------------------- #


def test_matrix_covers_exactly_the_production_features():
    assert set(FEATURE_AVAILABILITY) == set(FEATURE_COLUMNS)
    assert len(FEATURE_AVAILABILITY) == 22


def test_every_availability_record_is_complete():
    for feature, meta in FEATURE_AVAILABILITY.items():
        assert set(meta) == REQUIRED_META_KEYS, feature
        assert meta["stage"] in STAGES, feature
        assert meta["inputs"], feature
        assert meta["calculation"], feature
        assert meta["earliest_availability"], feature
        # consistency of the derived axis with the declared stage
        assert meta["future_event_info"] is (meta["stage"] != "publication"), feature


def test_stage_sets_are_monotone_and_complete():
    plain = [stage_columns(s) for s in STAGES]
    strict = [strict_stage_columns(s) for s in STAGES]
    for series in (plain, strict):
        for earlier, later in zip(series, series[1:]):
            assert set(earlier) <= set(later), (earlier, later)
    # the last stage is the production (as-of-now) set: all 22, in order
    assert plain[-1] == FEATURE_COLUMNS
    assert strict[-1] == FEATURE_COLUMNS


def test_unknown_stage_raises():
    with pytest.raises(ValueError, match="unknown stage"):
        stage_columns("contract_signing")
    with pytest.raises(ValueError, match="unknown stage"):
        stage_columns("publicationn")


def test_publication_stage_is_exactly_the_four_pre_award_inputs():
    pub = set(stage_columns("publication"))
    assert pub == PUBLICATION_FEATURES
    # nothing at publication needs an event after publication
    for f in pub:
        assert availability(f)["future_event_info"] is False
    # the bid stage adds exactly the competition-at-close family
    bid = set(stage_columns("bid_submission"))
    assert bid == PUBLICATION_FEATURES | BID_FEATURES


def test_mta0013_leak_suspects_unavailable_before_award():
    # nothing classified as post-decision is usable at publication/bid close
    available_by_bid = set(stage_columns("bid_submission"))
    assert not (set(LEAK_SUSPECT_FEATURES) & available_by_bid)
    assert not (set(LEAK_SUSPECT_FEATURES) & set(stage_columns("publication")))
    for feature in LEAK_SUSPECT_FEATURES:
        assert STAGE_ORDER[availability(feature)["stage"]] >= STAGE_ORDER["award_decision"]


def test_corpus_reference_features_excluded_from_point_in_time_sets():
    assert {f for f in FEATURE_COLUMNS if not availability(f)["point_in_time_safe"]} == (
        NOT_POINT_IN_TIME
    )
    award_strict = set(strict_stage_columns("award_decision"))
    assert NOT_POINT_IN_TIME & award_strict == set()
    assert set(stage_columns("award_decision")) - award_strict == NOT_POINT_IN_TIME
    # production stage keeps them: as-of-now scoring observes the corpus
    assert set(strict_stage_columns("post_award")) == set(FEATURE_COLUMNS)


def test_labels_are_never_features():
    assert not (set(LABEL_ONLY_FIELDS) & set(FEATURE_COLUMNS))
    assert not (set(LABEL_ONLY_FIELDS) & set(FEATURE_AVAILABILITY))


def test_feature_matrix_is_json_serialisable_and_documented():
    matrix = feature_matrix()
    json.dumps(matrix)  # must not raise
    assert matrix["production_stage"] == "post_award"
    assert len(matrix["stages"]) == len(STAGES)
    for stage in STAGES:
        assert matrix["stages"][stage]["n_features"] == len(
            matrix["stages"][stage]["features"]
        )
        assert (
            matrix["stages"][stage]["n_features_point_in_time"]
            == len(matrix["stages"][stage]["features_point_in_time"])
        )
    assert matrix["not_point_in_time_safe"] == sorted(
        matrix["not_point_in_time_safe"],
        key=FEATURE_COLUMNS.index,
    )
    assert "risk indicator" in matrix["disclaimer"]


def test_stage_sets_match_detection_summary_when_artefact_present():
    """Cross-check the matrix against the columns production v0 actually ran."""
    from pathlib import Path

    path = Path("results/mongo/detection_summary.json")
    if not path.exists():
        pytest.skip("detection_summary.json not present (regenerable artefact)")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["feature_columns"] == FEATURE_COLUMNS


# --------------------------------------------------------------------------- #
# functional invariance: later events must not move earlier-stage features
# --------------------------------------------------------------------------- #


def _base_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "award_value": [100.0, 200.0, None, 400.0, 500.0, 600.0],
            "award_total": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
            "estimated_value": [110.0, 190.0, 320.0, 410.0, 520.0, 590.0],
            "cpv_primary": ["45000000", "45000000", "30000000", "30000000", "45000000", "30000000"],
            "n_bidders": [1, 3, 0, 5, 2, 1],
            "n_suppliers": [1, 2, 1, 1, 3, 1],
            "tender_start": ["2021-01-01"] * 6,
            "tender_end": ["2021-01-05", "2021-03-01", "2021-01-20", "2021-06-01", "2021-02-10", "2021-01-12"],
            "n_amendments": [0, 1, 0, 2, 0, 0],
            "n_awards_with_value": [1, 3, 1, 1, 2, 1],
            "procurement_method_details": [
                "licitație deschisă",
                "procedură accelerată",
                "negociere",
                "licitație deschisă",
                "ofertă spontană",
                "licitație deschisă",
            ],
            "status": ["complete", "active", "cancelled", "complete", "unsuccessful", "active"],
            "buyer_id": ["b1", "b1", "b2", "b2", "b3", "b1"],
            "winner_id": ["w1", "w2", "w1", "w3", "w2", "w1"],
        }
    )


def _features(df: pd.DataFrame, columns: set[str]) -> pd.DataFrame:
    from src.mtender.features import add_behavioural_features, engineer_features

    out = add_behavioural_features(engineer_features(df))
    return out[list(sorted(columns))]


def test_publication_features_invariant_to_all_later_events():
    base = _base_frame()
    future = base.copy()
    # perturb everything that happens after publication
    future["award_value"] = future["award_value"] * 7 + 5
    future["award_total"] = future["award_total"] * 3
    future["n_bidders"] = [5, 0, 3, 1, 4, 2]
    future["n_suppliers"] = [3, 1, 2, 2, 1, 3]
    future["n_amendments"] = [4, 0, 3, 1, 5, 2]
    future["n_awards_with_value"] = [4, 1, 2, 3, 1, 5]
    future["status"] = ["cancelled", "complete", "active", "unsuccessful", "complete", "cancelled"]

    a = _features(base, PUBLICATION_FEATURES)
    b = _features(future, PUBLICATION_FEATURES)
    pd.testing.assert_frame_equal(a, b)

    # non-vacuous: the later-stage outputs really do react to those columns
    changed = _features(future, PUBLICATION_FEATURES | BID_FEATURES)
    same = _features(base, PUBLICATION_FEATURES | BID_FEATURES)
    assert not changed.equals(same)


def test_bid_stage_features_invariant_to_award_and_terminal_state():
    base = _base_frame()
    later = base.copy()
    # only post-bid-close events change
    later["award_value"] = later["award_value"] * 11
    later["award_total"] = later["award_total"] * 2
    later["n_amendments"] = later["n_amendments"] + 5
    later["status"] = ["complete", "cancelled", "active", "unsuccessful", "complete", "cancelled"]

    bid_set = PUBLICATION_FEATURES | BID_FEATURES
    pd.testing.assert_frame_equal(_features(base, bid_set), _features(later, bid_set))

    # non-vacuous: terminal-state features do change
    from src.mtender.features import add_behavioural_features, engineer_features

    a = add_behavioural_features(engineer_features(base))["cancelled"]
    b = add_behavioural_features(engineer_features(later))["cancelled"]
    assert not a.equals(b)


def test_award_stage_features_invariant_to_terminal_state_only():
    from src.mtender.features import add_behavioural_features, engineer_features

    base = _base_frame()
    terminal = base.copy()
    # row 2 has no award value; making it terminal-complete is exactly the
    # no_award_after_tender transition, and only `status` changes.
    terminal["status"] = ["cancelled", "complete", "complete", "unsuccessful", "cancelled", "active"]
    terminal["n_amendments"] = terminal["n_amendments"] + 3

    a = add_behavioural_features(engineer_features(base))
    b = add_behavioural_features(engineer_features(terminal))
    award_set = set(stage_columns("award_decision"))
    pd.testing.assert_frame_equal(a[list(sorted(award_set))], b[list(sorted(award_set))])

    # non-vacuous: post-award features do change
    for col in ("cancelled", "amended", "no_award_after_tender"):
        assert not a[col].equals(b[col]), col
