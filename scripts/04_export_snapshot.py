"""Step 04 - export a deterministic modelling snapshot from MongoDB.

Modelling must not require a running MongoDB instance, so the feature table is
exported to CSV/JSON together with a manifest recording the export query, the
document count and a checksum.

Usage:
    .venv/bin/python scripts/04_export_snapshot.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, DATA_PROCESSED, RESULTS  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS  # noqa: E402
from src.mtender.mongo_client import connect, utcnow_iso  # noqa: E402
from src.mtender.mongo_schema import FEATURES_TENDERS, INGEST_RUNS  # noqa: E402

KEEP = [
    "ocid", "tender_id", "title", "status", "procurement_method",
    "procurement_method_details", "main_procurement_category", "currency",
    "estimated_value", "award_value", "award_total", "award_id", "award_status",
    "n_awards_with_value",
    "buyer_id", "buyer_name",
    "buyer_identifier", "buyer_locality", "buyer_scale", "winner_id",
    "winner_name", "winner_identifier", "cpv_primary", "n_cpvs", "n_lots",
    "n_items", "n_amendments", "n_bidders", "n_bids", "n_suppliers",
    "n_awards", "n_contracts", "tender_start", "tender_end", "award_date",
    # Without this the exported 0 for a missing relationship is indistinguishable
    # from a genuine zero, so the model cannot tell "no history" from "no repeat".
    "relationship_features_available",
    "published_date", "list_date", "has_bid_data", "has_award_data",
    *FEATURE_COLUMNS,
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    _, db = connect()
    export_query = {FEATURES_TENDERS: {}}
    projection = {f: 1 for f in KEEP}
    projection["_id"] = 0

    # Sorted by the server on the unique ocid index rather than by sorting a
    # materialised list: a full-history export does not fit in memory, and the
    # order still has to be deterministic for the checksum to mean anything.
    def rows():
        return db[FEATURES_TENDERS].find(export_query[FEATURES_TENDERS], projection).sort(
            "ocid", 1
        )

    n_documents = db[FEATURES_TENDERS].count_documents({})

    # First pass: which projected fields are actually present. The column set is
    # the union over all documents, which cannot be known before writing the
    # header, and a field that only some rows carry still belongs in it.
    present: set[str] = set()
    for doc in rows():
        present.update(doc.keys())
    cols = [c for c in KEEP if c in present]
    extra = sorted(present - set(KEEP))
    if extra:
        print(f"note: {len(extra)} stored field(s) outside the export list: {extra}")
    print(f"exporting {n_documents:,} feature documents, {len(cols)} columns")

    # Second pass: streamed to disk. A materialised list plus a joined CSV string
    # plus a joined JSON string is three copies of the corpus in RAM.
    # Second pass: streamed to disk. A materialised list plus a joined CSV string
    # plus a joined JSON string is three copies of the corpus in RAM.
    #
    # The CSV is written through the csv module rather than by joining strings.
    # A hand-rolled writer that neutralises the delimiter and the newline but
    # leaves the quote character alone emits invalid CSV: MTender party names
    # such as FARM "COOPERATIVA" produce a field that opens a quoted string, and
    # every reader downstream then swallows the following records until it
    # happens to find a closing quote. That surfaced as
    # "Expected 62 fields in line 30439, saw 67" and left scripts 06 and 07
    # unable to read the snapshot at all.
    csv_path = DATA_FEATURES / "features.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(cols)
        for doc in rows():
            writer.writerow(
                "" if doc.get(c) is None else str(doc[c]).replace("\r\n", " ").replace("\n", " ")
                for c in cols
            )

    json_path = DATA_PROCESSED / "tenders.json"
    with json_path.open("w", encoding="utf-8") as fh:
        fh.write("[")
        for i, doc in enumerate(rows()):
            if i:
                fh.write(",")
            fh.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        fh.write("]")
    print(f"wrote {csv_path} and {json_path}")

    manifest = {
        "exported_at": utcnow_iso(),
        "database": db.name,
        "source_collection": FEATURES_TENDERS,
        "export_query": export_query,
        "sort": ["ocid"],
        "projection_fields": KEEP,
        "n_documents": n_documents,
        "feature_columns": FEATURE_COLUMNS,
        "outputs": {
            str(csv_path): {"sha256": sha256(csv_path), "bytes": csv_path.stat().st_size},
            str(json_path): {"sha256": sha256(json_path), "bytes": json_path.stat().st_size},
        },
    }
    out = RESULTS / "mongo" / "export_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Provenance travels with the snapshot: without the run log the exported
    # numbers cannot be traced back to a dated ingest, and the specification
    # requires results/mongo/ingest_runs.json.
    runs = list(db[INGEST_RUNS].find({}, {"_id": 0}).sort("started_at", 1))
    runs_path = RESULTS / "mongo" / "ingest_runs.json"
    runs_path.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["outputs"][str(runs_path)] = {
        "sha256": sha256(runs_path),
        "bytes": runs_path.stat().st_size,
    }
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"ingest runs -> {runs_path} ({len(runs)} run(s))")

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
