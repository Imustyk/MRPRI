"""MTA-0018 step 5: quality metrics vs the manual review (scripts/45).

The central contract: REFUSE to compute Accuracy / Precision / Recall / F1 /
the confusion matrix while any ``reviewer_outcome`` of the sample is empty
(the manual review is never imitated), refuse invalid labels, and compute
correct, hand-checkable numbers once every row is labelled. ``unknown`` is an
abstention, never a negative label, and no external ``ansc_upheld`` label
leaks into the outputs.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"s{name.split('_')[0]}", ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s45 = _load("45_ansc_review_metrics.py")

FIELDS = ["ocid", "decision_id", "document_url", "extracted_outcome",
          "evidence_quote", "page_number", "extraction_method", "confidence",
          "reviewer_outcome", "reviewer_notes"]


def srow(i: int, extracted: str, reviewer: str, notes: str = "",
         layer: str = "1") -> dict:
    return {"ocid": f"ocds-{i}", "decision_id": f"03D-{i}-22",
            "document_url": f"http://storage.mtender.gov.md/get/u{i}",
            "extracted_outcome": extracted, "evidence_quote": "q",
            "page_number": "1", "extraction_method": "resolutory_strong_anchor",
            "confidence": "high", "reviewer_outcome": reviewer,
            "reviewer_notes": notes, "_layer": layer}


def write_sample(rows: list[dict], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_outcomes(rows: list[dict], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["url", "text_layer"],
                                extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({"url": r["document_url"],
                             "text_layer": r["_layer"]})
    return path


# --- refusal while labels are missing (the core contract) -------------------
class TestRefusal:
    def test_refuses_when_any_label_missing(self, tmp_path, monkeypatch,
                                            capsys):
        rows = [srow(1, "admitted", "admitted"),
                srow(2, "rejected", ""),           # not reviewed yet
                srow(3, "unknown", "unknown")]
        sample = write_sample(rows, tmp_path / "sample.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        rc = s45.main(["--sample", str(sample),
                       "--outcomes", str(tmp_path / "absent.csv")])
        assert rc == 5
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["status"] == "awaiting_manual_review"
        assert payload["metrics"] is None
        assert payload["n_labeled"] == 2 and payload["n_total"] == 3
        assert payload["missing_rows"][0]["decision_id"] == "03D-2-22"
        # no metric VALUES anywhere (the note only states their absence)
        assert not [k for k in payload
                    if "accuracy" in k or "macro" in k or "f1" in k]
        out = capsys.readouterr().out
        assert '"accuracy"' not in out

    def test_refuses_on_invalid_label(self, tmp_path, monkeypatch):
        rows = [srow(1, "admitted", "admitted"),
                srow(2, "rejected", "partially yes")]
        sample = write_sample(rows, tmp_path / "sample.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        rc = s45.main(["--sample", str(sample),
                       "--outcomes", str(tmp_path / "absent.csv")])
        assert rc == 6
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["status"] == "invalid_labels"
        assert payload["metrics"] is None
        assert payload["invalid_rows"][0]["value"] == "partially yes"

    def test_missing_sample_file(self, tmp_path):
        assert s45.main(["--sample", str(tmp_path / "nope.csv")]) == 4


# --- metrics math on hand-checkable data ------------------------------------
class TestComputeMetrics:
    @staticmethod
    def _labeled():
        # truth -> extracted:
        #   admitted  -> admitted   (correct)
        #   rejected  -> rejected   (correct)
        #   rejected  -> admitted   (error: false admission)
        #   unknown   -> unknown    (abstention agreement)
        return [srow(1, "admitted", "admitted"),
                srow(2, "rejected", "rejected"),
                srow(3, "admitted", "rejected"),
                srow(4, "unknown", "unknown",
                     notes="mislink: award decision, not a complaint "
                           "decision")]

    def test_known_values(self):
        labeled = self._labeled()
        layer = {r["document_url"]: r["_layer"] for r in labeled}
        m = s45.compute_metrics(labeled, layer)
        assert m["n_labeled"] == 4
        assert m["accuracy"] == pytest.approx(0.75)
        # per class
        rej = m["per_class"]["rejected"]
        assert rej["precision"] == pytest.approx(1.0)
        assert rej["recall"] == pytest.approx(0.5)
        assert rej["f1"] == pytest.approx(2 / 3, abs=1e-3)
        adm = m["per_class"]["admitted"]
        assert adm["precision"] == pytest.approx(0.5)
        assert adm["recall"] == pytest.approx(1.0)
        assert m["per_class"]["unknown"]["f1"] == pytest.approx(1.0)
        # macro over the FIXED seven labels, zero-division = 0
        assert m["macro_f1"] == pytest.approx((2 / 3 + 2 / 3 + 1) / 7,
                                              abs=1e-3)        # confusion: rows = reviewer truth, cols = extracted
        assert m["confusion_matrix"]["rejected"]["admitted"] == 1
        assert m["confusion_matrix"]["rejected"]["rejected"] == 1
        # shares
        assert m["unknown_share_extracted"] == pytest.approx(0.25)
        assert m["unknown_share_reviewer"] == pytest.approx(0.25)
        assert m["mislink_share"] == pytest.approx(0.25)
        # split by source type (all four rows are text-PDF here)
        assert m["split_by_source_type"]["text_layer"] == {"n": 4,
                                                           "accuracy": 0.75}
        assert m["split_by_source_type"]["scan"] == {"n": 0,
                                                     "accuracy": None}

    def test_split_by_text_layer_and_scan(self):
        rows = [srow(1, "admitted", "admitted", layer="1"),
                srow(2, "admitted", "rejected", layer="1"),
                srow(3, "rejected", "rejected", layer="0"),
                srow(4, "unknown", "unknown", layer="0")]
        layer = {r["document_url"]: r["_layer"] for r in rows}
        m = s45.compute_metrics(rows, layer)
        assert m["split_by_source_type"]["text_layer"] == {"n": 2,
                                                           "accuracy": 0.5}
        assert m["split_by_source_type"]["scan"] == {"n": 2,
                                                     "accuracy": 1.0}
        assert m["rows_without_source_type_join"] == 0

    def test_unknown_is_an_abstention_not_a_negative(self):
        rows = [srow(1, "unknown", "unknown")]
        m = s45.compute_metrics(rows, {})
        assert m["accuracy"] == 1.0
        assert m["per_class"]["unknown"]["recall"] == 1.0
        assert m["unknown_share_extracted"] == 1.0


# --- full run over a fully labelled sample ----------------------------------
class TestFullRun:
    def test_full_labelled_run(self, tmp_path, monkeypatch, capsys):
        rows = [srow(1, "admitted", "admitted"),
                srow(2, "rejected", "rejected",
                     notes="quote page 2"),
                srow(3, "unknown", "unknown",
                     notes="mislink: instiintare, not a decision")]
        sample = write_sample(rows, tmp_path / "sample.csv")
        outcomes = write_outcomes(rows, tmp_path / "outcomes.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        monkeypatch.setattr(s45, "OUT_MD", tmp_path / "m.md")
        rc = s45.main(["--sample", str(sample), "--outcomes", str(outcomes)])
        assert rc == 0
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["status"] == "metrics_computed"
        assert payload["metrics"]["n_labeled"] == 3
        assert payload["metrics"]["accuracy"] == 1.0
        assert payload["metrics"]["mislink_share"] == pytest.approx(
            1 / 3, abs=1e-3)
        report = (tmp_path / "m.md").read_text("utf-8")
        assert "Accuracy" in report and "матрица ошибок" in report.lower()
        # disclaimers and the no-model-claim stance
        assert "does not constitute proof of corruption" in report
        assert "ansc_upheld" not in report
        assert "ansc_upheld" not in json.dumps(payload)
        out = capsys.readouterr().out
        assert "metrics_computed" in out
