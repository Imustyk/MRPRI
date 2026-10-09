"""Step 05 - descriptive aggregations executed by MongoDB.

Every number produced here is written to ``results/tables/`` and is safe to quote
in chapter 3. The same quantities are recomputed in pandas by
``06_detect_anomalies.py`` as a cross-check of the two toolchains.

Usage:
    .venv/bin/python scripts/05_aggregations.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.aggregations import median_pipeline  # noqa: E402
from src.mtender.config import TABLES, RESULTS  # noqa: E402
from src.mtender.mongo_client import connect, collection_stats, utcnow_iso  # noqa: E402
from src.mtender.mongo_schema import (  # noqa: E402
    ANOMALY_SCORES,
    FEATURES_TENDERS,
    NORM_PARTIES,
    NORM_TENDERS,
)

# Fixed value bands (MDL). Declared as $switch branches rather than $bucket
# because $bucket emits only _id, leaving nowhere to accumulate counts or sums.
QUANTILE_BANDS: list[dict] = [
    {"case": {"$lt": ["$award_total", 100_000]}, "then": "<100k"},
    {"case": {"$lt": ["$award_total", 500_000]}, "then": "100k-500k"},
    {"case": {"$lt": ["$award_total", 1_000_000]}, "then": "500k-1m"},
    {"case": {"$lt": ["$award_total", 5_000_000]}, "then": "1m-5m"},
    {"case": {"$lt": ["$award_total", 10_000_000]}, "then": "5m-10m"},
    {"case": {"$lt": ["$award_total", 50_000_000]}, "then": "10m-50m"},
    {"case": {"$gte": ["$award_total", 50_000_000]}, "then": ">=50m"},
]

# Missing group keys get an explicit label: an empty cell in a results table is
# indistinguishable from a rendering bug, and null grouping would otherwise
# merge "unknown" with a real category.
UNKNOWN_LABEL = {"$cond": [{"$in": ["$_id", [None, ""]]}, "(unknown)", "$_id"]}
NO_BID_DATA_LABEL = {"$cond": [{"$eq": ["$_id", None]}, "(no bid data)", "$_id"]}

AGGREGATIONS: dict[str, tuple[list, list]] = {
    "tenders_per_year": (
        [
            {"$match": {"tender_start": {"$nin": [None, ""]}}},
            {
                "$group": {
                    # group by the *year number* ("$year"), not by the whole
                    # timestamp, otherwise every day becomes its own row.
                    "_id": {"$year": {"$dateFromString": {"dateString": "$tender_start", "onError": None}}},
                    "n_tenders": {"$sum": 1},
                    "n_awarded": {"$sum": {"$cond": [{"$ne": ["$award_value", None]}, 1, 0]}},
                    # award_total sums every lot award; award_value alone would
                    # understate a multi-lot tender (up to 219 awards observed).
                    "sum_award_total": {"$sum": {"$ifNull": ["$award_total", "$award_value", 0]}},
                }
            },
            # _id is the year number, so sort on it directly.
            {"$sort": {"_id": 1}},
            # rename so the CSV column is `year`
            # _id is the year *number* here, so reference "$_id", not "$_id.year".
            {"$project": {"_id": 0, "year": "$_id", "n_tenders": 1,
                          "n_awarded": 1, "sum_award_total": 1}},
        ],
        ["year", "n_tenders", "n_awarded", "sum_award_total"],
    ),
    "top_procurers_by_value": (
        [
            {"$match": {"award_value": {"$ne": None}}},
            {
                "$group": {
                    "_id": {"id": "$buyer_id", "name": "$buyer_name"},
                    "n_awards": {"$sum": 1},
                    "total_value": {"$sum": {"$ifNull": ["$award_total", "$award_value"]}},
                    # $stdDevSamp to match the convention used elsewhere
                    "std_value": {"$stdDevSamp": "$award_total"},
                }
            },
            {"$sort": {"total_value": -1}},
            {"$limit": 25},
            # Rename the _id sub-keys: the CSV column names are id/name, and
            # _flatten cannot know them. Money under a missing buyer is kept but
            # labelled, never silently attributed to an empty id.
            {
                "$project": {
                    "_id": 0,
                    "id": {"$ifNull": ["$_id.id", "(unknown)"]},
                    "name": {"$ifNull": ["$_id.name", "(unknown)"]},
                    "n_awards": 1,
                    "total_value": 1,
                    "std_value": 1,
                }
            },
        ],
        ["id", "name", "n_awards", "total_value", "std_value"],
    ),
    "top_suppliers_by_value": (
        [
            {"$match": {"winner_id": {"$nin": [None, ""]}, "award_value": {"$ne": None}}},
            {
                "$group": {
                    "_id": {"id": "$winner_id", "name": "$winner_name", "identifier": "$winner_identifier"},
                    "n_wins": {"$sum": 1},
                    "total_value": {"$sum": {"$ifNull": ["$award_total", "$award_value"]}},
                    "buyers": {"$addToSet": "$buyer_id"},
                }
            },
            {
                "$project": {
                    "id": "$_id.id",
                    "name": "$_id.name",
                    "identifier": "$_id.identifier",
                    "n_wins": 1,
                    "total_value": 1,
                    "n_distinct_buyers": {"$size": "$buyers"},
                }
            },
            {"$sort": {"total_value": -1}},
            {"$limit": 25},
        ],
        ["id", "name", "identifier", "n_wins", "total_value", "n_distinct_buyers"],
    ),
    "procedure_type_distribution": (
        [
            {"$group": {"_id": "$procurement_method_details", "n": {"$sum": 1},
                        "n_awarded": {"$sum": {"$cond": [{"$ne": ["$award_value", None]}, 1, 0]}}}},
            {"$project": {"_id": 0, "method_details": UNKNOWN_LABEL, "n": 1, "n_awarded": 1}},
            {"$sort": {"n": -1}},
        ],
        ["method_details", "n", "n_awarded"],
    ),
    "status_distribution": (
        [
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
            {"$project": {"_id": 0, "status": UNKNOWN_LABEL, "n": 1}},
            {"$sort": {"n": -1}},
        ],
        ["status", "n"],
    ),
    "cpv_median_by_code": (
        median_pipeline(
            "cpv_primary",
            # Deliberately award_value (the primary award), because this median
            # is the denominator of the value_vs_cpv_median feature.
            "award_value",
            match={"award_value": {"$ne": None}, "cpv_primary": {"$nin": [None, ""]}},
        )
        + [
            # median_pipeline groups by _id; rename it to the CSV column name.
            {"$project": {"_id": 0, "cpv": "$_id", "n": 1, "median": 1, "std": 1, "sum": 1}},
            {"$sort": {"n": -1}},
            {"$limit": 30},
        ],
        ["cpv", "n", "median", "std", "sum"],
    ),
    "competition_profile": (
        [
            {
                "$group": {
                    "_id": "$n_bidders",
                    "n_tenders": {"$sum": 1},
                    "n_awarded": {"$sum": {"$cond": [{"$ne": ["$award_value", None]}, 1, 0]}},
                }
            },
            {"$project": {"_id": 0, "n_bidders": NO_BID_DATA_LABEL, "n_tenders": 1, "n_awarded": 1}},
            {"$sort": {"_id": 1}},
        ],
        ["n_bidders", "n_tenders", "n_awarded"],
    ),
    "supplier_concentration_top_buyers": (
        [
            {"$match": {"winner_id": {"$nin": [None, ""]}}},
            {
                "$group": {
                    "_id": {"buyer_id": "$buyer_id", "winner_id": "$winner_id"},
                    "n": {"$sum": 1},
                }
            },
            {
                "$group": {
                    "_id": "$_id.buyer_id",
                    "pairs": {"$push": "$_id.winner_id"},
                    "pair_counts": {"$push": "$n"},
                    "n_awards": {"$sum": "$n"},
                }
            },
            {
                "$project": {
                    "buyer_id": "$_id",
                    "n_awards": 1,
                    "n_distinct_winners": {"$size": "$pairs"},
                    "top_winner_share": {"$divide": [{"$max": "$pair_counts"}, "$n_awards"]},
                }
            },
            {"$sort": {"n_awards": -1}},
            {"$limit": 25},
        ],
        ["buyer_id", "n_awards", "n_distinct_winners", "top_winner_share"],
    ),
    "value_bands": (
        [
            {"$match": {"award_value": {"$ne": None}}},
            # Coalesce first: a row ingested before award_total existed must not
            # fall into a different band just because the field is missing.
            {"$set": {"award_total": {"$ifNull": ["$award_total", "$award_value"]}}},
            {
                # $bucket cannot be used here: it emits only _id, so the counts
                # and the value sum have to be accumulated in the same $group.
                "$group": {
                    "_id": {"$switch": {"branches": QUANTILE_BANDS}},
                    "n": {"$sum": 1},
                    "sum_value": {"$sum": "$award_total"},
                    "n_single_bidder": {"$sum": {"$cond": [{"$eq": ["$n_bidders", 1]}, 1, 0]}},
                }
            },
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0, "band": "$_id", "n": 1, "sum_value": 1,
                          "n_single_bidder": 1}},
        ],
        ["band", "n", "sum_value", "n_single_bidder"],
    ),
}


def _flatten(doc: dict) -> dict:
    out: dict = {}
    for key, value in doc.items():
        if isinstance(value, dict) and set(value) <= {"id", "name", "identifier", "year"}:
            # Fallback only: every table now renames its own _id via $project.
            # Keys are kept unprefixed so the CSV header matches the data.
            out.update(value)
        else:
            out[key] = value
    return out


def _to_csv(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return ",".join(columns) + "\n"
    lines = [",".join(columns)]
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, list):
                value = str(len(value))
            cells.append("" if value is None else str(value).replace(",", ";").replace("\n", " "))
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def main() -> int:
    _, db = connect()
    TABLES.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}

    for name, (pipeline, columns) in AGGREGATIONS.items():
        rows = [_flatten(d) for d in db[NORM_TENDERS].aggregate(pipeline, allowDiskUse=True)]
        path = TABLES / f"{name}.csv"
        path.write_text(_to_csv(rows, columns), encoding="utf-8")
        index[name] = {
            "file": path.name,
            "n_rows": len(rows),
            "columns": columns,
            "pipeline": pipeline,
        }
        print(f"{name:<38} rows={len(rows):>6}  -> {path.name}")

    roles = [
        {"role": d["_id"], "n_parties": d["n"]}
        for d in db[NORM_PARTIES].aggregate([{"$group": {"_id": "$role", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}])
    ]
    (TABLES / "parties_by_role.csv").write_text(
        _to_csv(roles, ["role", "n_parties"]), encoding="utf-8"
    )
    index["parties_by_role"] = {"file": "parties_by_role.csv", "n_rows": len(roles)}

    stats = collection_stats(db)
    manifest = {
        "generated_at": utcnow_iso(),
        "database": db.name,
        "aggregations": index,
        "collection_stats": stats,
        "anomaly_scores_stored": db[ANOMALY_SCORES].count_documents({}),
        "features_stored": db[FEATURES_TENDERS].count_documents({}),
    }
    out = RESULTS / "mongo" / "aggregations_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(index)} aggregation tables -> {TABLES}")
    print(f"manifest -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
