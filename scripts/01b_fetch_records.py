"""Step 01b - fetch OCDS packages for inventoried OCIDs into MongoDB.

Reads ``data/raw/ocid_inventory.jsonl`` (produced by ``01a_scan_ocids.py``),
downloads each OCDS 1.1 package, flattens it with ``src.mtender.ocds`` and
stores it in ``raw_tenders`` / ``raw_parties`` / ``raw_releases``.

``raw_tenders`` and ``raw_parties`` are written with ``$setOnInsert`` (never
overwritten), so re-running this script cannot mutate already stored raw data.

A full-history run is hundreds of thousands of HTTP requests, so the script is
resumable: every response is checkpointed into ``raw_releases`` as it is
written, and an OCID that is already marked ``record_fetched`` is not requested
again. Killing the process (or the machine) costs at most the requests that were
in flight, and restarting continues where it stopped. Use ``--no-skip-fetched``
to force every inventoried OCID to be requested again.

Usage:
    .venv/bin/python scripts/01b_fetch_records.py --limit 5000
    .venv/bin/python scripts/01b_fetch_records.py --limit 5000 --since 2024-01-01
    .venv/bin/python scripts/01b_fetch_records.py --archive --concurrency 8
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import signal
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from pymongo import UpdateOne

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.api_client import MTenderClient, MTenderUnavailable  # noqa: E402
from src.mtender.config import (  # noqa: E402
    DATA_RAW,
    INGEST_CONCURRENCY,
    MTENDER_BASE,
    RESULTS,
)
from src.mtender.mongo_client import connect, ensure_indexes, make_run_id, upsert_many, utcnow_iso  # noqa: E402
from src.mtender.mongo_schema import (  # noqa: E402
    INGEST_RUNS,
    RAW_PARTIES,
    RAW_RELEASES,
    RAW_TENDERS,
)
from src.mtender.ocds import extract_parties, extract_tender  # noqa: E402

log = logging.getLogger("fetch")
PACKAGES_DIR = DATA_RAW / "ocds_packages"

BATCH = 200
#: A party is unique per procurement *and* role, not per procurement.
PARTY_KEY = "party_key"


def humanize(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:d}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes:d}m{secs:02d}s"


def settled_ocids(db, retry_empty: bool) -> set[str]:
    """OCIDs already accounted for, so a resumed run does not re-request them.

    A successful response is checkpointed as ``record_fetched``; a response with
    no records is checkpointed as ``record_empty``. Errors are deliberately not
    checkpointed, so a failed request is retried on the next run.
    """
    query: dict = (
        {"$or": [{"record_fetched": True}, {"record_empty": True}]}
        if retry_empty
        else {"record_fetched": True}
    )
    return {d["ocid"] for d in db[RAW_RELEASES].find(query, {"ocid": 1, "_id": 0})}


def load_inventory(
    path: Path,
    limit: int | None,
    since: str | None,
    done: set[str] | None = None,
) -> tuple[list[dict], int]:
    """Inventory rows still needing a request, plus how many were skipped.

    ``limit`` counts OCIDs that still have to be fetched, not rows read, so
    ``--limit 500`` on a resumed database means 500 *new* packages.
    """
    rows: list[dict] = []
    skipped = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            if since and (doc.get("list_date") or "") < since:
                continue
            if done is not None and doc.get("ocid") in done:
                skipped += 1
                continue
            rows.append(doc)
            if limit and len(rows) >= limit:
                break
    return rows, skipped


def archive_package(ocid: str, package: dict) -> None:
    """Write the response body to ``data/raw/ocds_packages/<ocid>.json.gz``.

    The stored tender document is already a *projection* of the package, so on
    its own it cannot rebuild the raw layer. Archiving the untouched body is what
    makes "rebuild the database from the raw files" possible. Writes are skipped
    when the file already exists, so re-running is cheap and idempotent.
    """
    path = PACKAGES_DIR / f"{ocid}.json.gz"
    if path.exists():
        return
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    # with_suffix() would replace ".gz" and produce "...json.json.gz.tmp".
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(package, fh, ensure_ascii=False)
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default=str(DATA_RAW / "ocid_inventory.jsonl"))
    ap.add_argument(
        "--archive",
        action="store_true",
        help="also store each untouched response body under data/raw/ocds_packages/",
    )
    ap.add_argument("--limit", type=int, default=None, help="max OCIDs to fetch")
    ap.add_argument("--since", default=None, help="only OCIDs with list_date >= this ISO date")
    ap.add_argument("--concurrency", type=int, default=INGEST_CONCURRENCY)
    ap.add_argument(
        "--no-skip-fetched",
        dest="skip_fetched",
        action="store_false",
        help="request every inventoried OCID again instead of resuming",
    )
    ap.add_argument(
        "--retry-empty",
        action="store_true",
        help="also re-request OCIDs whose record came back without records",
    )
    ap.add_argument(
        "--progress-every",
        type=float,
        default=30.0,
        help="seconds between throughput/ETA log lines",
    )
    ap.add_argument("--out", default=str(RESULTS / "mongo" / "fetch_summary.json"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_id = make_run_id("fetch")
    started = utcnow_iso()
    client = MTenderClient(MTENDER_BASE)
    _, db = connect()
    ensure_indexes(db)

    already = settled_ocids(db, args.retry_empty) if args.skip_fetched else set()
    inventory, skipped_already = load_inventory(
        Path(args.inventory), args.limit, args.since, already or None
    )
    log.info(
        "inventory slice: %s ocids to fetch (%s already settled, %s matched --since/--limit)",
        f"{len(inventory):,}",
        f"{len(already):,}",
        f"{skipped_already:,}",
    )
    if not inventory:
        log.info("nothing to fetch: every matching OCID is already stored")

    stop = threading.Event()

    def request_stop(signum, _frame) -> None:
        log.warning(
            "signal %s received: no new requests will be started, "
            "in-flight ones are checkpointed before exit",
            signum,
        )
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)

    t0 = time.time()
    stats = {
        "requested": len(inventory),
        "ok": 0,
        "empty": 0,
        "error": 0,
        "already_settled": len(already),
        "skipped_by_filter": skipped_already,
    }
    errors: dict[str, int] = {}
    tender_batch: list[dict] = []
    party_batch: list[dict] = []
    marker_batch: list[dict] = []

    def flush() -> None:
        """Persist the buffered batch *and* its checkpoint before continuing.

        Checkpointing together with the data is what makes a resume correct: a
        crash can never leave a response fetched but unmarked, which would make
        the next run request it a second time.
        """
        nonlocal tender_batch, party_batch, marker_batch
        if tender_batch:
            upsert_many(db, RAW_TENDERS, tender_batch, key="ocid", immutable=True)
        if party_batch:
            upsert_many(db, RAW_PARTIES, party_batch, key=PARTY_KEY, immutable=True)
        if marker_batch:
            db[RAW_RELEASES].bulk_write(
                [
                    UpdateOne({"ocid": m["ocid"]}, {"$set": m}, upsert=True)
                    for m in marker_batch
                ],
                ordered=False,
            )
        tender_batch, party_batch, marker_batch = [], [], []

    def work(item: dict) -> tuple[str, dict | None, list[dict], dict | None]:
        ocid, list_date = item["ocid"], item.get("list_date")
        try:
            package = client.fetch_record(ocid)
        except MTenderUnavailable:
            return ("error", None, [], None)
        if not package or not package.get("records"):
            return ("empty", None, [], {"ocid": ocid, "record_empty": True, "fetch_run_id": run_id})
        if args.archive:
            # Store the exact response body, so the whole database can be rebuilt
            # without touching the API again (scripts/seed_mongo.py).
            archive_package(ocid, package)
        doc = extract_tender(ocid, package, list_date)
        doc["run_id"] = run_id
        doc["fetched_at"] = started
        parties = extract_parties(doc)
        for p in parties:
            p["run_id"] = run_id
        marker = {
            "ocid": doc["ocid"],
            "record_fetched": True,
            "n_records": doc.get("n_records", 0),
            "fetch_run_id": run_id,
        }
        return ("ok", doc, parties, marker)

    done = 0
    interrupted = False
    # Bounded window instead of one future per OCID: a full-history inventory is
    # hundreds of thousands of rows, and submitting them all up front would hold
    # every request in memory at once.
    window = max(args.concurrency * 8, 32)
    with ThreadPoolExecutor(args.concurrency) as pool:
        source = iter(inventory)
        pending: set = set()
        exhausted = False

        def submit_one() -> None:
            nonlocal exhausted
            if exhausted or stop.is_set():
                return
            try:
                item = next(source)
            except StopIteration:
                exhausted = True
                return
            pending.add(pool.submit(work, item))

        for _ in range(window):
            submit_one()
            if exhausted:
                break

        reported = time.time()
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                status, doc, parties, marker = fut.result()
                stats[status] = stats.get(status, 0) + 1
                if status == "error":
                    errors["fetch_failed"] = errors.get("fetch_failed", 0) + 1
                if doc:
                    tender_batch.append(doc)
                    party_batch.extend(parties)
                if marker:
                    marker_batch.append(marker)
                done += 1
                if len(tender_batch) >= BATCH:
                    flush()
                submit_one()
            if time.time() - reported >= args.progress_every:
                reported = time.time()
                rate = done / max(time.time() - t0, 1e-9)
                left = len(inventory) - done
                log.info(
                    "fetched %s/%s (%.0f/s) eta %s",
                    f"{done:,}",
                    f"{len(inventory):,}",
                    rate,
                    humanize(left / rate) if rate else "unknown",
                )

    interrupted = stop.is_set()
    flush()
    if interrupted:
        log.warning("interrupted: checkpoint written, re-run to resume")
    elapsed = time.time() - t0
    summary = {
        "run_id": run_id,
        "stage": "fetch_records",
        "started_at": started,
        "finished_at": utcnow_iso(),
        "elapsed_seconds": round(elapsed, 1),
        "concurrency": args.concurrency,
        "since": args.since,
        "limit": args.limit,
        "interrupted": interrupted,
        "endpoint": f"{MTENDER_BASE}/tenders/{{ocid}}",
        **stats,
        "errors": errors,
        "stored": {
            RAW_TENDERS: db[RAW_TENDERS].count_documents({}),
            RAW_PARTIES: db[RAW_PARTIES].count_documents({}),
            RAW_RELEASES: db[RAW_RELEASES].count_documents({}),
        },
    }
    db[INGEST_RUNS].insert_one(dict(summary))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
