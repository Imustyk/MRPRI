"""Corruption-risk indicator features, computed only from fields verified to
exist in the MTender OCDS response (see docs/DATA_DICTIONARY.md).

A feature is implemented only if every input it needs was observed in the real
data. ``FEATURE_COLUMNS`` is therefore a subset of the normalised schema, and
``unavailable`` records the indicators that could not be built and why.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Features whose inputs are all present in the verified MTender data.
FEATURE_COLUMNS = [
    # financial
    "log_award_value",
    "value_vs_cpv_median",
    "value_zscore_cpv",
    "estimate_to_award_ratio",
    "log_award_total",
    "multi_award_tender",
    # competition
    "n_bidders_log",
    "single_bidder",
    "no_bid_data",
    "multi_supplier_award",
    # procedural
    "bid_window_days",
    "short_deadline",
    "long_deadline",
    "n_amendments",
    "amended",
    "accelerated_like",
    "cancelled",
    "no_award_after_tender",
    # behavioural (computed by the caller from group statistics)
    "buyer_supplier_repeat_share",
    "winner_share_of_buyer_awards",
    "supplier_win_concentration",
    "supplier_award_count_log",
]

#: Indicators that cannot be computed from the verified MTender response, and why.
UNAVAILABLE = {
    "winning_margin": "awards expose no per-supplier split of the award value",
    "bid_spread": "bids.details values are published only for a small minority of procurements",
    "direct_award_flag": "no field in the response marks a single-source award",
    "supplier_age": "party.details carries no founding date",
    "change_in_award_value": "no amended award values observed",
    "collusion_contact_cluster": "party.contactPoint is the literal string '-' for most parties",
}

# Produced by add_behavioural_features (needs cross-tender group statistics,
# so it cannot be part of the per-row FEATURE_COLUMNS contract).
BEHAVIOURAL_COLUMNS = (
    "buyer_supplier_repeat_share",
    "winner_share_of_buyer_awards",
    "supplier_win_concentration",
    "supplier_award_count_log",
    "relationship_features_available",
)

_CATEGORICAL = ["procurement_method", "procurement_method_details", "main_procurement_category", "buyer_scale"]


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Fetch a column as an all-NaN Series when it is absent.

    ``DataFrame.get`` returns ``None`` for a missing column, which then breaks
    every chained ``.fillna()``. Treating an absent column as "all missing" keeps
    the documented behaviour: a field the publisher does not supply becomes an
    explicit unavailable indicator, never a fabricated zero-mean value.
    """
    if name in df.columns:
        return df[name]
    return pd.Series(np.nan, index=df.index)


def _log1p(series: pd.Series) -> pd.Series:
    return np.log1p(_num(series).clip(lower=0))


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build the indicator table. Expects the output of ``04_export_snapshot``."""
    out = df.copy()
    if out.empty:
        for col in FEATURE_COLUMNS:
            out[col] = pd.Series(dtype="float64")
        return out

    award = _num(_col(out, "award_value"))
    # `estimated_value` is stated for the whole tender, so the comparable
    # awarded amount is the sum over all lots, not the primary award alone.
    award_total = _num(_col(out, "award_total")).fillna(award)
    est = _num(_col(out, "estimated_value"))
    cpv = _col(out, "cpv_primary")

    # -- financial ---------------------------------------------------------
    out["log_award_value"] = _log1p(award)
    out["log_award_total"] = _log1p(award_total)
    out["multi_award_tender"] = (
        _num(_col(out, "n_awards_with_value")).fillna(0) > 1
    ).astype(int)
    median = award.groupby(cpv).transform("median") if cpv is not None else pd.Series(np.nan, index=out.index)
    std = award.groupby(cpv).transform("std") if cpv is not None else pd.Series(np.nan, index=out.index)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = award / median.replace(0, np.nan)
        zscore = (award - median) / std.replace(0, np.nan)
    out["value_vs_cpv_median"] = ratio.replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(0, 20)
    out["value_zscore_cpv"] = zscore.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-10, 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        est_ratio = est / award_total.replace(0, np.nan)
    out["estimate_to_award_ratio"] = est_ratio.replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(0, 20)

    # -- competition -------------------------------------------------------
    n_bidders = _num(_col(out, "n_bidders")).fillna(0)
    out["n_bidders_log"] = np.log1p(n_bidders)
    out["single_bidder"] = (n_bidders == 1).astype(int)
    out["no_bid_data"] = (n_bidders == 0).astype(int)
    out["multi_supplier_award"] = (_num(_col(out, "n_suppliers")).fillna(0) > 1).astype(int)

    # -- procedural --------------------------------------------------------
    start = pd.to_datetime(_col(out, "tender_start"), errors="coerce", utc=True)
    end = pd.to_datetime(_col(out, "tender_end"), errors="coerce", utc=True)
    window = (end - start).dt.days
    out["bid_window_days"] = window.fillna(30).clip(0, 3650)
    out["short_deadline"] = ((out["bid_window_days"] >= 0) & (out["bid_window_days"] < 7)).astype(int)
    out["long_deadline"] = (out["bid_window_days"] > 90).astype(int)
    out["n_amendments"] = _num(_col(out, "n_amendments")).fillna(0)
    out["amended"] = (out["n_amendments"] > 0).astype(int)
    method = _col(out, "procurement_method_details")
    out["accelerated_like"] = (
        method.astype(str).str.contains("accelerated|urgent|exception", case=False, na=False).astype(int)
        if method is not None
        else pd.Series(0, index=out.index)
    )
    status = _col(out, "status").astype(str)
    out["cancelled"] = status.isin(["cancelled", "unsuccessful"]).astype(int)
    out["no_award_after_tender"] = (
        (status == "complete") & (_num(_col(out, "award_value")).isna())
    ).astype(int)

    # -- behavioural (group statistics supplied by the caller) -------------
    for col, default in (
        ("buyer_supplier_repeat_share", 0.0),
        ("winner_share_of_buyer_awards", 0.0),
        ("supplier_win_concentration", 0.0),
        ("supplier_award_count_log", 0.0),
    ):
        if col not in out.columns:
            out[col] = default

    for col in FEATURE_COLUMNS:
        out[col] = _num(out[col]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def add_behavioural_features(df: pd.DataFrame) -> pd.DataFrame:
    """Relationship and concentration indicators derived from the same frame.

    Computed in pandas here so the result is identical whether or not MongoDB is
    running; ``scripts/05_aggregations.py`` cross-checks the same quantities with
    MongoDB aggregation pipelines.
    """
    out = df.copy()
    if out.empty:
        return out

    behavioural = BEHAVIOURAL_COLUMNS
    # Relationship features need a real buyer id and a real winner id. If either
    # is absent the features stay 0.0 and ``relationship_features_available`` is
    # 0, so downstream models can tell "no repeat relationship" from "no data".
    if "buyer_id" not in out.columns or "winner_id" not in out.columns:
        for col in behavioural:
            out[col] = 0.0
        out["relationship_features_available"] = 0
        return out

    # Work on explicit temporary columns instead of merging on Series objects:
    # merging with ``on=[series]`` only works when the series happens to be named
    # after an existing column, which broke as soon as the column was absent.
    work = pd.DataFrame(
        {
            "_buyer": out["buyer_id"].astype("object"),
            "_winner": out["winner_id"].astype("object"),
        },
        index=out.index,
    )
    known = work["_buyer"].notna() & work["_winner"].notna()
    work = work[known]

    if work.empty:
        for col in behavioural:
            out[col] = 0.0
        out["relationship_features_available"] = 0
        return out

    pair_n = work.groupby(["_buyer", "_winner"], dropna=False).size()
    buyer_n = work.groupby("_buyer", dropna=False).size()
    winner_n = work.groupby("_winner", dropna=False).size()

    # Map by key explicitly. Dividing the (buyer, winner)-indexed counts by a
    # buyer-indexed Series relies on index alignment that does not hold between a
    # MultiIndex and a plain Index, and silently produces the wrong length.
    pair_map = pair_n.to_dict()
    buyer_map = buyer_n.to_dict()
    winner_map = winner_n.to_dict()
    buyers = work["_buyer"].tolist()
    winners = work["_winner"].tolist()
    pair_vals = pd.Series(
        [float(pair_map.get((b, w), 0)) for b, w in zip(buyers, winners)], index=work.index
    )
    buyer_vals = pd.Series(
        [float(buyer_map.get(b, 0) or 1) for b in buyers], index=work.index
    )
    winner_vals = pd.Series(
        [float(winner_map.get(w, 0)) for w in winners], index=work.index
    )

    # share of this buyer's awarded tenders that went to this particular winner
    share = pair_vals / buyer_vals
    total_awards = float(len(work))

    result = pd.DataFrame(index=out.index)
    lookup = pd.DataFrame(
        {
            "buyer_supplier_repeat_share": share.to_numpy(),
            "winner_share_of_buyer_awards": share.to_numpy(),
            "supplier_award_count_log": np.log1p(winner_vals.to_numpy()),
            "supplier_win_concentration": np.clip(
                winner_vals.to_numpy() / total_awards, 0, 1
            ),
        },
        index=work.index,
    )
    result = result.join(lookup)
    for col in BEHAVIOURAL_COLUMNS:
        if col == "relationship_features_available":
            continue
        out[col] = _num(result[col] if col in result.columns else pd.Series(np.nan, index=out.index))
        out[col] = out[col].fillna(0.0)
    out["relationship_features_available"] = known.astype(int).reindex(out.index).fillna(0).astype(int)
    return out
