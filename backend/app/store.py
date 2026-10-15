"""Loads the real analytical artefacts and serves them to the dashboard.

The single source of truth is the ETL output (``data/processed/tenders.json``)
plus the anomaly scores in MongoDB. Nothing here reads the synthetic generator,
so the API can never present invented indicators as measurements.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .adapter import UNAVAILABLE, build_graph, build_stats, project_tender
from .config import DATA_PROCESSED, MODELS_DIR, TABLES_DIR

# Real feature columns, i.e. the ones the ETL actually computes.
INDICATOR_COLUMNS = [
    "single_bidder",
    "short_deadline",
    "value_vs_cpv_median",
    "winner_share_of_buyer_awards",
    "buyer_supplier_repeat_share",
    "estimate_to_award_ratio",
    # n_bidders, not n_bids: bids.details is per-lot (see adapter.UNAVAILABLE).
    "n_bidders",
]


def _read(name: str):
    path = DATA_PROCESSED / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


#: ``$in`` is capped by the 16 MB BSON command limit, which a full-history
#: snapshot (one OCID per procurement, six years) exceeds, so the lookup is
#: chunked against the (ocid, run_id) index instead of sent as one huge query.
SCORE_LOOKUP_CHUNK = 5000


def _scores_by_ocid(ocids: list[str]) -> dict[str, dict]:
    """Latest anomaly score per OCID.

    Prefers MongoDB (the pipeline's own store), then falls back to
    ``results/tables/tender_anomaly_scores.csv``, which ``scripts/06`` also
    writes. Without the fallback the API reports *zero* scored records whenever
    Mongo has no ``anomaly_scores`` documents, every row collapses into the
    ``low`` band, and the whole risk section of the UI becomes one flat category.
    """
    if not ocids:
        return {}
    out: dict[str, dict] = {}
    unique = set(dict.fromkeys(ocids))
    try:
        from src.mtender.mongo_client import connect
        from src.mtender.mongo_schema import ANOMALY_SCORES
    except Exception:  # pragma: no cover - pipeline package not importable
        pass
    else:
        try:
            _, db = connect()
            for start in range(0, len(unique), SCORE_LOOKUP_CHUNK):
                chunk = list(unique)[start : start + SCORE_LOOKUP_CHUNK]
                # newest run first so a re-run supersedes older scores
                for doc in db[ANOMALY_SCORES].find({"ocid": {"$in": chunk}}).sort("run_id", -1):
                    out.setdefault(doc["ocid"], doc)
        except Exception:  # noqa: BLE001 - Mongo unavailable, fall back to CSV
            out = {}

    if len(out) < len(unique):
        for ocid, doc in _csv_scores().items():
            if ocid not in out and ocid in unique:
                out[ocid] = doc
    return out


#: Score columns that must be numbers. csv.DictReader yields every value as a
#: str, and adapter._num() deliberately refuses non-numeric input, so a CSV
#: fallback that skipped this coercion produced risk_level bands but a null
#: risk_score for every row - i.e. "scored: 0" next to a full band breakdown.
_SCORE_NUMERIC = (
    "score_statistical_mad_zscore",
    "score_isolation_forest",
    "score_local_outlier_factor",
    "score_one_class_svm",
    "max_score",
    "n_models_flagging",
    "flag_statistical_mad_zscore",
    "flag_isolation_forest",
    "flag_local_outlier_factor",
    "flag_one_class_svm",
    "consensus",
)


@lru_cache(maxsize=1)
def _csv_scores() -> dict[str, dict]:
    """Anomaly scores from the detection run's CSV export."""
    path = TABLES_DIR / "tender_anomaly_scores.csv"
    if not path.exists() or path.stat().st_size == 0:
        return {}
    import csv as _csv

    out: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        # Raw '"' characters occur inside unquoted party names in this export,
        # so quoting is disabled to keep them as literal data.
        for row in _csv.DictReader(fh, quoting=_csv.QUOTE_NONE):
            ocid = (row.get("ocid") or "").strip()
            if not ocid:
                continue
            for key in _SCORE_NUMERIC:
                if key in row:
                    row[key] = _to_number(row[key])
            out[ocid] = row
    return out


def _to_number(value):
    """Best-effort numeric coercion that leaves unusable input as None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


@lru_cache(maxsize=1)
def load_tenders() -> list[dict]:
    raw = _read("tenders.json") or []
    scores = _scores_by_ocid([r.get("ocid") for r in raw if r.get("ocid")])
    return [project_tender(r, scores.get(r.get("ocid"))) for r in raw]


@lru_cache(maxsize=1)
def load_meta() -> dict:
    raw = _read("tenders.json") or []
    base = _read("meta.json") or {}
    return {
        "source": "mtender-ocds (real public procurement data)",
        "n_tenders": len(raw),
        "scored": sum(1 for r in load_tenders() if r["risk_score"] is not None),
        "feature_columns": INDICATOR_COLUMNS,
        "indicator_columns": INDICATOR_COLUMNS,
        "unavailable": UNAVAILABLE,
        "risk_bands": {
            "unscored": "no detector output exists for this record (not a clearance)",
            "low": "no model flagged the record",
            "medium": "1 model flagged it",
            "high": "2 models flagged it",
            "critical": "3 or more models flagged it (consensus)",
        },
        "model": base.get("model", "IsolationForest + LOF + MAD z-score"),
        "etl_run_id": base.get("run_id"),
    }


@lru_cache(maxsize=1)
def load_stats() -> dict:
    return build_stats(load_tenders(), INDICATOR_COLUMNS)


@lru_cache(maxsize=64)
def load_graph(
    limit: int = 300,
    min_awards: int = 2,
    min_risk: float | None = None,
    sort: str = "awards",
) -> dict:
    """Bounded buyer-winner subgraph; every argument is part of the cache key.

    The parameters are cached individually so an analyst can widen the view
    (``min_awards=1``), ask only for the risky pairs or re-rank by value without
    re-reading ``tenders.json``, while ``invalidate()`` still drops every
    combination at once after a rebuild.
    """
    return build_graph(
        load_tenders(),
        limit=limit,
        min_awards=min_awards,
        min_risk=min_risk,
        sort=sort,
    )


# Cached like the other row-derived views: it walks all 152k rows on every call,
# and invalidate() clears it by name -- calling cache_clear() on an uncached
# function made POST /api/pipeline/run raise AttributeError after it had already
# overwritten data/processed.
@lru_cache(maxsize=1)
def load_indicators() -> dict:
    """Mean of each real indicator per risk band, with availability flags.

    A feature absent from the data yields ``None`` and ``available: false`` so
    the chart shows a gap instead of a fabricated zero.
    """
    rows = load_tenders()
    bands: dict[str, list[dict]] = {}
    for r in rows:
        bands.setdefault(r["risk_level"], []).append(r)

    out: dict[str, dict] = {}
    for band, items in bands.items():
        entry: dict = {"n": len(items)}
        for col in INDICATOR_COLUMNS:
            values = [i[col] for i in items if i.get(col) is not None]
            if not values:
                entry[col] = None
                entry.setdefault("unavailable", []).append(col)
            else:
                entry[col] = round(sum(values) / len(values), 3)
        out[band] = entry
    return out


@lru_cache(maxsize=1)
def load_model_kpis() -> dict:
    """Detector KPI catalogue plus live checks over the served scores.

    Cached like the other row-derived views: the report walks every served row
    once, and ``invalidate()`` clears it by name after a pipeline rebuild.
    """
    from .model_kpis import build_kpi_report

    return build_kpi_report(load_tenders())


def mongo_status() -> dict:
    """Live MongoDB topology, so the dashboard can prove its data source."""
    try:
        from src.mtender.mongo_client import (
            cluster_info,
            connect,
            supports_transactions,
        )
    except Exception as exc:  # pragma: no cover
        return {"connected": False, "error": str(exc)}
    try:
        client, db = connect()
        info = cluster_info(client)
    except Exception as exc:
        return {"connected": False, "error": str(exc)}
    info["connected"] = True
    info["database"] = db.name
    info["transactions"] = supports_transactions(client)
    info["collections"] = {
        name: db[name].count_documents({})
        for name in sorted(db.list_collection_names())
    }
    return info


def artefacts_ready() -> bool:
    return (DATA_PROCESSED / "tenders.json").exists()


def invalidate() -> None:
    load_tenders.cache_clear()
    load_meta.cache_clear()
    load_stats.cache_clear()
    load_graph.cache_clear()
    load_indicators.cache_clear()
    load_model_kpis.cache_clear()


def model_present() -> bool:
    return (MODELS_DIR / "detectors.joblib").exists()
