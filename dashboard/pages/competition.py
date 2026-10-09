from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.metrics import kpi_row
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import UNAVAILABLE_WINNING_MARGIN, fmt_int, fmt_pct
from dashboard.utils.timeseries import time_series


def render(df, bundle) -> None:
    st.title("Competition")
    st.markdown(
        '<p class="story">How many distinct bidders are published, and how often is there a single bidder?</p>',
        unsafe_allow_html=True,
    )

    with_bids = df[df["has_bid_data_bool"] == True] if "has_bid_data_bool" in df.columns else df.iloc[0:0]  # noqa: E712
    n_single = int(df["single_bid_obs"].sum()) if "single_bid_obs" in df.columns else 0
    denom = max(len(with_bids), 1)
    kpi_row(
        [
            ("Procedures with bid data", fmt_int(len(with_bids)), "has_bid_data is true in the snapshot."),
            ("Single-bidder procedures", fmt_int(n_single), "Exactly one distinct tenderer, among rows with bid data."),
            ("Single-bid share (where bid data exists)", fmt_pct(n_single / denom), "Not computed on rows with no bid list — that would invent competition."),
            (
                "Median n_bidders (with bid data)",
                fmt_int(with_bids["n_bidders"].median()) if not with_bids.empty else "—",
                None,
            ),
        ]
    )

    st.caption(
        "`n_bids` in OCDS here counts lot-level bid records, not bidders. "
        "Competition charts use **n_bidders** (distinct tenderers)."
    )

    tab_dist, tab_trend, tab_cut, tab_margin = st.tabs(
        ["Bidder distribution", "Single-bid trend", "By method / CPV", "Winning margin"]
    )

    with tab_dist:
        if with_bids.empty:
            st.info("No bid-level coverage under the current filter.")
        else:
            charts.hist(with_bids["n_bidders"], "Number of bidders", "comp_hist", nbins=30)
            charts.box(with_bids["n_bidders"], "Bidder count — distribution and extremes", "comp_box")
            dist = with_bids["n_bidders"].clip(upper=15).value_counts().sort_index().rename_axis("n_bidders").reset_index(name="n")
            charts.bar(dist, "n_bidders", "n", "Bidder counts (15+ grouped into 15)", "comp_bar")

    with tab_trend:
        grain = st.radio("Time grain", ["Monthly", "Quarterly", "Yearly"], horizontal=True, key="comp_grain")
        ts = time_series(df, grain)
        c1, c2 = st.columns(2)
        with c1:
            charts.line_count_value(ts, "single_bid_pct", "Single-bid share among procedures with bid data", "Share", "comp_ts")
        with c2:
            if not ts.empty and "n_procedures" in ts:
                ts = ts.copy()
                ts["single_count"] = (ts["single_bid_pct"] * ts["n_procedures"]).fillna(0)
            charts.line_count_value(ts, "n_procedures", "All procedures (context)", "Count", "comp_ts2")

    with tab_cut:
        if not with_bids.empty and "procurement_method" in with_bids.columns:
            g = with_bids.groupby(with_bids["procurement_method"].fillna("(not published)"))["single_bid_obs"].mean()
            g = g.reset_index()
            g.columns = ["procurement_method", "single_bid_share"]
            charts.bar(g, "procurement_method", "single_bid_share", "Single-bid share by procurement method", "comp_m")
        if not with_bids.empty and "cpv_div" in with_bids.columns:
            g = (
                with_bids.groupby("cpv_div")["single_bid_obs"]
                .agg(["mean", "size"])
                .reset_index()
            )
            g = g[g["size"] >= 20].sort_values("mean", ascending=False).head(20)
            g = g.rename(columns={"mean": "single_bid_share"})
            charts.bar(g, "single_bid_share", "cpv_div", "Single-bid share by CPV division (n≥20)", "comp_cpv", horizontal=True)

    with tab_margin:
        st.warning(UNAVAILABLE_WINNING_MARGIN)
        if "bids" in df.columns and df["bids"].notna().any():
            st.write("Bid arrays are present for a minority of rows; per-supplier prices are still not a complete series.")
        interactive_table(
            with_bids[
                [c for c in ("ocid", "title", "buyer_name", "winner_name", "n_bidders", "award_amount", "procurement_method_details") if c in with_bids.columns]
            ].sort_values("n_bidders", ascending=True).head(2000),
            key="comp_tbl",
            download_stem="competition",
            caption="Sorted toward lower published bidder counts.",
        )
