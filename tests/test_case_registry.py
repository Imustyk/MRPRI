"""MTA-0016 tests: the case registry — schema, matching, temporal protection.

Covers the pieces the third external label trusts: the registry schema
(required columns, no-source rejection, enum validation, evidence D never in
the label), the matching ladder (IDNO -> exact name -> fuzzy candidate that
stays ``low`` and is never auto-promoted), the TEMPORAL GUARD of
``scripts/39`` (only procedures published strictly before the case's
``first_publication_date`` are positive; post-date rows leave the population),
the power gate and the pre-registered verdict rule.

Security regression: ``scripts/38/39/40`` must perform no network requests -
no network imports, standalone under ``python -I``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REGISTRY_TEMPLATE = ROOT / "data" / "external" / "case_registry.csv"
SCHEMA_DOC = ROOT / "docs" / "case_registry_schema.md"


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S38 = _load_script("38_case_registry_match.py")
S39 = _load_script("39_case_registry_check.py")


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------

FEATURES = pd.DataFrame({
    "ocid": ["ocd-P1", "ocd-P2", "ocd-P3", "ocd-P4", "ocd-B1"],
    "buyer_identifier": ["2000000000001", "2000000000001", "2000000000002",
                         "2000000000003", "2000000000004"],
    "buyer_name": ["PRIMARIA X", "PRIMARIA X", "MINISTERUL Y", "CONSILIUL Z",
                   "AGENTIA W"],
    "winner_identifier": ["1000000000001", "1000000000001", "1000000000002",
                          "1000000000003", "1000000000004"],
    "winner_name": ["ALPHA SRL", "ALPHA SRL", "BETA INDUSTRIES S.R.L.",
                    "GAMMA", "DELTA SRL"],
    "published_date": ["2020-01-01T00:00:00Z", "2021-06-01T00:00:00Z",
                       "2019-03-01T00:00:00Z", "2022-05-01T00:00:00Z",
                       "2021-01-01T00:00:00Z"],
    # columns scripts/39 merges for the baselines and the group control
    "log_award_total": [15.0, 16.0, 14.0, 17.0, 15.5],
    "n_bidders_log": [1.0, 0.0, 2.0, 0.0, 1.0],
    "log_award_value": [15.0, 16.0, 14.0, 17.0, 15.5],
    "procurement_method_details": ["open", "open", "open", "direct",
                                   "open"],
})


def _registry_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a registry CSV; missing fields default to a valid baseline."""
    base = {c: "" for c in S38.REQUIRED_COLUMNS}
    base.update({
        "case_id": "C-1", "title_short": "Эпизод",
        "entity_type": "supplier", "entity_id_mtender": "1000000000001",
        "entity_name_as_in_source": "ALPHA SRL",
        "source_url_1": "https://example.org/act", "source_type_1": "court",
        "source_date_1": "2023-01-10", "evidence_level": "A",
        "risk_type": "collusion", "first_publication_date": "2023-01-15",
        "verified_by_human": "true",
    })
    frame = pd.DataFrame([{**base, **row} for row in rows])
    path = tmp_path / "registry.csv"
    frame.to_csv(path, index=False)
    return path


def _load(tmp_path: Path, rows: list[dict]):
    raw = pd.read_csv(_registry_csv(tmp_path, rows), dtype="string",
                      keep_default_na=False)
    registry, validation = S38.validate_registry(raw)
    corpus = S38.load_corpus(_features_csv(tmp_path))
    per_case, proc, summary = S38.match_cases(registry, corpus)
    return registry, validation, corpus, per_case, summary


def _features_csv(tmp_path: Path) -> Path:
    path = tmp_path / "features.csv"
    FEATURES.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def test_template_header_matches_schema_exactly():
    header = pd.read_csv(REGISTRY_TEMPLATE, nrows=0).columns.tolist()
    assert header == S38.REQUIRED_COLUMNS
    assert len(pd.read_csv(REGISTRY_TEMPLATE)) == 0  # template carries no cases


def test_schema_doc_lists_every_column():
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    for col in S38.REQUIRED_COLUMNS:
        assert f"`{col}`" in text, f"docs/case_registry_schema.md omits {col}"
    for token in ("evidence_level", "first_publication_date", "name_fuzzy",
                  "не принимаются", "компетентным органом"):
        assert token in text


def test_normalize_idno_variants_and_garbage():
    assert S38.normalize_idno("MD-IDNO-1006601001182") == "1006601001182"
    assert S38.normalize_idno(" 1006601001182 ") == "1006601001182"
    assert S38.normalize_idno(1006601001182.0) == "1006601001182"
    assert S38.normalize_idno("не-идно") is None
    assert S38.normalize_idno("") is None
    assert S38.normalize_idno(None) is None


def test_row_without_source_is_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [
        {"case_id": "C-ok"},
        {"case_id": "C-bad", "source_url_1": "", "source_date_1": ""},
    ])
    assert validation["n_rows"] == 2
    assert validation["n_valid"] == 1
    assert validation["n_rejected"] == 1
    assert validation["rejected"][0]["case_id"] == "C-bad"
    assert any("источника" in r for r in validation["rejected"][0]["reasons"])


def test_row_without_first_publication_is_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [
        {"case_id": "C-nodate", "first_publication_date": ""}])
    assert validation["n_rejected"] == 1
    assert any("first_publication_date" in r
               for r in validation["rejected"][0]["reasons"])


def test_enum_violations_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [
        {"case_id": "C-ev", "evidence_level": "Z"},
        {"case_id": "C-risk", "risk_type": "bribery"},
        {"case_id": "C-type", "entity_type": " intermediary "},
        {"case_id": "C-range", "period_from": "2022-01-01",
         "period_to": "2021-01-01"},
    ])
    assert validation["n_rejected"] == 4


def test_duplicate_case_id_rejected(tmp_path):
    _, validation, *_ = _load(tmp_path, [{"case_id": "C-1"},
                                         {"case_id": "C-1"}])
    assert validation["n_rejected"] == 1


# ---------------------------------------------------------------------------
# matching ladder
# ---------------------------------------------------------------------------

def test_idno_match_priority_and_label_grade(tmp_path):
    _, _, _, per_case, summary = _load(tmp_path, [
        {"entity_id_mtender": "1000000000001", "entity_name_as_in_source": "ALPHA SRL"}])
    rec = per_case[0]
    assert rec["match_method"] == "idno_exact"
    assert rec["match_confidence"] == "high"
    assert sorted(rec["procedure_ids"]) == ["ocd-P1", "ocd-P2"]
    assert rec["label_grade"] is True
    assert summary["n_matched_label_grade"] == 1


def test_idno_falls_back_to_exact_name(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"entity_id_mtender": "9999999999999", "entity_name_as_in_source": "Beta Industries S.R.L."}])
    rec = per_case[0]
    assert rec["match_method"] == "name_exact"
    assert rec["match_confidence"] == "high"
    assert rec["procedure_ids"] == ["ocd-P3"]


def test_fuzzy_is_candidate_only_never_high(tmp_path):
    _, _, corpus, per_case, summary = _load(tmp_path, [
        {"entity_id_mtender": "", "entity_name_as_in_source": "BETA"}])
    rec = per_case[0]
    assert rec["match_method"] == "name_fuzzy"
    assert rec["match_confidence"] == "low"          # never auto-promoted
    assert rec["label_grade"] is False
    assert rec["procedure_ids"] == ["ocd-P3"]        # carried as candidate
    assert summary["n_fuzzy_candidates"] == 1
    assert summary["n_matched_label_grade"] == 0
    # and the fuzzy candidate builds NO label positives
    frame, info = S39.build_label_population(per_case, corpus)
    assert frame is None or info.get("n_positives", 0) == 0


def test_buyer_match_by_buyer_columns(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"entity_type": "buyer", "entity_id_mtender": "2000000000002",
         "entity_name_as_in_source": ""}])
    rec = per_case[0]
    assert rec["match_method"] == "idno_exact"
    assert rec["procedure_ids"] == ["ocd-P3"]


def test_manual_requires_verified_human(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"match_method": "manual", "procedure_ids": "ocd-P4",
         "verified_by_human": "true", "match_confidence": "high"},
        {"case_id": "C-2", "match_method": "manual",
         "procedure_ids": "ocd-P4", "verified_by_human": "false",
         "entity_id_mtender": "1000000000001"},
    ])
    assert per_case[0]["match_method"] == "manual"
    assert per_case[0]["procedure_ids"] == ["ocd-P4"]
    # unverified manual falls back to the automatic ladder (IDNO 1000000000001 here)
    assert per_case[1]["match_method"] == "idno_exact"
    assert "manual без verified_by_human" in per_case[1]["note"]


def test_evidence_d_never_enters_the_label(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"evidence_level": "D"}])
    rec = per_case[0]
    assert rec["match_method"] == "idno_exact"      # still matched & reported
    assert rec["label_grade"] is False              # but D is never label-grade


def test_declared_columns_are_crosschecked(tmp_path):
    _, _, _, per_case, _ = _load(tmp_path, [
        {"n_procedures_matched": "7", "match_confidence": "medium"}])
    diffs = S38.crosscheck_declared(per_case)
    fields = {d["field"] for d in diffs}
    assert "n_procedures_matched" in fields
    assert "match_confidence" in fields


# ---------------------------------------------------------------------------
# temporal protection (scripts/39)
# ---------------------------------------------------------------------------

def test_temporal_guard_labels_only_pre_publication_procedures(tmp_path):
    _, _, corpus, per_case, _ = _load(tmp_path, [
        {"entity_id_mtender": "1000000000001", "first_publication_date": "2021-01-01"}])
    frame, info = S39.build_label_population(per_case, corpus)
    # window: published < 2021-01-01 -> P1 (2020) and P3 (2019); P2 (2021-06)
    # postdates the case and is excluded from the population entirely
    assert set(frame["ocid"]) == {"ocd-P1", "ocd-P3"}
    assert info["n_positives"] == 1
    assert frame.loc[frame["ocid"] == "ocd-P1", "y"].iloc[0] == 1
    assert "ocd-P2" not in set(frame["ocid"])
    assert info["n_dropped_post_publication"] == 1
    assert info["max_cutoff"] == "2021-01-01"


def test_temporal_guard_same_day_excluded(tmp_path):
    # published ON the first_publication_date is NOT strictly before it
    _, _, corpus, per_case, _ = _load(tmp_path, [
        {"entity_id_mtender": "1000000000004", "first_publication_date": "2021-01-01"}])
    frame, info = S39.build_label_population(per_case, corpus)
    assert info["n_positives"] == 0


def test_temporal_guard_excludes_d_and_low_confidence(tmp_path):
    _, _, corpus, per_case, _ = _load(tmp_path, [
        {"case_id": "C-D", "entity_id_mtender": "1000000000002", "evidence_level": "D",
         "first_publication_date": "2023-01-01"},
        {"case_id": "C-low", "entity_id_mtender": "1000000000004",
         "evidence_level": "A", "match_method": "manual",
         "match_confidence": "low", "verified_by_human": "true",
         "procedure_ids": "ocd-B1",
         "first_publication_date": "2023-01-01"}])
    frame, info = S39.build_label_population(per_case, corpus)
    assert info.get("n_positives", 0) == 0


# ---------------------------------------------------------------------------
# power gate + verdict rule
# ---------------------------------------------------------------------------

def test_small_sample_gate_blocks_verdict():
    y = np.array([1] * 12 + [0] * 100)
    sup = np.array([f"s{i % 6}" for i in range(112)])
    buy = np.array([f"b{i % 20}" for i in range(112)])
    gate = S39.small_sample_gate(y, sup, buy)
    assert gate["enough_power"] is False
    assert "выборка мала" in gate["warning"]
    y2 = np.array([1] * 40 + [0] * 200)
    sup2 = np.array([f"s{i}" for i in range(240)])
    buy2 = np.array([f"b{i % 30}" for i in range(240)])
    assert S39.small_sample_gate(y2, sup2, buy2)["enough_power"] is True


def _cluster(point, lo, hi):
    return {"point": point, "ci": [lo, hi]}


_FLAG = {"auc": {"p97_5": 0.55}}


def test_verdict_rule_a():
    v = S39.decide_verdict(_cluster(0.62, 0.55, 0.69), 0.55, 0.52, 0.53, _FLAG)
    assert v["code"] == "а" and not v["determined_by_baseline"]


def test_verdict_rule_b_ci_includes_half():
    v = S39.decide_verdict(_cluster(0.52, 0.45, 0.60), 0.50, 0.50, 0.53, _FLAG)
    assert v["code"] == "б"


def test_verdict_rule_v_determined_by_size():
    v = S39.decide_verdict(_cluster(0.58, 0.54, 0.62), 0.62, 0.50, 0.53, _FLAG)
    assert v["code"] == "в" and v["determined_by_baseline"]


def test_verdict_rule_v_below_half():
    v = S39.decide_verdict(_cluster(0.42, 0.35, 0.48), 0.50, 0.50, 0.53, _FLAG)
    assert v["code"] == "в"


def test_random_flag_control_deterministic_and_uses_no_scores():
    y = np.array([1] * 20 + [0] * 180)
    groups = np.array(["g1"] * 100 + ["g2"] * 100)
    a = S39.random_flag_control(y, groups, repeats=10, seed=7700)
    b = S39.random_flag_control(y, groups, repeats=10, seed=7700)
    assert a == b
    assert a["repeats"] == 10 and a["rate"] == 0.05
    assert 0.0 < a["auc"]["median"] < 1.0


# ---------------------------------------------------------------------------
# end-to-end on the EMPTY template (no fabrication, graceful zeros)
# ---------------------------------------------------------------------------

def _run(script: str, *argv: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / script), *argv],
        capture_output=True, text=True, cwd=str(ROOT), timeout=timeout)


def test_empty_template_end_to_end(tmp_path):
    feats = _features_csv(tmp_path)
    out_json = tmp_path / "match.json"
    out_md = tmp_path / "match.md"
    proc = _run("38_case_registry_match.py", "--registry",
                str(REGISTRY_TEMPLATE), "--features", str(feats),
                "--out-json", str(out_json), "--out-md", str(out_md))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["matching"]["n_matched"] == 0
    assert payload["validation"]["n_rows"] == 0
    assert "сопоставление" in out_md.read_text(encoding="utf-8")


def test_empty_registry_check_issues_no_verdict(tmp_path):
    feats = _features_csv(tmp_path)
    out_json = tmp_path / "check.json"
    out_md = tmp_path / "check.md"
    proc = _run("39_case_registry_check.py", "--registry",
                str(REGISTRY_TEMPLATE), "--features", str(feats),
                "--out-json", str(out_json), "--out-md", str(out_md))
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["status"] == "no_label"
    assert payload["verdict"]["code"] is None
    assert "МЕТКА ПУСТА" in proc.stdout


def test_populated_registry_runs_metric_path_descriptively(tmp_path):
    """End-to-end on synthetic data: the full metric path executes, the
    power gate withholds the verdict and the report says «выборка мала»."""
    feats = _features_csv(tmp_path)
    scores = tmp_path / "scores.csv"
    pd.DataFrame({"ocid": FEATURES["ocid"],
                  "max_score": [0.95, 0.4, 0.6, 0.1, 0.8]}).to_csv(
        scores, index=False)
    registry = _registry_csv(tmp_path, [
        {"entity_id_mtender": "1000000000001",
         "first_publication_date": "2021-06-01"},
        {"case_id": "C-2", "entity_id_mtender": "1000000000002",
         "entity_name_as_in_source": "", "evidence_level": "B",
         "first_publication_date": "2020-01-01"},
    ])
    out_json = tmp_path / "check.json"
    out_md = tmp_path / "check.md"
    proc = _run("39_case_registry_check.py", "--registry", str(registry),
                "--features", str(feats), "--scores", str(scores),
                "--out-json", str(out_json), "--out-md", str(out_md),
                "--n-boot", "20", "--random-repeats", "20",
                "--flag-repeats", "5")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    # window < max cutoff (2021-06-01): P1, P3, B1 stay; P2 (=C-1 cutoff)
    # postdates its case and leaves the population; P4 (2022) is outside
    assert payload["label"]["n_population"] == 3
    assert payload["label"]["n_positives"] == 2       # P1 (<2021-06), P3 (<2020-01)
    assert payload["label"]["n_dropped_post_publication"] == 1
    assert payload["label"]["base_rate"] == pytest.approx(2 / 3)
    # metrics exist for the main ranking and every required comparison
    assert payload["v0_external"]["roc_auc"] is not None
    for key in ("log_award_total", "n_bidders_log", "random_ranking",
                "random_flags_5pct_within_group"):
        assert key in payload["baselines"]
    assert payload["pre_registered"]["temporal_guard"]
    # 2 positives < 30 -> power gate withholds the verdict
    assert payload["verdict"]["code"] is None
    assert "выборка мала" in payload["power_gate"]["warning"]
    assert "выборка мала" in out_md.read_text(encoding="utf-8")


def test_empty_registry_case_studies_graceful(tmp_path):
    feats = _features_csv(tmp_path)
    scores = tmp_path / "scores.csv"
    pd.DataFrame({
        "ocid": FEATURES["ocid"],
        "max_score": [0.9, 0.5, 0.3, 0.1, 0.7],
        "n_models_flagging": [3, 1, 0, 0, 2],
        "score_statistical_mad_zscore": [0.9] * 5,
        "score_isolation_forest": [0.8] * 5,
        "score_local_outlier_factor": [0.7] * 5,
        "score_one_class_svm": [0.6] * 5,
    }).to_csv(scores, index=False)
    out_md = tmp_path / "studies.md"
    proc = _run("40_case_registry_studies.py", "--registry",
                str(REGISTRY_TEMPLATE), "--features", str(feats),
                "--scores", str(scores),
                "--models", str(tmp_path / "no-such-model.joblib"),
                "--out-md", str(out_md))
    assert proc.returncode == 0, proc.stderr
    text = out_md.read_text(encoding="utf-8")
    assert "уровня A/B" in text
    assert "шаблон без записей" in text


# ---------------------------------------------------------------------------
# security regressions
# ---------------------------------------------------------------------------

def test_new_scripts_have_no_network_imports():
    for name in ("38_case_registry_match.py", "39_case_registry_check.py",
                 "40_case_registry_studies.py"):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for banned in ("import requests", "urllib.request", "http.client",
                       "httpx", "socket"):
            assert banned not in source, f"{name} contains {banned}"


def test_new_scripts_run_standalone_help():
    for name in ("38_case_registry_match.py", "39_case_registry_check.py",
                 "40_case_registry_studies.py"):
        proc = _run(name, "--help")
        assert proc.returncode == 0, proc.stderr
