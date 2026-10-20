"""HTTP-route tests for the real-data integration layer (2026-10-20).

Every route added or fixed on ``feature/risk-specific-detection`` is exercised
through ``TestClient`` against small fixture rows, so the suite is hermetic
(neither MongoDB nor the 249 MB snapshot is loaded) and fast. The tests pin
the behaviours the audit brief demands:

* synthetic meta artefacts are never served as the production model,
* dataset origin is detected and labelled honestly,
* evaluation payloads keep the *negative* external-label results,
* explanations are layered, deterministic and carry their limitations,
* invalid filters are client errors (422), not empty pages,
* stale score caches are dropped on ``invalidate()``.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

import backend.app.store as store
from backend.app.main import app
from backend.app.adapter import RISK_BANDS

client = TestClient(app)

#: Real lru-wrapped loaders captured before any monkeypatching, so teardown
#: (and tests that call the genuine ``invalidate()``) always clear the *real*
#: cached functions even while a test has patched the module attributes.
_REAL_LOAD_TENDERS = store.load_tenders
_CACHED_LOADERS = (
    store.search_keys,
    store.load_population_stats,
    store.load_dataset_report,
    store.load_evaluation,
    store.load_explainability,
    store.origin_kind,
    store.load_meta,
    store.load_tenders,
    store._csv_scores,
)


def _row(**over) -> dict:
    base = {
        "tender_id": "T-1",
        "ocid": "ocds-t1",
        "title": "Alpha bridge repair",
        "buyer_id": "B-1",
        "buyer_name": "Alpha Commune",
        "buyer_locality": "Chișinău",
        "winner_name": "Beta SRL",
        "winner_idno": "1002600",
        "procedure": "licitație deschisă",
        "procurement_method": "open",
        "status": "active",
        "cpv_code": "45211300",
        "published_at": "2021-03-01",
        "tender_start": "2021-03-01",
        "bid_deadline": "2021-03-20",
        "award_date": "2021-04-10",
        "estimated_value_mdl": 1_000_000,
        "award_value_mdl": 950_000,
        "award_total_mdl": 950_000,
        "currency": "MDL",
        "n_bidders": 3,
        "bid_window_days": 19,
        "n_lots": 1,
        "n_awards": 1,
        "risk_score": 88.0,
        "risk_level": "critical",
        "n_models_flagging": 3,
        "model_flags": {
            "statistical_mad_zscore": True,
            "isolation_forest": True,
            "local_outlier_factor": True,
            "one_class_svm": True,
        },
        "consensus_flag": True,
        "iso_score": 0.61,
        "lof_score": -12.4,
        "svm_score": -0.42,
        "rule_score": 4.1,
        "flags": ["Single bidder"],
        "single_bidder": 1.0,
        "short_deadline": 0.0,
        "value_vs_cpv_median": 1.4,
        "winner_share_of_buyer_awards": 0.2,
        "buyer_supplier_repeat_share": 0.3,
        "estimate_to_award_ratio": 1.05,
        "has_bid_data": True,
        "has_award_data": True,
        "bids": None,
        "bids_json": None,
        "planted_pattern": None,
        "is_planted_anomaly": None,
    }
    base.update(over)
    return base


def build_rows() -> list[dict]:
    """Four rows covering scored bands, an unscored record and null dates."""
    return [
        _row(),
        _row(
            tender_id="T-2",
            ocid="ocds-t2",
            title="Beta school roof",
            buyer_id="B-2",
            buyer_name="Beta Town",
            winner_name="Gamma Invest",
            procedure="negociere",
            tender_start="2022-05-05",
            published_at="2022-05-01",
            award_date="2022-06-01",
            award_value_mdl=300_000,
            award_total_mdl=300_000,
            estimated_value_mdl=320_000,
            n_bidders=1,
            bid_window_days=7,
            risk_score=55.0,
            risk_level="medium",
            n_models_flagging=1,
            model_flags={
                "statistical_mad_zscore": False,
                "isolation_forest": True,
                "local_outlier_factor": False,
                "one_class_svm": False,
            },
            consensus_flag=False,
            flags=["Single bidder", "Short bidding window"],
        ),
        _row(
            tender_id="T-3",
            ocid="ocds-t3",
            title="Gamma clinic supplies",
            buyer_id="B-3",
            buyer_name="Gamma District",
            winner_name=None,
            procedure="ofertă spontană",
            published_at=None,
            tender_start=None,
            bid_deadline=None,
            award_date=None,
            award_value_mdl=None,
            award_total_mdl=None,
            estimated_value_mdl=None,
            n_bidders=None,
            bid_window_days=None,
            n_lots=None,
            n_awards=None,
            risk_score=None,
            risk_level="unscored",
            n_models_flagging=None,
            model_flags={
                "statistical_mad_zscore": None,
                "isolation_forest": None,
                "local_outlier_factor": None,
                "one_class_svm": None,
            },
            consensus_flag=None,
            iso_score=None,
            lof_score=None,
            svm_score=None,
            rule_score=None,
            flags=[],
            has_bid_data=False,
            has_award_data=False,
        ),
        _row(
            tender_id="T-4",
            ocid="ocds-t4",
            title="Gamma water supply",
            buyer_id="B-4",
            buyer_name="Delta Commune",
            winner_name="Delta Group",
            procedure="licitație deschisă",
            tender_start="2023-06-01",
            published_at="2023-05-20",
            award_date="2023-07-15",
            award_value_mdl=5_000_000,
            award_total_mdl=5_000_000,
            estimated_value_mdl=4_800_000,
            n_bidders=5,
            bid_window_days=31,
            risk_score=12.0,
            risk_level="low",
            n_models_flagging=0,
            model_flags={
                "statistical_mad_zscore": False,
                "isolation_forest": False,
                "local_outlier_factor": False,
                "one_class_svm": False,
            },
            consensus_flag=False,
            flags=[],
        ),
    ]


@pytest.fixture(autouse=True)
def fixture_store(monkeypatch):
    """Serve four fixture rows; reset every view cache the new code adds."""
    rows = build_rows()
    for clearer in _CACHED_LOADERS:
        clearer.cache_clear()
    monkeypatch.setattr(store, "load_tenders", lambda: rows)
    monkeypatch.setattr(store, "artefacts_ready", lambda: True)
    yield rows
    for clearer in _CACHED_LOADERS:
        clearer.cache_clear()


# --------------------------------------------------------------------------- #
# /api/meta: production model identity, honest origin
# --------------------------------------------------------------------------- #


def _patch_meta_reads(monkeypatch, origin: str):
    def fake_read(name):
        if name == "meta.json":
            # The stale synthetic artefact actually on disk.
            return {
                "source": "synthetic",
                "n_tenders": 1200,
                "model": "IsolationForest + LOF + rule layer",
                "run_id": None,
            }
        if name == "tenders.json":
            return [{"ocid": "a"}]
        return None

    monkeypatch.setattr(store, "_read", fake_read)
    monkeypatch.setattr(store, "origin_kind", lambda: origin)
    monkeypatch.setattr(
        store,
        "_read_results",
        lambda *parts: {"run_id": "detect-20261009-8e1170", "generated_at": "2026-10-09T06:48:37Z"}
        if parts[-1] == "detection_summary.json"
        else None,
    )


def test_meta_serves_production_model_not_synthetic_meta(monkeypatch):
    _patch_meta_reads(monkeypatch, "real-ocds")
    body = client.get("/api/meta").json()
    assert body["model"] == store._PRODUCTION_MODEL_LABEL
    assert body["model"].startswith("v0 production")
    assert "rule layer" not in body["model"]
    assert body["source"].startswith("mtender-ocds")
    assert body["data_origin"] == "real-ocds"
    assert body["etl_run_id"] == "detect-20261009-8e1170"
    assert body["scoring_generated_at"] == "2026-10-09T06:48:37Z"


def test_meta_marks_synthetic_dataset_loudly(monkeypatch):
    _patch_meta_reads(monkeypatch, "synthetic-demo")
    body = client.get("/api/meta").json()
    assert body["data_origin"] == "synthetic-demo"
    assert body["source"].startswith("SYNTHETIC DEMO")
    assert "not real procurement data" in body["source"]


def test_origin_probe_detects_schema(tmp_path, monkeypatch):
    (tmp_path / "tenders.json").write_text(
        '[{"ocid": "x", "planted_pattern": "p"}]', encoding="utf-8"
    )
    monkeypatch.setattr(store, "DATA_PROCESSED", tmp_path)
    store.origin_kind.cache_clear()
    assert store.origin_kind() == "synthetic-demo"

    (tmp_path / "tenders.json").write_text(
        '[{"ocid": "x", "procurement_method_details": "open"}]', encoding="utf-8"
    )
    store.origin_kind.cache_clear()
    assert store.origin_kind() == "real-ocds"


# --------------------------------------------------------------------------- #
# /api/tenders: validation, filtering, sorting, search
# --------------------------------------------------------------------------- #


def test_unknown_risk_level_is_422_not_empty_page():
    resp = client.get("/api/tenders", params={"level": "highh"})
    assert resp.status_code == 422
    assert "unknown risk level" in resp.json()["detail"]
    # every real band (including unscored) is accepted
    for band in RISK_BANDS:
        assert client.get("/api/tenders", params={"level": band}).status_code == 200


def test_level_filter_and_pagination():
    body = client.get("/api/tenders", params={"level": "critical"}).json()
    assert body["total"] == 1
    assert {i["risk_level"] for i in body["items"]} == {"critical"}

    body = client.get(
        "/api/tenders", params={"limit": 2, "offset": 1}
    ).json()
    assert body["total"] == 4
    assert [i["tender_id"] for i in body["items"]] == ["T-2", "T-3"]


def test_default_sort_keeps_file_order():
    body = client.get("/api/tenders").json()
    assert [i["tender_id"] for i in body["items"]] == ["T-1", "T-2", "T-3", "T-4"]


def test_sort_risk_value_date():
    risk = client.get("/api/tenders", params={"sort": "risk"}).json()
    # descending score, unscored record last - not treated as 0-score "low"
    assert [i["tender_id"] for i in risk["items"]] == ["T-1", "T-2", "T-4", "T-3"]

    value = client.get("/api/tenders", params={"sort": "value"}).json()
    assert [i["tender_id"] for i in value["items"]] == ["T-4", "T-1", "T-2", "T-3"]

    date = client.get("/api/tenders", params={"sort": "date"}).json()
    assert [i["tender_id"] for i in date["items"]] == ["T-4", "T-2", "T-1", "T-3"]


def test_search_case_insensitive_and_field_bounded():
    body = client.get("/api/tenders", params={"q": "ALPHA"}).json()
    assert body["total"] == 1
    assert body["items"][0]["tender_id"] == "T-1"

    # matches the winner name field
    body = client.get("/api/tenders", params={"q": "gamma invest"}).json()
    assert body["total"] == 1
    assert body["items"][0]["tender_id"] == "T-2"

    # would match a naive space-joined haystack; must not match across fields
    body = client.get("/api/tenders", params={"q": "repair alpha"}).json()
    assert body["total"] == 0


# --------------------------------------------------------------------------- #
# /api/dataset: origin, counts, provenance, hash verification
# --------------------------------------------------------------------------- #


def test_dataset_report_shape_and_counts(monkeypatch):
    monkeypatch.setattr(store, "origin_kind", lambda: "real-ocds")
    monkeypatch.setattr(store, "_csv_scores", lambda: {"ocd-1": {}, "ocd-2": {}})
    monkeypatch.setattr(
        store,
        "_read_results",
        lambda *parts: {
            "exported_at": "2026-09-26T00:00:00Z",
            "n_documents": 4,
            "outputs": {},
        }
        if parts[-1] == "export_manifest.json"
        else {
            "run_id": "detect-1",
            "generated_at": "2026-10-09T06:48:37Z",
            "contamination_assumption": 0.05,
            "random_state": 42,
            "feature_columns": ["a"] * 22,
            "n_rows": 4,
            "models": [
                {"model": "isolation_forest", "n_flagged": 1},
                {"model": "lof", "n_flagged": 0},
            ],
        }
        if parts[-1] == "detection_summary.json"
        else None,
    )
    body = client.get("/api/dataset").json()
    assert body["origin"]["kind"] == "real-ocds"
    assert body["origin"]["synthetic_in_use"] is False
    assert body["corpus"] == {
        "records": 4,
        "scored": 3,
        "unscored": 1,
        "year_from": "2021",
        "year_to": "2023",
        "band_counts": {"critical": 1, "medium": 1, "unscored": 1, "low": 1},
    }
    assert body["model"]["version"] == "v0"
    assert "unchanged" in body["model"]["role"]
    assert body["scoring"]["run_id"] == "detect-1"
    assert body["scoring"]["generated_at"] == "2026-10-09T06:48:37Z"
    assert body["scoring"]["scored_rows_in_csv"] == 2
    assert body["manifest"]["exported_at"] == "2026-09-26T00:00:00Z"
    assert "not evidence of corruption" in body["disclaimer"]


def test_dataset_verify_hash_detects_mismatch(tmp_path, monkeypatch):
    good = tmp_path / "features.csv"
    good.write_bytes(b"real-bytes")
    wrong = tmp_path / "tenders.json"
    wrong.write_bytes(b"other-bytes")
    manifest = {
        "exported_at": "2026-09-26T00:00:00Z",
        "outputs": {
            str(good): {
                "sha256": hashlib.sha256(b"real-bytes").hexdigest(),
                "bytes": 10,
            },
            str(wrong): {
                "sha256": hashlib.sha256(b"expected-bytes").hexdigest(),
                "bytes": 12,
            },
        },
    }
    monkeypatch.setattr("backend.app.config.ROOT", tmp_path)
    monkeypatch.setattr(store, "origin_kind", lambda: "real-ocds")
    monkeypatch.setattr(store, "_csv_scores", lambda: {})
    monkeypatch.setattr(
        store, "_read_results", lambda *parts: manifest if "export_manifest" in parts[-1] else None
    )
    body = client.get("/api/dataset", params={"verify_hash": True}).json()
    ver = body["verification"]
    assert ver["hash_verified"] is True
    assert ver["hash_matches_manifest"] is False
    assert ver["compared_files"] == 2
    assert [m["path"] for m in ver["mismatches"]] == ["tenders.json"]


# --------------------------------------------------------------------------- #
# /api/evaluation: negative external results stay in the payload
# --------------------------------------------------------------------------- #


def _evaluation_fixture() -> dict:
    return {
        ("methodology", "final_verification.json"): {
            "external_headline": {
                "roc_auc_max_score": 0.493453,
                "pr_auc_max_score": 0.004377,
                "base_rate": 0.004154,
                "votes_ge_3_precision": 0.008248,
            },
            "aap_supplier_concentration": {
                "n_exact_suppliers": 17,
                "positives": 633,
                "largest_supplier_share": 0.183,
            },
            "seed_stability": {"runs": 20, "consensus_mean": 3013.3, "jaccard_mean": 0.7111},
            "disclaimer": "proxy labels; anomaly is not evidence",
        },
        ("methodology", "ansc_external_check.json"): {
            "v0_external": {
                "cluster_by_buyer": {
                    "point": 0.511196,
                    "ci": [0.488919, 0.557061],
                    "n_boot": 1000,
                    "n_clusters": 2019,
                },
                "precision": {"top_100": 0.02},
            },
            "baselines": {"random": {"repeats": 200, "mean": 0.500558}},
            "verdict": {"code": "б", "text": "ensemble at random level"},
        },
        ("methodology", "threshold_calibration.json"): {
            "production_boundary": "votes >= 3 of 4 detectors",
            "tune_period": "2018-2021",
            "test_period": "2022-2024",
            "drift": [{"measure": "max_score", "psi": 0.292597, "ks_statistic": 0.206509}],
            "overfitting_warning": False,
        },
        ("methodology", "noise_sensitivity.json"): {
            "verdicts": {
                "H1_noise_small_rho": {"threshold": 0.99, "observed_min": 0.9604, "passed": False},
                "H2_noise_moderate": {"rho_threshold": 0.97, "passed": False},
            },
            "aggregate": {
                "round": {
                    "n_runs": 1,
                    "spearman_max_score": {"mean": 1.0},
                    "spearman_ci_low": {"mean": 1.0},
                    "spearman_ci_high": {"mean": 1.0},
                    "jaccard_top200_score": {"mean": 1.0},
                    "band_change_pct": {"mean": 0.0},
                    "spearman_type_directaward": {"mean": 1.0},
                }
            },
        },
        ("methodology", "bias_audit.json"): {
            "n_dimensions": 13,
            "high_plus_share_corpus": 0.050283,
            "critical_share_corpus": 0.019891,
            "verdict_counts": {"допустимо": 11, "нарушение": 24},
        },
    }


def test_evaluation_keeps_negative_external_results(monkeypatch):
    fixture = _evaluation_fixture()
    monkeypatch.setattr(store, "_read_results", lambda *parts: fixture.get(tuple(parts)))
    body = client.get("/api/evaluation").json()

    assert body["production"]["version"] == "v0"
    aap = {e["id"]: e for e in body["external_labels"]}["aap"]
    ansc = {e["id"]: e for e in body["external_labels"]}["ansc"]
    assert aap["roc_auc"] == 0.493453  # below 0.5 stays visible
    assert aap["supplier_concentration"]["positives"] == 633
    assert ansc["roc_auc"] == 0.511196
    assert ansc["cluster_ci"] == [0.488919, 0.557061]
    assert ansc["verdict_code"] == "б"
    assert ansc["baselines"]["random"]["mean"] == 0.500558
    # failed noise hypotheses are reported, not hidden
    assert body["noise_sensitivity"]["verdicts"]["H1_noise_small_rho"]["passed"] is False
    assert body["noise_sensitivity"]["regimes"][0]["spearman"] == 1.0
    assert body["drift"]["psi_max"] == 0.292597
    assert body["bias"]["n_dimensions"] == 13


def test_evaluation_degrades_to_unavailable_without_artifacts(monkeypatch):
    monkeypatch.setattr(store, "_read_results", lambda *parts: None)
    body = client.get("/api/evaluation").json()
    for entry in body["external_labels"]:
        assert entry["available"] is False
        assert entry["roc_auc"] is None  # never a fabricated number
    assert body["noise_sensitivity"]["available"] is False
    assert body["bias"]["available"] is False


# --------------------------------------------------------------------------- #
# /api/explainability and per-procedure explanations
# --------------------------------------------------------------------------- #


def test_explainability_states_shap_lime_disagreement(monkeypatch):
    fixture = {
        ("methodology", "xai_consistency.json"): {
            "model_explained": "isolation_forest",
            "verdict": "не согласованы",
            "agreement": {"spearman": {"mean": -0.6169}},
            "low_agreement_diagnosis": "scores collapse near the boundary",
        },
        ("methodology", "explainability_summary.json"): {},
    }
    monkeypatch.setattr(store, "_read_results", lambda *parts: fixture.get(tuple(parts)))
    body = client.get("/api/explainability").json()
    assert body["xai_consistency"]["available"] is True
    assert body["xai_consistency"]["verdict"] == "не согласованы"
    assert body["xai_consistency"]["agreement"]["spearman"]["mean"] == -0.6169
    assert any("not causal" in n for n in body["notes"])
    assert body["permutation_importance"]  # read from the real 22-row table
    assert "not evidence of a violation" in body["disclaimer"]


def _patch_explanation_reads(monkeypatch):
    monkeypatch.setattr(
        store,
        "_read_results",
        lambda *parts: {"verdict": "не согласованы"}
        if parts[-1] == "xai_consistency.json"
        else {"run_id": "detect-1", "generated_at": "2026-10-09T06:48:37Z"}
        if parts[-1] == "detection_summary.json"
        else None,
    )


def test_explanation_layers_and_determinism(monkeypatch):
    _patch_explanation_reads(monkeypatch)
    first = client.get("/api/tenders/T-1/explanation")
    assert first.status_code == 200
    body = first.json()

    assert [layer["id"] for layer in body["layers"]] == [
        "facts",
        "indicators",
        "detectors",
        "references",
        "limitations",
    ]
    assert body["model_version"] == "v0"
    assert body["scoring_run_id"] == "detect-1"

    facts = {i["field"]: i for i in body["layers"][0]["items"]}
    assert facts["title"]["value"] == "Alpha bridge repair"
    assert "percentile" in facts["n_bidders"]

    indicators = body["layers"][1]["items"]
    assert len(indicators) == 10  # every FLAG_FEATURES entry is reported
    assert indicators[0]["triggered"] is True  # triggered indicators come first
    assert {"key", "label", "triggered", "corpus_rate", "corpus_n"} <= set(indicators[0])

    detectors = {d["key"]: d for d in body["layers"][2]["items"]}
    assert detectors["isolation_forest"]["verdict"] == "flagged"
    assert detectors["isolation_forest"]["score_percentile"] is not None

    references = body["layers"][3]["items"]
    assert all(isinstance(r["available"], bool) for r in references)
    assert any(r["path"] == "/api/explainability" and r["available"] for r in references)

    limitations = [i["text"] for i in body["layers"][4]["items"]]
    assert any("not evidence of corruption" in t for t in limitations)
    assert any("SHAP and LIME disagree" in t for t in limitations)
    assert any('measured verdict: "не согласованы"' in t for t in limitations)

    # deterministic: identical payload on a repeat call
    assert client.get("/api/tenders/T-1/explanation").json() == body


def test_explanation_unscored_record_is_not_a_clearance(monkeypatch):
    _patch_explanation_reads(monkeypatch)
    body = client.get("/api/tenders/T-3/explanation").json()
    detectors = body["layers"][2]["items"]
    assert all(d["verdict"] == "unscored" for d in detectors)
    limitations = [i["text"] for i in body["layers"][4]["items"]]
    assert any("never scored" in t for t in limitations)
    assert any("'unscored' is not" in t for t in limitations)


def test_explanation_unknown_id_404():
    assert client.get("/api/tenders/NOPE/explanation").status_code == 404


def test_explanation_facts_omit_absent_fields(monkeypatch):
    _patch_explanation_reads(monkeypatch)
    body = client.get("/api/tenders/T-3/explanation").json()
    facts = {i["field"] for i in body["layers"][0]["items"]}
    assert "award_date" not in facts  # None, reported via limitations instead
    limitations = [i["text"] for i in body["layers"][4]["items"]]
    assert any("Not present in this record" in t for t in limitations)


# --------------------------------------------------------------------------- #
# cache hygiene and pipeline error handling
# --------------------------------------------------------------------------- #


def test_invalidate_clears_csv_score_cache(tmp_path, monkeypatch):
    (tmp_path / "tender_anomaly_scores.csv").write_text(
        "ocid,max_score\nocd-1,0.9\n", encoding="utf-8"
    )
    monkeypatch.setattr(store, "TABLES_DIR", tmp_path)
    # genuine cache-bearing function, so invalidate() can call .cache_clear()
    monkeypatch.setattr(store, "load_tenders", _REAL_LOAD_TENDERS)
    store._csv_scores.cache_clear()
    assert store._csv_scores() and store._csv_scores.cache_info().currsize >= 1

    store.invalidate()

    # Before the fix, _csv_scores survived invalidate() and the API kept
    # serving the previous run's scores after a rebuild.
    assert store._csv_scores.cache_info().currsize == 0


def test_pipeline_argument_error_is_422(monkeypatch):
    import backend.ml.pipeline as pipeline

    def boom(**_kw):
        raise ValueError("ocds source file not found: /nope.json")

    monkeypatch.setattr(pipeline, "run_pipeline", boom)
    resp = client.post(
        "/api/pipeline/run", params={"source": "ocds", "ocds_path": "/nope.json"}
    )
    assert resp.status_code == 422
    assert "not found" in resp.json()["detail"]


def test_pipeline_synthetic_guard_keeps_409():
    resp = client.post("/api/pipeline/run", params={"source": "synthetic"})
    assert resp.status_code == 409
    assert "synthetic" in resp.json()["detail"].lower()

