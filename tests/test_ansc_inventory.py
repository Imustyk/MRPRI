"""MTA-0018 step 2: inventory probe (scripts/42) regression tests.

Pins two things this task depends on:

* ``fetch`` never leaves a TRANSIENT failure of a retried attempt in the
  ``error`` field of a fully fetched document (the concrete bug found in the
  2026-11 full run: 4 rows carried ``error=ConnectionError`` while
  ``format=pdf``, ``bytes>0`` and the file existed in the sandbox);
* the summary/report counts the procedure-level linkage split
  (unambiguous vs ambiguous document->procedure links) required by
  MTA-0018 step 2.

No network: the session is a stub, and the retry backoff sleeps are patched.
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


s42 = _load("42_ansc_decision_inventory.py")


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Retry backoff must not slow the tests down."""
    monkeypatch.setattr(s42.time, "sleep", lambda s: None)


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"",
                 ctype: str = "application/pdf", url: str = "",
                 body_error: Exception | None = None):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self.url = url or f"http://{s42.STORAGE_HOST}/get/x"
        self._body = body
        self._body_error = body_error
        self.closed = False

    def iter_content(self, size):
        if self._body_error is not None:
            raise self._body_error
        yield self._body

    def close(self):
        self.closed = True


class FakeSession:
    """Replays a scripted sequence of exceptions/responses for ``get``."""

    def __init__(self, plan: list):
        self.plan = list(plan)

    def get(self, url, timeout=None, stream=None):
        item = self.plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _blank_pdf_bytes() -> bytes:
    from io import BytesIO

    from pypdf import PdfWriter
    buf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buf)
    return buf.getvalue()


def _log_writer(tmp_path: Path):
    return s42.make_log_writer(tmp_path / "errors.csv")


# --- fetch: error-field hygiene --------------------------------------------
class TestFetchErrorField:
    def test_stale_error_cleared_after_successful_retry(self, tmp_path):
        """A failed attempt followed by a full success must NOT leave the
        transient exception in ``error`` (the bug found in the full run)."""
        pdf = _blank_pdf_bytes()
        session = FakeSession([
            ConnectionError("reset"),
            FakeResponse(body=pdf),
        ])
        out = s42.fetch(session, f"http://{s42.STORAGE_HOST}/get/a",
                        tmp_path, _log_writer(tmp_path))
        assert out["http_status"] == 200
        assert out["format"] == "pdf"
        assert out["error"] == ""            # <-- the regression assertion
        assert out["bytes"] == len(pdf)
        files = list(tmp_path.glob("*.pdf"))
        assert len(files) == 1

    def test_body_failure_keeps_error_and_writes_no_file(self, tmp_path):
        session = FakeSession([
            FakeResponse(body_error=ChunkedEncodingError()),
        ])
        out = s42.fetch(session, f"http://{s42.STORAGE_HOST}/get/b",
                        tmp_path, _log_writer(tmp_path))
        assert out["http_status"] == 200
        assert out["error"] == "ChunkedEncodingError"
        assert out["bytes"] == 0
        assert list(tmp_path.glob("*.pdf")) == []

    def test_terminal_connection_failure_returns_error_without_status(
            self, tmp_path):
        session = FakeSession([ConnectionError("x")]
                              * (s42.MAX_RETRIES + 1))
        out = s42.fetch(session, f"http://{s42.STORAGE_HOST}/get/c",
                        tmp_path, _log_writer(tmp_path))
        assert out["error"] == "ConnectionError"
        assert out["http_status"] is None

    def test_non_200_is_recorded_as_unavailable(self, tmp_path):
        session = FakeSession([FakeResponse(status=400, ctype="")])
        out = s42.fetch(session, f"http://{s42.STORAGE_HOST}/get/d",
                        tmp_path, _log_writer(tmp_path))
        assert out["http_status"] == 400
        assert out["error"] == "http 400"


class ChunkedEncodingError(Exception):
    """Stand-in for requests.exceptions.ChunkedEncodingError (its class name
    is what lands in the error field)."""


# --- summary: procedure-level linkage (MTA-0018 step 2) ---------------------
def _row(ocid: str, url: str, ambiguous: str = "0", status: str = "200",
         fmt: str = "pdf") -> dict:
    return {"ocid": ocid, "url": url, "http_status": status, "format": fmt,
            "link_ambiguous": ambiguous, "needs_ocr": "0",
            "decision_numbers": "", "error": "", "bytes": 1, "chars": 10,
            "letters": 5, "pages": 1, "id_confirmed": "1",
            "content_type": "application/pdf", "year": "2023"}


class TestSummaryLinkage:
    @staticmethod
    def _summary(rows):
        procs = {"procedures_with_complaint_doctype": 2,
                 "expected_from_mta0012": 2, "documents_rows": len(rows),
                 "documents_unique": len(rows),
                 "documents_removed_duplicate": 0,
                 "pn_ocids_aliases_added": 0}
        return s42.build_summary(rows, len(rows), procs, len(rows), "",
                                 Path("/nonexistent"), 1.0)

    def test_all_unambiguous(self):
        rows = [_row("ocds-1", "http://s/get/1"),
                _row("ocds-2", "http://s/get/2")]
        link = self._summary(rows)["linkage"]
        assert link["procedures_unambiguous_link"] == 2
        assert link["procedures_ambiguous_link"] == 0
        assert link["ambiguous_rows_url_on_several_ocids"] == 0

    def test_ambiguous_url_moves_the_procedure(self):
        # one URL shared by two procedures -> both procedures ambiguous
        rows = [_row("ocds-1", "http://s/get/shared", ambiguous="1"),
                _row("ocds-2", "http://s/get/shared", ambiguous="1"),
                _row("ocds-3", "http://s/get/3")]
        link = self._summary(rows)["linkage"]
        assert link["procedures_ambiguous_link"] == 2
        assert link["procedures_unambiguous_link"] == 1

    def test_report_contains_the_linkage_lines(self, tmp_path,
                                               monkeypatch):
        rows = [_row("ocds-1", "http://s/get/1")]
        summary = self._summary(rows)
        monkeypatch.setattr(s42, "OUT_MD", tmp_path / "report.md")
        s42.write_report(summary)
        text = (tmp_path / "report.md").read_text("utf-8")
        assert "однозначно связанных" in text
        assert "неоднозначно связанных" in text

    def test_body_download_failures_are_counted_separately(self):
        # 200 + connection error + 0 bytes = no content received
        rows = [_row("ocds-1", "http://s/get/1"),
                dict(_row("ocds-2", "http://s/get/2"),
                     error="ConnectionError", bytes="0", format=""),
                dict(_row("ocds-3", "http://s/get/3"),
                     error="ChunkedEncodingError", bytes="0", format="")]
        summary = self._summary(rows)
        assert summary["availability"]["available_200"] == 3
        assert summary["availability"]["body_download_failed_0_bytes"] == 2
        # a transient error on a FULLY fetched document (bytes > 0) must not
        # count as a failure - that is the stale-error case
        rows.append(dict(_row("ocds-4", "http://s/get/4"),
                         error="ConnectTimeout", bytes="1234"))
        summary = self._summary(rows)
        assert summary["availability"]["body_download_failed_0_bytes"] == 2


# --- resume semantics -------------------------------------------------------
class TestReadPrevious:
    def test_only_terminal_rows_count_as_done(self, tmp_path):
        path = tmp_path / "inv.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["ocid", "url", "http_status"])
            w.writeheader()
            w.writerow({"ocid": "a", "url": "http://s/get/1",
                        "http_status": "200"})
            w.writerow({"ocid": "b", "url": "http://s/get/2",
                        "http_status": ""})     # never probed -> re-probe
            w.writerow({"ocid": "c", "url": "http://s/get/3",
                        "http_status": "400"})  # terminal -> done
        rows, done = s42.read_previous(path)
        assert len(rows) == 3
        assert done == {"http://s/get/1", "http://s/get/3"}
