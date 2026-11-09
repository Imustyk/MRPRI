"""MTA-0019: evidence pack + sample duplicate check (scripts/49).

Contracts pinned here:

* the pack carries ORIGINAL pages labelled with identity only (pilot
  number, OCID, decision number, source page) - no outcome word, no
  machine prediction, no assistance hint (reviewer instruction of
  2026-11-09);
* document type and procedure link are stated separately: the pack never
  implies that a non-decision document is mislinked;
* neither mode opens ``ansc_review_sample_50.csv`` (blindness) and
  neither writes a ``reviewer_*`` cell - the review CSVs stay
  byte-identical after a run;
* the duplicate check only REPORTS identity groups (byte hash, text
  fingerprint, OCID, decision number) and never copies a human value;
* exit codes: 0 ok, 4 missing input/rendering aid, 5 missing or
  inconsistent local PDF.

No network; PDFs are blank pages written with pypdf.
"""
from __future__ import annotations

import builtins
import csv
import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"s{name.split('_')[0]}", ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s49 = _load("49_ansc_review_pack.py")

OUTCOMES = ("admitted", "partially", "rejected", "inadmissible", "withdrawn",
            "terminated", "unknown")


def _blank_pdf(path: Path, pages: int = 1) -> Path:
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    writer.write(str(path))
    return path


def _pilot_csv(path: Path, rows: list[dict]) -> Path:
    header = ["ocid", "decision_id", "document_url", "local_pdf_path",
              "page_number", "evidence_quote", "reviewer_outcome"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in header})
    return path


def _review_csv(path: Path, rows: list[dict]) -> Path:
    header = ["ocid", "decision_id", "document_url", "local_pdf_path"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in header})
    return path


def _entry(pilot_no: int, *, decision: str = "03D-355-20",
           kind: str = "resolutory page", what: str = "") -> dict:
    spec = dict(s49.PACK_SPEC.get(pilot_no,
                                  {"pages": ((1, kind),),
                                   "decision": decision, "what": what}))
    spec.update(pages_kind=kind, pilot_no=pilot_no, source_page=15,
                row={"ocid": "ocds-b3wdp1-MD-1586765700891-PN-1586765700928",
                     "_pdf_pages": "15"})
    spec["decision"] = decision
    spec["what"] = what
    return spec


# --- pack spec --------------------------------------------------------------
class TestPackSpec:
    def test_spec_covers_pilot_2_to_10_exactly(self):
        assert set(s49.PACK_SPEC) == set(range(2, 11))

    def test_pages_are_positive_with_known_kinds(self):
        kinds = {"resolutory page", "document-type page"}
        for pilot_no, entry in s49.PACK_SPEC.items():
            assert entry["pages"], pilot_no
            for page_no, kind in entry["pages"]:
                assert page_no >= 1, pilot_no
                assert kind in kinds, pilot_no

    def test_decision_numbers_only_on_the_five_decisions(self):
        with_dec = {n for n, e in s49.PACK_SPEC.items() if e["decision"]}
        assert with_dec == {2, 3, 4, 6, 8}
        assert s49.PACK_SPEC[6]["decision"] == "03D-94-19"   # deep analysis

    def test_non_decision_documents_have_type_pages(self):
        for pilot_no in (5, 7, 9, 10):
            kinds = {k for _, k in s49.PACK_SPEC[pilot_no]["pages"]}
            assert kinds == {"document-type page"}, pilot_no
            assert s49.PACK_SPEC[pilot_no]["decision"] == ""

    def test_decision_documents_have_resolutory_pages(self):
        for pilot_no in (2, 3, 4, 6, 8):
            kinds = {k for _, k in s49.PACK_SPEC[pilot_no]["pages"]}
            assert kinds == {"resolutory page"}, pilot_no


# --- labels and cover: identity only ---------------------------------------
class TestIdentityOnly:
    def test_label_carries_pilot_ocid_decision_page(self):
        line1, line2 = s49.label_lines(2, _entry(2)["row"], 15, _entry(2))
        assert "pilot No 2" in line1
        assert "ocds-b3wdp1-MD-1586765700891" in line1
        assert "decision 03D-355-20" in line1
        assert "source page 15/15" in line2
        assert "resolutory page" in line2

    def test_label_without_a_decision_number(self):
        entry = _entry(5, decision="", kind="document-type page",
                       what="ANSC letter nr. 05/795/21 of 14.04.2021")
        line1, line2 = s49.label_lines(5, entry["row"], 1, entry)
        assert "decision" not in line1
        assert "ANSC letter nr. 05/795/21" in line2

    def test_type_and_link_are_not_conflated_in_labels(self):
        # a non-decision document keeps its type page: nothing in the pack
        # may call it a link error (reviewer instruction 1, 2026-11-09)
        for pilot_no in (5, 7, 9, 10):
            entry = _entry(pilot_no, decision="", kind="document-type page",
                           what=s49.PACK_SPEC[pilot_no]["what"])
            _, line2 = s49.label_lines(pilot_no, entry["row"], 1, entry)
            assert "mislink" not in line2.lower()

    def test_label_refuses_outcome_words(self):
        entry = _entry(5, decision="", what="complaint rejected")
        with pytest.raises(AssertionError):
            s49.label_lines(5, entry["row"], 1, entry)

    def test_forbidden_hits(self):
        text = "the complaint was rejected and later withdrawn"
        hits = s49.forbidden_hits(text)
        assert "rejected" in hits and "withdrawn" in hits
        assert s49.forbidden_hits("Se admite contestatia") == []

    def test_cover_has_contents_disclaimers_and_no_prediction_note(self):
        entries = [_entry(2), _entry(5, decision="",
                                    kind="document-type page",
                                    what="ANSC letter nr. 05/795/21")]
        lines = s49.cover_lines(entries)
        joined = "\n".join(lines)
        assert any("No 2 | source page 15/15" in ln for ln in lines)
        assert any("No 5 |" in ln and "no ANSC decision number" in ln
                   for ln in lines)
        assert s49.DISCLAIMER_EN in lines and s49.DISCLAIMER_RU in lines
        assert any("No automatic outcome" in ln for ln in lines)
        assert any("judged separately" in ln for ln in lines)
        assert s49.forbidden_hits(joined) == []


# --- pack build -------------------------------------------------------------
class TestBuildPack:
    @pytest.fixture
    def fixture(self, tmp_path):
        pdf = _blank_pdf(tmp_path / "doc2.pdf", pages=15)
        pilot = _pilot_csv(tmp_path / "pilot.csv", [
            {"ocid": "ocds-b3wdp1-MD-1", "local_pdf_path": "unused.pdf"},
            {"ocid": "ocds-b3wdp1-MD-1586765700891-PN-1586765700928",
             "local_pdf_path": str(pdf)},
        ])
        spec = {2: {"pages": ((15, "resolutory page"),),
                    "decision": "03D-355-20", "what": ""}}
        return pilot, spec

    def test_pack_builds_pdf_and_manifest(self, tmp_path, monkeypatch,
                                          fixture):
        pilot, spec = fixture
        out = tmp_path / "pack.pdf"
        manifest = tmp_path / "manifest.csv"
        monkeypatch.setattr(s49, "PILOT_10", pilot)
        monkeypatch.setattr(s49, "PACK_SPEC", spec)
        before = pilot.read_bytes()

        assert s49.main(["pack", "--out", str(out),
                         "--manifest", str(manifest)]) == 0
        assert pilot.read_bytes() == before          # read-only

        from pypdf import PdfReader
        assert len(PdfReader(str(out)).pages) == 2   # cover + 1 page

        with manifest.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        row = rows[0]
        assert row["pilot_no"] == "2" and row["source_page"] == "15"
        assert row["decision_id"] == "03D-355-20"
        assert "ocds-b3wdp1-MD-1586765700891" in row["ocid"]
        text = manifest.read_text(encoding="utf-8")
        assert s49.forbidden_hits(text) == []

    def test_missing_pilot_file_is_4(self, tmp_path, monkeypatch):
        monkeypatch.setattr(s49, "PILOT_10", tmp_path / "nope.csv")
        assert s49.main(["pack", "--out", str(tmp_path / "p.pdf"),
                         "--manifest", str(tmp_path / "m.csv")]) == 4

    def test_missing_local_pdf_is_5(self, tmp_path, monkeypatch):
        pilot = _pilot_csv(tmp_path / "pilot.csv", [
            {"ocid": "x"},
            {"ocid": "ocds-b3wdp1-MD-2",
             "local_pdf_path": str(tmp_path / "gone.pdf")},
        ])
        monkeypatch.setattr(s49, "PILOT_10", pilot)
        monkeypatch.setattr(s49, "PACK_SPEC",
                            {2: {"pages": ((1, "resolutory page"),),
                                 "decision": "", "what": ""}})
        assert s49.main(["pack", "--out", str(tmp_path / "p.pdf"),
                         "--manifest", str(tmp_path / "m.csv")]) == 5

    def test_spec_page_beyond_the_pdf_is_5(self, tmp_path, monkeypatch):
        pdf = _blank_pdf(tmp_path / "short.pdf", pages=3)
        pilot = _pilot_csv(tmp_path / "pilot.csv", [
            {"ocid": "x"},
            {"ocid": "ocds-b3wdp1-MD-3", "local_pdf_path": str(pdf)},
        ])
        monkeypatch.setattr(s49, "PILOT_10", pilot)
        monkeypatch.setattr(s49, "PACK_SPEC",
                            {2: {"pages": ((15, "resolutory page"),),
                                 "decision": "", "what": ""}})
        assert s49.main(["pack", "--out", str(tmp_path / "p.pdf"),
                         "--manifest", str(tmp_path / "m.csv")]) == 5


# --- duplicate check --------------------------------------------------------
class TestGroupIds:
    def test_groups_need_at_least_two_members(self):
        rows = [{"row_index": "1", "ocid": "a"},
                {"row_index": "2", "ocid": "a"},
                {"row_index": "3", "ocid": "b"},
                {"row_index": "4", "ocid": ""}]
        assert s49.group_ids(rows, "ocid") == {"a": ["1", "2"]}

    def test_text_fingerprint_ignores_spacing_and_case(self):
        long_text = "Se respinge contestatia nr. 02/100/24 " * 30
        variant = "SE  RESPINGE\ncontestatia, NR. 02/100/24 " * 30
        assert s49.text_fingerprint(long_text) == \
            s49.text_fingerprint(variant)
        assert s49.text_fingerprint("too short") == ""


class TestDuplicatesRun:
    @pytest.fixture
    def fixture(self, tmp_path):
        shared = _blank_pdf(tmp_path / "shared.pdf", pages=2)
        other = _blank_pdf(tmp_path / "other.pdf", pages=1)
        review = _review_csv(tmp_path / "review.csv", [
            {"ocid": "ocds-b3wdp1-MD-1000000000001",
             "decision_id": "03D-1-24",
             "local_pdf_path": str(shared)},
            {"ocid": "ocds-b3wdp1-MD-1000000000001",
             "decision_id": "03D-1-24",
             "local_pdf_path": str(shared)},
            {"ocid": "ocds-b3wdp1-MD-3000000000003",
             "local_pdf_path": str(other)},
            {"ocid": "ocds-b3wdp1-MD-4000000000004",
             "local_pdf_path": str(tmp_path / "gone.pdf")},
        ])
        out = tmp_path / "duplicates.csv"
        return review, out

    def test_reports_identity_and_never_copies(self, tmp_path, monkeypatch,
                                               fixture):
        review, out = fixture
        monkeypatch.setattr(s49, "REVIEW_50", review)
        monkeypatch.setattr(s49, "DUP_CSV", out)
        monkeypatch.setattr(s49, "ASSIST_CSV", tmp_path / "absent.csv")
        before = review.read_bytes()

        assert s49.main(["duplicates"]) == 0
        assert review.read_bytes() == before          # read-only

        with out.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 4
        # identical file reported as identical - nothing is merged away
        assert rows[0]["pdf_sha256_12"] == rows[1]["pdf_sha256_12"]
        assert rows[0]["ocid"] == rows[1]["ocid"]
        assert rows[0]["decision_ref"] == "03D-1-24"
        assert rows[2]["pdf_sha256_12"] != rows[0]["pdf_sha256_12"]
        # a missing PDF is reported, not guessed
        assert rows[3]["note"] == "missing local PDF"
        assert rows[3]["pdf_sha256_12"] == ""

    def test_missing_review_file_is_4(self, tmp_path, monkeypatch):
        monkeypatch.setattr(s49, "REVIEW_50", tmp_path / "nope.csv")
        assert s49.main(["duplicates"]) == 4


# --- blindness --------------------------------------------------------------
class TestBlindness:
    @pytest.fixture(autouse=True)
    def guard(self, monkeypatch):
        real_open = io.open
        opened: list[str] = []

        def guarded(file, *args, **kwargs):          # noqa: ANN001
            opened.append(str(file))
            assert "ansc_review_sample_50" not in str(file), \
                "the machine sample must never be opened"
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(io, "open", guarded)
        monkeypatch.setattr(builtins, "open", guarded)
        return opened

    def test_guard_is_active(self):
        with pytest.raises(AssertionError):
            io.open(ROOT / "data" / "external" / "ansc_review_sample_50.csv")

    def test_pack_never_opens_the_machine_sample(self, tmp_path, monkeypatch,
                                                 guard):
        pdf = _blank_pdf(tmp_path / "doc.pdf", pages=3)
        pilot = _pilot_csv(tmp_path / "pilot.csv", [
            {"ocid": "x"},
            {"ocid": "ocds-b3wdp1-MD-2", "local_pdf_path": str(pdf)},
        ])
        monkeypatch.setattr(s49, "PILOT_10", pilot)
        monkeypatch.setattr(s49, "PACK_SPEC",
                            {2: {"pages": ((2, "resolutory page"),),
                                 "decision": "", "what": ""}})
        assert s49.main(["pack", "--out", str(tmp_path / "p.pdf"),
                         "--manifest", str(tmp_path / "m.csv")]) == 0
        assert guard                                     # no forbidden open

    def test_duplicates_never_opens_the_machine_sample(self, tmp_path,
                                                       monkeypatch, guard):
        pdf = _blank_pdf(tmp_path / "doc.pdf", pages=1)
        review = _review_csv(tmp_path / "review.csv", [
            {"ocid": "ocds-b3wdp1-MD-1", "local_pdf_path": str(pdf)},
        ])
        monkeypatch.setattr(s49, "REVIEW_50", review)
        monkeypatch.setattr(s49, "DUP_CSV", tmp_path / "d.csv")
        monkeypatch.setattr(s49, "ASSIST_CSV", tmp_path / "absent.csv")
        assert s49.main(["duplicates"]) == 0
        assert guard
