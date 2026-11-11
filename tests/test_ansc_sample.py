"""MTA-0018 step 4: the stratified 50-document manual-review sample (scripts/44).

Pins the properties the manual review depends on: exact size and field set,
EMPTY reviewer columns (the script never imitates the review), stratification
across outcomes/years/PDF types/confidence levels, deterministic re-runs, and
the step-7 verification that every sampled quote/page can be opened in the
source document.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

OUTCOMES7 = ("admitted", "partially_admitted", "rejected", "inadmissible",
             "withdrawn", "terminated", "unknown")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"s{name.split('_')[0]}", ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s44 = _load("44_ansc_review_sample.py")


def make_row(i: int, **over) -> dict:
    row = {"ocid": f"ocds-md-{i}",
           "url": f"http://storage.mtender.gov.md/get/u{i}",
           "title": "t", "year": str(2019 + i % 6),
           "decision_numbers": f"03D-{i}-22" if i % 3 else "",
           "decision_date": "", "outcome": "unknown", "quote": "",
           "page_number": "", "extraction_method": "resolutory_strong_anchor",
           "confidence": "high", "document_present": "1", "text_layer": "1",
           "needs_ocr": "0", "resolution_anchor": "", "unknown_reason": "",
           "error": ""}
    row.update(over)
    return row


QUOTE = "1. Se admite parțial contestația nr. 02/739/19."


def make_pool(per_class: int = 40) -> list[dict]:
    rows: list[dict] = []
    i = 0
    for outcome in OUTCOMES7:
        for j in range(per_class):
            rows.append(make_row(
                i, outcome=outcome,
                confidence=("high", "medium", "low", "none")[j % 4],
                text_layer="0" if j % 3 == 0 else "1",
                quote=QUOTE, page_number="1"))
            i += 1
    return rows


def write_outcomes_csv(rows: list[dict], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


# --- sample construction -----------------------------------------------------
class TestBuildSample:
    def test_size_and_minimum_per_outcome(self):
        sampled, strata = s44.build_sample(make_pool(), total=50, min_per=3)
        assert len(sampled) == 50
        counts = Counter(r["outcome"] for r in sampled)
        for c in OUTCOMES7:
            assert counts[c] >= 3, c
        assert strata["shortage"] == 0

    def test_years_pdf_types_and_confidence_present(self):
        sampled, strata = s44.build_sample(make_pool(), total=50, min_per=3)
        assert {r["year"] for r in sampled} == {str(2019 + k)
                                                for k in range(6)}
        assert {r["text_layer"] for r in sampled} == {"0", "1"}
        assert {r["confidence"] for r in sampled} == \
            {"high", "medium", "low", "none"}
        assert strata["pool_years"] == sorted(strata["pool_years"])

    def test_deterministic(self):
        a, _ = s44.build_sample(make_pool(), total=50, min_per=3)
        b, _ = s44.build_sample(make_pool(), total=50, min_per=3)
        assert [r["url"] for r in a] == [r["url"] for r in b]

    def test_absent_documents_never_sampled(self):
        rows = make_pool(5)
        absent_url = rows[0]["url"]
        rows[0]["document_present"] = "0"
        sampled, strata = s44.build_sample(rows, total=50, min_per=3)
        assert absent_url not in {r["url"] for r in sampled}
        assert strata["pool_present_unique_urls"] == len(rows) - 1

    def test_duplicate_urls_deduplicated(self):
        rows = make_pool(5)
        dup = dict(rows[0])                    # same url, another ocid
        rows.append(dup)
        sampled, strata = s44.build_sample(rows, total=50, min_per=3)
        urls = [r["url"] for r in sampled]
        assert len(urls) == len(set(urls))
        assert strata["duplicate_urls_dropped"] >= 1

    def test_shortage_when_pool_small(self):
        rows = [make_row(i) for i in range(10)]
        sampled, strata = s44.build_sample(rows, total=50, min_per=3)
        assert len(sampled) == 10
        assert strata["shortage"] == 40

    def test_empty_pool_raises(self):
        with pytest.raises(ValueError):
            s44.build_sample([], total=50)


# --- CSV contract ------------------------------------------------------------
class TestSampleCsv:
    def test_fields_and_empty_reviewer_columns(self, tmp_path):
        sampled, _ = s44.build_sample(make_pool(), total=50, min_per=3)
        out = tmp_path / "sample.csv"
        s44.write_sample_csv(sampled, out)
        with open(out, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert reader.fieldnames == s44.SAMPLE_FIELDS
            rows = list(reader)
        assert len(rows) == 50
        for r in rows:
            assert r["reviewer_outcome"] == ""
            assert r["reviewer_notes"] == ""
            assert r["document_url"].startswith("http")
            assert r["extracted_outcome"] in OUTCOMES7

    def test_byte_identical_rerun(self, tmp_path):
        sampled, _ = s44.build_sample(make_pool(), total=50, min_per=3)
        a, b = tmp_path / "a.csv", tmp_path / "b.csv"
        s44.write_sample_csv(sampled, a)
        s44.write_sample_csv(sampled, b)
        assert a.read_bytes() == b.read_bytes()

    def test_reads_scripts43_evidence_quote_column(self, tmp_path):
        """scripts/43 stores the evidence in ``evidence_quote`` (its CSV
        column); the sample must carry it into ``evidence_quote`` instead of
        silently writing an empty cell (regression: the first real run of 44
        failed verification on 13/13 classified rows because it looked for a
        ``quote`` key that never exists in the CSV)."""
        row = make_row(1, outcome="admitted", page_number="4")
        row.pop("quote")
        row["evidence_quote"] = "1. Se admite contestația nr. 01/100/23."
        assert s44._quote_of(row) == "1. Se admite contestația nr. 01/100/23."
        out = tmp_path / "sample.csv"
        s44.write_sample_csv([row], out)
        with open(out, newline="", encoding="utf-8") as fh:
            got = list(csv.DictReader(fh))
        assert got[0]["evidence_quote"] == \
            "1. Se admite contestația nr. 01/100/23."

    def test_verification_uses_evidence_quote_column(self, tmp_path,
                                                      monkeypatch):
        url = make_row(1)["url"]
        (tmp_path / f"{_digest(url)}.pdf").write_bytes(b"x")
        quote = "Se respinge contestația nr. 07/500/21."
        monkeypatch.setattr(s44.S43, "read_pdf_pages",
                            lambda p: ([quote], ""))
        row = make_row(1, outcome="rejected", page_number="1",
                       text_layer="1")
        row.pop("quote")
        row["evidence_quote"] = quote
        res = s44.verify_sample([row], tmp_path)
        assert res["failures"] == 0
        assert res["verdicts"].get("quote_locatable") == 1


# --- verification that the reviewer can open the source page (step 7) --------
def _digest(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


class TestVerification:
    def test_missing_pdf_fails(self, tmp_path):
        row = make_row(1, outcome="admitted", quote="Se admite contestația",
                       page_number="2", text_layer="1")
        res = s44.verify_sample([row], tmp_path)
        assert res["failures"] == 1
        assert res["failure_items"][0]["verdict"] == "missing_pdf"

    def test_page_out_of_range_fails(self, tmp_path, monkeypatch):
        url = make_row(1)["url"]
        (tmp_path / f"{_digest(url)}.pdf").write_bytes(b"x")
        monkeypatch.setattr(s44.S43, "read_pdf_pages",
                            lambda p: (["only one page"], ""))
        row = make_row(1, outcome="admitted", quote="Se admite",
                       page_number="9", text_layer="1")
        res = s44.verify_sample([row], tmp_path)
        assert res["failure_items"][0]["verdict"] == "page_out_of_range"

    def test_quote_locatable_on_reported_page(self, tmp_path, monkeypatch):
        url = make_row(1)["url"]
        (tmp_path / f"{_digest(url)}.pdf").write_bytes(b"x")
        quote = "1. Se admite parțial contestația nr. 02/739/19."
        monkeypatch.setattr(s44.S43, "read_pdf_pages",
                            lambda p: (["rezumat", quote], ""))
        row = make_row(1, outcome="partially_admitted", quote=quote,
                       page_number="2", text_layer="1")
        res = s44.verify_sample([row], tmp_path)
        assert res["failures"] == 0
        assert res["verdicts"].get("quote_locatable") == 1

    def test_quote_on_wrong_page_is_a_failure(self, tmp_path, monkeypatch):
        url = make_row(1)["url"]
        (tmp_path / f"{_digest(url)}.pdf").write_bytes(b"x")
        quote = "Se admite contestația nr. 01/100/24."
        monkeypatch.setattr(s44.S43, "read_pdf_pages",
                            lambda p: ([quote, "other page"], ""))
        row = make_row(1, outcome="admitted", quote=quote,
                       page_number="2", text_layer="1")
        res = s44.verify_sample([row], tmp_path)
        assert res["failures"] == 1
        item = res["failure_items"][0]
        assert item["verdict"] == "quote_locatable_other_page"
        assert item["located_page"] == 1

    def test_scan_verified_by_fresh_ocr(self, tmp_path, monkeypatch):
        url = make_row(1)["url"]
        (tmp_path / f"{_digest(url)}.pdf").write_bytes(b"x")
        quote = "Se respinge contestația nr. 03/500/21."
        monkeypatch.setattr(s44.S43, "read_pdf_pages", lambda p: ([""], ""))
        monkeypatch.setattr(s44.S43, "ocr_page",
                            lambda pdf, page, n: quote)
        row = make_row(1, outcome="rejected", quote=quote,
                       page_number="1", text_layer="0")
        res = s44.verify_sample([row], tmp_path)
        assert res["failures"] == 0
        assert res["verdicts"].get("quote_locatable_ocr") == 1

    def test_scan_ocr_miss_is_a_warning_not_a_pass(self, tmp_path,
                                                    monkeypatch):
        url = make_row(1)["url"]
        (tmp_path / f"{_digest(url)}.pdf").write_bytes(b"x")
        monkeypatch.setattr(s44.S43, "read_pdf_pages", lambda p: ([""], ""))
        monkeypatch.setattr(s44.S43, "ocr_page", lambda pdf, page, n: "")
        row = make_row(1, outcome="rejected", quote="Se respinge",
                       page_number="1", text_layer="0")
        res = s44.verify_sample([row], tmp_path)
        assert res["failures"] == 0
        assert res["verdicts"].get("manual_visual_check") == 1

    def test_unknown_without_quote_needs_only_structure(self, tmp_path,
                                                         monkeypatch):
        url = make_row(1)["url"]
        (tmp_path / f"{_digest(url)}.pdf").write_bytes(b"x")
        monkeypatch.setattr(s44.S43, "read_pdf_pages",
                            lambda p: (["two", "pages"], ""))
        row = make_row(1, outcome="unknown", quote="", page_number="")
        res = s44.verify_sample([row], tmp_path)
        assert res["failures"] == 0
        assert res["verdicts"].get("no_quote_expected") == 1


# --- main() ------------------------------------------------------------------
class TestMain:
    @staticmethod
    def _sandbox_json(path: Path) -> Path:
        path.write_text(json.dumps({"sandbox_dir": "/nonexistent"}),
                        encoding="utf-8")
        return path

    def test_refuses_without_sandbox(self, tmp_path, monkeypatch):
        rows = make_pool(6)
        csv_path = write_outcomes_csv(rows, tmp_path / "outcomes.csv")
        monkeypatch.setattr(s44, "IN_OUTCOMES", csv_path)
        monkeypatch.setattr(s44, "INV_JSON",
                            self._sandbox_json(tmp_path / "inv.json"))
        monkeypatch.setattr(s44, "OUT_SAMPLE", tmp_path / "sample.csv")
        monkeypatch.setattr(s44, "OUT_JSON", tmp_path / "m.json")
        rc = s44.main(["--quiet"])
        assert rc == 4
        assert not (tmp_path / "sample.csv").exists()

    def test_happy_path_end_to_end(self, tmp_path, monkeypatch):
        rows = make_pool(10)                    # 70 present -> sample = 50
        csv_path = write_outcomes_csv(rows, tmp_path / "outcomes.csv")
        sampled, _ = s44.build_sample(rows, total=50, min_per=3)
        assert len(sampled) == 50
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        for r in sampled:                     # every sampled doc "downloaded"
            (sandbox / f"{_digest(r['url'])}.pdf").write_bytes(b"x")
        monkeypatch.setattr(s44.S43, "read_pdf_pages",
                            lambda p: ([QUOTE], ""))
        monkeypatch.setattr(s44.S43, "ocr_page",
                            lambda pdf, page, n: QUOTE)
        monkeypatch.setattr(s44, "IN_OUTCOMES", csv_path)
        monkeypatch.setattr(s44, "OUT_SAMPLE", tmp_path / "sample.csv")
        monkeypatch.setattr(s44, "OUT_JSON", tmp_path / "m.json")
        rc = s44.main(["--sandbox", str(sandbox), "--quiet"])
        assert rc == 0
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["sample_size"] == 50
        assert payload["verification"]["failures"] == 0
        assert payload["reviewer_fields"].startswith("empty")
        with open(tmp_path / "sample.csv", newline="",
                  encoding="utf-8") as fh:
            data = list(csv.DictReader(fh))
        assert len(data) == 50
        assert all(r["reviewer_outcome"] == "" for r in data)

    def test_verification_failure_exits_6(self, tmp_path, monkeypatch):
        rows = make_pool(6)
        rows[0].update(outcome="admitted", quote="Se admite contestația "
                                                 "nr. 99/99/99.",
                       page_number="1", text_layer="1")
        csv_path = write_outcomes_csv(rows, tmp_path / "outcomes.csv")
        sampled, _ = s44.build_sample(rows, total=50, min_per=3)
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        for r in sampled:
            (sandbox / f"{_digest(r['url'])}.pdf").write_bytes(b"x")
        # blank pages: the quote of rows[0] cannot be located
        monkeypatch.setattr(s44.S43, "read_pdf_pages",
                            lambda p: (["blank text layer"], ""))
        monkeypatch.setattr(s44, "IN_OUTCOMES", csv_path)
        monkeypatch.setattr(s44, "OUT_SAMPLE", tmp_path / "sample.csv")
        monkeypatch.setattr(s44, "OUT_JSON", tmp_path / "m.json")
        rc = s44.main(["--sandbox", str(sandbox), "--quiet"])
        assert rc == 6
        payload = json.loads((tmp_path / "m.json").read_text("utf-8"))
        assert payload["verification"]["failures"] >= 1
        # the sample is still written (it is valid; the failure is reported)
        assert (tmp_path / "sample.csv").exists()
