"""Aggregation helpers that work on the deployed MongoDB version.

The local server is MongoDB 6.0.18, which has no ``$percentile`` accumulator
(that arrived in 7.0). Medians are therefore computed by sorting the input and
reading the middle element of each group, which is exact and version-safe.
"""

from __future__ import annotations

from typing import Any

#: Median / stdDevPop over ``field``, grouped by ``group_by``.
def median_pipeline(
    group_by: str,
    field: str,
    match: dict[str, Any] | None = None,
) -> list[dict]:
    return [
        *([{"$match": match}] if match else []),
        {"$sort": {group_by: 1, field: 1}},
        {
            "$group": {
                "_id": f"${group_by}",
                "n": {"$sum": 1},
                "vals": {"$push": f"${field}"},
                # $stdDevSamp matches pandas' default ddof=1; $stdDevPop would
                # silently disagree for every group.
                "std": {"$stdDevSamp": f"${field}"},
                "sum": {"$sum": f"${field}"},
            }
        },
        {
            "$project": {
                "n": 1,
                "std": 1,
                "sum": 1,
                # Standard median: for an even group size the two middle values
                # are averaged, which is what pandas/numpy compute. Taking only
                # the lower middle element (the obvious shortcut) disagreed with
                # pandas by up to 50% on even-sized groups.
                "median": {
                    "$cond": [
                        {"$eq": [{"$mod": ["$n", 2]}, 0]},
                        {
                            "$divide": [
                                {
                                    "$add": [
                                        {"$arrayElemAt": ["$vals", {"$divide": ["$n", 2]}]},
                                        {
                                            "$arrayElemAt": [
                                                "$vals",
                                                {"$subtract": [{"$divide": ["$n", 2]}, 1]},
                                            ]
                                        },
                                    ]
                                },
                                2,
                            ]
                        },
                        # odd group size: the exact middle element
                        {"$arrayElemAt": ["$vals", {"$floor": {"$divide": ["$n", 2]}}]},
                    ]
                },
            }
        },
    ]
