from __future__ import annotations

import pandas as pd

from dashboard.utils.preprocessing import resample_rule


def time_series(df: pd.DataFrame, grain: str) -> pd.DataFrame:
    if df.empty or "event_date" not in df.columns:
        return pd.DataFrame(columns=["period", "n_procedures", "award_value", "n_anomalous", "anomaly_pct", "single_bid_pct"])
    work = df.dropna(subset=["event_date"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["period", "n_procedures", "award_value", "n_anomalous", "anomaly_pct", "single_bid_pct"])
    work = work.set_index("event_date").sort_index()
    rule = resample_rule(grain)
    n = work.resample(rule).size().rename("n_procedures")
    value = work["award_amount"].resample(rule).sum(min_count=1).rename("award_value")
    if "is_anomalous" in work.columns:
        anom = work["is_anomalous"].astype(int).resample(rule).sum().rename("n_anomalous")
        scored = work["is_scored"].astype(int).resample(rule).sum().replace(0, pd.NA)
        anomaly_pct = (anom / scored).rename("anomaly_pct")
    else:
        anom = pd.Series(0, index=n.index, name="n_anomalous")
        anomaly_pct = pd.Series(pd.NA, index=n.index, name="anomaly_pct")
    if "single_bid_obs" in work.columns and "has_bid_data_bool" in work.columns:
        single = work["single_bid_obs"].astype(int).resample(rule).sum()
        with_bids = work["has_bid_data_bool"].astype(int).resample(rule).sum().replace(0, pd.NA)
        single_pct = (single / with_bids).rename("single_bid_pct")
    else:
        single_pct = pd.Series(pd.NA, index=n.index, name="single_bid_pct")
    out = pd.concat([n, value, anom, anomaly_pct, single_pct], axis=1).reset_index()
    out = out.rename(columns={"event_date": "period"})
    return out
