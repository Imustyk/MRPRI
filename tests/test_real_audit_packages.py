"""The eight MTA-0022 packages keep separate planning and evaluation periods."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.audit_expectations import AUDIT_PACKAGES
from src.mtender.mta_protocol import DIPLOM_ROOT
from src.mtender.stage_periods import stage_period_view

PACKAGES = DIPLOM_ROOT / "data" / "raw" / "ocds_packages"


@pytest.mark.skipif(not PACKAGES.is_dir(), reason="read-only corpus is not mounted")
@pytest.mark.parametrize("expected", AUDIT_PACKAGES, ids=lambda row: row["ocid"])
def test_real_package_matches_the_mta0022_snapshot(expected):
    path = PACKAGES / f"{expected['ocid']}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        package = json.load(handle)
    view = stage_period_view(package)
    assert view["legacy_cross_stage"] == 1
    assert view["legacy_start_stage"] == "planning"
    assert view["legacy_end_stage"] == "evaluation"
    assert view["legacy_merged_start"] == expected["pn_start"]
    assert view["legacy_merged_end"] == expected["ev_end"]
    assert view["legacy_window_days"] == expected["legacy_days"]
    assert view["evaluation_start"] == expected["ev_start"]
    assert view["evaluation_end"] == expected["ev_end"]
    assert view["submission_window_days"] == expected["evaluation_days"]
    assert view["submission_window_status"] == "evaluation_complete"
    assert view["historically_certified"] == 0
