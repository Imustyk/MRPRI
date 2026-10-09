"""Derived columns computed once from the real snapshot."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.mtender.features import FEATURE_COLUMNS

FLAG_LABELS = {
    "single_bidder": "Potential low competition (single bidder)",
    "short_deadline": "Potential unusual short bidding window",
    "long_deadline": "Unusually long bidding window",
    "accelerated_like": "Accelerated / exception-like procedure wording",
    "no_award_after_tender": "Complete status with no published award value",
    "multi_award_tender": "Award split across several valued lots",
    "multi_supplier_award": "Several suppliers on one award",
    "cancelled": "Cancelled or unsuccessful",
    "amended": "Amended after publication",
    "no_bid_data": "No bid data published",
}

MODEL_SPECS = [
    {
        "key": "statistical_mad_zscore",
        "label": "Statistical (MAD z-score)",
        "flag": "flag_statistical_mad_zscore",
        "score": "score_statistical_mad_zscore",
        "implemented": True,
    },
    {
        "key": "isolation_forest",
        "label": "Isolation Forest",
        "flag": "flag_isolation_forest",
        "score": "score_isolation_forest",
        "implemented": True,
    },
    {
        "key": "local_outlier_factor",
        "label": "Local Outlier Factor",
        "flag": "flag_local_outlier_factor",
        "score": "score_local_outlier_factor",
        "implemented": True,
    },
    {
        "key": "one_class_svm",
        "label": "One-Class SVM",
        "flag": "flag_one_class_svm",
        "score": "score_one_class_svm",
        "implemented": True,
    },
    {
        "key": "autoencoder",
        "label": "Autoencoder",
        "flag": None,
        "score": None,
        "implemented": False,
    },
]


def risk_band(n_models_flagging) -> str:
    if n_models_flagging is None or (isinstance(n_models_flagging, float) and np.isnan(n_models_flagging)):
        return "unscored"
    n = int(n_models_flagging)
    if n >= 3:
        return "critical"
    if n == 2:
        return "high"
    if n == 1:
        return "medium"
    return "low"


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("published_date", "tender_start", "tender_end", "award_date", "list_date"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")

    if "published_date" in out.columns:
        event = out["published_date"]
    else:
        event = pd.Series(pd.NaT, index=out.index)
    if "tender_start" in out.columns:
        event = event.fillna(out["tender_start"])
    out["event_date"] = event
    out["event_year"] = out["event_date"].dt.year

    award_total = pd.to_numeric(out.get("award_total"), errors="coerce")
    award_value = pd.to_numeric(out.get("award_value"), errors="coerce")
    out["award_amount"] = award_total.fillna(award_value)
    out["estimated_value"] = pd.to_numeric(out.get("estimated_value"), errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = out["award_amount"] / out["estimated_value"].replace(0, np.nan)
    out["price_ratio"] = ratio.replace([np.inf, -np.inf], np.nan)

    cpv = out["cpv_primary"].astype(str) if "cpv_primary" in out.columns else pd.Series("", index=out.index)
    out["cpv_div"] = cpv.str.extract(r"^(\d{2})", expand=False).fillna("(missing)")

    n_bidders = pd.to_numeric(out.get("n_bidders"), errors="coerce")
    out["n_bidders"] = n_bidders
    has_bid = out["has_bid_data"] if "has_bid_data" in out.columns else n_bidders.fillna(0) > 0
    if has_bid.dtype == object:
        has_bid = has_bid.astype(str).str.lower().isin(("true", "1", "yes"))
    out["has_bid_data_bool"] = has_bid.fillna(False).astype(bool)
    out["single_bid_obs"] = out["has_bid_data_bool"] & (n_bidders == 1)

    if "n_models_flagging" in out.columns:
        out["risk_band"] = out["n_models_flagging"].map(risk_band)
        out["is_scored"] = out["n_models_flagging"].notna()
        out["is_anomalous"] = out["n_models_flagging"].fillna(0) >= 1
        out["is_high_risk"] = out["n_models_flagging"].fillna(0) >= 2
    else:
        out["risk_band"] = "unscored"
        out["is_scored"] = False
        out["is_anomalous"] = False
        out["is_high_risk"] = False

    present_flags = [c for c in FLAG_LABELS if c in out.columns]
    for col in present_flags:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["n_risk_indicators"] = out[present_flags].sum(axis=1) if present_flags else 0

    for col in FEATURE_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def indicator_badges(row: pd.Series) -> list[str]:
    badges = []
    for field, label in FLAG_LABELS.items():
        val = row.get(field)
        if val in (1, 1.0, True):
            badges.append(label)
    if pd.to_numeric(row.get("value_vs_cpv_median"), errors="coerce") not in (None,) and pd.notna(
        row.get("value_vs_cpv_median")
    ):
        if float(row["value_vs_cpv_median"]) >= 5:
            badges.append("Potential unusual contract value vs CPV median")
    share = pd.to_numeric(row.get("buyer_supplier_repeat_share"), errors="coerce")
    if pd.notna(share) and float(share) >= 0.25:
        badges.append("Repeated supplier–procurer relationship (share ≥ 25%)")
    return badges


#: Human labels for the numeric columns offered on the analytics page.
FEATURE_LABELS: dict[str, str] = {
    "award_amount": "Award total (MDL)",
    "award_value": "First award value (MDL)",
    "award_total": "Award total, all lots (MDL)",
    "estimated_value": "Estimated value (MDL)",
    "log_award_value": "log10 award value",
    "log_award_total": "log10 award total",
    "price_ratio": "Award / estimate",
    "value_vs_cpv_median": "Value vs CPV median",
    "value_zscore_cpv": "Value z-score within CPV",
    "estimate_to_award_ratio": "Estimate to award ratio",
    "n_bidders": "Distinct bidders",
    "n_bids": "Bid records (per lot)",
    "n_bidders_log": "log10 bidder count",
    "n_lots": "Lots",
    "n_items": "Items",
    "n_awards": "Awards",
    "n_contracts": "Contracts",
    "n_suppliers": "Suppliers",
    "n_cpvs": "CPV codes",
    "n_amendments": "Amendments",
    "bid_window_days": "Bidding window (days)",
    "buyer_supplier_repeat_share": "Repeat pair share",
    "winner_share_of_buyer_awards": "Winner share of buyer awards",
    "supplier_win_concentration": "Supplier win concentration",
    "supplier_award_count_log": "log10 supplier award count",
    "buyer_scale": "Procurer size band",
    "max_score": "Highest model score",
    "score_isolation_forest": "Isolation Forest score",
    "score_local_outlier_factor": "LOF score",
    "score_one_class_svm": "One-Class SVM score",
    "score_statistical_mad_zscore": "MAD z-score",
    "pc1": "Principal component 1",
    "pc2": "Principal component 2",
    "n_models_flagging": "Detectors flagging",
    "n_risk_indicators": "Risk indicators set",
}

#: Columns offered on the analytics page, in a sensible reading order. Kept as an
#: explicit allowlist so a stray ID or free-text column cannot end up on an axis.
NUMERIC_CATALOG: list[str] = [
    "award_amount",
    "estimated_value",
    "price_ratio",
    "value_vs_cpv_median",
    "value_zscore_cpv",
    "log_award_value",
    "n_bidders",
    "n_bids",
    "n_lots",
    "n_items",
    "n_awards",
    "n_contracts",
    "n_cpvs",
    "n_amendments",
    "bid_window_days",
    "buyer_supplier_repeat_share",
    "winner_share_of_buyer_awards",
    "supplier_win_concentration",
    "supplier_award_count_log",
    "max_score",
    "score_isolation_forest",
    "score_local_outlier_factor",
    "score_one_class_svm",
    "score_statistical_mad_zscore",
    "n_models_flagging",
    "n_risk_indicators",
    "pc1",
    "pc2",
]


def resample_rule(grain: str) -> str:
    return {
        "Daily": "D",
        "Weekly": "W",
        "Monthly": "MS",
        "Quarterly": "QS",
        "Yearly": "YS",
    }.get(grain, "MS")
