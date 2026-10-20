"""Loads the real analytical artefacts and serves them to the dashboard.

The single source of truth is the ETL output (``data/processed/tenders.json``)
plus the anomaly scores in MongoDB. Nothing here reads the synthetic generator,
so the API can never present invented indicators as measurements.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from functools import lru_cache
from pathlib import Path

from .adapter import FLAG_FEATURES, UNAVAILABLE, build_graph, build_stats, project_tender
from .config import DATA_PROCESSED, MODELS_DIR, RESULTS, TABLES_DIR

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


def _read_results(*parts: str) -> dict | None:
    """Read a JSON artefact under ``results/``; ``None`` when absent/broken.

    Research artefacts are optional inputs to the API: a missing or truncated
    file must degrade to "unavailable" in the payload, never to a 500.
    """
    path = RESULTS.joinpath(*parts)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


#: The synthetic generator writes a different record schema (it carries
#: ``planted_pattern``), so the head of the served file is enough to say
#: which dataset the API is actually looking at - without loading 249 MB.
_ORIGIN_SYNTHETIC_MARKER = '"planted_pattern"'
_ORIGIN_REAL_MARKER = '"procurement_method_details"'
_ORIGIN_PROBE_BYTES = 65536


@lru_cache(maxsize=1)
def origin_kind() -> str:
    """``"real-ocds"`` or ``"synthetic-demo"`` for the served ``tenders.json``.

    Used by /api/meta and /api/dataset so the UI can never mislabel a
    synthetic demo run as real procurement data (and vice versa).
    """
    path = DATA_PROCESSED / "tenders.json"
    if not path.exists():
        return "missing"
    try:
        head = path.open(encoding="utf-8", errors="replace").read(_ORIGIN_PROBE_BYTES)
    except OSError:
        return "unknown"
    if _ORIGIN_SYNTHETIC_MARKER in head:
        return "synthetic-demo"
    if _ORIGIN_REAL_MARKER in head:
        return "real-ocds"
    return "unknown"


def _sha256(path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


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


#: Detectors of the frozen production ensemble (detection_summary.json order).
_PRODUCTION_MODEL_LABEL = (
    "v0 production: MAD robust z-score + IsolationForest + LOF + "
    "One-Class SVM (4-vote consensus)"
)


def _detection_run() -> dict | None:
    return _read_results("mongo", "detection_summary.json")


#: Public alias: the research router needs the run identity (model run id +
#: scoring date) of the scores it is explaining.
detection_run = _detection_run


@lru_cache(maxsize=1)
def load_meta() -> dict:
    raw = _read("tenders.json") or []
    origin = origin_kind()
    summary = _detection_run() or {}
    run_id = summary.get("run_id")
    if origin == "synthetic-demo":
        source = "SYNTHETIC DEMO data (pipeline source=synthetic) - not real procurement data"
    elif origin == "real-ocds":
        source = "mtender-ocds (real public procurement data)"
    else:
        source = "unknown origin (tenders.json absent or unrecognised schema)"
    return {
        "source": source,
        "data_origin": origin,
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
        # Legacy meta.json belongs to the synthetic generator and carries its
        # own model name; serving it against real rows was the documented
        # defect (docs/IMPROVEMENT_PLAN.md, phase 2). The production label is
        # derived from the detection run, never from the demo artefact.
        "model": _PRODUCTION_MODEL_LABEL,
        "model_run_id": run_id,
        "scoring_generated_at": summary.get("generated_at"),
        # Kept for old clients; the value now points at the run that actually
        # produced the scores being served.
        "etl_run_id": run_id,
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


# --------------------------------------------------------------------------- #
# Research provenance views (added 2026-10-20, branch feature/risk-specific-detection)
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def search_keys() -> list[str]:
    """Lowercased search haystacks aligned with ``load_tenders()`` order.

    /api/tenders used to lower four fields on all 152k rows per request; the
    key is now built once per dataset version (NUL separator so a needle
    cannot match across field boundaries) and cleared by ``invalidate()``.
    """
    fields = ("title", "buyer_name", "winner_name", "tender_id")
    return [
        "\x00".join(str(r.get(f) or "").lower() for f in fields)
        for r in load_tenders()
    ]


#: Numeric fields whose corpus distribution backs per-procedure percentiles.
_EXPLAIN_NUMERIC = (
    "risk_score",
    "rule_score",
    "iso_score",
    "lof_score",
    "svm_score",
    "n_bidders",
    "bid_window_days",
    "value_vs_cpv_median",
    "estimate_to_award_ratio",
    "winner_share_of_buyer_awards",
    "buyer_supplier_repeat_share",
    "award_value_mdl",
    "award_total_mdl",
    "estimated_value_mdl",
)


@lru_cache(maxsize=1)
def load_population_stats() -> dict:
    """Population aggregates behind the per-procedure explanation endpoint.

    Pure function of the served rows: sorted value arrays (percentiles) and
    corpus-wide trigger rates per risk indicator, so an explanation never
    invents a reference the data does not contain. Cleared by ``invalidate()``.
    """
    rows = load_tenders()
    sorted_cols: dict[str, list[float]] = {}
    for col in _EXPLAIN_NUMERIC:
        vals = sorted(
            float(v)
            for v in (r.get(col) for r in rows)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v
        )
        if vals:
            sorted_cols[col] = vals

    flag_rates: dict[str, dict] = {}
    for field, label in FLAG_FEATURES.items():
        n = 0
        for r in rows:
            if label in (r.get("flags") or []):
                n += 1
        flag_rates[field] = {
            "label": label,
            "n": n,
            "rate": (n / len(rows)) if rows else None,
        }

    band_counts: dict[str, int] = {}
    scored = 0
    year_from = year_to = None
    for r in rows:
        band = r.get("risk_level") or "unscored"
        band_counts[band] = band_counts.get(band, 0) + 1
        if r.get("risk_score") is not None:
            scored += 1
        year = str(r.get("tender_start") or "")[:4]
        if year.isdigit() and len(year) == 4:
            year_from = year if year_from is None or year < year_from else year_from
            year_to = year if year_to is None or year > year_to else year_to

    return {
        "n": len(rows),
        "n_scored": scored,
        "sorted": sorted_cols,
        "flag_rates": flag_rates,
        "band_counts": band_counts,
        "year_from": year_from,
        "year_to": year_to,
    }


def percentile(sorted_vals: list[float], value: float | None) -> float | None:
    """Percentile (0-100, mid-rank for ties) of ``value`` in a sorted array.

    Deterministic and dependency-free: the same row and dataset always yield
    the same explanation. ``None`` when the value or the distribution is
    absent - reported as "no reference distribution", never as zero.
    """
    if value is None or not sorted_vals or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v:  # NaN
        return None
    lo = bisect_left(sorted_vals, v)
    hi = bisect_right(sorted_vals, v)
    mid = (lo + hi) / 2.0
    return round(100.0 * mid / len(sorted_vals), 1)


def _file_entry(path) -> dict | None:
    from .config import ROOT as _ROOT

    try:
        stat = path.stat()
        rel = str(path.relative_to(_ROOT))
    except (OSError, ValueError):
        return None
    return {
        "path": rel,
        "bytes": stat.st_size,
        "modified_at": _iso(stat.st_mtime),
    }


def _iso(ts: float) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat(
        timespec="seconds"
    )


def _manifest_entries(manifest: dict) -> list[dict]:
    """Manifest outputs keyed by absolute path -> relative file entries."""
    from .config import ROOT as _ROOT

    out = []
    for key, val in (manifest.get("outputs") or {}).items():
        if not isinstance(val, dict) or "sha256" not in val:
            continue
        try:
            rel = str(Path(key).relative_to(_ROOT))
        except Exception:  # noqa: BLE001 - foreign path, fall back to basename
            rel = str(key).replace("\\", "/").rsplit("/", 1)[-1]
        out.append(
            {"path": rel, "bytes": val.get("bytes"), "sha256": val.get("sha256")}
        )
    return out


@lru_cache(maxsize=2)
def load_dataset_report(verify_hash: bool = False) -> dict:
    """Dataset/provenance metadata for GET /api/dataset.

    Answers the audit brief's provenance requirements: record counts and
    schema sanity, model version + scoring date, links back to original
    artefacts, and an explicit real-vs-synthetic verdict with evidence.
    ``verify_hash=True`` recomputes SHA-256 and compares against the export
    manifest (cached separately from the cheap variant).
    """
    from .config import ROOT as _ROOT

    stats = load_population_stats()
    origin = origin_kind()
    manifest = _read_results("mongo", "export_manifest.json") or {}
    summary = _detection_run() or {}

    files = [
        entry
        for entry in (
            _file_entry(DATA_PROCESSED / "tenders.json"),
            _file_entry(DATA_PROCESSED / "meta.json"),
            _file_entry(_ROOT / "data" / "features" / "features.csv"),
            _file_entry(TABLES_DIR / "tender_anomaly_scores.csv"),
            _file_entry(RESULTS / "models" / "anomaly_models.joblib"),
            _file_entry(RESULTS / "mongo" / "export_manifest.json"),
        )
        if entry
    ]

    manifest_hashes = {
        e["path"]: e["sha256"] for e in _manifest_entries(manifest) if e["sha256"]
    }
    verification: dict = {
        "hash_verified": False,
        "hash_matches_manifest": None,
        "compared_files": 0,
        "mismatches": [],
    }
    if verify_hash and manifest_hashes:
        mismatches = []
        compared = 0
        for rel, expected in manifest_hashes.items():
            path = _ROOT / rel
            if not path.exists() or path.stat().st_size == 0:
                continue
            compared += 1
            actual = _sha256(path)
            if actual != expected:
                mismatches.append(
                    {"path": rel, "expected": expected, "actual": actual}
                )
        verification = {
            "hash_verified": compared > 0,
            "hash_matches_manifest": compared > 0 and not mismatches,
            "compared_files": compared,
            "mismatches": mismatches,
        }

    model_flags = {
        m.get("model"): m.get("n_flagged")
        for m in (summary.get("models") or [])
        if isinstance(m, dict)
    }
    return {
        "origin": {
            "kind": origin,
            "synthetic_in_use": origin == "synthetic-demo",
            "meta_declared_source": (_read("meta.json") or {}).get("source"),
            "evidence": (
                "record schema probed from the head of data/processed/tenders.json "
                "(procurement_method_details = real ETL output; planted_pattern = "
                "synthetic generator output)"
            ),
        },
        "corpus": {
            "records": stats["n"],
            "scored": stats["n_scored"],
            "unscored": stats["n"] - stats["n_scored"],
            "year_from": stats["year_from"],
            "year_to": stats["year_to"],
            "band_counts": stats["band_counts"],
        },
        "files": files,
        "manifest": {
            "exported_at": manifest.get("exported_at"),
            "n_documents": manifest.get("n_documents"),
            "entries": _manifest_entries(manifest),
        },
        "scoring": {
            "run_id": summary.get("run_id"),
            "generated_at": summary.get("generated_at"),
            "contamination": summary.get("contamination_assumption"),
            "random_state": summary.get("random_state"),
            "n_feature_columns": len(summary.get("feature_columns") or []) or None,
            "rows_in_run": summary.get("n_rows"),
            "scores_source": (
                "MongoDB anomaly_scores with CSV fallback "
                "(results/tables/tender_anomaly_scores.csv)"
            ),
            "scored_rows_in_csv": len(_csv_scores()),
        },
        "model": {
            "version": "v0",
            "role": "production baseline (unchanged; no experimental model is promoted)",
            "label": _PRODUCTION_MODEL_LABEL,
            "detectors": model_flags,
            "artefact": "results/models/anomaly_models.joblib",
            "artefact_present": (RESULTS / "models" / "anomaly_models.joblib").exists(),
        },
        "verification": verification,
        "disclaimer": (
            "An anomaly score is an indicator of potential risk, not evidence of "
            "corruption or a violation. Competent-authority verification required."
        ),
    }


def _csv_rows(path, limit: int | None = None) -> list[dict]:
    """Small CSV artefact (importance tables) as plain dicts, no pandas."""
    if not path.exists():
        return []
    import csv as _csv

    out: list[dict] = []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            for row in _csv.DictReader(fh):
                out.append(dict(row))
                if limit is not None and len(out) >= limit:
                    break
    except OSError:
        return []
    return out


def _num_or_str(value):
    if not isinstance(value, str):
        return value
    try:
        f = float(value)
    except ValueError:
        return value
    if f == f and abs(f) != float("inf"):
        # keep integers crisp
        return int(f) if f.is_integer() and "." not in value else f
    return value


@lru_cache(maxsize=1)
def load_evaluation() -> dict:
    """Research evaluation metrics for GET /api/evaluation.

    Assembles only figures that exist in ``results/methodology`` artefacts -
    external label AUCs with cluster CIs, baselines, seed/noise stability,
    drift and bias summaries - so the dashboard can show model reliability
    honestly instead of hiding negative results. Missing artefacts degrade to
    ``available: false`` entries, never to fabricated numbers.
    """
    tv = _read_results("methodology", "final_verification.json") or {}
    ansc = _read_results("methodology", "ansc_external_check.json") or {}
    thr = _read_results("methodology", "threshold_calibration.json") or {}
    noise = _read_results("methodology", "noise_sensitivity.json") or {}
    bias = _read_results("methodology", "bias_audit.json") or {}
    summary = _detection_run() or {}

    ext = tv.get("external_headline") or {}
    conc = tv.get("aap_supplier_concentration") or {}
    seed = tv.get("seed_stability") or {}
    v0 = ansc.get("v0_external") or {}
    cluster = v0.get("cluster_by_buyer") if isinstance(v0, dict) else None
    cluster = cluster if isinstance(cluster, dict) else {}
    verdict = ansc.get("verdict") or {}

    regimes = []
    for rid, entry in (noise.get("aggregate") or {}).items():
        if not isinstance(entry, dict):
            continue

        def _m(key):
            v = entry.get(key)
            return v.get("mean") if isinstance(v, dict) else None

        def _band(prefix):
            v = entry.get("band_change_pct_" + prefix)
            if isinstance(v, dict):
                return v.get("mean")
            return None

        regimes.append(
            {
                "id": rid,
                "n_runs": entry.get("n_runs"),
                "spearman": _m("spearman_max_score"),
                "spearman_ci_low": _m("spearman_ci_low"),
                "spearman_ci_high": _m("spearman_ci_high"),
                "top200_jaccard": _m("jaccard_top200_score"),
                "band_change_pct": _m("band_change_pct"),
                "directaward_spearman": _m("spearman_type_directaward"),
                "directaward_band_change_pct": _band("type_directaward"),
            }
        )

    drift_rows = [d for d in (thr.get("drift") or []) if isinstance(d, dict)]
    psi_values = [d["psi"] for d in drift_rows if isinstance(d.get("psi"), (int, float))]
    ks_values = [
        d["ks_statistic"]
        for d in drift_rows
        if isinstance(d.get("ks_statistic"), (int, float))
    ]

    aap = {
        "id": "aap",
        "label": "AAP supplier interdiction list (proxy label)",
        "available": bool(ext),
        "roc_auc": ext.get("roc_auc_max_score"),
        "pr_auc": ext.get("pr_auc_max_score"),
        "base_rate": ext.get("base_rate"),
        "precision_votes_ge3": ext.get("votes_ge_3_precision"),
        "supplier_concentration": conc or None,
        "caveat": (
            "Proxy label: procedures of sanctioned suppliers, not ground truth. "
            "The label is driven by size and competition (single-feature "
            "n_bidders baseline ~0.80); the 4-vote ensemble at ~0.49 is at "
            "random level - reported as measured."
        ),
    }
    ansc_entry = {
        "id": "ansc",
        "label": "Procedure contested (ANSC complaints document; proxy label)",
        "available": bool(cluster),
        "roc_auc": cluster.get("point"),
        "cluster_ci": cluster.get("ci"),
        "cluster_by": "buyer" if cluster else None,
        "n_boot": cluster.get("n_boot"),
        "n_clusters": cluster.get("n_clusters"),
        "procedure_metric": v0.get("procedure"),
        "precision": v0.get("precision"),
        "base_rate_main_population": v0.get("base_rate_main_population"),
        "baselines": ansc.get("baselines"),
        "verdict_code": verdict.get("code"),
        "verdict_text": verdict.get("text"),
        "caveat": (
            "Complaints are a contested-procedure marker, not a confirmed "
            "violation: ANSC decisions were not accessible for this corpus, "
            "so confirmed vs rejected appeals cannot be distinguished."
        ),
    }

    return {
        "production": {
            "version": "v0",
            "unchanged": True,
            "run_id": summary.get("run_id"),
            "generated_at": summary.get("generated_at"),
            "boundary": thr.get("production_boundary"),
            "tune_period": thr.get("tune_period"),
            "test_period": thr.get("test_period"),
        },
        "external_labels": [aap, ansc_entry],
        "seed_stability": seed or None,
        "noise_sensitivity": {
            "available": bool(noise),
            "verdicts": noise.get("verdicts"),
            "regimes": regimes,
            "note": (
                "Input-noise experiment (measurement, not a cycle): score ranks "
                "are stable for exact/near-exact inputs but positions move under "
                "counterfactual noise; review top-K lists, not exact ranks."
            ),
        },
        "drift": {
            "psi_max": max(psi_values) if psi_values else None,
            "ks_max": max(ks_values) if ks_values else None,
            "overfitting_warning": thr.get("overfitting_warning"),
            "note": (
                "Score-distribution drift between tune (2018-2021) and test "
                "(2022-2024): the vote boundary needs periodic recalibration."
            ),
        },
        "bias": {
            "n_dimensions": bias.get("n_dimensions"),
            "high_plus_share_corpus": bias.get("high_plus_share_corpus"),
            "critical_share_corpus": bias.get("critical_share_corpus"),
            "verdict_counts": bias.get("verdict_counts"),
            "available": bool(bias),
        },
        "disclaimer": tv.get("disclaimer")
        or (
            "External labels are proxies with known selection bias. An anomaly "
            "score is a potential risk indicator, not evidence of corruption."
        ),
    }


@lru_cache(maxsize=1)
def load_explainability() -> dict:
    """Global explainability artefacts for GET /api/explainability.

    Deliberately reports the SHAP/LIME disagreement as measured (the audit
    found them *not* consistent) instead of presenting a single \"explanation\".
    """
    xai = _read_results("methodology", "xai_consistency.json") or {}
    summary = _read_results("mongo", "explainability_summary.json") or {}
    perm = [
        {
            "feature": r.get("feature"),
            "mean": _num_or_str(r.get("perm_importance_mean")),
            "std": _num_or_str(r.get("perm_importance_std")),
        }
        for r in _csv_rows(TABLES_DIR / "permutation_importance.csv", limit=50)
    ]
    shap = [
        {"feature": r.get("feature"), "mean_abs": _num_or_str(r.get("mean_abs_shap"))}
        for r in _csv_rows(TABLES_DIR / "shap_feature_importance.csv", limit=50)
    ]
    agreement = xai.get("agreement") or {}
    return {
        "model_explained": xai.get("model_explained"),
        "why_same_model": xai.get("why_same_model"),
        "xai_consistency": {
            "available": bool(xai),
            "verdict": xai.get("verdict"),
            "agreement": agreement,
            "low_agreement_diagnosis": xai.get("low_agreement_diagnosis"),
            "disclaimer": xai.get("disclaimer"),
        },
        "global_summary": {
            "available": bool(summary),
            "stage": summary.get("stage"),
            "generated_at": summary.get("generated_at"),
            "shap_status": summary.get("shap_status"),
            "strongest_separators": summary.get("strongest_separators"),
            "permutation_importance_top": summary.get("permutation_importance_top"),
            "unavailable_indicators": summary.get("unavailable_indicators"),
        },
        "permutation_importance": perm,
        "shap_importance": shap,
        "notes": [
            "SHAP values here are computed for the Isolation Forest only; LOF, "
            "One-Class SVM and MAD have no per-row attributions.",
            "SHAP and LIME disagree on this model (see xai_consistency.verdict); "
            "treat attributions as model-internal, not causal.",
        ],
        "disclaimer": (
            "Explanations describe why the model scored a record unusually; they "
            "are not causal proof and not evidence of a violation."
        ),
    }


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
    # Bug fixed 2026-10-20: the CSV fallback cache was never cleared, so after
    # a rebuild the API kept serving the scores of the *previous* run (stale
    # data risk the audit brief explicitly forbids). New caches follow the
    # same by-name convention.
    _csv_scores.cache_clear()
    origin_kind.cache_clear()
    search_keys.cache_clear()
    load_population_stats.cache_clear()
    load_dataset_report.cache_clear()
    load_evaluation.cache_clear()
    load_explainability.cache_clear()


def model_present() -> bool:
    return (MODELS_DIR / "detectors.joblib").exists()
