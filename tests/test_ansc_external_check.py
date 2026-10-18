"""MTA-0013 tests: the «procedure contested» external check (scripts 31).

Covers the pieces the measurement trusts: the label builder (dedup counters
included) on SYNTHETIC OCDS packages in a temp dir - the real ``data/raw``
is never touched - the competitive rule, the buyer-cluster bootstrap, the
precision@k / stratification helpers and the pre-registered conclusion rule.

Security regression: ``scripts/31`` must have no network imports at all and
must run standalone under ``python -I``.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S31 = _load_script("31_ansc_external_check.py")


def _package(ocid: str, tender_docs=None, awards=None, planning_docs=None) -> dict:
    compiled = {"ocid": ocid, "tag": ["compiled"]}
    if tender_docs is not None:
        compiled["tender"] = {"id": "t", "documents": tender_docs}
    if awards is not None:
        compiled["awards"] = awards
    if planning_docs is not None:
        compiled["planning"] = {"documents": planning_docs}
    return {"records": [{"ocid": ocid, "compiledRelease": compiled}]}


def _write_package(tmp_path: Path, ocid: str, package: dict) -> None:
    with gzip.open(tmp_path / f"{ocid}.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(package, fh)


def test_build_contested_label_dedup(tmp_path):
    _write_package(tmp_path, "ocd-A", _package(
        "ocd-A",
        tender_docs=[
            {"documentType": "complaints", "url": "http://s/x.pdf", "title": "x"},
            {"documentType": "tenderNotice", "url": "http://s/n.pdf"},
        ],
        awards=[{"id": "1", "documents": [
            {"documentType": "complaints", "url": "http://s/x.pdf"}]}],
        planning_docs=[{"documentType": "complaints", "url": "http://s/p.pdf"}],
    ))
    _write_package(tmp_path, "ocd-B", _package(
        "ocd-B", tender_docs=[{"documentType": "awardNotice"}]))
    procs, stats = S31.build_contested_label(tmp_path)
    assert procs == {"ocd-A"}
    assert stats["documents_rows"] == 3
    assert stats["documents_unique"] == 2       # x.pdf (dup) + p.pdf
    assert stats["documents_removed_duplicate"] == 1
    assert stats["procedures"] == 1


def test_build_contested_label_empty_url_falls_back_to_title(tmp_path):
    _write_package(tmp_path, "ocd-C", _package(
        "ocd-C", tender_docs=[{"documentType": "complaints", "title": "t.pdf"}]))
    procs, stats = S31.build_contested_label(tmp_path)
    assert procs == {"ocd-C"} and stats["documents_unique"] == 1


def test_build_contested_label_pn_ocid_alias(tmp_path):
    # a planning-notice package keeps its "-PN-" ocid inside while the corpus
    # indexes the same procedure under the base MD ocid - the label must
    # register both so it joins to the production ranking
    pn = "ocds-b3wdp1-MD-123-PN-1234"
    _write_package(tmp_path, "ocds-b3wdp1-MD-123", _package(
        pn, tender_docs=[{"documentType": "complaints", "url": "http://s/x.pdf"}]))
    procs, stats = S31.build_contested_label(tmp_path)
    assert procs == {pn, "ocds-b3wdp1-MD-123"}
    assert stats["procedures"] == 1
    assert stats["pn_ocid_aliases_added"] == 1


def test_leakage_suspect_is_subset_of_production_features():
    from src.mtender.features import FEATURE_COLUMNS
    assert len(S31.LEAKAGE_SUSPECT) == 10
    assert set(S31.LEAKAGE_SUSPECT) <= set(FEATURE_COLUMNS)
    # pre-registered categories: award counts, amendments, statuses, amounts
    assert {"multi_award_tender", "amended", "n_amendments", "cancelled",
            "no_award_after_tender"} <= set(S31.LEAKAGE_SUSPECT)


def test_cluster_bootstrap_deterministic_and_point_is_plain_auc():
    rng = np.random.default_rng(7)
    y = rng.integers(0, 2, size=300)
    scores = rng.random(300)
    clusters = rng.choice(["b1", "b2", "b3", "b4"], size=300)
    a = S31.cluster_bootstrap_auc(y, scores, clusters, n_boot=100, seed=42)
    b = S31.cluster_bootstrap_auc(y, scores, clusters, n_boot=100, seed=42)
    assert a == b
    from src.mtender.eval_metrics import roc_auc
    assert a["point"] == pytest.approx(roc_auc(y, scores), abs=1e-6)
    assert a["n_clusters"] == 4
    assert a["ci"][0] <= a["point"] <= a["ci"][1]


def test_cluster_bootstrap_perfect_separation_above_half():
    y = np.array([0] * 40 + [1] * 40)
    scores = np.array([0.1] * 40 + [0.9] * 40)
    clusters = np.array([f"b{i // 2}" for i in range(80)])
    out = S31.cluster_bootstrap_auc(y, scores, clusters, n_boot=100, seed=42)
    assert out["ci"][0] > 0.5


def test_precision_at_k_known_case():
    y = np.array([1, 0, 1, 0, 0])
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
    assert S31.precision_at_k(y, scores, 2) == 0.5   # top-2 = [1, 0]
    assert S31.precision_at_k(y, scores, 3) == pytest.approx(2 / 3)
    assert S31.precision_at_k(np.array([]), np.array([]), 10) is None


def test_stratified_auc_power_threshold():
    groups = np.array(["g"] * 60 + ["h"] * 60)
    y = np.array([1] * 10 + [0] * 50 + [1] * 55 + [0] * 5)
    scores = np.linspace(0, 1, 120)
    out = S31.stratified_auc(y, scores, groups, min_positives=50)
    assert out["g"]["auc"] is None and "мощность" in out["g"]["note"]
    assert out["h"]["auc"] is not None and out["h"]["positives"] == 55


def test_random_auc_baseline_brackets_half():
    y = np.array([0, 1] * 200)
    out = S31.random_auc_baseline(y, repeats=50, seed=42)
    assert out["q025"] < 0.5 < out["q975"]
    assert out["repeats"] == 50


def _cluster(point, lo, hi):
    return {"point": point, "ci": [lo, hi], "n_boot": 1000, "n_clusters": 10,
            "method": "test"}


def test_verdict_rule_a():
    v = S31.decide_verdict(_cluster(0.62, 0.55, 0.69), 0.55, 0.52,
                           _cluster(0.60, 0.53, 0.66), 0.53)
    assert v["code"] == "а" and not v["determined_by_leakage"]


def test_verdict_rule_b_ci_includes_half():
    v = S31.decide_verdict(_cluster(0.52, 0.45, 0.60), 0.50, 0.50,
                           _cluster(0.51, 0.44, 0.59), 0.53)
    assert v["code"] == "б"


def test_verdict_rule_v_leakage():
    v = S31.decide_verdict(_cluster(0.62, 0.55, 0.68), 0.55, 0.52,
                           _cluster(0.51, 0.45, 0.58), 0.53)
    assert v["code"] == "в" and v["determined_by_leakage"]


def test_verdict_rule_v_determined_by_size():
    v = S31.decide_verdict(_cluster(0.58, 0.54, 0.62), 0.62, 0.50,
                           _cluster(0.57, 0.53, 0.61), 0.53)
    assert v["code"] == "в" and v["determined_by_baseline"]


def test_script31_has_no_network_imports():
    source = (ROOT / "scripts" / "31_ansc_external_check.py").read_text(
        encoding="utf-8")
    for banned in ("import requests", "urllib.request", "http.client",
                   "httpx", "socket"):
        assert banned not in source
    assert not hasattr(S31, "requests")


def test_script31_runs_standalone_help():
    proc = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" /
                                   "31_ansc_external_check.py"), "--help"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300)
    assert proc.returncode == 0, proc.stderr
    assert "--limit-scan" in proc.stdout
