"""Experimental risk-specific indicator modules (added 2026-10-20).

Four modules over the real corpus, none of which replaces or retrains the
production v0 ensemble - they add *lenses* the general anomaly score does not
provide:

* **A. Competition** - bidder-count anomalies scoped to populations where
  competition is expected, plus a prior-only buyer pattern (share of the
  buyer's *previous* 12 months of procedures with at most one bidder).
* **B. Splitting** - repeated same-buyer / same-CPV2 purchases inside a short
  window: cluster size, aggregated value, interval concentration, same-supplier
  share, share of "small" cluster members relative to the buyer's own
  distribution. **Threshold-independent by design**: no legal procurement
  thresholds are assumed, because no authoritative date-versioned threshold
  history is in the corpus (``threshold_interpretation.enabled = false`` in
  every output).
* **C. Buyer-supplier network** - strictly prior-only temporal features: counts
  and shares computed from awards dated *strictly before* the evaluated event
  (same-day events never backfill each other - no invented ordering).
* **D. Value distribution** - robust z-scores and percentiles within
  CPV2 x procedure-type groups, explicitly **not** an overpricing verdict
  (quantities/specifications/unit prices are absent): a value-distribution
  anomaly only.

Plus :func:`future_confirmation_indicators` - *evaluation-only* outcomes that
look FORWARD in time to check whether module-selected cases show meaningful,
reviewable follow-up patterns. They are labelled evaluation-only and must never
be fed to any model or used as features.

Everything here is descriptive: a hit is a *potential risk indicator* for
human review, never evidence of wrongdoing, and equal alert rates across
procurement types are **not** a goal (rates are reported per population as
measured).

Design notes
------------
* Windows and rules are fixed constants with stated rationale (90 days for
  splitting, 365 days for repeat patterns, |z| >= 3 for the distribution tail,
  min group size 20 for MAD stability) - statistical choices, not legal ones.
* Point-in-time honesty mirrors ``stage_features``: prior-only module C is
  valid for historical scoring; module B's +/-90-day cluster and the
  buyer-level quartile are retrospective (as-of-now) by nature - splitting only
  becomes visible after the repeat contracts exist, and this is documented in
  the outputs rather than hidden.
* Hit flags are ``NaN`` when their inputs are unknown (missing date, buyer,
  winner or value); ``0`` means "inputs known, indicator not triggered".
  Unknown never counts as a hit and never counts as a clearance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Windows (documented statistical choices, not legal thresholds).
SPLIT_WINDOW_DAYS = 90
REPEAT_WINDOW_DAYS = 365
MIN_GROUP_SIZE = 20          # min rows in a CPV2 x procedure group for MAD
OUTLIER_Z = 3.0              # robust |z| cut for the value-distribution tail
SMALL_CLUSTER_SHARE = 0.5    # same-supplier share rule for module B
PAIR_BUYER_SHARE = 0.5       # pair share rule for module C

#: Procedure details where competition is structurally expected (module A).
OPEN_DETAILS = (
    "opentender",
    "licitație_deschisă",
    "restrictedtender",
    "testminicompetition",
)

#: The corpus's direct-award marker (51.5% of procedures; scripts/34 track).
DIRECT_DETAILS = "directaward"

#: Human-readable policy strings embedded in every output so downstream
#: consumers cannot strip the caveats.
THRESHOLD_INTERPRETATION = {
    "enabled": False,
    "reason": (
        "no authoritative Moldovan threshold history by date/category is in "
        "the corpus; all splitting indicators are threshold-independent and "
        "carry no legal interpretation"
    ),
}
SINGLE_BIDDER_NOTE = (
    "a single bidder is a review indicator, not evidence of wrongdoing"
)
OVERPRICING_NOTE = (
    "value-distribution anomaly only: quantities, specifications and unit "
    "prices are unavailable, so overpricing is NOT established"
)
OUTCOME_NOTE = (
    "evaluation-only: these outcomes look FORWARD in time and are used solely "
    "to assess whether module-selected cases show reviewable follow-up "
    "patterns; they are never model inputs"
)
COLLUSION_NOTE = (
    "repeated buyer-supplier relationships are a review indicator; they never "
    "prove collusion"
)

_DATE_FALLBACK = ("award_date", "tender_start", "published_date")

_HIT_COLUMNS = ("module_a_hit", "module_b_hit", "module_c_hit", "module_d_hit")


def event_date(df: pd.DataFrame) -> pd.Series:
    """Event date: award date, falling back to start, then publication.

    Returned as tz-naive UTC ``datetime64`` so numpy comparisons in the
    window helpers are plain datetime arithmetic.
    """
    out = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for col in _DATE_FALLBACK:
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
            out = out.fillna(parsed.dt.tz_localize(None))
    return out


def _cpv2(df: pd.DataFrame) -> pd.Series:
    if "cpv_primary" not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype=object)
    digits = df["cpv_primary"].astype(str).str.extract(r"^(\d{2})", expand=False)
    return digits.fillna(pd.NA)


def contract_value(df: pd.DataFrame) -> pd.Series:
    """Comparable contract value: award_total -> award_value (never imputed)."""
    total = pd.Series(np.nan, index=df.index, dtype="float64")
    for col in ("award_total", "award_value"):
        if col in df.columns:
            total = total.fillna(pd.to_numeric(df[col], errors="coerce"))
    return total


def _is_null(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):  # pragma: no cover - exotic types
        return False


def _require_range_index(df: pd.DataFrame) -> None:
    """Rows are addressed positionally (label == position): fail fast otherwise.

    Silently writing a computed indicator to the wrong row of a filtered
    frame would be worse than an exception, so non-positional indices are
    rejected. ``module_indicators()`` normalises automatically.
    """
    if not df.index.equals(pd.RangeIndex(len(df))):
        raise ValueError(
            "indicator functions require a 0..n-1 RangeIndex; call "
            "df.reset_index(drop=True) first (module_indicators does it for you)"
        )


# --------------------------------------------------------------------------- #
# Module A - competition risk (population-scoped)
# --------------------------------------------------------------------------- #

def _prior_single_bidder(
    df: pd.DataFrame, dates: pd.Series, n_bidders: pd.Series
) -> tuple[np.ndarray, np.ndarray]:
    """Prior-365d buyer pattern: (count of known-bidder procedures, share of
    those with at most one bidder).

    Strictly earlier procedures only; procedures with unknown ``n_bidders``
    leave both the count and the numerator unchanged (unknown is not zero).
    """
    counts = np.zeros(len(df), dtype="float64")
    shares = np.full(len(df), np.nan, dtype="float64")
    if "buyer_id" not in df.columns:
        return counts, shares

    buyers = df["buyer_id"].to_numpy()
    dvals = dates.to_numpy(dtype="datetime64[ns]")
    known_b = pd.to_numeric(n_bidders, errors="coerce").to_numpy(dtype="float64")
    single = ((known_b <= 1) & ~np.isnan(known_b)).astype("float64")
    known = (~np.isnan(known_b)).astype("float64")

    by_buyer: dict = {}
    for i in range(len(df)):
        if _is_null(buyers[i]) or np.isnat(dvals[i]):
            continue
        by_buyer.setdefault(buyers[i], []).append(i)

    window = np.timedelta64(REPEAT_WINDOW_DAYS, "D")
    for idxs in by_buyer.values():
        if len(idxs) < 2:
            continue
        idxs.sort(key=lambda i: dvals[i])
        dates_b = dvals[idxs]
        left = 0
        run_count = 0.0
        run_single = 0.0
        for pos, i in enumerate(idxs):
            start = dates_b[pos] - window
            while left < pos and dates_b[left] < start:
                run_count -= known[idxs[left]]
                run_single -= single[idxs[left]]
                left += 1
            counts[i] = run_count
            if run_count > 0:
                shares[i] = run_single / run_count
            run_count += known[i]
            run_single += single[i]
    return counts, shares


def competition_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Competition indicators + a prior-only buyer pattern.

    ``buyer_prior_single_share`` = share of this buyer's *strictly earlier*
    procedures within 365 days that had at most one known bidder. Procedures
    with unknown ``n_bidders`` leave the denominator unchanged (unknown is not
    zero bidders). Valid at bid close or later; no future procedure is used.
    ``comp_a_hit`` is NaN outside competition-expecting populations - a direct
    award with no bids is the legal form, not an anomaly.
    """
    out = pd.DataFrame(index=df.index)
    _require_range_index(df)
    n_bidders = (
        pd.to_numeric(df["n_bidders"], errors="coerce")
        if "n_bidders" in df.columns
        else pd.Series(np.nan, index=df.index, dtype="float64")
    )
    window = (
        pd.to_numeric(df["bid_window_days"], errors="coerce")
        if "bid_window_days" in df.columns
        else pd.Series(np.nan, index=df.index, dtype="float64")
    )
    out["comp_single_bidder"] = (n_bidders == 1).astype("float64").where(
        n_bidders.notna()
    )
    out["comp_no_bid_data"] = (n_bidders == 0).astype("float64").where(
        n_bidders.notna()
    )
    out["comp_short_window"] = (window < 7).astype("float64").where(window.notna())

    details = (
        df["procurement_method_details"].astype(str)
        if "procurement_method_details" in df.columns
        else pd.Series("", index=df.index)
    )
    expects_competition = details.isin(OPEN_DETAILS)
    a_hit = (
        (out["comp_short_window"].fillna(0) > 0)
        | (expects_competition & (out["comp_single_bidder"].fillna(0) > 0))
        | (expects_competition & (out["comp_no_bid_data"].fillna(0) > 0))
    ).astype("float64")
    out["comp_a_hit"] = a_hit.where(expects_competition)

    counts, shares = _prior_single_bidder(df, event_date(df), n_bidders)
    out["buyer_prior_365d_count"] = counts
    out["buyer_prior_single_share"] = shares
    return out


# --------------------------------------------------------------------------- #
# Module B - procurement splitting (threshold-independent)
# --------------------------------------------------------------------------- #

def splitting_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Repeated same-buyer/same-CPV2 purchases inside ``SPLIT_WINDOW_DAYS``.

    The cluster is the +/-90-day neighbourhood of the event date among the
    buyer's procedures with the same CPV2 prefix. Retrospective by nature
    (the repeat contracts must exist to be counted) - valid for as-of-now
    monitoring, not a point-in-time publication feature. Rows outside any
    cluster get ``split_cluster_member = 0``; rows without a date/buyer/CPV
    get ``NaN`` (unknown, not "no cluster").
    """
    out = pd.DataFrame(index=df.index)
    _require_range_index(df)
    out["split_cluster_member"] = np.nan
    out["split_cluster_n"] = np.nan
    out["split_cluster_value_mdl"] = np.nan
    out["split_same_supplier_share"] = np.nan
    out["split_min_gap_days"] = np.nan
    out["split_small_value_share"] = np.nan

    if "buyer_id" not in df.columns:
        out["split_b_hit"] = np.nan
        return out

    dates = event_date(df)
    cpv = _cpv2(df)
    money = contract_value(df)
    buyers = df["buyer_id"].to_numpy()
    winners = (
        df["winner_id"].to_numpy()
        if "winner_id" in df.columns
        else np.full(len(df), None, dtype=object)
    )

    # Buyer's own value quartile (retrospective, as-of-now - documented).
    buyer_q25: dict = {}
    frame = pd.DataFrame({"b": buyers, "v": money})
    for b, grp in frame.dropna(subset=["b"]).groupby("b", sort=False)["v"]:
        vals = grp.dropna()
        if len(vals) >= 4:
            buyer_q25[b] = float(vals.quantile(0.25))

    by_key: dict = {}
    for i in range(len(df)):
        b = buyers[i]
        if _is_null(b) or _is_null(cpv.iloc[i]) or pd.isna(dates.iloc[i]):
            continue
        by_key.setdefault((b, cpv.iloc[i]), []).append(i)

    window = np.timedelta64(SPLIT_WINDOW_DAYS, "D")
    for idxs in by_key.values():
        if len(idxs) < 2:
            # inputs known, only this procedure exists for the key: a
            # definite "no cluster" (0), not an unknown (NaN).
            for i in idxs:
                out.at[i, "split_cluster_member"] = 0.0
            continue
        idxs.sort(key=lambda i: dates.iloc[i])
        dvals = np.array([dates.iloc[i].to_datetime64() for i in idxs])
        n = len(idxs)
        for pos in range(n):
            # expand the +/- window around pos (two pointers over sorted dates)
            right = pos
            while right + 1 < n and dvals[right + 1] - dvals[pos] <= window:
                right += 1
            left = pos
            while left > 0 and dvals[pos] - dvals[left - 1] <= window:
                left -= 1
            if right - left + 1 < 2:
                continue
            self_i = idxs[pos]
            span = right - left + 1
            if span < 2:
                # inputs known, but no repeat in the window: a definite "no",
                # not an unknown (unknown stays NaN from the initial column).
                out.at[self_i, "split_cluster_member"] = 0.0
                continue
            member_positions = range(left, right + 1)
            gaps = [
                abs(round(float((dvals[pos] - dvals[p]) / np.timedelta64(1, "D"))))
                for p in member_positions
                if p != pos
            ]
            out.at[self_i, "split_cluster_member"] = 1.0
            out.at[self_i, "split_cluster_n"] = float(span)
            vals = [money.iloc[idxs[p]] for p in member_positions]
            known_vals = [v for v in vals if not np.isnan(v)]
            out.at[self_i, "split_cluster_value_mdl"] = (
                float(sum(known_vals)) if known_vals else np.nan
            )
            w_self = winners[self_i]
            if _is_null(w_self):
                out.at[self_i, "split_same_supplier_share"] = np.nan
            else:
                same = sum(
                    1
                    for p in member_positions
                    if not _is_null(winners[idxs[p]]) and winners[idxs[p]] == w_self
                )
                out.at[self_i, "split_same_supplier_share"] = same / len(idxs[left : right + 1])
            out.at[self_i, "split_min_gap_days"] = float(min(gaps)) if gaps else np.nan
            q25 = buyer_q25.get(buyers[self_i])
            if q25 is None:
                out.at[self_i, "split_small_value_share"] = np.nan
            else:
                out.at[self_i, "split_small_value_share"] = (
                    float(sum(1 for v in known_vals if v <= q25) / len(known_vals))
                    if known_vals
                    else np.nan
                )

    # B hit: known cluster member whose members mostly share the supplier;
    # undetermined (NaN) when the cluster exists but the supplier is unknown.
    member = out["split_cluster_member"]
    share = out["split_same_supplier_share"]
    hit = pd.Series(np.nan, index=df.index, dtype="float64")
    known_member = member.notna()
    hit[known_member & (member == 0)] = 0.0
    clustered = known_member & (member == 1)
    determined = clustered & share.notna()
    hit[determined] = (share[determined] >= SMALL_CLUSTER_SHARE).astype("float64")
    out["split_b_hit"] = hit
    return out


# --------------------------------------------------------------------------- #
# Module C - buyer-supplier network, strictly prior-only
# --------------------------------------------------------------------------- #

def network_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Prior-only relationship features.

    Every count uses awards dated **strictly before** the evaluated event.
    Events sharing a date are committed as one batch, so two procedures on the
    same day never see each other (no fabricated ordering). Rows without a
    date, buyer or winner get NaN (unknown, not zero).
    """
    _require_range_index(df)
    numeric_cols = (
        "pair_prior_awards",
        "buyer_prior_awards",
        "supplier_prior_awards",
        "supplier_prior_buyers",
        "pair_buyer_share",
        "supplier_dep_share",
        "pair_prior_365d",
    )
    out = pd.DataFrame(index=df.index)
    for c in numeric_cols:
        out[c] = np.nan
    out["net_c_hit"] = np.nan

    if "buyer_id" not in df.columns or "winner_id" not in df.columns:
        return out

    dates = event_date(df)
    buyers = df["buyer_id"].to_numpy()
    winners = df["winner_id"].to_numpy()

    eligible = [
        i
        for i in range(len(df))
        if not _is_null(buyers[i]) and not _is_null(winners[i]) and not pd.isna(dates.iloc[i])
    ]
    eligible.sort(key=lambda i: (dates.iloc[i], i))

    pair_counts: dict = {}
    buyer_counts: dict = {}
    supplier_counts: dict = {}
    supplier_buyers: dict = {}
    pair_dates: dict = {}

    i = 0
    window = np.timedelta64(REPEAT_WINDOW_DAYS, "D")
    while i < len(eligible):
        cur_date = dates.iloc[eligible[i]]
        batch: list[int] = []
        while i < len(eligible) and dates.iloc[eligible[i]] == cur_date:
            batch.append(eligible[i])
            i += 1
        # 1) read state strictly before today's batch
        window_start = cur_date - window
        for idx in batch:
            b, w = buyers[idx], winners[idx]
            pair = (b, w)
            p = pair_counts.get(pair, 0)
            bb = buyer_counts.get(b, 0)
            ss = supplier_counts.get(w, 0)
            out.at[idx, "pair_prior_awards"] = float(p)
            out.at[idx, "buyer_prior_awards"] = float(bb)
            out.at[idx, "supplier_prior_awards"] = float(ss)
            out.at[idx, "supplier_prior_buyers"] = float(
                len(supplier_buyers.get(w, ()))
            )
            out.at[idx, "pair_buyer_share"] = (p / bb) if bb else np.nan
            out.at[idx, "supplier_dep_share"] = (p / ss) if ss else np.nan
            dq = pair_dates.get(pair)
            if dq:
                k = len(dq)
                while k > 0 and dq[k - 1] >= window_start:
                    k -= 1
                out.at[idx, "pair_prior_365d"] = float(len(dq) - k)
            else:
                out.at[idx, "pair_prior_365d"] = 0.0
        # 2) commit the batch
        for idx in batch:
            b, w = buyers[idx], winners[idx]
            pair = (b, w)
            pair_counts[pair] = pair_counts.get(pair, 0) + 1
            buyer_counts[b] = buyer_counts.get(b, 0) + 1
            supplier_counts[w] = supplier_counts.get(w, 0) + 1
            supplier_buyers.setdefault(w, set()).add(b)
            pair_dates.setdefault(pair, []).append(dates.iloc[idx])

    # C hit: known repetition with the pair taking at least half of the
    # buyer's known prior awards; NaN where the relationship is unknown.
    p = out["pair_prior_awards"]
    share = out["pair_buyer_share"]
    hit = pd.Series(np.nan, index=df.index, dtype="float64")
    known = p.notna()
    hit[known & (p == 0)] = 0.0
    repeated = known & (p >= 1)
    determined = repeated & share.notna()
    hit[determined] = (share[determined] >= PAIR_BUYER_SHARE).astype("float64")
    out["net_c_hit"] = hit
    return out


# --------------------------------------------------------------------------- #
# Module D - value-distribution anomaly (not overpricing)
# --------------------------------------------------------------------------- #

def value_distribution_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Robust z / percentile of the contract value within CPV2 x procedure.

    Groups smaller than ``MIN_GROUP_SIZE`` yield NaN - too few peers to be a
    distribution. Output carries :data:`OVERPRICING_NOTE` semantics: this
    cannot and must not be read as a verified overpricing indicator.
    """
    out = pd.DataFrame(index=df.index)
    _require_range_index(df)
    for c in ("val_group_n", "val_robust_z", "val_pctile", "val_d_hit"):
        out[c] = np.nan

    money = contract_value(df)
    cpv = _cpv2(df)
    details = (
        df["procurement_method_details"].astype(str)
        if "procurement_method_details" in df.columns
        else pd.Series("", index=df.index)
    )
    valid = money.notna() & (money > 0) & cpv.notna()
    if not valid.any():
        out["val_d_hit"] = np.nan
        return out

    logv = pd.Series(np.nan, index=df.index, dtype="float64")
    logv.loc[valid] = np.log1p(money.loc[valid].astype(float))
    grp = pd.DataFrame({"cpv": cpv, "d": details, "logv": logv})

    def _z_block(block: pd.Series) -> pd.Series:
        # Group size and statistics use *priced* rows only: NaN rows must not
        # inflate the group past MIN_GROUP_SIZE while only a handful of real
        # values define the distribution.
        clean = block.dropna()
        if len(clean) < MIN_GROUP_SIZE:
            return pd.Series(np.nan, index=block.index)
        med = clean.median()
        mad = (clean - med).abs().median()
        if mad <= 0:
            return pd.Series(np.nan, index=block.index)
        return (block - med) / (1.4826 * mad)  # NaN in -> NaN out

    grouped = grp.groupby(["cpv", "d"], dropna=False)["logv"]
    out["val_robust_z"] = grouped.transform(_z_block)
    out["val_pctile"] = grouped.rank(pct=True).where(valid)
    # group size = priced rows in the group (same basis as _z_block)
    out["val_group_n"] = grouped.transform(lambda b: float(b.notna().sum())).where(
        valid
    )
    out["val_d_hit"] = (
        out["val_robust_z"].abs() >= OUTLIER_Z
    ).astype("float64").where(out["val_robust_z"].notna())
    return out


# --------------------------------------------------------------------------- #
# Evaluation-only forward outcomes (never features)
# --------------------------------------------------------------------------- #

def future_confirmation_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-looking outcomes for *evaluation only* (see :data:`OUTCOME_NOTE`).

    * ``future_repeat_same_winner_365d`` - the same (buyer, winner) pair
      awarded again strictly after this event within 365 days.
    * ``future_same_buyer_cpv2_90d`` - the same buyer awarded in the same CPV2
      group strictly after this event within 90 days (splitting follow-up).

    Same-day events never confirm each other. NaN when inputs are missing.
    """
    out = pd.DataFrame(index=df.index)
    _require_range_index(df)
    out["future_repeat_same_winner_365d"] = np.nan
    out["future_same_buyer_cpv2_90d"] = np.nan

    dates = event_date(df)
    if "buyer_id" not in df.columns:
        return out
    buyers = df["buyer_id"].to_numpy()
    cpv = _cpv2(df)
    winners = (
        df["winner_id"].to_numpy()
        if "winner_id" in df.columns
        else np.full(len(df), None, dtype=object)
    )

    # date lists per key, ascending
    pair_dates: dict = {}
    buyer_cpv_dates: dict = {}
    for i in range(len(df)):
        d = dates.iloc[i]
        if pd.isna(d):
            continue
        if not _is_null(buyers[i]) and not _is_null(winners[i]):
            pair_dates.setdefault((buyers[i], winners[i]), []).append(d)
        if not _is_null(buyers[i]) and not _is_null(cpv.iloc[i]):
            buyer_cpv_dates.setdefault((buyers[i], cpv.iloc[i]), []).append(d)
    pair_arr = {k: np.array(sorted(v), dtype="datetime64[ns]") for k, v in pair_dates.items()}
    bc_arr = {k: np.array(sorted(v), dtype="datetime64[ns]") for k, v in buyer_cpv_dates.items()}

    def _future_count(arr, d, days) -> int:
        # strictly after d (side="right" skips same-day events, incl. this row)
        lo = np.searchsorted(arr, d, side="right")
        hi = np.searchsorted(arr, d + np.timedelta64(days, "D"), side="right")
        return int(hi - lo)

    for i in range(len(df)):
        d = dates.iloc[i]
        if pd.isna(d):
            continue
        d64 = d.to_datetime64()
        if not _is_null(buyers[i]) and not _is_null(winners[i]):
            arr = pair_arr.get((buyers[i], winners[i]))
            if arr is not None:
                out.at[i, "future_repeat_same_winner_365d"] = float(
                    _future_count(arr, d64, REPEAT_WINDOW_DAYS) > 0
                )
        if not _is_null(buyers[i]) and not _is_null(cpv.iloc[i]):
            arr = bc_arr.get((buyers[i], cpv.iloc[i]))
            if arr is not None:
                out.at[i, "future_same_buyer_cpv2_90d"] = float(
                    _future_count(arr, d64, SPLIT_WINDOW_DAYS) > 0
                )
    return out


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #

def module_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """All four modules + per-module hit flags, aligned to ``df.index``.

    ``n_module_hits`` sums *known* hits only (NaN contributions are skipped);
    ``n_module_known`` counts how many of the four module hits are determined,
    so "0 of 3 known" is distinguishable from "0 of 3 triggered".
    """
    orig_index = df.index
    if not df.index.equals(pd.RangeIndex(len(df))):
        df = df.reset_index(drop=True)
    parts = [
        competition_indicators(df),
        splitting_indicators(df),
        network_indicators(df),
        value_distribution_indicators(df),
    ]
    out = pd.concat(parts, axis=1)

    out["module_a_hit"] = out["comp_a_hit"]
    out["module_b_hit"] = out["split_b_hit"]
    out["module_c_hit"] = out["net_c_hit"]
    out["module_d_hit"] = out["val_d_hit"]
    hits = out[list(_HIT_COLUMNS)]
    out["n_module_hits"] = hits.sum(axis=1, skipna=True)
    out["n_module_known"] = hits.notna().sum(axis=1).astype("float64")
    out.index = orig_index
    return out


def indicator_metadata() -> dict:
    """Machine-readable rulebook that travels with every scripts/34 output."""
    return {
        "modules": {
            "A_competition": {
                "indicators": [
                    "comp_single_bidder",
                    "comp_no_bid_data",
                    "comp_short_window",
                    "buyer_prior_single_share",
                ],
                "population": "procedures expecting competition "
                f"({', '.join(OPEN_DETAILS)}); undefined for direct awards",
                "hit_rule": "short window, or (single bidder / no bid data) "
                "within a competition-expecting procedure type",
                "note": SINGLE_BIDDER_NOTE,
            },
            "B_splitting": {
                "window_days": SPLIT_WINDOW_DAYS,
                "indicators": [
                    "split_cluster_member",
                    "split_cluster_n",
                    "split_cluster_value_mdl",
                    "split_same_supplier_share",
                    "split_min_gap_days",
                    "split_small_value_share",
                ],
                "hit_rule": "cluster member (same buyer, same CPV2, +/-90 days) "
                f"and same-supplier share >= {SMALL_CLUSTER_SHARE}",
                "point_in_time": "retrospective (as-of-now): the +/-90-day "
                "cluster needs the repeat contracts to exist",
                "threshold_interpretation": THRESHOLD_INTERPRETATION,
            },
            "C_network": {
                "indicators": [
                    "pair_prior_awards",
                    "buyer_prior_awards",
                    "supplier_prior_awards",
                    "supplier_prior_buyers",
                    "pair_buyer_share",
                    "supplier_dep_share",
                    "pair_prior_365d",
                ],
                "point_in_time": "prior-only: strictly earlier dates; "
                "same-day events never backfill each other",
                "hit_rule": "pair_prior_awards >= 1 and "
                f"pair_buyer_share >= {PAIR_BUYER_SHARE}",
                "note": COLLUSION_NOTE,
            },
            "D_value_distribution": {
                "group": "CPV2 x procedure type",
                "min_group_size": MIN_GROUP_SIZE,
                "outlier_z": OUTLIER_Z,
                "note": OVERPRICING_NOTE,
            },
        },
        "evaluation_only_outcomes": {
            "indicators": [
                "future_repeat_same_winner_365d",
                "future_same_buyer_cpv2_90d",
            ],
            "note": OUTCOME_NOTE,
        },
        "direct_population_marker": DIRECT_DETAILS,
        "equal_alert_rates_are_not_a_goal": (
            "rates are reported per population as measured; equal representation "
            "across procurement types is not evidence of model quality"
        ),
        "hit_semantics": "NaN = inputs unknown (not a hit, not a clearance); "
        "0 = known and not triggered; 1 = triggered",
        "disclaimer": (
            "Indicators of potential risk requiring independent review by a "
            "competent authority; not evidence of corruption or violation."
        ),
    }
