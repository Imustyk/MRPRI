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

#: The four detectors ``scripts/06_detect_anomalies.py`` runs, in run order.
#: Score documents carry ``score_<key>`` and ``flag_<key>`` for each of them, so
#: the same keys drive the per-detector verdicts here and the KPI checks in
#: ``model_kpis.py``.
MODEL_KEYS = (
    "statistical_mad_zscore",
    "isolation_forest",
    "local_outlier_factor",
    "one_class_svm",
)

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


def _bin_flag(value: Any) -> bool | None:
    """One detector's verdict: ``True`` / ``False`` / ``None`` = never scored.

    ``_flag`` collapses everything it does not recognise into ``False``, which is
    right for a red-flag *feature* (absent == not set) but wrong for a detector
    verdict, where "scored and cleared" and "never examined" are different
    claims. The detection run writes ``flag_<model>`` as 0/1 ints and the CSV
    fallback serves them as 0.0/1.0 floats, so both are accepted; anything else
    (strings such as ``"0"``, out-of-range numbers, a missing column) stays
    ``None`` rather than being read as a negative verdict.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value) if value in (0, 1) else None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return bool(value) if value in (0.0, 1.0) else None
    return None


def project_tender(row: dict, score: dict | None) -> dict:
    """Map one real tender (+ its anomaly score) to the dashboard contract."""
    score = score or {}
    flags = [label for field, label in FLAG_FEATURES.items() if _flag(row.get(field))]
    n_flagging = score.get("n_models_flagging")
    # Per-detector verdicts, kept tri-state: True/False only when this run
    # actually scored the record, None when no score document exists. That is
    # what lets the UI (and the KPI checks) separate "four detectors looked and
    # disagreed" from "no detector ever looked".
    model_flags = {key: _bin_flag(score.get(f"flag_{key}")) for key in MODEL_KEYS}

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
        # null = this detector never scored the record (see _bin_flag)
        "model_flags": model_flags,
        "consensus_flag": _bin_flag(score.get("consensus")),
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


#: Ranking modes ``/api/graph`` accepts, shared with the query validation in
#: ``main.py`` and the toolbar in the UI so the three cannot drift apart.
GRAPH_SORTS = ("awards", "risk", "value")


def build_graph(
    rows: list[dict],
    *,
    limit: int = 300,
    min_awards: int = 2,
    min_risk: float | None = None,
    sort: str = "awards",
) -> dict:
    """Buyer <-> winner bipartite network, bounded and honest about the bound.

    Why an edge needs ``min_awards`` awards
    ---------------------------------------
    The full history holds ~63k distinct buyer-supplier pairs, but the large
    majority are a single award: a transaction, not a relationship. The
    relational view exists to expose *repeat* ties, so by default a pair only
    qualifies once the same supplier has won twice from the same authority.

    Why the payload is bounded
    --------------------------
    Even after that filter there are ~20k qualifying pairs over ~7k parties --
    far more than a screen can show. Rather than silently dropping to the 60
    most connected nodes (which showed under 1% of the network and chose nodes
    by degree instead of relevance), the pairs are ranked by ``sort`` and the
    top ``limit`` are returned together with a ``stats`` block that states
    exactly what was left out: qualifying pairs, parties, awards and awarded
    value in the full set versus the returned slice. The UI is then able to
    say "showing 300 of 20,127 relationships, 4.1% of the awarded value"
    instead of pretending the drawing *is* the network.

    Node totals (``awards``, ``value``, ``max_risk``, ``n_partners``) are
    aggregated over every qualifying pair, not only the drawn ones, so a
    party's card keeps its real magnitude even when the ``limit`` clipped one
    of its relationships away.
    """
    limit = max(0, int(limit))
    min_awards = max(1, int(min_awards))
    if sort not in GRAPH_SORTS:
        sort = "awards"
    if min_risk is not None:
        min_risk = max(0.0, min(100.0, float(min_risk)))

    # One pass over the rows: per-pair aggregates plus the metadata needed to
    # label a node later. A score that is not a finite percentile (absent, or a
    # NaN that leaked out of the detector) is dropped rather than fed to max():
    # a single NaN would poison every comparison downstream and silently order
    # the whole network wrong.
    pairs: dict[tuple[str, str], dict] = {}
    meta: dict[str, dict] = {}
    for r in rows:
        b = _s(r.get("buyer_id"))
        w = _s(r.get("winner_id"))
        if not b or not w:
            continue

        risk = r.get("risk_score")
        if isinstance(risk, bool) or not isinstance(risk, (int, float)) or not math.isfinite(risk):
            risk = None
        else:
            risk = float(risk)

        value = r.get("award_total_mdl") or r.get("award_value_mdl") or 0.0
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            value = 0.0

        p = pairs.get((b, w))
        if p is None:
            p = pairs[(b, w)] = {"n": 0, "value": 0.0, "max_risk": None}
        p["n"] += 1
        p["value"] += float(value)
        if risk is not None and (p["max_risk"] is None or risk > p["max_risk"]):
            p["max_risk"] = risk

        if b not in meta:
            meta[b] = {
                "kind": "buyer",
                "name": _s(r.get("buyer_name")) or b,
                "locality": _s(r.get("buyer_locality")),
            }
        if w not in meta:
            # MTender publishes no registered address for winners, so a supplier
            # locality is genuinely unknown rather than empty-by-omission.
            meta[w] = {"kind": "supplier", "name": _s(r.get("winner_name")) or w, "locality": ""}

    def qualifies(v: dict) -> bool:
        if v["n"] < min_awards:
            return False
        if min_risk is None:
            return True
        # A threshold excludes unscored pairs: "at least percentile X" cannot
        # be satisfied by a record no model ever scored.
        return v["max_risk"] is not None and v["max_risk"] >= min_risk

    qualifying = {k: v for k, v in pairs.items() if qualifies(v)}

    def rank(item: tuple[tuple[str, str], dict]) -> tuple:
        (pair, v) = item
        # None must sort last, never first: an unscored pair is not the least
        # risky one, it is the unexamined one.
        risk_key = -v["max_risk"] if v["max_risk"] is not None else math.inf
        if sort == "risk":
            head = (risk_key, -v["n"], -v["value"])
        elif sort == "value":
            head = (-v["value"], -v["n"], risk_key)
        else:
            head = (-v["n"], risk_key, -v["value"])
        # The pair id breaks ties so the same request always returns the same
        # slice instead of depending on the order rows happen to arrive in.
        return head + pair

    shown = sorted(qualifying.items(), key=rank)[:limit]

    # Aggregates cover every qualifying pair, so a node's totals stay meaningful
    # even when the limit clipped one of its relationships out of the drawing.
    agg: dict[str, dict] = {}
    partners: dict[str, set[str]] = {}
    for (b, w), v in qualifying.items():
        for pid, other in ((b, w), (w, b)):
            a = agg.get(pid)
            if a is None:
                a = agg[pid] = {"awards": 0, "value": 0.0, "max_risk": None}
            a["awards"] += v["n"]
            a["value"] += v["value"]
            if v["max_risk"] is not None and (a["max_risk"] is None or v["max_risk"] > a["max_risk"]):
                a["max_risk"] = v["max_risk"]
            partners.setdefault(pid, set()).add(other)

    links = [
        {
            "source": b,
            "target": w,
            "weight": v["n"],
            "value": round(v["value"], 2),
            "max_risk": round(v["max_risk"], 2) if v["max_risk"] is not None else None,
        }
        for (b, w), v in shown
    ]

    # ``degree`` is the partners actually drawn (drives layout and node size);
    # ``n_partners`` is the party's full qualifying fan-out (drives the panel).
    degree: dict[str, int] = {}
    for link in links:
        degree[link["source"]] = degree.get(link["source"], 0) + 1
        degree[link["target"]] = degree.get(link["target"], 0) + 1

    nodes = [
        {
            "id": pid,
            "kind": meta[pid]["kind"],
            "name": meta[pid]["name"],
            "locality": meta[pid]["locality"],
            "degree": degree[pid],
            "awards": a["awards"],
            "value": round(a["value"], 2),
            "max_risk": round(a["max_risk"], 2) if a["max_risk"] is not None else None,
            "n_partners": len(partners.get(pid, ())),
        }
        for pid, a in sorted(agg.items(), key=lambda kv: (-kv[1]["awards"], kv[0]))
        if pid in degree
    ]

    stats = {
        "limit": limit,
        "min_awards": min_awards,
        "min_risk": min_risk,
        "sort": sort,
        "pairs_all": len(pairs),
        "pairs_repeated": sum(1 for v in pairs.values() if v["n"] >= 2),
        "pairs_qualifying": len(qualifying),
        "pairs_shown": len(links),
        "nodes_qualifying": len(agg),
        "nodes_shown": len(nodes),
        "awards_qualifying": sum(v["n"] for v in qualifying.values()),
        "awards_shown": sum(v["n"] for _, v in shown),
        "value_qualifying": round(sum(v["value"] for v in qualifying.values()), 2),
        "value_shown": round(sum(v["value"] for _, v in shown), 2),
        "truncated": len(shown) < len(qualifying),
    }
    return {"nodes": nodes, "links": links, "stats": stats}
