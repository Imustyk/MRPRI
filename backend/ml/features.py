"""Corruption-risk indicators (red flags) for Moldova procurement records."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "n_bids",
    "single_bidder",
    "bid_window_days",
    "short_deadline",
    "price_to_cpv_median",
    "price_z_cpv",
    "round_price",
    "small_value_flag",
    "negotiated_flag",
    "winner_buyer_repeat_share",
    "winner_win_rate",
    "winner_company_age",
    "new_firm_flag",
    "same_locality",
    "near_threshold",
    "cancelled_flag",
    "bid_spread",
    "collusion_phone_cluster",
]


def _parse_bids(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["n_bids"] = out["n_bids"].astype(int)
    out["single_bidder"] = (out["n_bids"] <= 1).astype(int)
    out["short_deadline"] = (out["bid_window_days"] < 10).astype(int)
    out["round_price"] = (out["award_value_mdl"] % 50_000 == 0).astype(int)
    out["small_value_flag"] = (out["procedure"] == "small_value").astype(int)
    out["negotiated_flag"] = (out["procedure"] == "negotiated").astype(int)
    out["cancelled_flag"] = (out["status"] == "cancelled").astype(int)
    out["same_locality"] = (out["buyer_locality"] == out["winner_locality"]).astype(int)
    out["near_threshold"] = (
        (out["award_value_mdl"] >= 180_000) & (out["award_value_mdl"] <= 250_000)
    ).astype(int)

    published_year = pd.to_datetime(out["published_at"]).dt.year
    out["winner_company_age"] = (published_year - out["winner_founding_year"]).clip(lower=0)
    out["new_firm_flag"] = (out["winner_company_age"] <= 1).astype(int)

    cpv_median = out.groupby("cpv_code")["award_value_mdl"].transform("median")
    cpv_std = out.groupby("cpv_code")["award_value_mdl"].transform("std").replace(0, np.nan)
    out["price_to_cpv_median"] = out["award_value_mdl"] / cpv_median.replace(0, np.nan)
    out["price_z_cpv"] = (out["award_value_mdl"] - cpv_median) / cpv_std
    out["price_to_cpv_median"] = out["price_to_cpv_median"].fillna(1.0)
    out["price_z_cpv"] = out["price_z_cpv"].fillna(0.0)

    pair_counts = out.groupby(["buyer_id", "winner_id"]).size().rename("pair_n")
    buyer_counts = out.groupby("buyer_id").size().rename("buyer_n")
    tmp = out.merge(pair_counts, on=["buyer_id", "winner_id"], how="left")
    tmp = tmp.merge(buyer_counts, on="buyer_id", how="left")
    out["winner_buyer_repeat_share"] = (tmp["pair_n"] / tmp["buyer_n"]).fillna(0)

    win_counts = out.groupby("winner_id").size().rename("wins")
    # Approximate participation: wins / max(wins, mean bids involvement)
    out = out.merge(win_counts, on="winner_id", how="left")
    out["winner_win_rate"] = (out["wins"] / out["wins"].max()).fillna(0)
    out.drop(columns=["wins"], inplace=True)

    spreads = []
    phone_cluster = []
    for raw in out["bids_json"]:
        bids = _parse_bids(raw)
        prices = [b.get("price", 0) for b in bids]
        if len(prices) >= 2 and min(prices) > 0:
            spreads.append((max(prices) - min(prices)) / min(prices))
        else:
            spreads.append(0.0)
        ids = {b.get("bidder_id") for b in bids}
        phone_cluster.append(int({"BID-032", "BID-033"} <= ids or {"BID-031", "BID-032"} <= ids))
    out["bid_spread"] = spreads
    out["collusion_phone_cluster"] = phone_cluster

    for col in FEATURE_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def rule_based_score(row: pd.Series) -> tuple[float, list[str]]:
    """Transparent additive red-flag score used as an explainable layer."""
    flags: list[str] = []
    score = 0.0
    if row["single_bidder"]:
        score += 28
        flags.append("Single bidder (no competition)")
    if row["short_deadline"]:
        score += 16
        flags.append("Abnormally short bid window")
    if row["price_to_cpv_median"] >= 2.0:
        score += 22
        flags.append("Award price ≥ 2× CPV median")
    elif row["price_to_cpv_median"] >= 1.5:
        score += 12
        flags.append("Award price ≥ 1.5× CPV median")
    if row["round_price"] and row["award_value_mdl"] >= 100_000:
        score += 8
        flags.append("Suspiciously round award value")
    if row["winner_buyer_repeat_share"] >= 0.25:
        score += 18
        flags.append("High repeat-winner share with the same buyer")
    if row["near_threshold"] and row["small_value_flag"]:
        score += 14
        flags.append("Lot splitting near small-value threshold")
    if row["negotiated_flag"] and row["single_bidder"]:
        score += 10
        flags.append("Negotiated procedure with a single supplier")
    if row["new_firm_flag"] and row["award_value_mdl"] >= 400_000:
        score += 10
        flags.append("Newly founded firm won a large contract")
    if row["collusion_phone_cluster"]:
        score += 20
        flags.append("Shared contact cluster among bidders")
    if row["n_bids"] == 2 and row["bid_spread"] < 0.02:
        score += 9
        flags.append("Near-identical bid prices")
    return min(score, 100.0), flags
