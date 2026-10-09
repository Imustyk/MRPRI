from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import UNAVAILABLE_GEO_COORDS
from dashboard.utils.timeseries import time_series


def render(df, bundle) -> None:
    st.title("Procurement analysis")
    st.markdown(
        '<p class="story">Where is activity concentrated — in time, procedure type, status, CPV, and locality?</p>',
        unsafe_allow_html=True,
    )

    grain = st.radio("Time grain", ["Monthly", "Quarterly", "Yearly", "Weekly", "Daily"], horizontal=True, key="pr_grain")
    ts = time_series(df, grain)

    tab_time, tab_method, tab_status, tab_cpv, tab_geo = st.tabs(
        ["Time series", "Methods", "Status", "CPV categories", "Geography"]
    )

    with tab_time:
        c1, c2 = st.columns(2)
        with c1:
            charts.line_count_value(ts, "n_procedures", "Chart 1 — Procedures over time", "Count", "pr_c1")
        with c2:
            charts.line_count_value(ts, "award_value", "Chart 2 — Award value over time", "MDL", "pr_c2")
        st.caption("Value uses published award amounts. Procedures without an award contribute to the count chart only.")

    with tab_method:
        if "procurement_method" in df.columns:
            m = df.groupby("procurement_method", dropna=False).size().reset_index(name="n")
            m["procurement_method"] = m["procurement_method"].fillna("(not published)")
            charts.bar(m, "procurement_method", "n", "Chart 3 — Procedures by procurement method", "pr_c3")
            mv = (
                df.groupby("procurement_method", dropna=False)["award_amount"]
                .sum(min_count=1)
                .reset_index(name="award_value")
            )
            mv["procurement_method"] = mv["procurement_method"].fillna("(not published)")
            charts.bar(mv, "procurement_method", "award_value", "Chart 4 — Award value by method", "pr_c4")
        if "procurement_method_details" in df.columns:
            d = (
                df["procurement_method_details"]
                .fillna("(not published)")
                .value_counts()
                .head(15)
                .rename_axis("procedure")
                .reset_index(name="n")
            )
            charts.bar(d, "n", "procedure", "Procedure details (top 15)", "pr_c4b", horizontal=True)
            interactive_table(d, key="pr_method_tbl", download_stem="methods", caption="Counts from the filtered snapshot.")

    with tab_status:
        if "status" in df.columns:
            s = df["status"].fillna("(not published)").value_counts().rename_axis("status").reset_index(name="n")
            charts.donut(s, "status", "n", "Chart 5 — Procurement status", "pr_c5")
            charts.bar(s, "status", "n", "Status counts", "pr_c5b")

    with tab_cpv:
        if "cpv_div" in df.columns:
            c = df["cpv_div"].value_counts().head(20).rename_axis("cpv_division").reset_index(name="n")
            charts.bar(c, "n", "cpv_division", "Chart 6 — Most frequent CPV divisions (2-digit)", "pr_c6", horizontal=True)
        if "cpv_primary" in df.columns:
            top = df["cpv_primary"].fillna("(not published)").value_counts().head(25)
            interactive_table(
                top.rename_axis("cpv_primary").reset_index(name="n"),
                key="pr_cpv",
                download_stem="cpv_top",
                caption="Full CPV codes. MTender does not publish a complete code→label dictionary in the payload used here.",
            )

    with tab_geo:
        st.warning(UNAVAILABLE_GEO_COORDS)
        if "buyer_locality" in df.columns:
            g = (
                df["buyer_locality"]
                .fillna("(not published)")
                .replace("", "(not published)")
                .value_counts()
                .head(25)
                .rename_axis("buyer_locality")
                .reset_index(name="n")
            )
            charts.bar(g, "n", "buyer_locality", "Chart 7 — Procurer locality (name frequency, not a map)", "pr_c7", horizontal=True)
            interactive_table(g, key="pr_geo", download_stem="localities")
        else:
            st.info("Column `buyer_locality` is not in this snapshot.")
