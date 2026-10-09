from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.utils.data_loader import apply_filters, filter_catalog


def render_sidebar_filters(tenders: pd.DataFrame) -> dict:
    cat = filter_catalog(tenders)
    st.sidebar.markdown("### Filters")
    st.sidebar.caption("All KPIs and charts use the current filter. Empty means no restriction.")

    min_d = cat["min_date"]
    max_d = cat["max_date"]
    if min_d is not None and max_d is not None:
        start = st.sidebar.date_input("Start date", value=min_d.date(), min_value=min_d.date(), max_value=max_d.date())
        end = st.sidebar.date_input("End date", value=max_d.date(), min_value=min_d.date(), max_value=max_d.date())
    else:
        start = end = None

    methods = st.sidebar.multiselect("Procurement method", cat["methods"])
    method_details = st.sidebar.multiselect("Procedure details", cat["method_details"])
    statuses = st.sidebar.multiselect("Procurement status", cat["statuses"])
    cpv_div = st.sidebar.multiselect("CPV division (first 2 digits)", cat["cpv_div"])

    st.sidebar.markdown("#### Organizations")
    procurer = st.sidebar.text_input("Procurer contains", placeholder="name or IDNO")
    supplier = st.sidebar.text_input("Supplier contains", placeholder="name or IDNO")

    st.sidebar.markdown("#### Financial (MDL)")
    st.sidebar.caption(
        f"Observed max in snapshot: {cat['abs_max_amount']:,.0f} MDL. Leave both at 0 to apply no amount filter."
    )
    min_value = st.sidebar.number_input("Minimum award value", min_value=0.0, value=0.0, step=1000.0)
    max_value = st.sidebar.number_input("Maximum award value (0 = no max)", min_value=0.0, value=0.0, step=1000.0)

    risk = st.sidebar.radio(
        "Risk",
        ["Show all", "Normal", "Anomalous", "High-risk indicator"],
        help="Normal = 0 detectors (or unscored). Anomalous = ≥1 detector. "
        "High-risk indicator = ≥2 detectors. Unscored rows have no model output.",
    )

    return {
        "start": start,
        "end": end,
        "methods": methods,
        "method_details": method_details,
        "statuses": statuses,
        "cpv_div": cpv_div,
        "procurer": procurer,
        "supplier": supplier,
        "min_value": min_value if min_value > 0 else None,
        "max_value": max_value if max_value > 0 else None,
        "risk": risk,
    }


def filtered(tenders: pd.DataFrame, filters: dict) -> pd.DataFrame:
    return apply_filters(tenders, filters)
