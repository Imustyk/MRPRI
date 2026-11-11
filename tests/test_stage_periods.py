"""The versioned period view must not mix a planning start with an evaluation end.

The eight rows are the snapshot values measured by MTA-0022. They lock the
defect and the correction. They do not certify publication-time features.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.stage_periods import (
    EVALUATION_COMPLETE,
    EVALUATION_CONFLICT,
    EVALUATION_INCOMPLETE,
    INVERTED,
    NO_EVALUATION_RECORD,
    stage_period_view,
)

# suffix, PN start, EV start, EV end, mixed legacy days, same-release EV days
AUDIT_ROWS = [
    ("1644854422949", "2022-03-01T00:00:00Z", "2022-02-24T09:00:00Z", "2022-03-09T07:00:00Z", 8, 12),
    ("1644995653154", "2022-02-01T00:00:00Z", "2022-02-26T13:00:00Z", "2022-03-07T13:00:00Z", 34, 9),
    ("1649084017389", "2022-04-01T00:00:00Z", "2022-04-16T05:00:00Z", "2022-04-29T05:00:00Z", 28, 13),
    ("1656940842812", "2022-07-01T00:00:00Z", "2022-07-11T13:30:00Z", "2022-07-14T13:30:10Z", 13, 3),
    ("1659961877383", "2022-08-01T00:00:00Z", "2022-08-19T07:00:00Z", "2022-08-29T08:00:00Z", 28, 10),
    ("1663056980047", "2022-09-01T00:00:00Z", "2022-09-26T06:00:00Z", "2022-10-03T06:00:00Z", 32, 7),
    ("1665058207960", "2022-10-01T00:00:00Z", "2022-10-17T11:30:00Z", "2022-10-26T11:30:00Z", 25, 9),
    ("1685970121601", "2023-06-01T00:00:00Z", "2023-06-10T13:30:00Z", "2023-06-19T06:00:00Z", 18, 8),
]


def _release(ocid: str, tag: str, start: str | None, end: str | None) -> dict:
    period = {}
    if start:
        period["startDate"] = start
    if end:
        period["endDate"] = end
    tender = {"id": "t1"}
    if period:
        tender["tenderPeriod"] = period
    return {"ocid": ocid, "tag": [tag], "tender": tender}


def _package(suffix: str, pn_start: str, ev_start: str, ev_end: str) -> dict:
    """Shape of MD-1644854422949: PN start only, empty base, EV both bounds."""
    base = f"ocds-b3wdp1-MD-{suffix}"
    return {
        "records": [
            {"compiledRelease": _release(f"{base}-PN-{suffix}", "planningUpdate", pn_start, None)},
            {"compiledRelease": _release(base, "compiled", None, None)},
            {"compiledRelease": _release(f"{base}-EV-{suffix}", "awardUpdate", ev_start, ev_end)},
        ]
    }


def test_audit_rows_keep_the_mixed_legacy_window_and_the_evaluation_window():
    for suffix, pn_start, ev_start, ev_end, legacy_days, evaluation_days in AUDIT_ROWS:
        package = _package(suffix, pn_start, ev_start, ev_end)
        view = stage_period_view(package)
        assert view["legacy_cross_stage"] == 1
        assert view["legacy_start_stage"] == "planning"
        assert view["legacy_end_stage"] == "evaluation"
        assert view["legacy_merged_start"] == pn_start
        assert view["legacy_merged_end"] == ev_end
        assert view["legacy_window_days"] == legacy_days
        assert view["submission_window_days"] == evaluation_days
        assert view["submission_window_status"] == EVALUATION_COMPLETE
        assert view["historically_certified"] == 0
        # The planning release must still have no end after the view is built.
        planning = package["records"][0]["compiledRelease"]["tender"]["tenderPeriod"]
        assert planning.get("endDate") is None


def test_conflicting_evaluation_periods_stay_missing():
    base = "ocds-b3wdp1-MD-1"
    package = {
        "records": [
            {"compiledRelease": _release(base, "compiled", None, None)},
            {"compiledRelease": _release(f"{base}-EV-a", "awardUpdate", "2022-02-01T00:00:00Z", "2022-02-10T00:00:00Z")},
            {"compiledRelease": _release(f"{base}-EV-b", "awardUpdate", "2022-02-01T00:00:00Z", "2022-02-20T00:00:00Z")},
        ]
    }
    view = stage_period_view(package)
    assert view["submission_window_status"] == EVALUATION_CONFLICT
    assert view["submission_window_days"] == ""
    assert view["n_evaluation_complete_pairs"] == 2


def test_evaluation_without_an_end_is_not_filled_from_planning_or_with_thirty():
    package = _package("1", "2022-03-01T00:00:00Z", "2022-02-24T09:00:00Z", "2022-03-09T07:00:00Z")
    package["records"][2]["compiledRelease"]["tender"]["tenderPeriod"].pop("endDate")
    view = stage_period_view(package)
    assert view["submission_window_status"] == EVALUATION_INCOMPLETE
    assert view["submission_window_days"] == ""


def test_inverted_evaluation_period_is_not_a_window():
    base = "ocds-b3wdp1-MD-1"
    package = {
        "records": [
            {"compiledRelease": _release(f"{base}-EV-1", "awardUpdate", "2022-03-09T00:00:00Z", "2022-03-01T00:00:00Z")},
        ]
    }
    view = stage_period_view(package)
    assert view["submission_window_status"] == INVERTED
    assert view["submission_window_days"] == ""


def test_no_evaluation_record_is_explicit():
    base = "ocds-b3wdp1-MD-1"
    package = {"records": [{"compiledRelease": _release(base, "compiled", "2022-03-01T00:00:00Z", "2022-03-20T00:00:00Z")}]}
    view = stage_period_view(package)
    assert view["submission_window_status"] == NO_EVALUATION_RECORD
    assert view["submission_window_days"] == ""
    assert view["legacy_cross_stage"] == 0
