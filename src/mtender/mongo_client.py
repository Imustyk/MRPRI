"""MongoDB connection, index creation and small helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient, ReplaceOne, UpdateOne
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import BulkWriteError, PyMongoError

from .config import MONGO_DB_NAME, MONGO_URI
from .mongo_schema import ALL_COLLECTIONS, INDEXES

log = logging.getLogger(__name__)


def make_run_id(prefix: str = "run") -> str:
    """UTC timestamp + short hash so re-runs never collide."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    salt = os.urandom(4).hex()
    return f"{prefix}-{stamp}-{hashlib.sha256(salt.encode()).hexdigest()[:6]}"


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cluster_info(client: MongoClient) -> dict:
    """Topology facts, so callers can prove which MongoDB they are talking to."""
    hello = client.admin.command("hello")
    info = {
        "uri": ", ".join(f"{h}:{p}" for h, p in sorted(client.nodes)) or "not connected",
        "set_name": hello.get("setName"),
        "is_writable_primary": bool(hello.get("isWritablePrimary")),
        "hosts": hello.get("hosts", []),
        "max_wire_version": hello.get("maxWireVersion"),
    }
    if hello.get("setName"):
        try:
            status = client.admin.command("replSetGetStatus")
            info["my_state"] = status.get("myState")
            info["members"] = [
                {"name": m.get("name"), "state": m.get("stateStr")}
                for m in status.get("members", [])
            ]
        except PyMongoError as exc:
            info["repl_status_error"] = str(exc)
    return info


def supports_transactions(client: MongoClient) -> bool:
    """Multi-document transactions need a replica set or a sharded cluster."""
    try:
        hello = client.admin.command("hello")
    except PyMongoError:
        return False
    return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")


def connect(uri: str = MONGO_URI, db_name: str = MONGO_DB_NAME) -> tuple[MongoClient, Database]:
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, tz_aware=True)
    client.admin.command("ping")
    return client, client[db_name]


def ensure_indexes(db: Database, prune: bool = True) -> dict[str, list[str]]:
    """Create the declared indexes. Returns {collection: [index names]}.

    ``prune=True`` also drops indexes on the managed collections that
    ``mongo_schema.INDEXES`` no longer declares. Without it a renamed or removed
    declaration leaves its old index behind, and an index over a field no
    document carries is not merely useless: it makes ``explain()`` claim the
    query is served by an index when in fact every entry is a single null.
    """
    created: dict[str, list[str]] = {}
    for coll_name, specs in INDEXES.items():
        coll: Collection = db[coll_name]
        names = []
        for name, fields, options in specs:
            keys = [(f, ASCENDING if d == 1 else DESCENDING) for f, d in fields]
            try:
                coll.create_index(keys, name=name, **options)
                names.append(name)
            except PyMongoError as exc:
                log.warning("index %s on %s failed: %s", name, coll_name, exc)
        if prune:
            declared = {name for name, _, _ in specs} | {"_id_"}
            try:
                for name in set(coll.index_information()) - declared:
                    coll.drop_index(name)
                    log.info("dropped undeclared index %s on %s", name, coll_name)
            except PyMongoError as exc:
                log.warning("pruning indexes on %s failed: %s", coll_name, exc)
        created[coll_name] = names
    return created


#: ``upsert_many`` batches. A full-history run writes millions of documents, so
#: the batch size is the main throughput knob against the server.
UPSERT_BATCH = 1000

_DUPLICATE_KEY = 11000


def upsert_many(
    db: Database,
    coll_name: str,
    docs: list[dict[str, Any]],
    key: str | list[str] = "ocid",
    immutable: bool = False,
) -> tuple[int, int]:
    """Idempotent bulk write. Returns ``(inserted, skipped)``.

    ``key`` is a field name or a list of field names forming a composite key.
    ``immutable=True`` refuses to overwrite an existing document, so a re-run of
    the ingestion cannot silently mutate stored raw data.

    Documents are sent as one unordered ``bulk_write`` per
    ``UPSERT_BATCH``-sized chunk instead of one round trip per document, which
    is what makes a full-history ingest finish in minutes rather than hours.
    Every operation either upserts or matches, so ``skipped`` is derived from the
    upsert count rather than counted separately.
    """
    coll: Collection = db[coll_name]
    fields = [key] if isinstance(key, str) else list(key)
    ops: list = []
    null_key = 0
    for doc in docs:
        if any(doc.get(f) is None for f in fields):
            null_key += 1
            continue
        selector = {f: doc[f] for f in fields}
        if immutable:
            ops.append(UpdateOne(selector, {"$setOnInsert": doc}, upsert=True))
        else:
            ops.append(ReplaceOne(selector, doc, upsert=True))

    inserted = 0
    for start in range(0, len(ops), UPSERT_BATCH):
        chunk = ops[start : start + UPSERT_BATCH]
        try:
            inserted += coll.bulk_write(chunk, ordered=False).upserted_count
        except BulkWriteError as exc:
            details = exc.details or {}
            inserted += details.get("nUpserted", 0)
            # The same key twice inside one unordered batch races on insert and
            # comes back as a duplicate key error. Sequentially it would simply
            # have matched, so it counts as skipped, not as a failure.
            for err in details.get("writeErrors", []):
                if err.get("code") == _DUPLICATE_KEY:
                    continue
                log.warning(
                    "bulk write on %s: %s", coll_name, err.get("errmsg", err)
                )
    return inserted, len(ops) + null_key - inserted


def collection_stats(db: Database) -> list[dict[str, Any]]:
    out = []
    for name in ALL_COLLECTIONS:
        if name not in db.list_collection_names():
            continue
        try:
            info = db.command("collStats", name)
        except PyMongoError:
            continue
        out.append(
            {
                "collection": name,
                "documents": info.get("count", 0),
                "size_bytes": info.get("size", 0),
                "storage_bytes": info.get("storageSize", 0),
                "indexes": sorted(info.get("indexSizes", {})),
                "total_index_bytes": sum(info.get("indexSizes", {}).values()),
            }
        )
    return out
