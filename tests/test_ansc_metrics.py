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


# --- MTA-0019: the blind review file, document types, links ----------------
REVIEW_FIELDS = ["ocid", "decision_id", "document_url", "reviewer_outcome",
                 "reviewer_document_type", "reviewer_link_verified",
                 "reviewer_evidence_page", "reviewer_evidence_quote",
                 "reviewer_notes"]


def mrow(i: int, extracted: str, outcome: str, doc_type: str = "",
         link: str = "", notes: str = "", layer: str = "1") -> dict:
    """Row as it arrives from the blind review file overlaid on the sample."""
    return {"ocid": f"ocds-m{i}", "decision_id": f"03D-{i}-22",
            "document_url": f"http://storage.mtender.gov.md/get/m{i}",
            "extracted_outcome": extracted, "evidence_quote": "q",
            "page_number": "1", "extraction_method": "resolutory_strong_anchor",
            "confidence": "high", "reviewer_outcome": outcome,
            "reviewer_document_type": doc_type, "reviewer_link_verified": link,
            "reviewer_evidence_page": "", "reviewer_evidence_quote": "",
            "reviewer_notes": notes, "_layer": layer}


def write_review(rows: list[dict], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


class TestReviewFileOverlay:
    """The human labels live in the blind file (scripts/46); 45 merges them
    with the machine sample by URL."""

    @staticmethod
    def _sample(tmp_path: Path) -> Path:
        # same URLs as the review rows (m1, m2) so the overlay can match
        rows = [mrow(1, "admitted", ""), mrow(2, "rejected", "")]
        fields = ["ocid", "decision_id", "document_url", "extracted_outcome",
                  "evidence_quote", "page_number", "extraction_method",
                  "confidence", "reviewer_outcome", "reviewer_notes"]
        with open(tmp_path / "sample.csv", "w", newline="",
                  encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields,
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return tmp_path / "sample.csv"

    def test_unfilled_review_blocks_metrics(self, tmp_path, monkeypatch):
        sample = self._sample(tmp_path)
        review = write_review(
            [mrow(1, "admitted", ""), mrow(2, "rejected", "")],
            tmp_path / "review.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        rc = s45.main(["--sample", str(sample), "--review", str(review),
                       "--outcomes", str(tmp_path / "absent.csv")])
        assert rc == 5                       # progress ONLY, no metrics
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["metrics"] is None
        assert payload["n_labeled"] == 0 and payload["n_total"] == 2
        assert payload["review_required_fields"] == [
            "reviewer_outcome", "reviewer_document_type",
            "reviewer_link_verified"]
        assert payload["review_rows_matched"] == 2
        # every unfilled field is listed (2 rows x 3 fields)
        assert len(payload["missing_rows"]) == 6

    def test_invalid_document_type_is_exit_6(self, tmp_path, monkeypatch):
        sample = self._sample(tmp_path)
        review = write_review(
            [mrow(1, "admitted", "admitted", "ansc_decision", "confirmed"),
             mrow(2, "rejected", "rejected", "decision", "confirmed")],
            tmp_path / "review.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        rc = s45.main(["--sample", str(sample), "--review", str(review),
                       "--outcomes", str(tmp_path / "absent.csv")])
        assert rc == 6
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["status"] == "invalid_labels"
        assert payload["metrics"] is None
        assert payload["invalid_rows"][0]["field"] == "reviewer_document_type"
        assert payload["invalid_rows"][0]["value"] == "decision"

    def test_labels_from_review_file_compute_metrics(self, tmp_path,
                                                     monkeypatch):
        sample = self._sample(tmp_path)
        review = write_review(
            [mrow(1, "admitted", "admitted", "ansc_decision", "confirmed"),
             mrow(2, "rejected", "rejected", "ansc_decision", "confirmed")],
            tmp_path / "review.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        monkeypatch.setattr(s45, "OUT_MD", tmp_path / "m.md")
        rc = s45.main(["--sample", str(sample), "--review", str(review),
                       "--outcomes", str(tmp_path / "absent.csv")])
        assert rc == 0                       # the sample itself was EMPTY
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["status"] == "metrics_computed"
        assert payload["review_file"] == str(review)
        assert payload["metrics"]["n_labeled"] == 2
        assert payload["metrics"]["accuracy"] == 1.0
        report = (tmp_path / "m.md").read_text("utf-8")
        assert "не обязательно репрезентативна" in report

    def test_sample_labels_still_work_without_review_file(self, tmp_path,
                                                          monkeypatch):
        """Legacy contract: no review file -> the sample's own columns."""
        rows = [srow(1, "admitted", "admitted"),
                srow(2, "rejected", "rejected")]
        sample = write_sample(rows, tmp_path / "sample.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        monkeypatch.setattr(s45, "OUT_MD", tmp_path / "m.md")
        rc = s45.main(["--sample", str(sample), "--review", "",
                       "--outcomes", str(tmp_path / "absent.csv")])
        assert rc == 0


class TestDocumentTypeAndLinkMetrics:
    def test_other_document_excluded_from_outcome_metrics(self):
        rows = [
            mrow(1, "admitted", "admitted", "ansc_decision", "confirmed"),
            # machine says decision, reviewer says it is NOT one:
            mrow(2, "admitted", "rejected", "other_document", "confirmed"),
        ]
        m = s45.compute_metrics(rows, {})
        assert m["n_labeled"] == 2
        assert m["n_evaluated"] == 1            # outcome metrics exclude it
        assert m["accuracy"] == 1.0             # only the confirmed decision
        ex = m["excluded_non_decision"]
        assert ex == {"n": 1, "other_document": 1, "uncertain": 0}
        # ... but document-type detection counts it (binary: is a decision)
        dt = m["document_type_detection"]
        assert dt["reviewer_counts"] == {"ansc_decision": 1,
                                         "other_document": 1,
                                         "uncertain": 0, "unfilled": 0}
        assert dt["confusion"]["other_document"]["decision"] == 1
        assert dt["binary_n"] == 2
        assert dt["precision"] == 0.5 and dt["recall"] == 1.0

    def test_uncertain_type_is_excluded_from_outcome_metrics(self):
        rows = [mrow(1, "admitted", "admitted", "ansc_decision", "confirmed"),
                mrow(2, "rejected", "unknown", "uncertain", "confirmed")]
        m = s45.compute_metrics(rows, {})
        assert m["n_evaluated"] == 1
        assert m["excluded_non_decision"]["uncertain"] == 1

    def test_wrong_link_is_counted_and_excluded_from_confirmed(self):
        rows = [
            mrow(1, "admitted", "admitted", "ansc_decision", "confirmed"),
            mrow(2, "rejected", "rejected", "ansc_decision", "rejected",
                 notes="mislink: award decision, not a complaint"),
            mrow(3, "unknown", "unknown", "ansc_decision", "uncertain"),
            mrow(4, "admitted", "admitted", "ansc_decision", "confirmed"),
        ]
        m = s45.compute_metrics(rows, {})
        assert m["link_verification"] == {"confirmed": 2, "rejected": 1,
                                          "uncertain": 1, "unfilled": 0}
        # frequency of wrong links: the `rejected` row (notes marker too)
        assert m["mislink_rows"] == 1
        assert m["mislink_share"] == pytest.approx(0.25)
        # metrics on documents CONFIRMED as decisions (link == confirmed)
        conf = m["metrics_confirmed_decisions"]
        assert conf["n"] == 2                    # rows 2 and 3 excluded
        assert conf["accuracy"] == 1.0

    def test_confirmed_subset_can_be_empty(self):
        rows = [mrow(1, "admitted", "admitted", "ansc_decision", "rejected")]
        m = s45.compute_metrics(rows, {})
        assert m["metrics_confirmed_decisions"]["n"] == 0
        assert m["metrics_confirmed_decisions"]["accuracy"] is None

    def test_multi_complaint_rows_are_counted(self):
        rows = [mrow(1, "unknown", "unknown", "ansc_decision", "confirmed",
                     notes="multiple: 02/100/24 admitted; 03/103/24 "
                           "rejected"),
                mrow(2, "admitted", "admitted", "ansc_decision",
                     "confirmed")]
        m = s45.compute_metrics(rows, {})
        assert m["multi_complaint_rows"] == 1

    def test_sample_not_representative_note_is_carried(self):
        m = s45.compute_metrics(
            [mrow(1, "admitted", "admitted", "ansc_decision", "confirmed")],
            {})
        note = m["sample_is_stratified_not_representative"]
        assert "NOT necessarily representative" in note

    def test_report_has_type_link_and_representativeness_sections(
            self, tmp_path, monkeypatch):
        rows = [mrow(1, "admitted", "admitted", "ansc_decision", "confirmed"),
                mrow(2, "rejected", "rejected", "other_document",
                     "rejected", notes="mislink: notice"),
                mrow(3, "unknown", "unknown", "uncertain", "uncertain")]
        m = s45.compute_metrics(rows, {})
        report = s45.build_report(m, tmp_path / "sample.csv")
        assert "не обязательно репрезентативна" in report
        assert "Тип документа" in report
        assert "подтверждённых как решения ANSC" in report
        assert "Несколько жалоб" in report
        assert "ansc_upheld" not in report


# --- sample independence: independent documents/procedures (MTA-0019 §9) -----
class TestSampleIndependence:
    """Review instruction of 2026-11-09, item 4: the four byte-duplicate
    groups must be preserved and the denominators of future metrics must
    count INDEPENDENT documents/procedures - repeated URLs must never
    inflate the sample size."""

    @staticmethod
    def _write_review(path: Path, entries: list[tuple[str, str]]) -> Path:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["document_url",
                                                    "local_pdf_path"])
            writer.writeheader()
            for url, pdf in entries:
                writer.writerow({"document_url": url, "local_pdf_path": pdf})
        return path

    def test_byte_duplicates_count_once(self, tmp_path):
        same = tmp_path / "same.pdf"
        same.write_bytes(b"%PDF-1.4 byte-identical content")
        other = tmp_path / "other.pdf"
        other.write_bytes(b"%PDF-1.4 a completely different file")
        review = self._write_review(tmp_path / "review.csv", [
            ("http://x/u1", str(same)),
            ("http://x/u2", str(same)),        # same file, another URL
            ("http://x/u3", str(other)),
        ])
        rows = [{"document_url": "http://x/u1", "ocid": "ocds-a"},
                {"document_url": "http://x/u2", "ocid": "ocds-a"},
                {"document_url": "http://x/u3", "ocid": "ocds-b"}]
        indep = s45.sample_independence(rows, review)
        assert indep["n_rows"] == 3
        assert indep["n_unique_urls"] == 3          # 3 URLs, but:
        assert indep["n_independent_documents"] == 2   # only 2 files
        assert indep["byte_duplicate_groups"] == [[1, 2]]
        assert indep["n_independent_procedures"] == 2  # 2 unique OCIDs
        assert indep["rows_without_local_pdf"] == []
        assert "never copied between rows" in indep["note"]

    def test_without_local_pdfs_the_document_count_is_unknown(self,
                                                              tmp_path):
        rows = [{"document_url": "http://x/u1", "ocid": "ocds-1"}]
        indep = s45.sample_independence(rows, tmp_path / "absent.csv")
        assert indep["n_independent_documents"] is None   # never guessed
        assert indep["rows_without_local_pdf"] == [1]
        assert indep["n_independent_procedures"] == 1
        assert indep["byte_duplicate_groups"] == []

    def test_missing_pdf_file_is_reported_not_guessed(self, tmp_path):
        review = self._write_review(
            tmp_path / "review.csv",
            [("http://x/u1", str(tmp_path / "gone.pdf"))])
        rows = [{"document_url": "http://x/u1", "ocid": "ocds-1"}]
        indep = s45.sample_independence(rows, review)
        assert indep["n_independent_documents"] is None
        assert indep["rows_without_local_pdf"] == [1]

    def test_refusal_payload_carries_independence_but_no_metrics(
            self, tmp_path, monkeypatch):
        rows = [srow(1, "admitted", ""),                # not reviewed
                srow(2, "rejected", "rejected")]
        sample = write_sample(rows, tmp_path / "sample.csv")
        monkeypatch.setattr(s45, "OUT_JSON", tmp_path / "m.json")
        assert s45.main(["--sample", str(sample),
                         "--outcomes", str(tmp_path / "absent.csv")]) == 5
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["metrics"] is None               # still refused
        indep = payload["sample_independence"]
        assert indep["n_rows"] == 2
        assert indep["note"].startswith("denominators must use independent")
        assert not [k for k in payload
                    if "accuracy" in k or "macro" in k or "f1" in k]

    def test_metrics_and_report_carry_the_independence_block(self,
                                                             tmp_path):
        rows = [mrow(1, "admitted", "admitted", "ansc_decision", "confirmed"),
                mrow(2, "rejected", "rejected", "ansc_decision", "confirmed")]
        indep = {"n_rows": 2, "n_unique_urls": 2,
                 "n_independent_documents": 1, "n_independent_procedures": 1,
                 "byte_duplicate_groups": [[1, 2]],
                 "rows_without_local_pdf": [],
                 "note": "denominators must use independent documents"}
        m = s45.compute_metrics(rows, {}, independence=indep)
        assert m["sample_independence"] == indep
        report = s45.build_report(m, tmp_path / "sample.csv")
        assert "Независимость выборки" in report
        assert "Независимых документов" in report
        assert "| 1 |" in report            # duplicates counted ONCE

    def test_compute_metrics_defaults_to_no_independence_block(self):
        m = s45.compute_metrics([mrow(1, "admitted", "admitted")], {})
        assert m["sample_independence"] is None
