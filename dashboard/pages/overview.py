from __future__ import annotations

import streamlit as st

from dashboard.components import charts
from dashboard.components.metrics import overview_kpis
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import DISCLAIMER, fmt_int
from dashboard.utils.timeseries import time_series


def render(df, bundle) -> None:
    st.title("Overview")
    st.markdown(
        '<p class="story">What is happening in Moldovan public procurement under the current filter? '
        "Figures are computed from the pipeline snapshot, not typed constants.</p>",
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)

    scored = int(df["is_scored"].sum()) if "is_scored" in df.columns else 0
    if scored and scored < len(df):
        st.info(
            f"Analytics cover **{fmt_int(len(df))}** procedures. "
            f"Anomaly detectors scored **{fmt_int(scored)}** of them "
            f"(artefact `results/tables/tender_anomaly_scores.csv`). "
            f"The rest are shown as unscored, not as ‘normal’."
        )

    overview_kpis(df)

    grain = st.radio("Time grain", ["Monthly", "Quarterly", "Yearly", "Weekly", "Daily"], horizontal=True, key="ov_grain")
    ts = time_series(df, grain)
    c1, c2 = st.columns(2)
    with c1:
        charts.line_count_value(ts, "n_procedures", "Procurement volume over time", "Procedures", "ov_vol")
    with c2:
        charts.line_count_value(ts, "award_value", "Award value over time", "MDL", "ov_val")

    with st.expander("How to read this page", expanded=False):
        st.markdown(
            """
1. **What is happening?** volume and value over time.
2. **Who is involved?** unique procurers and suppliers in the KPI row.
3. **What looks unusual?** anomalous / high-risk counts use *model agreement*, not a legal label.
            """
        )

    preview_cols = [
        c
        for c in (
            "ocid",
            "title",
            "buyer_name",
            "winner_name",
            "status",
            "procurement_method_details",
            "award_amount",
            "n_bidders",
            "risk_band",
            "n_models_flagging",
            "max_score",
        )
        if c in df.columns
    ]
    st.subheader("Filtered procedures")
    search = st.text_input("Search title / OCID / organisation", key="ov_search")
    table = df[preview_cols].copy()
    if search.strip():
        q = search.strip().lower()
        mask = False
        for col in ("ocid", "title", "buyer_name", "winner_name"):
            if col in table.columns:
                mask = mask | table[col].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        table = table[mask]
    interactive_table(table, key="overview_table", download_stem="overview_filtered", max_rows=3000)
