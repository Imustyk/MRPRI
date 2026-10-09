"""Rebuild the database from the raw files on disk.

Required by section 18 of ``NEED_TO_DO.md``: the database must be reconstructible
without re-querying the MTender API, so the thesis can be re-run by someone else.

Two layers are rebuilt, in order:

1. ``raw_tenders`` / ``raw_parties`` are re-derived from the archived response
   bodies in ``data/raw/ocds_packages/``. Those bodies are written by
   ``scripts/01b_fetch_records.py --archive``. Extraction code can change without
   mutating what the API actually sent, so this is a genuine rebuild and not a
   re-download.
2. ``norm_*`` is then produced by the normal pipeline stages.

Usage:
    .venv/bin/python scripts/seed_mongo.py --target mtender_seed
    .venv/bin/python scripts/seed_mongo.py --target mtender_seed --drop

If the archive is empty the script stops with an explanation instead of creating an
empty database that looks like a successful run.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_RAW  # noqa: E402
from src.mtender.mongo_client import connect, ensure_indexes  # noqa: E402
from src.mtender.mongo_schema import RAW_PARTIES, RAW_TENDERS  # noqa: E402
from src.mtender.ocds import extract_parties, extract_tender  # noqa: E402

PACKAGES_DIR = DATA_RAW / "ocds_packages"
ROOT = Path(__file__).resolve().parents[1]
BATCH = 200


def load_archive() -> list[tuple[str, dict]]:
    """Read every archived response body."""
    if not PACKAGES_DIR.exists():
        return []
    out: list[tuple[str, dict]] = []
    for path in sorted(PACKAGES_DIR.glob("*.json.gz")):
        ocid = path.name[: -len(".json.gz")]
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                out.append((ocid, json.load(fh)))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  unreadable {path.name}: {type(exc).__name__}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=None, help="database to build (default: MONGO_DB_NAME)")
    ap.add_argument("--drop", action="store_true", help="drop the target database first")
    ap.add_argument("--skip-derived", action="store_true",
                    help="only rebuild raw_* and do not run the normal/features stages")
    args = ap.parse_args()

    client, db = connect()
    if args.target and args.target != db.name:
        db = client[args.target]
    if args.drop and db.name in client.list_database_names():
        client.drop_database(db.name)
        print(f"dropped database {db.name}")

    packages = load_archive()
    if not packages:
        print(
            "No archived packages found.\n"
            f"  expected: {PACKAGES_DIR}/*.json.gz\n"
            "  create it with: .venv/bin/python scripts/01b_fetch_records.py --archive"
        )
        return 1
    print(f"{len(packages):,} archived package(s) in {PACKAGES_DIR}")

    ensure_indexes(db)
    tenders: list[dict] = []
    parties: list[dict] = []
    for ocid, package in packages:
        doc = extract_tender(ocid, package)
        tenders.append(doc)
        parties.extend(extract_parties(doc))
        if len(tenders) >= BATCH:
            _flush(db, tenders, parties)
            tenders, parties = [], []
    _flush(db, tenders, parties)

    counts = {name: db[name].count_documents({}) for name in (RAW_TENDERS, RAW_PARTIES)}
    print(json.dumps({"database": db.name, "rebuilt": counts}, indent=2))

    if not args.skip_derived:
        for stage in ("02_normalize_mongo.py", "03_features_mongo.py"):
            print(f"\n== running {stage} ==")
            env = {**dict(__import__("os").environ), "MONGO_DB_NAME": db.name}
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / stage)],
                cwd=ROOT, env=env, check=False,
            )
            if result.returncode != 0:
                print(f"{stage} failed with exit code {result.returncode}")
                return result.returncode
    return 0


def _flush(db, tenders: list[dict], parties: list[dict]) -> None:
    """Insert raw documents immutably, mirroring scripts/01b_fetch_records.py."""
    from src.mtender.mongo_client import upsert_many

    if tenders:
        upsert_many(db, RAW_TENDERS, tenders, key="ocid", immutable=True)
    if parties:
        upsert_many(db, RAW_PARTIES, parties, key="party_key", immutable=True)


if __name__ == "__main__":
    raise SystemExit(main())
