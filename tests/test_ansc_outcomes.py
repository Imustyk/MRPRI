"""MTA-0018 step 3: ANSC outcome extraction tests (§9).

Two kinds of tests:

* REGRESSION on ACTUALLY EXTRACTED documents - the texts of 03D-630-19,
  03D-726-19 and 03D-533-22 were extracted from the PDFs downloaded by
  scripts/42 and each expected outcome was verified against the primary
  source before being pinned here:
    - 03D-630-19: genuine ANSC decision, ``d e c i d e:`` on page 18,
      item 1 = "Se admite parțial contestația nr. 02/739/19..." ->
      ``partially_admitted``;
    - 03D-726-19: NOT an ANSC decision - a contracting-authority award
      decision that only CITES decision 03d-726-19 -> ``unknown``;
    - 03D-533-22: one-page transmittal letter forwarding the decision ->
      ``unknown``;
* SYNTHETIC cases pinning every rule of MTA-0018 §3/§9: two-stage anchor
  logic, full-formulation classification, citation/claim suppression,
  contradiction and multi-complaint handling, missing documents, matching
  errors, ``unknown`` never being a negative label, no network in the
  extraction script, and no ``ansc_upheld`` leakage into model features.
"""
from __future__ import annotations

import csv
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "ansc"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"s43_{name}", ROOT / "scripts" / "43_ansc_outcome_extract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s43 = _load("outcome")


def load_fixture(filename: str) -> list[str]:
    """Per-page texts of an actually extracted document fixture."""
    text = (FIXTURES / filename).read_text(encoding="utf-8")
    pieces = re.split(r"<<<PAGE \d+>>>\n", text)
    return pieces[1:]          # pieces[0] is the leading ""


def strip_truncation(quote: str) -> str:
    return quote[:-4] if quote.endswith(" ...") else quote


# --- real-document regressions (primary source verified) --------------------
class TestRealDocuments:
    def test_630_is_partially_admitted(self):
        pages = load_fixture("03D-630-19.txt")
        res = s43.extract_outcome(pages)
        assert res["outcome"] == "partially_admitted"
        assert "d e c i d e" in res["resolution_anchor"]
        assert res["extraction_method"] == "resolutory_strong_anchor"
        assert res["confidence"] == "high"
        assert res["page_number"] == "18"
        assert res["unknown_reason"] == ""
        # resolutory item 1 of the primary source
        assert "Se admite parțial contestația nr. 02/739/19" in res["quote"]
        # the quote comes from the ORIGINAL text (accents intact), never
        # from the deaccented/normalised copy
        assert "parțial" in res["quote"]
        body = " ".join("\n".join(pages).split())
        quote = " ".join(strip_truncation(res["quote"]).split())
        assert quote in body

    def test_726_is_award_decision_not_ansc(self):
        # primary source: "DECIZIE de atribuire" of Primăria Ghidighici,
        # it only cites 03d-726-19 in a disqualification table
        res = s43.extract_outcome(load_fixture("03D-726-19.txt"))
        assert res["outcome"] == "unknown"
        assert res["quote"] == ""
        assert res["extraction_method"] == "no_resolutory_part"
        assert res["confidence"] == "none"
        assert "resolutory formulation" in res["unknown_reason"]
        # no resolutory anchor may be invented for it
        assert res["resolution_anchor"] == ""

    def test_533_is_transmittal_letter(self):
        # primary source: 1-page letter "remite copia deciziei nr. 03D-533-22"
        res = s43.extract_outcome(load_fixture("03D-533-22.txt"))
        assert res["outcome"] == "unknown"
        assert res["quote"] == ""
        assert "no structural anchor" in res["unknown_reason"]


# --- stage 1: anchor location ------------------------------------------------
class TestStage1Anchors:
    def test_last_anchor_is_not_taken_blindly(self):
        # a LATER contextless "decide" must not defeat the earlier
        # structurally valid "d e c i d e" that carries the formulation
        doc = ("d e c i d e:\n"
               "1. Se admite contestația nr. 01/001/24 din 01.01.2024.\n"
               "\n"
               + "umplere text motivational fara formulate.\n" * 40 +
               "Comisia decide sa se reuneasca ulterior.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "admitted"
        assert "d e c i d e" in res["resolution_anchor"]

    def test_ocr_spaced_hotaraste_anchor(self):
        doc = ("H O T Ă R ăș t e:\n"
               "1. Se respinge contestația nr. 02/002/23 din 05.05.2023.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "rejected"
        assert res["extraction_method"] == "resolutory_strong_anchor"

    def test_weak_anchor_without_formulation_is_unknown(self):
        # temeiul is auxiliary only: motivational/legal-basis text without
        # a resolutory formulation must not open the section
        doc = ("Temeiul adoptării prezentei hotărâri: art. 80.\n"
               "Președintele completului, semnătură.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "unknown"
        assert "resolutory formulation" in res["unknown_reason"]
        assert res["quote"] == ""

    def test_weak_anchor_with_formulation_classifies(self):
        doc = ("Temeiul: art. 71 alin. (3) lit. a) Cod administrativ.\n"
               "1. Se declară contestația inadmisibilă.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "inadmissible"
        assert res["extraction_method"] == "resolutory_weak_anchor"
        assert res["confidence"] == "medium"

    def test_no_anchor_at_all_is_unknown(self):
        res = s43.extract_outcome(["doar text oarecare, fara nicio ancora\n"])
        assert res["outcome"] == "unknown"
        assert "no structural anchor" in res["unknown_reason"]

    def test_empty_document_is_unknown(self):
        res = s43.extract_outcome([])
        assert res["outcome"] == "unknown"
        assert "no extractable text" in res["unknown_reason"]


# --- stage 2: full-formulation classification --------------------------------
class TestStage2Formulations:
    def test_body_claims_never_classify(self):
        doc = (
            "Contestatorul SRL X solicită admiterea contestației și "
            "anularea deciziei de atribuire.\n"
            "Agenția reține argumentele părților.\n"
            "d e c i d e:\n"
            "1. Se respinge contestația nr. 01/001/24 din 01.01.2024.\n"
        )
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "rejected"
        assert "Se respinge contestația" in res["quote"]

    def test_admitted(self):
        doc = ("hotărăște:\n"
               "1. Se admite contestația nr. 05/100/22 din 02.02.2022.\n"
               "2. Se anulează actele contestate.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "admitted"
        assert res["confidence"] == "high"

    def test_partial_admission_with_in_rest_rejection(self):
        doc = ("d e c i d e:\n"
               "1. Se admite parțial contestația nr. 03/500/21.\n"
               "2. În rest, contestația se respinge.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "partially_admitted"

    def test_ocr_variants_of_partial(self):
        # deaccented OCR text (no diacritics at all)
        doc = ("d e c i d e:\n1. Se admite partial contestatia nr. 2.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "partially_admitted"

    def test_withdrawn_by_retragerea(self):
        doc = ("d e c i d e:\n"
               "1. Se ia act de retragerea contestației nr. 04/100/23.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "withdrawn"

    def test_terminated(self):
        doc = ("d e c i d e:\n"
               "1. Se constată încetarea procedurii de soluționare a "
               "contestației nr. 06/200/20.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "terminated"

    def test_citation_of_another_decision_is_ignored(self):
        # only a citation after the anchor -> nothing to classify
        doc = ("d e c i d e:\n"
               "Potrivit deciziei nr. 03D-111/19, contestația se admite.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "unknown"
        assert res["quote"] == ""

    def test_citation_in_body_does_not_override_resolutory(self):
        doc = (
            "Conform deciziei Nr. 03D-111/19 a fost admisă contestația "
            "nr. 02/500/19.\n"
            "d e c i d e:\n"
            "1. Se respinge contestația nr. 03/900/19 din 01.02.2019.\n"
        )
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "rejected"

    def test_contradiction_without_partial_is_unknown(self):
        doc = ("d e c i d e:\n"
               "1. Se admite contestația nr. 07/300/21.\n"
               "2. Se respinge contestația nr. 07/300/21.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "unknown"
        assert "conflicting" in res["unknown_reason"]
        assert res["confidence"] == "none"


# --- multiple complaints per procedure --------------------------------------
class TestMultipleComplaints:
    def test_same_outcome_is_unambiguous(self):
        doc = ("d e c i d e:\n"
               "1. Se admite contestația nr. 01/100/24.\n"
               "2. Se admite contestația nr. 02/101/24.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "admitted"

    def test_different_outcomes_are_unknown(self):
        # decisions on different claims/complaints - no forced choice
        doc = ("d e c i d e:\n"
               "1. Se admite contestația nr. 01/100/24.\n"
               "2. Se respinge contestația nr. 02/101/24.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "unknown"
        assert res["unknown_reason"]

    def test_partial_and_rejection_of_different_complaints_unknown(self):
        # complaint A partially admitted, complaint B rejected - the numbers
        # differ, so this is NOT the usual single-complaint "în rest" pattern
        doc = ("d e c i d e:\n"
               "1. Se admite parțial contestația nr. 01/100/24.\n"
               "2. Se respinge contestația nr. 03/103/24.\n")
        res = s43.extract_outcome([doc])
        assert res["outcome"] == "unknown"
        assert "different complaints" in res["unknown_reason"]


# --- missing documents / matching errors ------------------------------------
class TestMissingAndMislinked:
    def _row(self, **over):
        row = {"ocid": "ocid-1", "url": "http://example.invalid/x.pdf",
               "title": "t", "year": "2024", "decision_numbers": "03D-1-24",
               "decision_date": "01.01.2024", "http_status": "200",
               "format": "pdf", "needs_ocr": "0"}
        row.update(over)
        return row

    def test_missing_document_file(self, tmp_path):
        res = s43.process_document(self._row(), tmp_path, 3)
        assert res["outcome"] == "unknown"
        assert res["document_present"] == "0"
        assert res["error"] == "document file absent from sandbox"

    def test_not_fetched_or_mismatched_row(self, tmp_path):
        # a row that was never fetched (404 / non-PDF after a document-link
        # matching error) must stay unknown with the reason recorded
        res = s43.process_document(self._row(http_status="404"), tmp_path, 3)
        assert res["outcome"] == "unknown"
        assert res["document_present"] == "0"
        assert res["error"] == "document not fetched or not a PDF"


# --- policy / leakage / network regressions ---------------------------------
def test_unknown_is_never_a_negative_label():
    row = {"outcome": "unknown", "quote": "", "page_number": "",
           "extraction_method": "no_resolutory_part", "confidence": "none",
           "document_present": "1", "text_layer": "1", "needs_ocr": "0",
           "resolution_anchor": "", "unknown_reason": "x", "error": ""}
    summary = s43.build_summary([row], 0.0)
    assert summary["policy"]["unknown_is_negative_label"] is False
    assert summary["outcomes"]["unknown"] == 1
    assert "unknown" in s43.OUTCOMES


def test_no_ansc_upheld_in_model_features():
    """Data-leakage protection: the external ANSC label (created only AFTER
    manual review, §6) must never become a model feature (§7)."""
    from src.mtender.features import FEATURE_COLUMNS
    assert "ansc_upheld" not in FEATURE_COLUMNS
    assert not any(c.startswith("ansc") for c in FEATURE_COLUMNS)
    # the extraction script itself must not emit an external label
    assert "ansc_upheld" not in s43.CSV_FIELDS
    src = (ROOT / "scripts" / "43_ansc_outcome_extract.py").read_text(
        encoding="utf-8")
    assert "ansc_upheld" not in src
    assert "FEATURE_COLUMNS" not in src


def test_script_43_performs_no_network_access():
    src = (ROOT / "scripts" / "43_ansc_outcome_extract.py").read_text(
        encoding="utf-8")
    forbidden = re.compile(
        r"^\s*(?:import|from)\s+(?:requests|urllib|socket|http|aiohttp)\b",
        re.MULTILINE)
    assert forbidden.search(src) is None


def test_script_42_network_is_gated():
    src = (ROOT / "scripts" / "42_ansc_decision_inventory.py").read_text(
        encoding="utf-8")
    assert "--allow-network" in src


def test_deaccent_is_length_preserving():
    samples = [
        "Se admite parțial contestația nr. 02/739/19",
        "declară contestația inadmisibilă",
        "retragerea contestației",
        "HOTĂRĂȘTE: încetează soluționarea",
        "d e c i d e:",
        "D E C I D E:",
        "Pre{ garbled OCR ăîâșț",
    ]
    for s in samples:
        flat = s43.deaccent(s)
        assert len(flat) == len(s), s
    assert s43.deaccent("Se admite parțial") == "se admite partial"
    # uppercase spaced OCR variant normalises to the anchor literal
    assert "d e c i d e" in s43.deaccent("D E C I D E:")


def test_quote_is_sliced_from_original_text():
    pages = load_fixture("03D-630-19.txt")
    res = s43.extract_outcome(pages)
    flat_quote = s43.deaccent(res["quote"])
    original = "\n".join(pages)
    # the evidence is the accented original, the deaccented copy is derived
    assert "parțial" in res["quote"] and "parțial" not in flat_quote
    assert res["quote"] != flat_quote
    assert " ".join(strip_truncation(res["quote"]).split()) in \
        " ".join(original.split())


def test_csv_roundtrip_exposes_evidence_quote(tmp_path):
    """The quote must survive the write/read cycle.

    The FIRST full run (2026-11-08) failed here: ``extract_outcome`` returns
    ``quote`` while the CSV column is ``evidence_quote`` and
    ``extrasaction="ignore"`` dropped it - all 138 classified rows shipped
    with an EMPTY evidence column, which would have made the step-7
    verification of every sampled quote impossible.
    """
    row = {"ocid": "ocds-x", "url": "http://storage.mtender.gov.md/get/x",
           "title": "decizie.pdf", "year": "2023",
           "decision_numbers": "03D-1-23", "decision_date": "",
           "outcome": "admitted",
           "quote": "1. Se admite contestația nr. 01/100/23.",
           "page_number": "3", "extraction_method": "resolutory_strong_anchor",
           "confidence": "high", "document_present": "1", "text_layer": "1",
           "needs_ocr": "0", "resolution_anchor": "d e c i d e",
           "unknown_reason": "", "error": ""}
    path = tmp_path / "outcomes.csv"
    s43.write_outcomes_csv([row], path)
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        got = list(reader)
    assert reader.fieldnames == s43.CSV_FIELDS
    assert len(got) == 1
    assert got[0]["evidence_quote"] == row["quote"]
    assert got[0]["page_number"] == "3"
    # no model-label leakage into the table
    assert "ansc_upheld" not in reader.fieldnames


def test_csv_roundtrip_unknown_row_has_empty_quote(tmp_path):
    row = {"ocid": "ocds-y", "url": "http://storage.mtender.gov.md/get/y",
           "title": "t", "year": "2024", "decision_numbers": "",
           "decision_date": "", "outcome": "unknown", "quote": "",
           "page_number": "", "extraction_method": "no_resolutory_part",
           "confidence": "none", "document_present": "1", "text_layer": "1",
           "needs_ocr": "0", "resolution_anchor": "",
           "unknown_reason": "no structural anchor in the document",
           "error": ""}
    path = tmp_path / "unknown.csv"
    s43.write_outcomes_csv([row], path)
    with open(path, newline="", encoding="utf-8") as fh:
        got = list(csv.DictReader(fh))
    assert got[0]["evidence_quote"] == ""
    assert got[0]["unknown_reason"].startswith("no structural anchor")
