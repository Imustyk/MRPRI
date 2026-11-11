"""Stage-pure submission windows for a versioned export.

``merge_compiled_releases`` keeps the first non-empty value and then fills
holes from later releases. On this corpus that pairs a planning-notice
``tenderPeriod.startDate`` with an evaluation-notice ``tenderPeriod.endDate``.
The two dates belong to different stages of one procedure.

This module does not change that merge and does not write ``features.csv``.
Nested objects are copied before the legacy merge is reproduced, because an
in-place merge would write the evaluation end back onto the planning period
and hide the mix. A submission window is reported only when both bounds come
from the same evaluation release. A missing bound stays missing. The result
describes the current snapshot. It is not a certified publication-time value.
"""

from __future__ import annotations

import copy
from typing import Any

import pandas as pd

PLANNING = "planning"
EVALUATION = "evaluation"
BASE = "base"

EVALUATION_COMPLETE = "evaluation_complete"
EVALUATION_CONFLICT = "evaluation_conflict"
EVALUATION_INCOMPLETE = "evaluation_incomplete"
NO_EVALUATION_RECORD = "no_evaluation_record"
INVERTED = "inverted"
UNPARSEABLE = "unparseable"


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(item) for item in _as_list(value)]


def stage_of(ocid: str | None) -> str:
    """Stage from the OCID suffix. The release tag is not a stage."""
    text = ocid or ""
    if "-PN-" in text:
        return PLANNING
    if "-EV-" in text:
        return EVALUATION
    return BASE


def compiled_releases(package: dict) -> list[dict]:
    found: list[dict] = []
    for record in _as_list(package.get("records")):
        if not isinstance(record, dict):
            continue
        release = record.get("compiledRelease")
        if isinstance(release, dict):
            found.append(release)
    return found


def _is_compiled_tag(release: dict) -> bool:
    return "compiled" in _tags(release.get("tag"))


def merge_order(releases: list[dict]) -> list[dict]:
    """Same order as ``merge_compiled_releases``: compiled tag first, then stable."""
    return sorted(releases, key=lambda release: not _is_compiled_tag(release))


def _period(release: dict) -> dict:
    tender = release.get("tender")
    if not isinstance(tender, dict):
        return {}
    period = tender.get("tenderPeriod")
    return period if isinstance(period, dict) else {}


def _merge_copies(base: dict, extra: dict) -> dict:
    for key, value in (extra or {}).items():
        if key not in base or base[key] in (None, "", [], {}):
            base[key] = copy.deepcopy(value)
        elif isinstance(base[key], dict) and isinstance(value, dict):
            _merge_copies(base[key], value)
    return base


def floor_days(start: str | None, end: str | None) -> int | None:
    """Whole days of ``end - start``, matching ``Series.dt.days``.

    Returns ``None`` when either bound is missing or unparseable. Does not
    fill, clip, or borrow a bound from another stage. A negative span is
    returned as a negative integer so the caller can flag it.
    """
    if not start or not end:
        return None
    start_ts = pd.to_datetime(start, utc=True, errors="coerce")
    end_ts = pd.to_datetime(end, utc=True, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        return None
    return int((end_ts - start_ts).days)


def _bound_source(ordered: list[dict], field: str, value: str | None) -> str | None:
    if not value:
        return None
    for release in ordered:
        if _period(release).get(field) == value:
            return stage_of(release.get("ocid"))
    return None


def _complete_pairs(releases: list[dict], stage: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for release in releases:
        if stage_of(release.get("ocid")) != stage:
            continue
        period = _period(release)
        start = period.get("startDate")
        end = period.get("endDate")
        if not start or not end:
            continue
        pair = (str(start), str(end))
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return pairs


def _has_stage(releases: list[dict], stage: str) -> bool:
    return any(stage_of(release.get("ocid")) == stage for release in releases)


def stage_period_view(package: dict) -> dict:
    """One row of the versioned period export.

    ``submission_window_days`` is set only for a single complete evaluation
    period whose span is zero or positive. Conflicting evaluation periods,
    a planning start, and a missing bound all leave it empty.
    """
    releases = compiled_releases(package)
    # Read stage periods before the legacy merge. The production merge assigns
    # nested dicts by reference; doing that here would paint the evaluation
    # end onto the planning release and then report a false single source.
    evaluation_pairs = _complete_pairs(releases, EVALUATION)
    planning_pairs = _complete_pairs(releases, PLANNING)
    ordered = merge_order(releases)
    merged: dict = {}
    for release in ordered:
        _merge_copies(merged, release)
    merged_period = _period(merged)
    merged_start = merged_period.get("startDate")
    merged_end = merged_period.get("endDate")
    start_stage = _bound_source(ordered, "startDate", merged_start)
    end_stage = _bound_source(ordered, "endDate", merged_end)
    legacy_days = floor_days(
        str(merged_start) if merged_start else None,
        str(merged_end) if merged_end else None,
    )

    status = NO_EVALUATION_RECORD
    submission_days: int | None = None
    chosen: tuple[str, str] | None = None
    if not _has_stage(releases, EVALUATION):
        status = NO_EVALUATION_RECORD
    elif len(evaluation_pairs) > 1:
        status = EVALUATION_CONFLICT
    elif len(evaluation_pairs) == 0:
        status = EVALUATION_INCOMPLETE
    else:
        chosen = evaluation_pairs[0]
        submission_days = floor_days(chosen[0], chosen[1])
        if submission_days is None:
            status = UNPARSEABLE
            submission_days = None
        elif submission_days < 0:
            status = INVERTED
            submission_days = None
        else:
            status = EVALUATION_COMPLETE

    return {
        "n_compiled_releases": len(releases),
        "has_planning_record": int(_has_stage(releases, PLANNING)),
        "has_evaluation_record": int(_has_stage(releases, EVALUATION)),
        "legacy_merged_start": merged_start or "",
        "legacy_merged_end": merged_end or "",
        "legacy_start_stage": start_stage or "",
        "legacy_end_stage": end_stage or "",
        "legacy_cross_stage": int(
            bool(merged_start and merged_end and start_stage and end_stage and start_stage != end_stage)
        ),
        "legacy_window_days": "" if legacy_days is None or legacy_days < 0 else legacy_days,
        "n_evaluation_complete_pairs": len(evaluation_pairs),
        "n_planning_complete_pairs": len(planning_pairs),
        "evaluation_start": chosen[0] if chosen else "",
        "evaluation_end": chosen[1] if chosen else "",
        "submission_window_days": "" if submission_days is None else submission_days,
        "submission_window_status": status,
        "historically_certified": 0,
    }
