"""MTA-0019 steps 2-3: the BLIND manual-review package (scripts/46).

Pins the contracts MTA-0019 depends on:

* the review files NEVER contain the machine prediction
  (``extracted_outcome``/``extraction_method``/``confidence``) and every
  ``reviewer_*`` cell is written EMPTY - the manual review is never
  imitated by algorithms, OCR, LLMs or classifiers;
* the reference columns (document number, OCID, source URL, local PDF
  path, expected resolutory page, evidence quote) are present;
* validate: 0 = complete, 5 = fields still empty (progress only),
  6 = invalid enum values, 4 = missing file;
* build refuses to overwrite a file the reviewer may already be filling;
* the shipped package (50 + pilot 10) keeps its shape.

No network; the sandbox is a tmp dir (build never requires the PDFs to
exist, it only records their paths).
"""
from __future__ import annotations

import csv
import hashlib
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


s46 = _load("46_ansc_review_package.py")

FORBIDDEN = {"extracted_outcome", "extraction_method", "confidence"}
REVIEWER = [f for f in s46.REVIEW_FIELDS if f.startswith("reviewer_")]


# --- helpers ---------------------------------------------------------------
def make_sample(n: int = 12) -> list[dict]:
    outcomes = ["admitted", "partially_admitted", "rejected", "withdrawn",
                "unknown"]
    rows = []
    for i in range(n):
        rows.append({
            "ocid": f"ocds-x{i}", "decision_id": f"03D-{i}-22" if i % 3 else "",
            "document_url": f"http://storage.mtender.gov.md/get/u{i}",
            "extracted_outcome": outcomes[i % len(outcomes)],
            "evidence_quote": "q" if i % 4 else "",
            "page_number": str(i + 1), "extraction_method": "resolutory_strong_anchor",
            "confidence": "high", "reviewer_outcome": "", "reviewer_notes": "",
        })
    return rows


def write_sample(rows: list[dict], path: Path) -> Path:
    fields = ["ocid", "decision_id", "document_url", "extracted_outcome",
              "evidence_quote", "page_number", "extraction_method",
              "confidence", "reviewer_outcome", "reviewer_notes"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path


def write_outcomes(rows: list[dict], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["url", "year", "text_layer",
                                           "confidence"])
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({"url": r["document_url"], "year": "2022",
                        "text_layer": "1" if i % 2 else "0",
                        "confidence": r["confidence"]})
    return path


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Build the package into tmp and return its constants."""
    sample = write_sample(make_sample(), tmp_path / "sample.csv")
    outcomes = write_outcomes(make_sample(), tmp_path / "outcomes.csv")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setattr(s46, "IN_SAMPLE", sample)
    monkeypatch.setattr(s46, "IN_OUTCOMES", outcomes)
    monkeypatch.setattr(s46, "OUT_REVIEW", tmp_path / "review50.csv")
    monkeypatch.setattr(s46, "OUT_PILOT", tmp_path / "pilot10.csv")
    monkeypatch.setattr(s46, "OUT_JSON", tmp_path / "pkg.json")
    rc = s46.main(["build", "--sandbox", str(sandbox), "--pilot-size", "5",
                   "--quiet"])
    assert rc == 0, "package build failed"
    return tmp_path


# --- blindness contract ----------------------------------------------------
class TestBlindness:
    def test_review_file_is_blind_and_empty(self, built):
        with open(built / "review50.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 12
        assert list(rows[0]) == s46.REVIEW_FIELDS
        assert not (FORBIDDEN & set(rows[0]))          # prediction hidden
        for row in rows:
            assert all(row[f] == "" for f in REVIEWER)  # never imitated
            # reference columns present
            assert row["ocid"] and row["document_url"]
            assert row["local_pdf_path"].endswith(".pdf")

    def test_local_pdf_path_is_the_documented_digest(self, built):
        with open(built / "review50.csv", newline="", encoding="utf-8") as fh:
            row = next(csv.DictReader(fh))
        digest = hashlib.sha1(row["document_url"].encode()).hexdigest()[:16]
        assert row["local_pdf_path"] == str(
            Path(row["local_pdf_path"]).parent / f"{digest}.pdf")

    def test_pilot_is_a_deterministic_subset(self, built):
        with open(built / "review50.csv", newline="", encoding="utf-8") as fh:
            all_rows = list(csv.DictReader(fh))
        with open(built / "pilot10.csv", newline="", encoding="utf-8") as fh:
            pilot = list(csv.DictReader(fh))
        assert len(pilot) == 5
        urls = {r["document_url"] for r in all_rows}
        assert {r["document_url"] for r in pilot} <= urls
        assert len({r["document_url"] for r in pilot}) == len(pilot)
        # deterministic: a rebuild overwrites with identical bytes
        first = (built / "pilot10.csv").read_bytes()
        assert s46.main(["build", "--sandbox", str(built / "sandbox"),
                         "--pilot-size", "5", "--quiet"]) == 0
        assert (built / "pilot10.csv").read_bytes() == first

    def test_coverage_spans_outcomes_layers_confidence(self, built):
        pkg = json.loads((built / "pkg.json").read_text("utf-8"))
        cov = pkg["pilot_coverage"]
        # the first 5 specs: admitted (text), admitted (scan), partially,
        # rejected, withdrawn -> every classified outcome, both PDF layers
        assert cov["outcomes"] == {"admitted": 2, "partially_admitted": 1,
                                   "rejected": 1, "withdrawn": 1}
        assert set(cov["text_layer"]) == {"0", "1"}
        assert set(cov["confidence"]) == {"high"}
        assert set(cov["years"]) == {"2022"}

    def test_refuses_overwrite_of_filled_file(self, built):
        path = built / "review50.csv"
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        rows[0]["reviewer_outcome"] = "admitted"      # the human is working
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=s46.REVIEW_FIELDS)
            w.writeheader()
            w.writerows(rows)
        rc = s46.main(["build", "--sandbox", str(built / "sandbox"),
                       "--quiet"])
        assert rc == 6

    def test_check_source_refuses_prefilled_sample(self):
        rows = make_sample(3)
        rows[1]["reviewer_outcome"] = "admitted"
        assert any("already has" in e for e in s46.check_source(rows))


# --- validate mode ---------------------------------------------------------
class TestValidate:
    def test_missing_file_is_4(self, tmp_path):
        assert s46.main(["validate", "--file",
                         str(tmp_path / "nope.csv"), "--quiet"]) == 4

    def test_unfilled_is_5_with_progress_only(self, built):
        rc = s46.main(["validate", "--file", str(built / "review50.csv"),
                       "--quiet"])
        assert rc == 5

    def test_complete_and_valid_is_0(self, built):
        path = built / "review50.csv"
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            r["reviewer_outcome"] = "unknown"
            r["reviewer_document_type"] = "ansc_decision"
            r["reviewer_link_verified"] = "confirmed"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=s46.REVIEW_FIELDS)
            w.writeheader()
            w.writerows(rows)
        assert s46.main(["validate", "--file", str(path), "--quiet"]) == 0

    def test_invalid_enum_is_6(self, built):
        path = built / "review50.csv"
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            r["reviewer_outcome"] = "accepted"        # not an enum value
            r["reviewer_document_type"] = "ansc_decision"
            r["reviewer_link_verified"] = "confirmed"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=s46.REVIEW_FIELDS)
            w.writeheader()
            w.writerows(rows)
        assert s46.main(["validate", "--file", str(path), "--quiet"]) == 6

    def test_invalid_document_type_is_6_not_silently_outcome(self, built):
        path = built / "review50.csv"
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            r["reviewer_outcome"] = "unknown"
            r["reviewer_document_type"] = "decision"  # not an enum value
            r["reviewer_link_verified"] = "confirmed"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=s46.REVIEW_FIELDS)
            w.writeheader()
            w.writerows(rows)
        assert s46.main(["validate", "--file", str(path), "--quiet"]) == 6

    def test_partially_filled_is_5_not_0(self, built):
        """A reviewer outcome without the document type/link does not pass:
        the metrics and labels need all three."""
        path = built / "review50.csv"
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            r["reviewer_outcome"] = "admitted"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=s46.REVIEW_FIELDS)
            w.writeheader()
            w.writerows(rows)
        assert s46.main(["validate", "--file", str(path), "--quiet"]) == 5


# --- the shipped package stays stable --------------------------------------
class TestShippedPackage:
    def test_shipped_shape(self):
        rev_path = ROOT / "data" / "external" / "ansc_manual_review_50.csv"
        pil_path = ROOT / "data" / "external" / "ansc_manual_review_pilot10.csv"
        with open(rev_path, newline="", encoding="utf-8") as fh:
            rev = list(csv.DictReader(fh))
        with open(pil_path, newline="", encoding="utf-8") as fh:
            pil = list(csv.DictReader(fh))
        assert len(rev) == 50 and len({r["document_url"] for r in rev}) == 50
        assert len(pil) == 10
        assert list(rev[0]) == s46.REVIEW_FIELDS
        assert not (FORBIDDEN & set(rev[0]))          # blindness forever
        urls = {r["document_url"] for r in rev}
        assert {r["document_url"] for r in pil} <= urls
        # reference cells exist for classified rows
        assert all(r["local_pdf_path"] for r in rev)
