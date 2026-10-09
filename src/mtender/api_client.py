"""HTTP client for the MTender OCDS API, using only verified endpoints.

Verified 2026-09-26 (see docs/API_INVESTIGATION_REPORT.md):

* ``GET /tenders/?limit={1..300}`` -> OCID list page.
* ``GET /tenders/?limit={n}&offset={ISO-8601}`` -> next page. ``offset`` is a
  *date cursor*, not a row number. A numeric ``offset`` makes the server return
  HTTP 500 with an empty body.
* ``GET /tenders/{base_ocid}`` -> OCDS 1.1 package for one procurement.

Known failure modes observed and handled here:
* the list endpoint intermittently answers HTTP 200 with an empty body;
* an out-of-range / malformed cursor answers HTTP 500 with an empty body.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone

import requests

from .config import (
    HTTP_TIMEOUT,
    LIST_MAX_RETRIES,
    LIST_PATH,
    MAX_LIMIT,
    RECORD_MAX_RETRIES,
    RECORD_PATH,
    REQUEST_PAUSE_SECONDS,
    USER_AGENT,
)

log = logging.getLogger(__name__)


class MTenderUnavailable(RuntimeError):
    """Raised when an endpoint stays unusable after all retries."""


def _to_cursor(value: str | datetime | None) -> str | None:
    """Render a cursor in the exact format the API emits: ``...T..:..:...000Z``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return f"{value}.000Z"
    text = str(value).strip()
    if text.endswith("Z") and "." in text:
        return text
    if text.endswith("Z"):
        return f"{text[:-1]}.000Z"
    return f"{text}.000Z"


class MTenderClient:
    def __init__(self, base_url: str, session: requests.Session | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    # -- low level ---------------------------------------------------------

    def _get(self, path: str, params: dict | None, max_retries: int) -> requests.Response:
        url = f"{self.base_url}{path}"
        last: str = "no attempt"
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=HTTP_TIMEOUT)
            except requests.RequestException as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200 and resp.content:
                    return resp
                last = f"HTTP {resp.status_code}, {len(resp.content)} bytes"
                if resp.status_code == 404:
                    raise MTenderUnavailable(f"{url} -> HTTP 404 (no such resource)")
            wait = min(2 ** (attempt - 1), 20)
            log.warning("GET %s failed (%s); retry %s/%s in %ss", url, last, attempt, max_retries, wait)
            time.sleep(wait)
        raise MTenderUnavailable(f"{url} unusable after {max_retries} attempts: {last}")

    # -- endpoints ---------------------------------------------------------

    def fetch_page(self, limit: int, cursor: str | None) -> dict:
        """One page of the OCID list. Raises if the server cannot serve it."""
        if limit > MAX_LIMIT:
            raise ValueError(f"limit={limit} exceeds the measured server cap of {MAX_LIMIT}")
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["offset"] = _to_cursor(cursor)
        return self._get(LIST_PATH, params, LIST_MAX_RETRIES).json()

    def iter_ocids(
        self,
        limit: int = MAX_LIMIT,
        start: str | datetime | None = None,
        max_pages: int | None = None,
        stop_when_empty: bool = True,
    ) -> Iterator[tuple[str, str]]:
        """Yield ``(ocid, date)`` walking the whole history via date cursors.

        The API returns records in ascending ``date`` order and hands back the
        cursor for the next page, so this is a complete, restartable scan.
        """
        cursor = _to_cursor(start)
        seen: set[str] = set()
        for page in range(max_pages or 10**9):
            payload = self.fetch_page(limit, cursor)
            rows = payload.get("data") or []
            if not rows:
                if stop_when_empty:
                    return
                raise MTenderUnavailable("empty page while stop_when_empty=False")
            for row in rows:
                ocid = row.get("ocid")
                if not ocid or ocid in seen:
                    continue
                seen.add(ocid)
                yield ocid, row.get("date") or ""
            nxt = payload.get("offset")
            if not nxt or nxt == cursor:
                return
            cursor = nxt
            if REQUEST_PAUSE_SECONDS:
                time.sleep(REQUEST_PAUSE_SECONDS)
            log.info("page %s: %s ocids, cursor=%s", page + 1, len(rows), cursor)
        log.warning("stopped at max_pages=%s", max_pages)

    def fetch_record(self, ocid: str) -> dict:
        """The OCDS 1.1 package for one procurement.

        The base OCID is required. Passing a suffixed OCID (e.g.
        ``...-PN-...``) returns HTTP 200 with ``{}`` rather than an error.
        """
        return self._get(RECORD_PATH.format(ocid=ocid), None, RECORD_MAX_RETRIES).json()
