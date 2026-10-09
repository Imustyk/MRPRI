"""Step 11 - load the AAP prohibition list into MongoDB.

The Agenția Achiziții Publice publishes the "Lista de interdicție" as an HTML
table of decisions. The snapshot in ``data/raw/blacklist/`` is kept as a file,
which makes it usable but not queryable: nothing in MongoDB knows that a
supplier is prohibited, so no aggregation can join against it.

This stage stores the entries in ``raw_blacklist`` and adds ``name_key``, the
folded comparison key from ``src.mtender.names``. With that key the join against
``norm_parties`` is a plain equality lookup in the database, and
``scripts/09_external_validation.py`` reports what the detectors said about every
matched supplier.

**The limitation is structural and is not worked around here** (spec §13): the
list publishes names only, with no IDNO, no fiscal code and no tender or contract
identifier, so it can never be joined on a real identifier. ``name_key`` makes a
name-based comparison *fast*, not *certain*: a shared name is a prompt to check
the award by hand, and no match is not a clean bill of health.

Usage:
    .venv/bin/python scripts/11_load_blacklist.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_RAW, MONGO_META  # noqa: E402
from src.mtender.mongo_client import (  # noqa: E402
    connect,
    ensure_indexes,
    make_run_id,
    upsert_many,
    utcnow_iso,
)
from src.mtender.mongo_schema import RAW_BLACKLIST  # noqa: E402
from src.mtender.names import normalise_name  # noqa: E402

BLACKLIST_DIR = DATA_RAW / "blacklist"


def read_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"entries": payload}


def build_docs(payload: dict[str, Any], path: Path, run_id: str, started: str) -> list[dict]:
    docs = []
    for entry in payload.get("entries") or []:
        nr = entry.get("nr")
        if nr is None:
            continue
        docs.append(
            {
                "nr": int(nr),
                "name": entry.get("name"),
                "name_key": normalise_name(entry.get("name")),
                "decision": entry.get("decision"),
                "ground": entry.get("ground"),
                "valid_until": entry.get("until"),
                "suspended_by_court": bool(entry.get("suspended")),
                "source_url": payload.get("source"),
                "publisher": payload.get("publisher"),
                "collected_at": payload.get("collected_at"),
                "source_file": path.name,
                "identifier_matching_possible": False,
                "run_id": run_id,
                "ingested_at": started,
            }
        )
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(BLACKLIST_DIR))
    args = ap.parse_args()

    _, db = connect()
    ensure_indexes(db)
    run_id = make_run_id("blacklist")
    started = utcnow_iso()

    files = sorted(Path(args.dir).glob("*.json"))
    if not files:
        print(f"no blacklist snapshots under {args.dir}")
        return 1

    docs: list[dict] = []
    for path in files:
        payload = read_snapshot(path)
        rows = build_docs(payload, path, run_id, started)
        print(f"  {path.name}: {len(rows)} entries (source: {payload.get('source')})")
        docs.extend(rows)

    inserted, skipped = upsert_many(db, RAW_BLACKLIST, docs, key="nr", immutable=True)

    # One company can appear under several decisions, so entries and distinct
    # operators are reported separately rather than conflated.
    operators = {d["name_key"] for d in docs if d.get("name_key")}
    summary = {
        "run_id": run_id,
        "stage": "load_blacklist",
        "generated_at": started,
        "source_files": [p.name for p in files],
        "entries_read": len(docs),
        "entries_inserted": inserted,
        "entries_skipped_existing": skipped,
        "distinct_operators": len(operators),
        "operators_with_several_decisions": len(docs) - len(operators),
        "suspended_by_court": sum(1 for d in docs if d["suspended_by_court"]),
        "entries_without_comparable_name": sum(1 for d in docs if not d.get("name_key")),
        "identifier_matching_possible": False,
        "stored_documents": db[RAW_BLACKLIST].count_documents({}),
    }
    MONGO_META.mkdir(parents=True, exist_ok=True)
    out = MONGO_META / "blacklist_load_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nsummary written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
