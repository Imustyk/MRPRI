"""MTA-0019 step 6: the external label ``ansc_upheld`` (scripts/47).

The contracts pinned here:

* REFUSAL: while the manual review is incomplete the script exits 5,
  writes only progress, and NO label file ever appears (invalid values ->
  exit 6, structurally wrong input -> exit 4);
* derivation: 1 = upheld fully/partially, 0 = rejected on the merits,
  NULL = everything else (unknown outcomes, non-decision documents,
  unconfirmed links, ``multiple:`` complaint rows);
* several complaints/documents of one procedure keep their OWN labels -
  never collapsed into one binary value;
* the literal ``ansc_upheld`` never appears in the feature pipeline
  (scripts 00-15 + backend) - a leak blocks labeling (exit 7);
* decision dates are summarised and future dates flagged.

No network; everything runs on tmp CSVs.
"""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"s{name.split('_')[0]}", ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s47 = _load("47_ansc_upheld_labels.py")


def make_row(i: int, outcome: str = "admitted", doc_type: str = "ansc_decision",
             link: str = "confirmed", notes: str = "",
             ocid: str | None = None) -> dict:
    return {"ocid": ocid or f"ocds-p{i}", "decision_id": f"03D-{i}-22",
            "document_url": f"http://storage.mtender.gov.md/get/r{i}",
            "reviewer_outcome": outcome, "reviewer_document_type": doc_type,
            "reviewer_link_verified": link, "reviewer_notes": notes,
            "reviewer_evidence_page": "", "reviewer_evidence_quote": ""}


def write_review(rows: list[dict], path: Path) -> Path:
    fields = ["ocid", "decision_id", "document_url", "reviewer_outcome",
              "reviewer_document_type", "reviewer_link_verified",
              "reviewer_evidence_page", "reviewer_evidence_quote",
              "reviewer_notes"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path


def run(main, rows, tmp_path, monkeypatch, outcomes: list[dict] | None = None,
        targets=None) -> tuple[int, Path, Path]:
    """Run 47 on tmp inputs; returns (rc, label_csv, json_path)."""
    review = write_review(rows, tmp_path / "review.csv")
    out = tmp_path / "labels.csv"
    payload = tmp_path / "labels.json"
    monkeypatch.setattr(s47, "OUT_LABELS", out)
    monkeypatch.setattr(s47, "OUT_JSON", payload)
    if outcomes is not None:
        with open(tmp_path / "outcomes.csv", "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["url", "decision_date"])
            w.writeheader()
            for r in outcomes:
                w.writerow(r)
        argv = ["--review", str(review), "--outcomes",
                str(tmp_path / "outcomes.csv"), "--out", str(out),
                "--quiet"]
    else:
        argv = ["--review", str(review), "--outcomes",
                str(tmp_path / "absent.csv"), "--out", str(out),
                "--quiet"]
    if targets is not None:
        monkeypatch.setattr(s47, "scan_targets", lambda: targets)
    return s47.main(argv), out, payload


# --- the gate --------------------------------------------------------------
class TestRefusal:
    def test_incomplete_review_writes_no_label_file(self, tmp_path,
                                                    monkeypatch):
        rows = [make_row(1), make_row(2, outcome="")]   # one unfilled
        rc, out, payload = run(s47.main, rows, tmp_path, monkeypatch)
        assert rc == 5
        assert not out.exists(), "NO labels before a human review exists"
        import json
        data = json.loads(payload.read_text("utf-8"))
        assert data["status"] == "awaiting_manual_review"
        assert data["labels"] is None
        assert data["label_file_written"] is False
        assert data["n_complete"] == 1 and data["n_total"] == 2

    def test_invalid_value_refuses(self, tmp_path, monkeypatch):
        rows = [make_row(1), make_row(2, outcome="upheld")]
        rc, out, _ = run(s47.main, rows, tmp_path, monkeypatch)
        assert rc == 6
        assert not out.exists()

    def test_invalid_document_type_refuses(self, tmp_path, monkeypatch):
        rows = [make_row(1, doc_type="decision")]
        rc, out, _ = run(s47.main, rows, tmp_path, monkeypatch)
        assert rc == 6
        assert not out.exists()

    def test_unfilled_link_refuses(self, tmp_path, monkeypatch):
        rows = [make_row(1, link="")]
        rc, out, _ = run(s47.main, rows, tmp_path, monkeypatch)
        assert rc == 5
        assert not out.exists()

    def test_missing_file_is_4(self, tmp_path, monkeypatch):
        monkeypatch.setattr(s47, "OUT_JSON", tmp_path / "p.json")
        monkeypatch.setattr(s47, "scan_targets", lambda: [])
        rc = s47.main(["--review", str(tmp_path / "nope.csv"), "--quiet"])
        assert rc == 4

    def test_missing_required_columns_is_4(self, tmp_path, monkeypatch):
        path = tmp_path / "legacy.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["ocid", "document_url",
                                               "reviewer_outcome"])
            w.writeheader()
            w.writerow({"ocid": "a", "document_url": "u", "reviewer_outcome":
                        "admitted"})
        monkeypatch.setattr(s47, "OUT_JSON", tmp_path / "p.json")
        monkeypatch.setattr(s47, "scan_targets", lambda: [])
        rc = s47.main(["--review", str(path), "--quiet"])
        assert rc == 4


# --- derivation rules ------------------------------------------------------
class TestDerivation:
    @staticmethod
    def _labels(rows, tmp_path, monkeypatch, outcomes=None):
        rc, out, payload = run(s47.main, rows, tmp_path, monkeypatch,
                               outcomes=outcomes)
        assert rc == 0, "complete valid review must produce labels"
        with open(out, newline="", encoding="utf-8") as fh:
            got = list(csv.DictReader(fh))
        return got, payload

    def test_binary_rules_and_nulls(self, tmp_path, monkeypatch):
        rows = [
            make_row(1, outcome="admitted"),              # -> 1
            make_row(2, outcome="partially_admitted"),    # -> 1
            make_row(3, outcome="rejected"),              # -> 0
            make_row(4, outcome="unknown"),               # -> NULL
            make_row(5, outcome="inadmissible"),          # -> NULL
            make_row(6, outcome="withdrawn"),             # -> NULL
            make_row(7, outcome="terminated"),            # -> NULL
        ]
        got, _ = self._labels(rows, tmp_path, monkeypatch)
        labels = {r["document_url"]: r["ansc_upheld"] for r in got}
        assert labels["http://storage.mtender.gov.md/get/r1"] == "1"
        assert labels["http://storage.mtender.gov.md/get/r2"] == "1"
        assert labels["http://storage.mtender.gov.md/get/r3"] == "0"
        for i in (4, 5, 6, 7):
            assert labels[f"http://storage.mtender.gov.md/get/r{i}"] == ""
        assert "proof of corruption" not in got[0]["label_reason"]

    def test_other_document_type_is_null_even_if_admitted(self, tmp_path,
                                                          monkeypatch):
        rows = [make_row(1, outcome="admitted",
                         doc_type="other_document"),
                make_row(2, outcome="admitted")]
        got, payload = self._labels(rows, tmp_path, monkeypatch)
        assert got[0]["ansc_upheld"] == ""
        assert "document type is other_document" in got[0]["label_reason"]
        assert got[1]["ansc_upheld"] == "1"
        import json
        data = json.loads(payload.read_text("utf-8"))
        assert data["document_type_distribution_manual"] == {
            "other_document": 1, "ansc_decision": 1}

    def test_uncertain_type_is_null(self, tmp_path, monkeypatch):
        rows = [make_row(1, doc_type="uncertain")]
        got, _ = self._labels(rows, tmp_path, monkeypatch)
        assert got[0]["ansc_upheld"] == ""

    def test_unconfirmed_link_is_null(self, tmp_path, monkeypatch):
        rows = [make_row(1, link="rejected"),
                make_row(2, link="uncertain")]
        got, _ = self._labels(rows, tmp_path, monkeypatch)
        assert all(r["ansc_upheld"] == "" for r in got)
        assert "not confirmed" in got[0]["label_reason"]

    def test_multi_complaint_marker_is_null_and_flagged(self, tmp_path,
                                                        monkeypatch):
        rows = [make_row(
            1, outcome="admitted",
            notes="multiple: 02/100/24 admitted; 03/103/24 rejected")]
        got, payload = self._labels(rows, tmp_path, monkeypatch)
        assert got[0]["ansc_upheld"] == ""
        assert got[0]["multi_complaint"] == "1"
        assert "NOT collapsed" in got[0]["label_reason"]
        import json
        data = json.loads(payload.read_text("utf-8"))
        assert data["n_multi_complaint_rows"] == 1

    def test_several_documents_of_one_procedure_keep_own_labels(
            self, tmp_path, monkeypatch):
        # one procedure, two complaints with OPPOSITE outcomes
        rows = [make_row(1, outcome="admitted", ocid="ocds-same"),
                make_row(2, outcome="rejected", ocid="ocds-same")]
        got, payload = self._labels(rows, tmp_path, monkeypatch)
        assert len(got) == 2                     # nothing collapsed
        assert got[0]["ansc_upheld"] == "1"
        assert got[1]["ansc_upheld"] == "0"
        import json
        data = json.loads(payload.read_text("utf-8"))
        proc = data["procedure_level"]
        assert proc["procedures_with_several_reviewed_documents"] == 1
        assert proc["procedures_with_conflicting_binary_labels"] == 1
        assert proc["conflicting_ocids"] == ["ocds-same"]

    def test_decision_dates_and_future_leakage_flagged(self, tmp_path,
                                                       monkeypatch):
        rows = [make_row(1), make_row(2)]
        outcomes = [
            {"url": "http://storage.mtender.gov.md/get/r1",
             "decision_date": "04.10.2023"},
            {"url": "http://storage.mtender.gov.md/get/r2",
             "decision_date": "01.01.2099"},     # future -> leakage flag
        ]
        _, payload = self._labels(rows, tmp_path, monkeypatch,
                                  outcomes=outcomes)
        import json
        data = json.loads(payload.read_text("utf-8"))
        dates = data["decision_dates"]
        assert dates["with_date"] == 2
        assert dates["min_date"] == "2023-10-04"
        assert [f["document_url"] for f in dates["dates_after_generation"]] \
            == ["http://storage.mtender.gov.md/get/r2"]
        assert "AFTER" in dates["rule"] or "after" in dates["rule"]


# --- leakage ---------------------------------------------------------------
class TestLeakage:
    def test_feature_pipeline_has_no_ansc_upheld(self):
        """Regression: the label must never appear in scripts 00-15 or
        backend/ (MTA-0019 §6/§8)."""
        hits = s47.scan_feature_leakage(s47.scan_targets())
        assert hits == [], f"ansc_upheld leaked into the pipeline: {hits}"

    def test_leak_blocks_labeling(self, tmp_path, monkeypatch):
        bad = tmp_path / "06_detect_anomalies.py"
        bad.write_text("features = ['ansc_upheld']\n", "utf-8")
        rows = [make_row(1)]
        rc, out, payload = run(s47.main, rows, tmp_path, monkeypatch,
                               targets=[bad])
        assert rc == 7
        assert not out.exists()
        import json
        data = json.loads(payload.read_text("utf-8"))
        assert data["status"] == "feature_leakage_detected"
        assert data["labels"] is None
        assert data["leakage"][0]["file"] == str(bad)

    def test_scan_ignores_the_label_script_itself(self):
        # 47 is above 15 by design and must not be part of the scan set
        targets = [p for p in s47.scan_targets() if p.name.startswith("47")]
        assert targets == []

    def test_label_file_payload_has_disclaimers(self, tmp_path, monkeypatch):
        rows = [make_row(1)]
        _, _, payload = run(s47.main, rows, tmp_path, monkeypatch)
        import json
        data = json.loads(payload.read_text("utf-8"))
        assert "does not constitute proof of corruption" in \
            data["disclaimer_en"]
        assert "не является доказательством коррупции" in data["disclaimer_ru"]
