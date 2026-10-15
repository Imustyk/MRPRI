"""KPI checks for the four detectors.

Two contracts are pinned here:

* ``_bin_flag`` keeps "scored and cleared" (False) apart from "never scored"
  (None) - collapsing them is how an unscored corpus starts reading as cleared.
* ``build_kpi_report`` fails when the served scores stop matching the declared
  catalogue: a missing verdict, a flagged share outside the contamination band,
  counts that disagree with the flags, or a model path that no longer resolves.

No check asserts a precision/recall figure, because none exists for this corpus.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.adapter import MODEL_KEYS, _bin_flag, project_tender  # noqa: E402
from backend.app.model_kpis import (  # noqa: E402
    CONTAMINATION_TOLERANCE,
    DETECTORS,
    Z_THRESHOLD,
    _artifact_check,
    build_kpi_report,
)

N_ROWS = 50


# -- _bin_flag ---------------------------------------------------------------

@pytest.mark.parametrize("value", [1, 1.0, True])
def test_bin_flag_accepts_set_values(value):
    assert _bin_flag(value) is True


@pytest.mark.parametrize("value", [0, 0.0, False])
def test_bin_flag_accepts_unset_values(value):
    assert _bin_flag(value) is False


@pytest.mark.parametrize("value", [None, "1", "0", "", 2, -1, 0.5, float("nan")])
def test_bin_flag_keeps_unknown_as_none(value):
    """Anything that is not a 0/1 must stay "no verdict", never a verdict.

    ``"0"`` read as False would assert a clearance the run never made.
    """
    assert _bin_flag(value) is None


# -- project_tender ----------------------------------------------------------

def _score(flagged: bool) -> dict:
    return {
        "max_score": 0.9 if flagged else 0.1,
        "n_models_flagging": 4 if flagged else 0,
        "consensus": int(flagged),
        "score_statistical_mad_zscore": 9.0 if flagged else 2.0,
        "score_isolation_forest": 0.9 if flagged else 0.4,
        "score_local_outlier_factor": 500.0 if flagged else 1.0,
        "score_one_class_svm": 2.0 if flagged else -6.0,
        "flag_statistical_mad_zscore": int(flagged),
        "flag_isolation_forest": int(flagged),
        "flag_local_outlier_factor": int(flagged),
        "flag_one_class_svm": int(flagged),
    }


def test_project_tender_exposes_every_detector_verdict():
    t = project_tender({"ocid": "ocds-x-1"}, _score(True))
    assert set(t["model_flags"]) == set(MODEL_KEYS)
    assert all(v is True for v in t["model_flags"].values())
    assert t["consensus_flag"] is True


def test_project_tender_flags_false_mean_cleared():
    t = project_tender({"ocid": "ocds-x-1"}, _score(False))
    assert all(v is False for v in t["model_flags"].values())
    assert t["consensus_flag"] is False


def test_project_tender_flags_none_mean_never_scored():
    """No score document: every verdict is absent, not a clearance."""
    t = project_tender({"ocid": "ocds-x-1"}, None)
    assert all(v is None for v in t["model_flags"].values())
    assert t["consensus_flag"] is None
    assert t["risk_level"] == "unscored"


def test_project_tender_rejects_non_binary_flag_values():
    score = _score(False)
    score["flag_isolation_forest"] = "1"  # a stray string must not become True
    t = project_tender({"ocid": "ocds-x-1"}, score)
    assert t["model_flags"]["isolation_forest"] is None


# -- catalogue ---------------------------------------------------------------

def test_catalogue_covers_the_four_project_detectors():
    assert tuple(d["key"] for d in DETECTORS) == MODEL_KEYS
    assert len(DETECTORS) == 4


def test_catalogue_declares_the_run_parameters():
    """The catalogue is the run's contract: contamination, threshold, paths."""
    by_key = {d["key"]: d for d in DETECTORS}
    assert by_key["statistical_mad_zscore"]["threshold"] == {
        "kind": "rule",
        "name": "z_threshold",
        "value": Z_THRESHOLD,
    }
    for key in ("isolation_forest", "local_outlier_factor", "one_class_svm"):
        assert by_key[key]["threshold"]["value"] == 0.05
    # Isolation Forest is the only fitted model scripts/06 persists.
    assert by_key["isolation_forest"]["artifact"]["path"]
    assert by_key["local_outlier_factor"]["artifact"]["path"] is None
    assert by_key["one_class_svm"]["artifact"]["path"] is None


# -- report helpers ----------------------------------------------------------

def _rows(n_flagged: int, **overrides) -> list[dict]:
    rows = []
    for i in range(N_ROWS):
        score = _score(i < n_flagged)
        score.update(overrides)
        rows.append(project_tender({"ocid": f"ocds-x-{i}"}, score))
    return rows


def _no_artifacts() -> list[dict]:
    """Catalogue with the on-disk artefact checks removed.

    Tests must not depend on whether results/models/ happens to exist in this
    checkout; artefact resolution is covered separately with tmp_path bundles.
    """
    out = copy.deepcopy(DETECTORS)
    for det in out:
        det["artifact"] = {"path": None, "members": [], "note": "not persisted"}
    return out


def _status(report: dict, check_id: str) -> str:
    for check in report["checks"]:
        if check["id"] == check_id:
            return check["status"]
    raise AssertionError(f"no check {check_id} in report")


def _detail(report: dict, check_id: str) -> str:
    for check in report["checks"]:
        if check["id"] == check_id:
            return check["detail"]
    raise AssertionError(f"no check {check_id} in report")


# -- report: passing corpus --------------------------------------------------

def test_report_passes_on_a_consistent_corpus():
    report = build_kpi_report(_rows(3), _no_artifacts(), {})
    assert report["ok"] is True
    assert report["n_failed"] == 0
    assert report["n_rows"] == N_ROWS
    assert report["n_scored"] == N_ROWS
    # 3/50 = 6% sits inside 5% +/- the 3 pp tolerance.
    for key in ("isolation_forest", "local_outlier_factor", "one_class_svm"):
        assert _status(report, f"threshold:{key}") == "pass"
    assert _status(report, "threshold:statistical_mad_zscore") == "pass"
    assert _status(report, "count_consistency") == "pass"
    assert _status(report, "consensus_consistency") == "pass"


def test_report_has_four_checks_per_detector():
    report = build_kpi_report(_rows(3), _no_artifacts(), {})
    for det in DETECTORS:
        ids = [c["id"] for c in report["checks"] if c["detector"] == det["key"]]
        assert len(ids) == 4, det["key"]
        assert {i.split(":", 1)[0] for i in ids} == {"flags", "threshold", "score", "artifact"}


def test_report_states_that_precision_recall_do_not_exist():
    report = build_kpi_report(_rows(3), _no_artifacts(), {})
    metrics = report["metrics"]
    assert metrics["available"] is False
    assert "precision" in metrics["reason"]
    # The numbers themselves must never appear, not even as nulls.
    assert not {"precision", "recall", "f1"} & set(metrics)


def test_report_carries_the_contamination_assumption_and_tolerance():
    report = build_kpi_report(_rows(3), _no_artifacts(), {})
    assert report["contamination"] == {"declared": 0.05, "tolerance": CONTAMINATION_TOLERANCE}
    assert CONTAMINATION_TOLERANCE == 0.03


def test_report_without_a_run_summary_skips_reproduction():
    report = build_kpi_report(_rows(3), _no_artifacts(), {})
    assert _status(report, "run_reproduction") == "skip"
    assert report["run"] is None


# -- report: failing corpora --------------------------------------------------

def test_flagged_share_outside_the_contamination_band_fails():
    """0% flagged is 5 pp off the declared 5%: outside the +/-3 pp band."""
    report = build_kpi_report(_rows(0), _no_artifacts(), {})
    for key in ("isolation_forest", "local_outlier_factor", "one_class_svm"):
        assert _status(report, f"threshold:{key}") == "fail"
    assert "tolerance +/-3 pp" in _detail(report, "threshold:isolation_forest")
    # The MAD baseline declares a rule, not a contamination, so it is unaffected.
    assert _status(report, "threshold:statistical_mad_zscore") == "pass"
    assert report["ok"] is False


def test_score_document_without_verdicts_fails_the_flag_check():
    rows = [
        project_tender(
            {"ocid": f"ocds-x-{i}"},
            {"max_score": 0.5, "n_models_flagging": 0, "consensus": 0,
             "score_statistical_mad_zscore": 2.0},
        )
        for i in range(N_ROWS)
    ]
    report = build_kpi_report(rows, _no_artifacts(), {})
    for key in MODEL_KEYS:
        assert _status(report, f"flags:{key}") == "fail"
        assert "none carries flag_" in _detail(report, f"flags:{key}")
    # A count with no verdicts behind it cannot be cross-checked, not "passed".
    assert _status(report, "count_consistency") == "skip"


def test_model_count_disagreeing_with_the_verdicts_fails():
    report = build_kpi_report(_rows(3, n_models_flagging=2), _no_artifacts(), {})
    assert _status(report, "count_consistency") == "fail"


def test_consensus_disagreeing_with_the_model_count_fails():
    report = build_kpi_report(_rows(3, consensus=1), _no_artifacts(), {})
    assert _status(report, "consensus_consistency") == "fail"


def test_mad_flag_that_the_score_does_not_reproduce_fails():
    """flag=1 on rows scoring 2.0 contradicts flag == (score > 5.0)."""
    report = build_kpi_report(_rows(3, flag_statistical_mad_zscore=1), _no_artifacts(), {})
    assert _status(report, "threshold:statistical_mad_zscore") == "fail"
    assert _status(report, "threshold:isolation_forest") == "pass"


def test_flagged_scores_must_exceed_cleared_scores():
    """A detector whose flagged rows score lower than its cleared ones is broken."""
    rows = _rows(3)
    # Isolation Forest: higher = more anomalous, so invert the direction.
    for row in rows:
        row["iso_score"] = 0.1 if row["model_flags"]["isolation_forest"] else 10.0
    report = build_kpi_report(rows, _no_artifacts(), {})
    assert _status(report, "score:isolation_forest") == "fail"


def test_run_reproduction_detects_a_corpus_that_moved():
    run = {"run_id": "detect-test", "models": [
        {"model": "isolation_forest", "n_flagged": 1, "pct_flagged": 4.999},
    ]}
    # live share is 6% (3/50): more than 0.1 pp away from the recorded 4.999%.
    report = build_kpi_report(_rows(3), _no_artifacts(), run)
    assert _status(report, "run_reproduction") == "fail"
    assert report["run"]["run_id"] == "detect-test"


def test_run_reproduction_passes_when_the_figures_match():
    run = {"run_id": "detect-test", "models": [
        {"model": "isolation_forest", "n_flagged": 3, "pct_flagged": 6.0},
    ]}
    report = build_kpi_report(_rows(3), _no_artifacts(), run)
    assert _status(report, "run_reproduction") == "pass"


def test_empty_corpus_skips_instead_of_reporting_a_clearance():
    """Nothing served means nothing to verify - skip, never a pass."""
    report = build_kpi_report([], _no_artifacts(), {})
    assert _status(report, "coverage") == "skip"
    assert report["ok"] is True
    for det in DETECTORS:
        assert _status(report, f"flags:{det['key']}") == "skip"


# -- artefact paths ----------------------------------------------------------

def test_artifact_missing_on_disk_fails(tmp_path):
    det = copy.deepcopy(DETECTORS[1])
    det["artifact"] = {"path": str(tmp_path / "absent.joblib"), "members": [], "note": None}
    status, detail = _artifact_check(det)
    assert status == "fail"
    assert "not found" in detail


def test_artifact_with_wrong_contamination_fails(tmp_path):
    """The bundle is rewritten every run, so its contents are checked too."""
    import joblib

    path = tmp_path / "anomaly_models.joblib"
    joblib.dump({"isolation_forest": 1, "scaler": 1, "contamination": 0.12}, path)
    det = copy.deepcopy(DETECTORS[1])
    det["artifact"] = {
        "path": str(path),
        "members": ["isolation_forest", "scaler"],
        "note": None,
    }
    status, detail = _artifact_check(det)
    assert status == "fail"
    assert "contamination" in detail


def test_artifact_matching_the_catalogue_passes(tmp_path):
    import joblib

    path = tmp_path / "anomaly_models.joblib"
    joblib.dump(
        {"isolation_forest": 1, "scaler": 1, "feature_columns": ["a"], "contamination": 0.05},
        path,
    )
    det = copy.deepcopy(DETECTORS[1])
    det["artifact"] = {
        "path": str(path),
        "members": ["isolation_forest", "scaler", "feature_columns"],
        "note": None,
    }
    status, detail = _artifact_check(det)
    assert status == "pass"
    assert str(path) in detail


def test_detectors_without_an_artefact_are_skipped_not_passed():
    for key in ("statistical_mad_zscore", "local_outlier_factor", "one_class_svm"):
        det = next(d for d in DETECTORS if d["key"] == key)
        status, detail = _artifact_check(det)
        assert status == "skip"
        assert detail  # the reason must be stated, not blank


def test_report_includes_artefact_status_per_detector():
    report = build_kpi_report(_rows(3), _no_artifacts(), {})
    for entry in report["detectors"]:
        assert entry["artifact"]["status"] == "skip"
        assert entry["artifact"]["detail"]
        assert entry["live"]["n_scored"] == N_ROWS
