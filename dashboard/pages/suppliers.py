from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.components import charts
from dashboard.components.metrics import kpi_row
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import DISCLAIMER, fmt_int, fmt_pct, safe_name
from dashboard.utils.timeseries import time_series


def render(df, bundle) -> None:
    st.title("Suppliers")
    st.markdown(
        '<p class="story">Who wins work, how concentrated is value, and which procurer–supplier pairs repeat?</p>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)

    awarded = df[df["winner_name"].notna() & (df["winner_name"].astype(str).str.strip() != "")].copy()
    if awarded.empty:
        st.info("No published winners under the current filter.")
        return

    kpi_row(
        [
            ("Awarded procedures", fmt_int(len(awarded)), "Rows with a published winner name."),
            ("Unique suppliers", fmt_int(awarded["winner_id"].nunique() if "winner_id" in awarded else awarded["winner_name"].nunique()), None),
            (
                "Top-10 value share",
                fmt_pct(_topk_share(awarded, 10)),
                "Share of award value held by the ten largest suppliers in this filter.",
            ),
        ]
    )

    by_value = (
        awarded.groupby("winner_name", dropna=True)["award_amount"]
        .sum(min_count=1)
        .sort_values(ascending=False)
        .head(20)
        .rename_axis("supplier")
        .reset_index(name="award_value")
    )
    by_n = (
        awarded.groupby("winner_name", dropna=True)
        .size()
        .sort_values(ascending=False)
        .head(20)
        .rename_axis("supplier")
        .reset_index(name="n_contracts")
    )
    c1, c2 = st.columns(2)
    with c1:
        charts.bar(by_value, "award_value", "supplier", "Top suppliers by award value", "sup_val", horizontal=True)
    with c2:
        charts.bar(by_n, "n_contracts", "supplier", "Top suppliers by number of awards", "sup_n", horizontal=True)

    st.subheader("Supplier concentration")
    conc = (
        awarded.groupby("winner_name")["award_amount"]
        .sum(min_count=1)
        .sort_values(ascending=False)
        .fillna(0)
    )
    if conc.sum() and conc.sum() > 0:
        share = (conc.cumsum() / conc.sum()).reset_index()
        share.columns = ["supplier", "cumulative_share"]
        share["rank"] = range(1, len(share) + 1)
        charts.line_count_value(share.rename(columns={"rank": "period", "cumulative_share": "n_procedures"}), "n_procedures", "Cumulative share of award value (Lorenz-style)", "Cumulative share", "sup_lorenz")
        st.caption("A steep early rise means a few suppliers account for most published award value in this filter.")

    st.subheader("Supplier activity over time")
    grain = st.radio("Time grain", ["Monthly", "Quarterly", "Yearly"], horizontal=True, key="sup_grain")
    top_names = by_value["supplier"].head(8).tolist()
    pick = st.multiselect("Suppliers on the time chart", top_names, default=top_names[:5])
    if not pick:
        st.info("Select at least one supplier to draw the activity timeline.")
    else:
        sub = awarded[awarded["winner_name"].isin(pick)]
        freq_map = {"Monthly": "M", "Quarterly": "Q", "Yearly": "Y"}
        piece = sub.dropna(subset=["event_date"]).copy()
        if not piece.empty:
            naive = piece["event_date"].dt.tz_convert("UTC").dt.tz_localize(None)
            piece["period"] = naive.dt.to_period(freq_map[grain]).dt.to_timestamp()
            ts = piece.groupby(["period", "winner_name"]).size().reset_index(name="n")
        else:
            ts = pd.DataFrame(columns=["period", "winner_name", "n"])
        if not ts.empty:
            fig = px.line(
                ts,
                x="period",
                y="n",
                color="winner_name",
                markers=True,
                title="Awards over time (selected suppliers)",
            )
            charts.show(fig, "sup_ts")

    st.subheader("Repeated winners (same procurer)")
    st.caption(
        "Pairs with several awards. This is an **analytical indicator of repeated awards**, "
        "not proof of corruption."
    )
    pair = (
        awarded.groupby(["buyer_name", "winner_name"], dropna=True)
        .agg(n_awards=("ocid", "count"), award_value=("award_amount", "sum"))
        .reset_index()
    )
    pair = pair[pair["n_awards"] >= 3].sort_values(["n_awards", "award_value"], ascending=False)
    interactive_table(pair.head(2000), key="sup_pairs", download_stem="repeated_winners", caption="Minimum 3 awards for the pair in the current filter.")

    st.subheader("Supplier–procurer concentration matrix")
    st.caption("Top procurers × top suppliers by award count. Cell = number of awards (not a legal network of collusion).")
    top_b = awarded["buyer_name"].value_counts().head(12).index
    top_s = awarded["winner_name"].value_counts().head(12).index
    sub = awarded[awarded["buyer_name"].isin(top_b) & awarded["winner_name"].isin(top_s)]
    if sub.empty:
        st.info("Not enough overlapping top organisations to build a matrix.")
        return
    mat = pd.crosstab(sub["buyer_name"], sub["winner_name"])
    charts.heatmap(mat.values, list(mat.columns), list(mat.index), "Awards between frequent procurers and suppliers", "sup_heat")


def _topk_share(awarded: pd.DataFrame, k: int) -> float | None:
    s = awarded.groupby("winner_name")["award_amount"].sum(min_count=1).sort_values(ascending=False)
    total = s.sum()
    if not total or pd.isna(total) or total == 0:
        return None
    return float(s.head(k).sum() / total)
