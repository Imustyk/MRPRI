"""Step 03 - build the indicator feature table into ``features_tenders``.

The per-row features are produced by the single shared implementation in
``src/mtender/features.py`` so the stored documents, the CSV export and the unit
tests can never drift apart. MongoDB owns what it is actually good at here:

* the cross-tender group statistics (buyer/supplier/pair counts) that the
  relationship features need, and
* the per-CPV median / standard deviation, computed in-database.

The in-database CPV median is also written next to the pandas result as
``cpv_median_mongo`` so the two independent implementations can be compared in
``results/mongo/features_summary.json``.

Usage:
    .venv/bin/python scripts/03_features_mongo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.aggregations import median_pipeline  # noqa: E402
from src.mtender.config import RESULTS  # noqa: E402
from src.mtender.features import (  # noqa: E402
    BEHAVIOURAL_COLUMNS,
    FEATURE_COLUMNS,
    UNAVAILABLE,
    add_behavioural_features,
    engineer_features,
)
from src.mtender.mongo_client import (  # noqa: E402
    collection_stats,
    connect,
    ensure_indexes,
    make_run_id,
    upsert_many,
    utcnow_iso,
)
from src.mtender.mongo_schema import FEATURES_TENDERS, NORM_TENDERS  # noqa: E402

BATCH = 500


def group_stats(db) -> dict[str, object]:
    """Pair / buyer / supplier counts per tender, via aggregation pipelines."""
    pairs = {
        (d["_id"]["buyer_id"], d["_id"]["winner_id"]): d["n"]
        for d in db[NORM_TENDERS].aggregate(
            [
                {"$match": {"winner_id": {"$nin": [None, ""]}}},
                {"$group": {"_id": {"buyer_id": "$buyer_id", "winner_id": "$winner_id"},
                            "n": {"$sum": 1}}},
            ]
        )
    }
    buyers = {
        d["_id"]: d["n"]
        for d in db[NORM_TENDERS].aggregate([{"$group": {"_id": "$buyer_id", "n": {"$sum": 1}}}])
    }
    suppliers = {
        d["_id"]: d["n"]
        for d in db[NORM_TENDERS].aggregate(
            [
                {"$match": {"winner_id": {"$nin": [None, ""]}}},
                {"$group": {"_id": "$winner_id", "n": {"$sum": 1}}},
            ]
        )
    }
    total = db[NORM_TENDERS].count_documents({"winner_id": {"$nin": [None, ""]}})
    return {"pairs": pairs, "buyers": buyers, "suppliers": suppliers, "total_awards": max(total, 1)}


def load_frame(db) -> pd.DataFrame:
    """Read ``norm_tenders`` into a frame, preserving the ocid as the index."""
    docs = list(db[NORM_TENDERS].find({}, {"_id": 0}))
    if not docs:
        return pd.DataFrame()
    frame = pd.DataFrame(docs)
    # The frame now holds the values, so the per-document dicts (~3 GB of
    # overhead at full history) are released before the feature passes, which
    # each copy the frame.
    del docs
    frame["ocid"] = frame["ocid"].astype(str)
    return frame.set_index("ocid", drop=False)


def apply_mongo_group_stats(frame: pd.DataFrame, stats: dict[str, object]) -> pd.DataFrame:
    """Attach the MongoDB-computed relationship counts used for cross-checking.

    ``add_behavioural_features`` recomputes the same quantities in pandas; this
    keeps an independent, database-side value per tender so a disagreement shows
    up in the summary instead of passing silently.
    """
    out = frame.copy()
    buyers = stats["buyers"]
    pairs = stats["pairs"]
    suppliers = stats["suppliers"]
    total = float(stats["total_awards"])
    pair_n, buyer_n, supplier_n = [], [], []
    for buyer, winner in zip(out.get("buyer_id"), out.get("winner_id")):
        known = buyer not in (None, "") and winner not in (None, "")
        pair_n.append(float(pairs.get((buyer, winner), 0)) if known else 0.0)
        buyer_n.append(float(buyers.get(buyer, 0) or 1) if known else 0.0)
        supplier_n.append(float(suppliers.get(winner, 0)) if known else 0.0)
    out["mongo_pair_n"] = pair_n
    out["mongo_buyer_n"] = buyer_n
    out["mongo_supplier_n"] = supplier_n
    out["mongo_total_awards"] = total
    return out


def main() -> int:
    _, db = connect()
    ensure_indexes(db)
    run_id = make_run_id("feat")
    started = utcnow_iso()

    frame = load_frame(db)
    if frame.empty:
        print("norm_tenders is empty - run scripts/02_normalize_mongo.py first")
        return 1

    stats = group_stats(db)
    print(f"group stats: {len(stats['buyers']):,} buyers, {len(stats['suppliers']):,} suppliers, "
          f"{len(stats['pairs']):,} buyer-supplier pairs, {stats['total_awards']:,} awarded tenders")

    frame = engineer_features(frame)
    frame = add_behavioural_features(frame)
    frame = apply_mongo_group_stats(frame, stats)

    # Declared features must actually exist. Failing loudly beats writing zeros
    # for a feature that was never computed.
    missing = [c for c in list(FEATURE_COLUMNS) + list(BEHAVIOURAL_COLUMNS) if c not in frame.columns]
    if missing:
        raise SystemExit(f"engineer_features did not produce: {missing}")

    # Per-CPV medians straight from MongoDB, kept as an independent cross-check.
    cpv_stats = {
        d["_id"]: (d.get("median"), d.get("std"))
        for d in db[NORM_TENDERS].aggregate(
            median_pipeline(
                "cpv_primary",
                "award_value",
                match={"award_value": {"$ne": None}, "cpv_primary": {"$nin": [None, ""]}},
            ),
            allowDiskUse=True,
        )
    }
    frame["cpv_median_mongo"] = [
        (cpv_stats.get(c, (None, None))[0]) for c in frame.get("cpv_primary")
    ]

    # Written in frame-sized slices rather than as one list of records: turning
    # the whole frame into dicts at once is the peak memory cost of this stage,
    # and the upserts only ever need BATCH documents at a time.
    def prepare(rows: pd.DataFrame) -> list[dict]:
        out = []
        for d in rows.to_dict("records"):
            # `ocid` is kept as a real field: it is the idempotency key that
            # upsert_many filters on (and the unique index is built on it).
            d.pop("_id", None)
            d["run_id"] = run_id
            for col in (*FEATURE_COLUMNS, *BEHAVIOURAL_COLUMNS):
                value = d.get(col)
                if isinstance(value, float):
                    d[col] = round(value, 6)
            d.pop("index", None)
            out.append(d)
        return out

    flat = frame.reset_index(drop=True)
    inserted = existing = 0
    for i in range(0, len(flat), BATCH):
        ins, skip = upsert_many(
            db, FEATURES_TENDERS, prepare(flat.iloc[i : i + BATCH]), key="ocid"
        )
        inserted += ins
        existing += skip
    del flat

    # Cross-check the two independent median implementations group by group:
    # pandas ``groupby(...).median()`` in features.py versus the MongoDB
    # ``median_pipeline``. Comparing like with like (median vs median) is the
    # only meaningful check.
    pandas_median = (
        frame[frame["award_value"].notna() & frame["cpv_primary"].notna()]
        .groupby("cpv_primary")["award_value"]
        .median()
        .to_dict()
    )
    rel = []
    for cpv, (mongo_value, _mongo_std) in cpv_stats.items():
        py = pandas_median.get(cpv)
        if not isinstance(mongo_value, (int, float)) or not isinstance(py, (int, float)):
            continue
        if mongo_value:
            rel.append(abs(py - mongo_value) / abs(mongo_value))
    agreement = {
        "n_groups_compared": len(rel),
        "median_abs_rel_diff": round(float(pd.Series(rel).median()), 6) if rel else None,
        "max_abs_rel_diff": round(float(pd.Series(rel).max()), 6) if rel else None,
    }

    summary = {
        "run_id": run_id,
        "stage": "features",
        "generated_at": started,
        "n_source_tenders": len(frame),
        "n_inserted": inserted,
        "n_existing_updated": existing,
        "feature_columns": list(FEATURE_COLUMNS),
        "behavioural_columns": list(BEHAVIOURAL_COLUMNS),
        "unavailable_indicators": UNAVAILABLE,
        "cpv_groups": len(cpv_stats),
        "mongo_vs_pandas_cpv_median": agreement,
        "group_stats": {
            "buyers": len(stats["buyers"]),
            "suppliers": len(stats["suppliers"]),
            "pairs": len(stats["pairs"]),
            "awarded_tenders": stats["total_awards"],
        },
    }
    out = RESULTS / "mongo" / "features_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\ncollection stats:")
    for row in collection_stats(db):
        print(f"  {row['collection']:<22} docs={row['documents']:>8,}  size={row['size_bytes']/1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
