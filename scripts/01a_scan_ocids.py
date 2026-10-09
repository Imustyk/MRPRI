"""Step 01a - walk the entire OCID history and store the inventory.

This is the enumeration step. The list endpoint is paginated by date cursor, so
the whole 2018->present history is reachable; this script records every OCID
with its list date and writes it both to MongoDB (``raw_releases``) and to a
JSONL file, so a re-run can resume from the last cursor.

The inventory is append-only and restartable: an interrupted run loses nothing.
Re-running the script resumes from the last cursor in the inventory file and
skips OCIDs already recorded, so a crash never rewrites or duplicates history.

Usage:
    .venv/bin/python scripts/01a_scan_ocids.py
    .venv/bin/python scripts/01a_scan_ocids.py --max-pages 20
    .venv/bin/python scripts/01a_scan_ocids.py --fresh   # discard and rescan
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.api_client import MTenderClient  # noqa: E402
from src.mtender.config import (  # noqa: E402
    DATA_RAW,
    MAX_LIMIT,
    MONGO_DB_NAME,
    MTENDER_BASE,
    RESULTS,
)
from src.mtender.mongo_client import connect, ensure_indexes, make_run_id, upsert_many, utcnow_iso  # noqa: E402
from src.mtender.mongo_schema import INGEST_RUNS, RAW_LOOKUPS, RAW_RELEASES  # noqa: E402

log = logging.getLogger("scan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=10**9)
    ap.add_argument("--out", default=str(DATA_RAW / "ocid_inventory.jsonl"))
    ap.add_argument("--no-mongo", action="store_true")
    ap.add_argument(
        "--fresh",
        action="store_true",
        help="truncate the inventory and rescan from the beginning",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_id = make_run_id("scan")
    started = utcnow_iso()
    out_path = Path(args.out)
    client = MTenderClient(MTENDER_BASE)

    # Resume support. The date cursor is inclusive, so restarting on the last
    # recorded date replays that page; ``seen`` drops the overlap so the JSONL
    # never gains a duplicate line and the counters stay truthful.
    seen: set[str] = set()
    start_cursor: str | None = None
    if out_path.exists() and not args.fresh:
        with out_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    # a torn final line from a killed process: stop here and keep
                    # everything before it
                    log.warning("truncated inventory line ignored: %.60s", line)
                    break
                ocid = row.get("ocid")
                if not ocid:
                    continue
                seen.add(ocid)
                date = row.get("list_date")
                if date and (start_cursor is None or date > start_cursor):
                    start_cursor = date
        if seen:
            log.info(
                "resuming after %s ocids, cursor=%s (use --fresh to rescan)",
                f"{len(seen):,}",
                start_cursor,
            )

    db = None
    if not args.no_mongo:
        _, db = connect()
        ensure_indexes(db)

    t0 = time.time()
    already = len(seen)
    total = already
    pages = 0
    batch: list[dict] = []
    mode = "w" if args.fresh else "a"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open(mode, encoding="utf-8") as fh:
        stream = client.iter_ocids(
            limit=MAX_LIMIT, start=start_cursor, max_pages=args.max_pages
        )
        for ocid, date in stream:
            if ocid in seen:
                continue
            seen.add(ocid)
            doc = {
                "ocid": ocid,
                "list_date": date,
                "source": f"{MTENDER_BASE}/tenders/",
                "run_id": run_id,
                "fetched_at": started,
            }
            batch.append(doc)
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
            total += 1
            if len(batch) >= MAX_LIMIT:
                if db is not None:
                    upsert_many(db, RAW_RELEASES, batch, key="ocid", immutable=True)
                pages += 1
                batch.clear()
                if pages % 20 == 0:
                    rate = (total - already) / max(time.time() - t0, 1e-9)
                    log.info("%s ocids (%s pages, %.0f/s)", f"{total:,}", pages, rate)
        fh.flush()
    if db is not None and batch:
        upsert_many(db, RAW_RELEASES, batch, key="ocid", immutable=True)

    elapsed = time.time() - t0
    summary = {
        "run_id": run_id,
        "stage": "scan_ocids",
        "started_at": started,
        "finished_at": utcnow_iso(),
        "elapsed_seconds": round(elapsed, 1),
        "ocids": total,
        "ocids_resumed_from_file": already,
        "ocids_added_this_run": total - already,
        "resumed": bool(already) and not args.fresh,
        "start_cursor": start_cursor,
        "pages": pages,
        "page_limit": MAX_LIMIT,
        "endpoint": f"{MTENDER_BASE}/tenders/",
        "inventory_file": str(out_path),
    }
    if db is not None:
        db[RAW_LOOKUPS].update_one(
            {"key": f"scan:{run_id}"}, {"$set": summary}, upsert=True
        )
        db[INGEST_RUNS].insert_one(dict(summary))
    (RESULTS / "mongo").mkdir(parents=True, exist_ok=True)
    (RESULTS / "mongo" / "scan_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
