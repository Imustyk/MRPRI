"""MTA-0019 step 7: technical assistance for the 50-document review
(scripts/48) + the complaint-level observation table (step 4).

Pins the contracts the assistance package depends on:

* the assistance CSV NEVER carries the machine prediction
  (``extracted_outcome``/``extraction_method``/``confidence``) and NEVER
  carries a ``reviewer_*`` column - it is a technical hint file, not a
  review file;
* every row states ``assistance_status = prepared_not_reviewed``: no human
  confirmation that never happened is ever stored (step 8);
* ``scripts/48`` never modifies the review CSVs (read-only, byte-identical
  after a run) and exits 4 when the review file is missing;
* text-layer classification (scan/partial/garbled/text), the OCR page plan,
  the document-type/link/outcome hints and multi-complaint detection behave
  as specified;
* ``data/external/ansc_complaint_level_review.csv`` keeps the step-4
  schema: one row per complaint, separate human field, review_status
  consistent with the filled human outcome, no machine-prediction columns.

No network; PDFs are stub files with the text layer injected through a
fake scripts/43 module (extraction itself is covered by
tests/test_ansc_outcomes.py).
"""
from __future__ import annotations

import csv
import importlib.util
import re
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPLAINT_CSV = ROOT / "data" / "external" / "ansc_complaint_level_review.csv"

OUTCOMES = {"admitted", "partially_admitted", "rejected", "inadmissible",
            "withdrawn", "terminated", "unknown"}
DOC_TYPES = {"ansc_decision", "other_document", "uncertain"}
LINKS = {"confirmed", "rejected", "uncertain"}
MACHINE_COLS = {"extracted_outcome", "extraction_method", "confidence"}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"s{name.split('_')[0]}", ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s48 = _load("48_ansc_review_assistance.py")
S43 = s48.S43


# --- text-layer status and OCR plan (pure functions) -------------------------
class TestTextStatus:
    @staticmethod
    def _pages(**kw):
        return [kw.get(str(i), "") for i in range(1, 7)]

    def test_no_text_layer_is_scan(self):
        status, empty = s48.text_status(["", "", ""])
        assert status == "scan" and empty == [1, 2, 3]

    def test_mostly_empty_pages_is_scan(self):
        status, empty = s48.text_status(["", "   \n", ""])
        assert status == "scan" and len(empty) == 3

    def test_short_pages_among_text_is_partial(self):
        pages = ["Contestația " * 40, "", "Contestația " * 40]
        status, empty = s48.text_status(pages)
        assert status == "partial" and empty == [2]

    def test_text_with_diacritics_is_text(self):
        pages = ["Contestația admisă de Agenția Națională " * 20]
        status, empty = s48.text_status(pages)
        assert status == "text" and empty == []

    def test_long_text_without_diacritics_is_garbled(self):
        pages = ["The national agency solving complaints decision " * 30]
        status, empty = s48.text_status(pages)
        assert status == "garbled" and empty == []


class TestOcrPlan:
    def test_no_empty_pages_needs_no_ocr(self):
        assert s48.ocr_plan("text", [], 10) == []

    def test_scan_ocrs_identity_plus_tail(self):
        empty = list(range(1, 9))
        plan = s48.ocr_plan("scan", empty, 8)
        assert plan[0] == 1                       # letterhead / decision no.
        assert plan[-1] == 8                      # resolutory part is last
        assert len(plan) <= s48.OCR_BUDGET

    def test_partial_ocrs_only_empty_pages(self):
        assert s48.ocr_plan("partial", [5], 9) == [5]

    def test_garbled_ocrs_first_and_last_pages(self):
        plan = s48.ocr_plan("garbled", [], 12)
        assert plan == [1, 2, 3, 11, 12]

    def test_garbled_short_document_no_duplicates(self):
        assert s48.ocr_plan("garbled", [], 2) == [1, 2]


# --- one document pass -------------------------------------------------------
DECISION_PAGE_1 = (
    "AGENŢIA NAȚIONALĂ PENTRU SOLUȚIONAREA CONTESTAȚIILOR\n"
    "NATIONAL AGENCY FOR SOLVING COMPLAINTS\n"
    "MD-2001, mun. Chișinău, bd. Ștefan cel Mare și Sfânt 124, et. 4\n"
    "D E C I Z I E Nr. 03D-111-24 Data: 05.03.2024 privind soluționarea "
    "contestației pe marginea procedurii de achiziție publică "
    "nr. MD-1000000000001 din 01.03.2024;\n"
)
RESOLUTORY_ADMIT = (
    "Reieșind din cele expuse, în conformitate cu prevederile art. 80 din "
    "Legea nr. 131/2015, Agenția Națională pentru Soluționarea Contestațiilor,\n"
    "d e c i d e:\n"
    "1. Se admite contestația nr. 02/100/24 din 10.02.2024, depusă de către "
    "„Exemplu” SRL, pe marginea rezultatelor procedurii de achiziție publică "
    "nr. MD-1000000000001 din 01.03.2024;\n"
    "Decizia este obligatorie pentru părți.\n"
)
RESOLUTORY_MIXED = (
    "Agenția Națională pentru Soluționarea Contestațiilor,\n"
    "d e c i d e:\n"
    "1. Se admite contestația nr. 02/100/24 din 10.02.2024, depusă de către "
    "„Exemplu” SRL, pe marginea procedurii de achiziție publică "
    "nr. MD-1000000000001 din 01.03.2024;\n"
    "2. Se respinge contestația nr. 02/101/24 "
    "din 11.02.2024, depusă de către „Altul” SRL, pe marginea aceleiași "
    "proceduri de achiziție publică nr. MD-1000000000001;\n"
)
AUTHORITY_DOC = (
    "Oficiul Teritorial pentru Achizitii Publice\n"
    "Procedura de achizitie publica nr. MD-2000000000002 din 01.03.2024, "
    "privind achizitionarea bunurilor, a fost atribuita de catre autoritatea "
    "contractanta in urma evaluarii ofertelor prezentate de operatorii "
    "economici participanti la licitatia deschisa organizata.\n"
)
OCR_DECISION = (
    "AGENTIA NATIONALA PENTRU SOLUTIONAREA CONTESTATIILOR\n"
    "MD-2001, mun. Chisinau\n"
    "decide:\n"
    "Se admite contestatia nr. 02/100/24 din 10.02.2024, depusa de catre "
    "SC Exemplu SRL, pe marginea rezultatelor procedurii de achizitie "
    "publica nr. MD-1000000000001 din 01.03.2024;\n"
)


def fake_s43(pages, ocr_texts=None):
    """Real scripts/43 logic with the PDF-reading part replaced."""
    ocr_texts = ocr_texts or {}
    fake = types.SimpleNamespace()
    fake.read_pdf_pages = lambda path: (list(pages), "")
    fake.ocr_page = lambda path, pageno, max_pages: ocr_texts.get(pageno, "")
    fake.deaccent = S43.deaccent
    fake.locate_resolution = S43.locate_resolution
    fake.extract_outcome = S43.extract_outcome
    fake.STRONG_ANCHORS = S43.STRONG_ANCHORS
    return fake


def stub_row(tmp_path, ocid="ocds-b3wdp1-MD-1000000000001"):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 % stub - text layer injected via fake")
    return {"ocid": ocid, "decision_id": "", "document_url": "http://x/y",
            "local_pdf_path": str(pdf)}


class TestAssistRow:
    def test_ansc_decision_pass(self, tmp_path):
        row = stub_row(tmp_path)
        rec = s48.assist_row(1, row, set(), render=False,
                             s43=fake_s43([DECISION_PAGE_1, RESOLUTORY_ADMIT]))
        assert rec["doc_type_hint"] == "ansc_decision"
        assert rec["fresh_outcome_hint"] == "admitted"
        assert rec["resolutory_page"] == "2"
        assert rec["decision_number"] == "03D-111-24"
        assert rec["complaint_count"] == "1"
        assert rec["complaint_ids"] == "02/100/24"
        assert rec["link_hint"] == "confirmed"
        assert rec["text_layer"] == "text"
        assert rec["assistance_status"] == "prepared_not_reviewed"

    def test_other_document_and_wrong_link(self, tmp_path):
        row = stub_row(tmp_path)     # ocid ...1000000000001, doc says ...2000000000002
        rec = s48.assist_row(1, row, set(), render=False,
                             s43=fake_s43([AUTHORITY_DOC]))
        assert rec["doc_type_hint"] == "other_document"
        assert rec["fresh_outcome_hint"] == "unknown"
        assert rec["link_hint"] == "rejected"

    def test_two_complaints_with_opposite_outcomes_is_unknown(self, tmp_path):
        row = stub_row(tmp_path)
        rec = s48.assist_row(1, row, set(), render=False,
                             s43=fake_s43([DECISION_PAGE_1, RESOLUTORY_MIXED]))
        assert rec["complaint_count"] == "2"
        assert rec["complaint_ids"] == "02/100/24;02/101/24"
        assert rec["fresh_outcome_hint"] == "unknown"

    def test_scan_is_ocr_ed_and_then_readable(self, tmp_path):
        row = stub_row(tmp_path)
        rec = s48.assist_row(1, row, set(), render=False,
                             s43=fake_s43(["", ""],
                                          ocr_texts={2: OCR_DECISION}))
        assert rec["text_layer"] == "scan"
        assert rec["ocr_pages_done"] == "2"   # page 1 OCR returned nothing
        assert rec["doc_type_hint"] == "ansc_decision"
        assert rec["fresh_outcome_hint"] == "admitted"

    def test_unreadable_scan_stays_uncertain_and_unknown(self, tmp_path):
        row = stub_row(tmp_path)
        rec = s48.assist_row(1, row, set(), render=False,
                             s43=fake_s43(["", ""]))       # OCR returns ""
        assert rec["doc_type_hint"] == "uncertain"
        assert rec["fresh_outcome_hint"] == "unknown"

    def test_missing_pdf_is_reported_not_raised(self, tmp_path):
        row = {"ocid": "ocds-b3wdp1-MD-1000000000001", "decision_id": "",
               "document_url": "http://x/y",
               "local_pdf_path": str(tmp_path / "gone.pdf")}
        rec = s48.assist_row(1, row, set(), render=False,
                             s43=fake_s43([]))
        assert rec["fresh_outcome_hint"] == "unknown"
        assert rec["fresh_unknown_reason"].startswith("missing local PDF")

    def test_no_prediction_and_no_reviewer_columns_in_header(self):
        forbidden = MACHINE_COLS | {"reviewer_outcome",
                                    "reviewer_link_verified",
                                    "extracted_page"}
        assert not forbidden & set(s48.HEADER)
        assert "assistance_status" in s48.HEADER


# --- main(): read-only + honest status --------------------------------------
def _write_review(path: Path, ocids=("ocds-b3wdp1-MD-1000000000001",)):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ocid", "decision_id", "document_url", "local_pdf_path",
                    "page_number", "evidence_quote", "reviewer_outcome"])
        for ocid in ocids:
            w.writerow([ocid, "", f"http://x/{ocid}", "", "3", "quote", ""])
    return path


class TestMain:
    def test_missing_review_file_is_4(self, tmp_path, monkeypatch):
        monkeypatch.setattr(s48, "REVIEW_50", tmp_path / "nope.csv")
        assert s48.main(["--quiet", "--no-render"]) == 4

    def test_run_writes_assistance_and_never_touches_review(
            self, tmp_path, monkeypatch):
        review = _write_review(tmp_path / "review.csv",
                               ("ocds-b3wdp1-MD-1000000000001",
                                "ocds-b3wdp1-MD-3000000000003"))
        pilot = _write_review(tmp_path / "pilot.csv")
        out = tmp_path / "assistance.csv"
        monkeypatch.setattr(s48, "REVIEW_50", review)
        monkeypatch.setattr(s48, "PILOT_10", pilot)
        monkeypatch.setattr(s48, "OUT_CSV", out)
        before = review.read_bytes()

        assert s48.main(["--quiet", "--no-render"]) == 0
        assert review.read_bytes() == before      # read-only, byte-identical

        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 2
        assert {r["assistance_status"] for r in rows} == {
            "prepared_not_reviewed"}
        assert not (MACHINE_COLS | {"reviewer_outcome"}) & set(rows[0])
        # no human confirmation is claimed anywhere in the file
        assert all(r["fresh_outcome_hint"] in OUTCOMES for r in rows)
        assert rows[0]["in_pilot"] == "yes" and rows[1]["in_pilot"] == "no"


# --- complaint-level table (step 4) -----------------------------------------
class TestComplaintLevelTable:
    @pytest.fixture
    def rows(self):
        assert COMPLAINT_CSV.is_file(), \
            "data/external/ansc_complaint_level_review.csv is missing"
        with COMPLAINT_CSV.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            return header, list(reader)

    def test_step4_schema_is_present(self, rows):
        header, _ = rows
        required = {"complaint_id", "decision_id", "ocid",
                    "complaint_outcome", "complaint_evidence_page",
                    "complaint_evidence_quote", "link_status",
                    "review_status"}
        assert required <= set(header)
        assert not (MACHINE_COLS | {"extracted_outcome"}) & set(header)

    def test_one_row_per_complaint_with_ids_and_quotes(self, rows):
        _, data = rows
        assert data, "complaint table must not be empty"
        seen = set()
        for r in data:
            assert re.fullmatch(r"02/\d{1,4}/\d{2}", r["complaint_id"]), r
            key = (r["ocid"], r["document_url"], r["complaint_id"])
            assert key not in seen, f"duplicate complaint row {key}"
            seen.add(key)
            assert r["complaint_outcome"] in OUTCOMES, r
            assert r["link_status"] in LINKS, r
            assert r["complaint_evidence_page"].isdigit(), r
            assert r["complaint_evidence_quote"].strip(), r

    def test_human_field_only_when_review_status_confirmed(self, rows):
        _, data = rows
        for r in data:
            assert r["review_status"] in {"preliminary", "confirmed"}, r
            if r["review_status"] == "confirmed":
                assert r["reviewer_complaint_outcome"] in OUTCOMES, r
            else:
                # no human confirmation that never happened
                assert r["reviewer_complaint_outcome"] == "", r

    def test_confirmed_row_matches_the_review_file_outcome(self, rows):
        """A confirmed complaint outcome must agree with the confirmed
        document-level record (single-complaint documents only)."""
        review = ROOT / "data" / "external" / "ansc_manual_review_50.csv"
        with review.open(encoding="utf-8") as fh:
            doc_rows = list(csv.DictReader(fh))
        by_url = {d["document_url"]: d for d in doc_rows}
        _, data = rows
        confirmed = [r for r in data if r["review_status"] == "confirmed"]
        for r in confirmed:
            doc = by_url.get(r["document_url"])
            if doc is None or not doc["reviewer_outcome"]:
                continue
            same_ocid_docs = [d for d in doc_rows
                              if d["ocid"] == r["ocid"]
                              and d["reviewer_outcome"]]
            if len(same_ocid_docs) == 1 and len(
                    [c for c in data if c["ocid"] == r["ocid"]
                     and c["review_status"] == "confirmed"]) == 1:
                # single confirmed complaint of a confirmed single-complaint
                # document -> outcomes must match
                assert r["reviewer_complaint_outcome"] == \
                    same_ocid_docs[0]["reviewer_outcome"], r
