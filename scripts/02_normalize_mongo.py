"""Step 02 - normalise raw_tenders/raw_parties and write a validation report.

Produces ``norm_tenders`` and ``norm_parties`` plus a ``validation_reports``
document, so every number later in the thesis can be traced to a stored report.

Both raw collections are streamed in chunks rather than read into a list: a
full-history ingest holds hundreds of thousands of documents whose nested
``bids``/``awards``/``contracts`` arrays decode to several times their BSON size,
which does not fit in memory. Only one chunk plus the party dedup keys are ever
resident.

Usage:
    .venv/bin/python scripts/02_normalize_mongo.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import RESULTS  # noqa: E402
from src.mtender.mongo_client import (  # noqa: E402
    connect,
    collection_stats,
    ensure_indexes,
    make_run_id,
    upsert_many,
    utcnow_iso,
)
from src.mtender.mongo_schema import (  # noqa: E402
    NORM_PARTIES,
    NORM_TENDERS,
    RAW_PARTIES,
    RAW_TENDERS,
    VALIDATION_REPORTS,
)
from src.mtender.normalize import normalize_party, normalize_tender, validation_report  # noqa: E402

#: Documents normalised per round trip. Large enough to amortise the write cost,
#: small enough that the decoded chunk stays far below the memory ceiling.
CHUNK = 2000


def chunks(cursor, size: int = CHUNK) -> Iterator[list[dict[str, Any]]]:
    """Yield decoded documents ``size`` at a time, without buffering the cursor."""
    batch: list[dict[str, Any]] = []
    for doc in cursor:
        batch.append(doc)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def main() -> int:
    _, db = connect()
    ensure_indexes(db)
    run_id = make_run_id("norm")
    started = utcnow_iso()

    ins_t = skip_t = ins_p = skip_p = 0
    n_raw_tenders = n_raw_parties = 0
    # The report and the dedup set are the only things that grow with the corpus.
    norm_tenders: list[dict] = []
    seen: set[str] = set()
    t_start = time.time()

    for batch in chunks(db[RAW_TENDERS].find({}, {"_id": 0})):
        n_raw_tenders += len(batch)
        for raw in batch:
            doc = normalize_tender(raw)
            if doc.get("ocid"):
                norm_tenders.append(doc)
        if len(norm_tenders) >= CHUNK:
            a, b = upsert_many(db, NORM_TENDERS, norm_tenders, key="ocid")
            ins_t += a
            skip_t += b
            norm_tenders = []
            print(f"  normalised {n_raw_tenders:,} raw tenders", flush=True)
    if norm_tenders:
        a, b = upsert_many(db, NORM_TENDERS, norm_tenders, key="ocid")
        ins_t += a
        skip_t += b

    # norm_parties is a derived layer: it is rebuilt from scratch so a party that
    # disappeared from the raw layer cannot survive here.
    #
    # The collection is keyed by (ocid, role, party), never by ocid alone: one
    # procurement has a buyer, several suppliers and several tenderers, so an
    # upsert keyed on ocid would keep only the last party of each batch. The
    # `seen` set already enforces that uniqueness across the whole corpus, so the
    # rows are appended in chunks.
    db[NORM_PARTIES].delete_many({})
    for batch in chunks(db[RAW_PARTIES].find({}, {"_id": 0})):
        n_raw_parties += len(batch)
        rows: list[dict] = []
        for raw in batch:
            party = normalize_party(raw)
            ident = party.get("identifier") or party.get("id") or party.get("name")
            if not ident or not party.get("ocid"):
                continue
            key = f"{party['ocid']}|{party['role']}|{ident}"
            if key in seen:
                skip_p += 1
                continue
            seen.add(key)
            rows.append(party)
        if rows:
            db[NORM_PARTIES].insert_many(rows, ordered=False)
            ins_p += len(rows)
        if n_raw_parties % (CHUNK * 25) < CHUNK:
            print(
                f"  parties {n_raw_parties:,} -> {ins_p:,} kept "
                f"({time.time() - t_start:.0f}s)",
                flush=True,
            )

    report = validation_report(
        db[NORM_TENDERS].find({}, {"_id": 0}),
        db[NORM_PARTIES].find({}, {"_id": 0}),
    )
    report.update(
        {
            "run_id": run_id,
            "generated_at": started,
            "source": {RAW_TENDERS: n_raw_tenders, RAW_PARTIES: n_raw_parties},
            "written": {NORM_TENDERS: ins_t, NORM_PARTIES: ins_p},
            "skipped": {NORM_TENDERS: skip_t, NORM_PARTIES: skip_p},
        }
    )
    db[VALIDATION_REPORTS].insert_one(dict(report))

    out = RESULTS / "validation_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("\ncollection stats:")
    for row in collection_stats(db):
        print(f"  {row['collection']:<22} docs={row['documents']:>8,}  "
              f"size={row['size_bytes']/1e6:.1f}MB  idx={[i for i in row['indexes'] if i != '_id_']}")
    print(f"\nreport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
