"""Step 00 - verify the live MTender API and the local MongoDB deployment.

Prints a factual report: every URL is really requested, and non-200 or
empty-body responses are reported as failures rather than hidden.

Usage:
    .venv/bin/python scripts/00_check_api.py
    .venv/bin/python scripts/00_check_api.py --mongo
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.api_client import MTenderClient, MTenderUnavailable  # noqa: E402
from src.mtender.config import (  # noqa: E402
    MAX_LIMIT,
    MONGO_DB_NAME,
    MONGO_URI,
    MTENDER_BASE,
    RESULTS,
)

CHECKS: list[dict] = []


def record(name: str, url: str, ok: bool, detail: str, extra: dict | None = None) -> None:
    CHECKS.append({"check": name, "url": url, "ok": ok, "detail": detail, **(extra or {})})


def check_ocid_list(client: MTenderClient) -> None:
    url = f"{MTENDER_BASE}/tenders/?limit=5"
    try:
        payload = client.fetch_page(5, None)
    except MTenderUnavailable as exc:
        record("ocid_list", url, False, str(exc))
        return
    rows = payload.get("data") or []
    record(
        "ocid_list",
        url,
        bool(rows),
        f"HTTP 200, {len(rows)} ocids, next offset={payload.get('offset')}",
        {"sample": rows[:2]},
    )


def check_cursor_pagination(client: MTenderClient) -> None:
    url = f"{MTENDER_BASE}/tenders/?limit=2&offset={{cursor}}"
    try:
        first = client.fetch_page(2, None)
        cursor = first.get("offset")
        if not cursor:
            record("cursor_pagination", url, False, "no offset returned")
            return
        second = client.fetch_page(2, cursor)
    except MTenderUnavailable as exc:
        record("cursor_pagination", url, False, str(exc))
        return
    a = [r["ocid"] for r in first.get("data") or []]
    b = [r["ocid"] for r in second.get("data") or []]
    ok = bool(b) and not set(a).intersection(b)
    record(
        "cursor_pagination",
        url,
        ok,
        f"page1={a} page2={b} cursor={cursor}",
        {"overlap": sorted(set(a) & set(b))},
    )


def check_limit_cap(client: MTenderClient) -> None:
    """The documented cap: request far more than allowed and see what arrives."""
    requested = 5000
    url = f"{MTENDER_BASE}/tenders/?limit={requested}"
    # Deliberately bypasses the client-side guard: we want the server's own answer.
    last = "no attempt"
    payload: dict = {}
    for _ in range(6):
        resp = client.session.get(url, timeout=60)
        last = f"HTTP {resp.status_code}, {len(resp.content)} bytes"
        if resp.status_code == 200 and resp.content:
            payload = resp.json()
            break
    if not payload:
        record("limit_cap", url, False, f"unusable after retries: {last}")
        return
    n = len(payload.get("data") or [])
    record(
        "limit_cap",
        url,
        n > 0,
        f"requested {requested}, server returned {n} (code cap={MAX_LIMIT})",
        {"returned": n, "configured_cap": MAX_LIMIT},
    )


def check_bad_cursor(client: MTenderClient) -> None:
    """A numeric offset is NOT valid; the API answers 500 with an empty body."""
    url = f"{MTENDER_BASE}/tenders/?offset=0"
    try:
        resp = client.session.get(url, timeout=30)
        record(
            "numeric_offset_rejected",
            url,
            resp.status_code >= 400,
            f"HTTP {resp.status_code}, {len(resp.content)} bytes (confirms cursor-only pagination)",
        )
    except Exception as exc:  # noqa: BLE001
        record("numeric_offset_rejected", url, False, f"{type(exc).__name__}: {exc}")


def check_ocds_record(client: MTenderClient) -> None:
    try:
        page = client.fetch_page(3, None)
    except MTenderUnavailable as exc:
        record("ocds_record", f"{MTENDER_BASE}/tenders/{{ocid}}", False, str(exc))
        return
    rows = page.get("data") or []
    if not rows:
        record("ocds_record", f"{MTENDER_BASE}/tenders/{{ocid}}", False, "no ocid to test")
        return
    ocid, date = rows[0]["ocid"], rows[0].get("date")
    url = f"{MTENDER_BASE}/tenders/{ocid}"
    try:
        package = client.fetch_record(ocid)
    except MTenderUnavailable as exc:
        record("ocds_record", url, False, str(exc))
        return
    records = package.get("records") or []
    tags = sorted({t for r in records for t in ((r.get("compiledRelease") or {}).get("tag") or [])})
    record(
        "ocds_record",
        url,
        bool(records),
        f"OCDS {package.get('version')}, {len(records)} records, tags={tags}, list date={date}",
        {
            "ocid": ocid,
            "package_keys": sorted(package),
            "publisher": package.get("publisher"),
            "extensions": package.get("extensions"),
        },
    )

    suffixed = f"{ocid}-PN-{ocid.rsplit('-', 1)[-1]}"
    surl = f"{MTENDER_BASE}/tenders/{suffixed}"
    sresp = client.session.get(surl, timeout=30)
    record(
        "suffixed_ocid_returns_empty",
        surl,
        sresp.status_code == 200 and sresp.content.strip() in (b"{}", b""),
        f"HTTP {sresp.status_code}, body={sresp.content[:40]!r} (base OCID is required)",
    )


def check_history_depth(client: MTenderClient) -> None:
    """Confirm how far back the list goes, using two explicit cursors."""
    spans = {}
    for label, cursor in (
        ("2018-10-18", "2018-10-18T00:00:00Z"),
        ("2020-01-01", "2020-01-01T00:00:00Z"),
        ("2023-01-01", "2023-01-01T00:00:00Z"),
        ("2026-01-01", "2026-01-01T00:00:00Z"),
    ):
        # cursor is the request itself; only the response is recorded below.
        try:
            payload = client.fetch_page(1, cursor)
        except MTenderUnavailable as exc:
            spans[label] = f"unavailable: {exc}"
            continue
        rows = payload.get("data") or []
        spans[label] = rows[0]["date"] if rows else "no rows"
    record(
        "historical_coverage",
        f"{MTENDER_BASE}/tenders/?limit=1&offset={{date}}",
        all(isinstance(v, str) and v.startswith("20") for v in spans.values()),
        "; ".join(f"cursor {k} -> {v}" for k, v in spans.items()),
    )


def check_mongo() -> None:
    from src.mtender.mongo_client import connect
    from src.mtender.mongo_schema import ALL_COLLECTIONS

    try:
        client, db = connect()
    except Exception as exc:  # noqa: BLE001
        record("mongodb", MONGO_URI, False, f"{type(exc).__name__}: {exc}")
        return
    info = client.server_info()
    record(
        "mongodb",
        MONGO_URI,
        True,
        f"server {info.get('version')}, database '{db.name}', existing collections={db.list_collection_names()}",
        {"uri_sanitized": MONGO_URI.replace("//", "//***@") if "@" in MONGO_URI else MONGO_URI},
    )
    record("mongodb_declared_collections", MONGO_DB_NAME, True, ", ".join(ALL_COLLECTIONS))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo", action="store_true", help="also check the local MongoDB")
    ap.add_argument("--out", default=str(RESULTS / "api_verification.json"))
    args = ap.parse_args()

    print("=" * 78)
    print("MTender API verification -", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    print("=" * 78)

    client = MTenderClient(MTENDER_BASE)
    check_ocid_list(client)
    check_cursor_pagination(client)
    check_limit_cap(client)
    check_bad_cursor(client)
    check_ocds_record(client)
    check_history_depth(client)
    if args.mongo:
        check_mongo()

    width = max(len(c["check"]) for c in CHECKS)
    for c in CHECKS:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"[{mark}] {c['check']:<{width}}  {c['detail']}")
        if c.get("sample"):
            print(f"       sample: {json.dumps(c['sample'], ensure_ascii=False)}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "base_url": MTENDER_BASE, "checks": CHECKS}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nreport written to {out}")
    failed = [c["check"] for c in CHECKS if not c["ok"]]
    print("FAILED:", ", ".join(failed) if failed else "none")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
