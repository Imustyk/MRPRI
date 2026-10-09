"""Cached loaders for the real ETL snapshot and pipeline artefacts."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.utils.preprocessing import add_derived
from src.mtender.config import DATA_FEATURES, DATA_PROCESSED, MODELS, RESULTS, ROOT, TABLES
from src.mtender.features import FEATURE_COLUMNS, UNAVAILABLE

SCORE_FLAG_COLS = [
    "score_statistical_mad_zscore",
    "score_isolation_forest",
    "score_local_outlier_factor",
    "score_one_class_svm",
    "max_score",
    "n_models_flagging",
    "consensus",
    "flag_statistical_mad_zscore",
    "flag_isolation_forest",
    "flag_local_outlier_factor",
    "flag_one_class_svm",
]


@dataclass(frozen=True)
class DataBundle:
    tenders: pd.DataFrame
    scores: pd.DataFrame
    pca: pd.DataFrame
    demo: bool
    source_label: str
    artefacts: dict


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except pd.errors.ParserError:
        # Some snapshots contain raw `"` characters inside otherwise unquoted
        # fields (party names, titles). QUOTE_MINIMAL then treats the rest of
        # the physical line as an open quoted string and swallows following
        # records, which surfaces as "Expected N fields ... saw M". Re-read
        # with quoting disabled so the quote is kept as literal data.
        return pd.read_csv(path, low_memory=False, quoting=csv.QUOTE_NONE)


def _read_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner="Loading MTender snapshot…")
def _load_raw_features() -> pd.DataFrame:
    path = DATA_FEATURES / "features.csv"
    if path.exists() and path.stat().st_size > 0:
        return _read_csv(path)
    processed = DATA_PROCESSED / "tenders.json"
    if processed.exists() and processed.stat().st_size > 0:
        return pd.read_json(processed)
    return pd.DataFrame()

@st.cache_data(show_spinner="Loading anomaly scores…")
def _load_raw_scores() -> pd.DataFrame:
    return _read_csv(TABLES / "tender_anomaly_scores.csv")


@st.cache_data
def _load_pca() -> pd.DataFrame:
    return _read_csv(TABLES / "pca_projection.csv")


@st.cache_data
def load_artefact_table(name: str) -> pd.DataFrame:
    return _read_csv(TABLES / name)


@st.cache_data
def load_json_artefact(relpath: str):
    return _read_json(RESULTS / relpath)


@st.cache_data(show_spinner="Preparing analytics frame…")
def load_bundle() -> DataBundle:
    features = _load_raw_features()
    scores = _load_raw_scores()
    pca = _load_pca()
    demo = features.empty
    if demo:
        tenders = _demo_frame()
        source_label = "DEMO DATA — NOT REAL PROCUREMENT DATA"
    else:
        tenders = features
        source_label = "Real MTender OCDS snapshot (pipeline features.csv)"

    if not scores.empty and "ocid" in tenders.columns:
        keep = ["ocid"] + [c for c in SCORE_FLAG_COLS if c in scores.columns]
        extra = [c for c in ("pc1", "pc2") if c in scores.columns]
        tenders = tenders.merge(scores[keep + extra], on="ocid", how="left")
    if not pca.empty and "ocid" in tenders.columns:
        pca_keep = [c for c in ("ocid", "pc1", "pc2") if c in pca.columns]
        if "pc1" not in tenders.columns:
            tenders = tenders.merge(pca[pca_keep], on="ocid", how="left")

    tenders = add_derived(tenders)
    artefacts = {
        "model_comparison": load_artefact_table("model_comparison.csv"),
        "shap": load_artefact_table("shap_feature_importance.csv"),
        "permutation": load_artefact_table("permutation_importance.csv"),
        "feature_profiles": load_artefact_table("feature_profiles_by_flag.csv"),
        "feature_significance": load_artefact_table("feature_significance.csv"),
        "red_flags": load_artefact_table("red_flag_prevalence.csv"),
        "validation": load_json_artefact("validation_report.json") or {},
        "detection": load_json_artefact("mongo/detection_summary.json") or {},
        "explainability": load_json_artefact("mongo/explainability_summary.json") or {},
        "features_summary": load_json_artefact("mongo/features_summary.json") or {},
        "blacklist": load_artefact_table("blacklist_matches.csv"),
        "unavailable": UNAVAILABLE,
        "feature_columns": [c for c in FEATURE_COLUMNS if c in tenders.columns],
        "models_on_disk": (MODELS / "anomaly_models.joblib").exists(),
        "root": str(ROOT),
    }
    return DataBundle(
        tenders=tenders,
        scores=scores,
        pca=pca,
        demo=demo,
        source_label=source_label,
        artefacts=artefacts,
    )


def _demo_frame() -> pd.DataFrame:
    """Tiny synthetic frame used only when the real snapshot is missing.

    Labels in the UI must remain demo — this is never mixed into real KPIs.
    """
    rng = pd.date_range("2023-01-01", periods=40, freq="7D", tz="UTC")
    return pd.DataFrame(
        {
            "ocid": [f"DEMO-{i}" for i in range(40)],
            "tender_id": [f"DEMO-{i}" for i in range(40)],
            "title": [f"Demo procedure {i}" for i in range(40)],
            "status": ["complete"] * 30 + ["active"] * 10,
            "procurement_method": ["open"] * 25 + ["limited"] * 15,
            "procurement_method_details": ["opentender"] * 25 + ["directaward"] * 15,
            "buyer_name": [f"Demo procurer {i % 5}" for i in range(40)],
            "buyer_id": [f"BUY-{i % 5}" for i in range(40)],
            "winner_name": [f"Demo supplier {i % 8}" for i in range(40)],
            "winner_id": [f"SUP-{i % 8}" for i in range(40)],
            "cpv_primary": ["45000000-7"] * 20 + ["33000000-0"] * 20,
            "estimated_value": [10000 + 500 * i for i in range(40)],
            "award_value": [9000 + 400 * i for i in range(40)],
            "award_total": [9000 + 400 * i for i in range(40)],
            "n_bidders": [1, 2, 3, 0] * 10,
            "has_bid_data": [True, True, True, False] * 10,
            "has_award_data": [True] * 40,
            "published_date": rng,
            "tender_start": rng,
            "buyer_locality": ["Chișinău"] * 20 + ["Bălți"] * 20,
            "single_bidder": [1, 0, 0, 0] * 10,
            "currency": ["MDL"] * 40,
        }
    )


def filter_catalog(tenders: pd.DataFrame) -> dict:
    def uniq(col: str, n: int = 400) -> list[str]:
        if col not in tenders.columns:
            return []
        values = (
            tenders[col]
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .head(n)
            .index.tolist()
        )
        return sorted(values)

    dates = tenders["event_date"].dropna() if "event_date" in tenders.columns else pd.Series(dtype="datetime64[ns, UTC]")
    amounts = pd.to_numeric(tenders.get("award_amount"), errors="coerce")
    return {
        "methods": uniq("procurement_method", 50),
        "method_details": uniq("procurement_method_details", 80),
        "statuses": uniq("status", 40),
        "cpv_div": uniq("cpv_div", 99),
        "min_date": dates.min() if not dates.empty else None,
        "max_date": dates.max() if not dates.empty else None,
        "min_amount": float(amounts.min()) if amounts.notna().any() else 0.0,
        "max_amount": float(amounts.quantile(0.99)) if amounts.notna().any() else 0.0,
        "abs_max_amount": float(amounts.max()) if amounts.notna().any() else 0.0,
    }


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df
    if f.get("start") is not None and "event_date" in out.columns:
        start = pd.Timestamp(f["start"]).tz_localize("UTC")
        out = out[out["event_date"].isna() | (out["event_date"] >= start)]
    if f.get("end") is not None and "event_date" in out.columns:
        end = pd.Timestamp(f["end"]).tz_localize("UTC") + pd.Timedelta(days=1)
        out = out[out["event_date"].isna() | (out["event_date"] < end)]
    if f.get("methods"):
        out = out[out["procurement_method"].isin(f["methods"])]
    if f.get("method_details"):
        out = out[out["procurement_method_details"].isin(f["method_details"])]
    if f.get("statuses"):
        out = out[out["status"].isin(f["statuses"])]
    if f.get("cpv_div"):
        out = out[out["cpv_div"].isin(f["cpv_div"])]
    if f.get("procurer"):
        q = f["procurer"].strip().lower()
        if q:
            names = out["buyer_name"].fillna("").str.lower()
            ids = out.get("buyer_identifier", pd.Series("", index=out.index)).fillna("").astype(str).str.lower()
            out = out[names.str.contains(q, regex=False) | ids.str.contains(q, regex=False)]
    if f.get("supplier"):
        q = f["supplier"].strip().lower()
        if q:
            names = out["winner_name"].fillna("").str.lower()
            ids = out.get("winner_identifier", pd.Series("", index=out.index)).fillna("").astype(str).str.lower()
            out = out[names.str.contains(q, regex=False) | ids.str.contains(q, regex=False)]
    if f.get("min_value") is not None:
        out = out[out["award_amount"].isna() | (out["award_amount"] >= f["min_value"])]
    if f.get("max_value") is not None:
        out = out[out["award_amount"].isna() | (out["award_amount"] <= f["max_value"])]
    risk = f.get("risk", "Show all")
    if risk == "Normal":
        out = out[out["risk_band"].isin(["low", "unscored"])]
    elif risk == "Anomalous":
        out = out[out["is_anomalous"] == True]  # noqa: E712
    elif risk == "High-risk indicator":
        out = out[out["is_high_risk"] == True]  # noqa: E712
    return out
