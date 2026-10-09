"""Adapts the real ETL output to the shape the dashboard expects.

Why this module exists
----------------------
The analytical pipeline (``scripts/01a``-``08``) writes the *real* MTender
records: ``data/processed/tenders.json`` plus anomaly scores in MongoDB. The
dashboard was originally written against a synthetic generator whose column
names never existed in the real feed (``price_to_cpv_median``,
``round_price``, ``near_threshold``, ``bid_spread``, ``negotiated_flag``,
``collusion_phone_cluster``, ...).

Serving one dataset under the other's column names silently reports invented
indicators as measurements: a missing feature averaged over a list becomes
``0.0``, which is indistinguishable from a genuine zero. So every field the UI
reads is mapped here explicitly, and anything MTender does not publish is
returned as ``null`` together with a reason in ``UNAVAILABLE``.
"""

from __future__ import annotations

import math
from typing import Any

# Fields MTender does not publish. The dashboard must render these as "not
# available" instead of 0. See UNAVAILABLE in src/mtender/features.py.
UNAVAILABLE: dict[str, str] = {
    "cpv_label": "MTender publishes CPV codes only; no code->label dictionary is served",
    "bids": "bids.details is published for a small minority of procurements only",
    "bid_spread": "derived from bid-level prices, which are mostly absent",
    "winning_margin": "requires both bid prices and the estimated value per lot",
    "direct_award_flag": "no direct-award indicator in the OCDS payload",
    "negotiated_flag": "no negotiated-procedure flag in the OCDS payload",
    "round_price": "not derivable from a single aggregate award amount",
    "near_threshold": "threshold proximity needs the per-procedure limit, which is not published",
    "supplier_company_age": "party registration dates are not in the payload",
    # bids.details holds one record per LOT that received a bid, not one per
    # bidder: a 10-item tender yields 10 bid records, and a 202-lot tender was
    # observed with 503. Counting them as "bids" invents competition.
    "n_bids": "bids.details is per-lot, so this counts bid records, not bidders",
    "planted_pattern": "ground-truth label, synthetic data only",
    "is_planted_anomaly": "ground-truth label, synthetic data only",
}

# Real boolean red flags -> human labels for the tender detail page.
FLAG_FEATURES: dict[str, str] = {
    "single_bidder": "Single bidder",
    "short_deadline": "Short bidding window",
    "accelerated_like": "Accelerated procedure",
    "no_award_after_tender": "No award published after tender",
    "multi_award_tender": "Award split into many lots",
    "multi_supplier_award": "Several suppliers on one award",
    "cancelled": "Cancelled",
    "amended": "Amended after publication",
    "no_bid_data": "No bid data published",
    "long_deadline": "Long bidding window",
}

RISK_BANDS = ("unscored", "low", "medium", "high", "critical")


def risk_level(n_models_flagging: int | None) -> str:
    """Risk band from how many independent models flagged the record.

    Banding on model *agreement* rather than on a score threshold keeps the
    bands reproducible and independent of the score scale, which differs per
    model (LOF scores are in the hundreds, the SVM scores are negative).

    A record with no detector output is ``unscored``, not ``low``. Only
    ``features.csv`` rows that appear in the score table were ever scored, so
    folding the unscored majority into ``low`` would assert that tens of
    thousands of procedures were examined and cleared. The corpus is scored
    sparsely on purpose (the detection run covers a flagged-candidate sample),
    and the UI has to show that gap rather than hide it.
    """
    if n_models_flagging is None:
        return "unscored"
    try:
        n = int(n_models_flagging)
    except (TypeError, ValueError):
        return "unscored"
    if n >= 3:
        return "critical"
    if n == 2:
        return "high"
    if n == 1:
        return "medium"
    return "low"


def _num(value: Any) -> float | None:
    """Finite float or None.

    ``value_vs_cpv_median`` divides by a CPV median that can be 0, and the
    pipeline stores the result as inf/NaN. JSON has no encoding for those, and
    FastAPI rejects the whole response, so they are dropped here rather than
    serialised as 0 - which would read as a genuine measurement.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _s(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iso(value: Any) -> str | None:
    return _s(value)


def _flag(value: Any) -> bool:
    """Truthiness of a red-flag field.

    The ETL stores these as 0/1 integers (pandas ``.astype(int)``), and MongoDB
    will not match ``1`` against ``true``, so a strict ``is True`` test would
    silently produce an empty flag list for every procedure. Strings are rejected
    so that "0" is not read as set.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, float):
        return value == 1.0
    return False


def project_tender(row: dict, score: dict | None) -> dict:
    """Map one real tender (+ its anomaly score) to the dashboard contract."""
    score = score or {}
    flags = [label for field, label in FLAG_FEATURES.items() if _flag(row.get(field))]
    n_flagging = score.get("n_models_flagging")

    return {
        # --- identity -----------------------------------------------------
        "tender_id": _s(row.get("tender_id")) or _s(row.get("ocid")),
        "ocid": _s(row.get("ocid")),
        "title": _s(row.get("title")),
        # --- buyer / procedure -------------------------------------------
        "buyer_id": _s(row.get("buyer_id")),
        "buyer_name": _s(row.get("buyer_name")),
        "buyer_identifier": _s(row.get("buyer_identifier")),
        "buyer_locality": _s(row.get("buyer_locality")),
        "procedure": _s(row.get("procurement_method_details")),
        "procurement_method": _s(row.get("procurement_method")),
        "status": _s(row.get("status")),
        "cpv_code": _s(row.get("cpv_primary")),
        "cpv_label": None,
        # --- dates --------------------------------------------------------
        "published_at": _iso(row.get("published_date")),
        "list_date": _iso(row.get("list_date")),
        "tender_start": _iso(row.get("tender_start")),
        "bid_deadline": _iso(row.get("tender_end")),
        "award_date": _iso(row.get("award_date")),
        "bid_window_days": _num(row.get("bid_window_days")),
        # --- money --------------------------------------------------------
        "estimated_value_mdl": _num(row.get("estimated_value")),
        "award_value_mdl": _num(row.get("award_value")),
        # sum over all lots: the only figure comparable with estimated_value_mdl
        "award_total_mdl": _num(row.get("award_total")),
        "currency": _s(row.get("currency")) or "MDL",
        # --- parties ------------------------------------------------------
        "winner_name": _s(row.get("winner_name")),
        "winner_idno": _s(row.get("winner_identifier")),
        "winner_id": _s(row.get("winner_id")),
        # n_bid_records counts lot-level bid entries; n_bidders is the only
        # sound competition measure. Both are exposed so the UI can label them.
        "n_bids": _num(row.get("n_bids")),
        "n_bid_records": _num(row.get("n_bids")),
        "n_bidders": _num(row.get("n_bidders")),
        "n_lots": _num(row.get("n_lots")),
        "n_awards": _num(row.get("n_awards")),
        # --- risk ---------------------------------------------------------
        # max_score is 0..1 across models; the UI works in 0..100.
        "risk_score": round(float(score["max_score"]) * 100, 2)
        if _num(score.get("max_score")) is not None
        else None,
        "risk_level": risk_level(n_flagging),
        "n_models_flagging": n_flagging,
        "iso_score": _num(score.get("score_isolation_forest")),
        "lof_score": _num(score.get("score_local_outlier_factor")),
        "svm_score": _num(score.get("score_one_class_svm")),
        "rule_score": _num(score.get("score_statistical_mad_zscore")),
        "flags": flags,
        # --- real feature values used by the indicator charts -------------
        "single_bidder": _num(row.get("single_bidder")),
        "short_deadline": _num(row.get("short_deadline")),
        "value_vs_cpv_median": _num(row.get("value_vs_cpv_median")),
        "winner_share_of_buyer_awards": _num(row.get("winner_share_of_buyer_awards")),
        "buyer_supplier_repeat_share": _num(row.get("buyer_supplier_repeat_share")),
        "estimate_to_award_ratio": _num(row.get("estimate_to_award_ratio")),
        "has_bid_data": row.get("has_bid_data"),
        "has_award_data": row.get("has_award_data"),
        # --- explicitly unavailable ---------------------------------------
        "bids": None,
        "planted_pattern": None,
        "is_planted_anomaly": None,
    }


def build_stats(rows: list[dict], feature_columns: list[str]) -> dict:
    """Descriptive statistics computed from the real rows, not from a file."""
    n = len(rows)
    buyers = {_s(r.get("buyer_id")) for r in rows if _s(r.get("buyer_id"))}
    winners = {_s(r.get("winner_id")) for r in rows if _s(r.get("winner_id"))}
    total_award = sum(
        r["award_total_mdl"] or r["award_value_mdl"] or 0.0 for r in rows
    )
    high = [r for r in rows if r["risk_level"] in {"high", "critical"}]
    scored = [r["risk_score"] for r in rows if r["risk_score"] is not None]
    # n_bidders == 0 means MTender published no participant list at all, which is
    # missing data rather than zero competition. Averaging those zeros in would
    # understate the number of bidders, and counting them as "records with
    # published bids" would make the denominator larger than the population the
    # share is actually computed over.
    bidders = [r["n_bidders"] for r in rows if (r["n_bidders"] or 0) > 0]
    # _flag, not "is True": the ETL writes 0/1 ints, so a strict identity
    # test reported a 0.0 single-bidder share for the whole dataset.
    single = [r for r in rows if _flag(r.get("single_bidder"))]
    n_with_bids = len(bidders)

    def _group(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows:
            k = _s(r.get(key)) or "(unknown)"
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def _top(key: str, limit: int = 10) -> list[dict]:
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            k = _s(r.get(key))
            if k:
                buckets.setdefault(k, []).append(r)
        scored_rows = []
        for k, items in buckets.items():
            risks = [i["risk_score"] for i in items if i["risk_score"] is not None]
            scored_rows.append(
                {
                    "cpv_code": k,
                    "cpv_label": None,
                    "n": len(items),
                    "avg_risk": round(sum(risks) / len(risks), 2) if risks else None,
                    "value": round(
                        sum(i["award_total_mdl"] or i["award_value_mdl"] or 0.0
                            for i in items),
                        2,
                    ),
                }
            )
        return sorted(scored_rows, key=lambda d: -d["n"])[:limit]

    monthly: dict[str, list[dict]] = {}
    for r in rows:
        month = _s(r.get("list_date"))[:7] if _s(r.get("list_date")) else None
        if month:
            monthly.setdefault(month, []).append(r)
    monthly_rows = []
    for month, items in sorted(monthly.items()):
        risks = [i["risk_score"] for i in items if i["risk_score"] is not None]
        monthly_rows.append(
            {
                "month": month,
                "n": len(items),
                "avg_risk": round(sum(risks) / len(risks), 2) if risks else None,
                "value": round(
                    sum(i["award_total_mdl"] or i["award_value_mdl"] or 0.0
                        for i in items),
                    2,
                ),
            }
        )

    buyer_rows: list[dict] = []
    by_buyer: dict[str, list[dict]] = {}
    for r in rows:
        b = _s(r.get("buyer_id"))
        if b:
            by_buyer.setdefault(b, []).append(r)
    for b, items in by_buyer.items():
        risks = [i["risk_score"] for i in items if i["risk_score"] is not None]
        buyer_rows.append(
            {
                "buyer_id": b,
                "buyer_name": _s(items[0].get("buyer_name")) or b,
                "n": len(items),
                "avg_risk": round(sum(risks) / len(risks), 2) if risks else None,
                "high": sum(1 for i in items
                            if i["risk_level"] in {"high", "critical"}),
            }
        )

    return {
        "n_tenders": n,
        "n_buyers": len(buyers),
        "n_winners": len(winners),
        "total_award_mdl": round(total_award, 2),
        "high_risk_count": len(high),
        "high_risk_value_mdl": round(
            sum(r["award_total_mdl"] or r["award_value_mdl"] or 0.0 for r in high), 2
        ),
        # Denominator is the records that published a participant list, matching
        # the "of N with published bids" caption in the dashboard.
        "single_bidder_share": round(len(single) / n_with_bids, 4) if n_with_bids else None,
        # mean bidder count, not mean bid-record count: the latter tracks the
        # number of lots and says nothing about competition.
        "mean_n_bidders": round(sum(bidders) / len(bidders), 3) if bidders else None,
        "mean_n_bid_records": (
            round(
                sum(r["n_bid_records"] for r in rows if r["n_bid_records"] is not None)
                / max(len([r for r in rows if r["n_bid_records"] is not None]), 1),
                3,
            )
            if bidders
            else None
        ),
        "n_with_bid_data": n_with_bids,
        "mean_risk": round(sum(scored) / len(scored), 2) if scored else None,
        "level_counts": {b: sum(1 for r in rows if r["risk_level"] == b)
                         for b in RISK_BANDS},
        "procedure_counts": _group("procedure"),
        "top_cpv": _top("cpv_code"),
        "monthly": monthly_rows,
        "top_risky_buyers": sorted(
            buyer_rows, key=lambda d: (-(d["avg_risk"] or 0), -d["n"])
        )[:10],
        "features": feature_columns,
        # No ground truth exists for real tenders, so precision/recall are not
        # computable. Reported as unavailable rather than omitted.
        "metrics": {
            "available": False,
            "reason": "real procurements have no planted-anomaly ground truth",
        },
    }


def build_graph(rows: list[dict], max_nodes: int = 60) -> dict:
    """Buyer <-> winner bipartite network from real awards."""
    pairs: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        b = _s(r.get("buyer_id"))
        w = _s(r.get("winner_id"))
        if not b or not w:
            continue
        pairs.setdefault((b, w), []).append(r)

    degree: dict[str, int] = {}
    for b, w in pairs:
        degree[b] = degree.get(b, 0) + 1
        degree[w] = degree.get(w, 0) + 1

    # keep the most connected parties so the payload stays renderable
    keep = {p for p, _ in sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))[:max_nodes]}

    names: dict[str, tuple[str, str]] = {}
    for r in rows:
        b = _s(r.get("buyer_id"))
        w = _s(r.get("winner_id"))
        if b and b in keep:
            names.setdefault(b, ("buyer", _s(r.get("buyer_name")) or b))
        if w and w in keep:
            names.setdefault(w, ("supplier", _s(r.get("winner_name")) or w))

    links = []
    for (b, w), items in pairs.items():
        if b not in keep or w not in keep:
            continue
        risks = [i["risk_score"] for i in items if i["risk_score"] is not None]
        links.append(
            {
                "source": b,
                "target": w,
                "weight": len(items),
                "value": round(
                    sum(i["award_total_mdl"] or i["award_value_mdl"] or 0.0
                        for i in items),
                    2,
                ),
                "max_risk": round(max(risks), 2) if risks else None,
            }
        )

    nodes = [
        {
            "id": pid,
            "kind": kind,
            "name": name,
            "locality": "",
            "degree": degree.get(pid, 0),
        }
        for pid, (kind, name) in names.items()
    ]
    return {"nodes": nodes, "links": links}
