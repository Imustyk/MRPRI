from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.metrics import kpi_row
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import fmt_int, fmt_mdl


def render(df, bundle) -> None:
    st.title("Financial analysis")
    st.markdown(
        '<p class="story">How are estimated and awarded amounts distributed, and which values are extreme?</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Extreme values are labelled **potential financial anomalies requiring further investigation**, "
        "not corruption."
    )

    amounts = pd.to_numeric(df.get("award_amount"), errors="coerce")
    est = pd.to_numeric(df.get("estimated_value"), errors="coerce")
    kpi_row(
        [
            ("Published awards", fmt_int(amounts.notna().sum()), None),
            ("Sum of awards", fmt_mdl(amounts.sum(min_count=1)), "Can be dominated by a few outliers — see Data quality."),
            ("Median award", fmt_mdl(amounts.median()), None),
            ("Median estimate", fmt_mdl(est.median()), None),
        ]
    )

    log_scale = st.checkbox("Log-scale histograms (recommended: award values are right-skewed)", value=True)

    tab_dist, tab_ratio, tab_large, tab_out = st.tabs(
        ["Distributions", "Estimate vs award", "Largest contracts", "Financial outliers"]
    )

    with tab_dist:
        s = amounts.dropna()
        if log_scale and not s.empty:
            s = s[s > 0]
            charts.hist(np.log10(s).rename("log10(award_amount)"), "Award amount (log10 MDL)", "fin_h1")
        else:
            charts.hist(amounts.rename("award_amount"), "Award amount (MDL)", "fin_h1")
        e = est.dropna()
        if log_scale and not e.empty:
            e = e[e > 0]
            charts.hist(np.log10(e).rename("log10(estimated_value)"), "Estimated value (log10 MDL)", "fin_h2")
        else:
            charts.hist(est.rename("estimated_value"), "Estimated value (MDL)", "fin_h2")
        charts.box(amounts.rename("award_amount"), "Award amount — box plot (extremes visible)", "fin_box")

    with tab_ratio:
        work = df[["estimated_value", "award_amount", "ocid", "title", "buyer_name", "winner_name"]].copy()
        work = work.dropna(subset=["estimated_value", "award_amount"])
        work = work[(work["estimated_value"] > 0) & (work["award_amount"] > 0)]
        if work.empty:
            st.info("No paired estimate and award under the current filter.")
        else:
            sample = work.sample(n=min(8000, len(work)), random_state=42)
            charts.scatter(
                sample,
                "estimated_value",
                "award_amount",
                "Estimated vs awarded amount (sample for rendering)",
                "fin_sc",
                hover=["ocid", "title", "buyer_name", "winner_name"],
            )
            ratio = (work["award_amount"] / work["estimated_value"]).rename("award / estimate")
            clipped = ratio[ratio.between(0, 5)]
            charts.hist(clipped, "Price ratio award/estimate (shown on 0–5; long tail exists)", "fin_ratio")
            st.caption(f"Paired rows: {len(work):,}. Share with ratio > 2: {(ratio > 2).mean():.1%}.")

    with tab_large:
        cols = [c for c in ("ocid", "title", "buyer_name", "winner_name", "estimated_value", "award_amount", "status", "event_date") if c in df.columns]
        large = df[cols].sort_values("award_amount", ascending=False, na_position="last")
        interactive_table(large.head(500), key="fin_large", download_stem="largest_contracts", caption="Top 500 by award amount in the current filter.")

    with tab_out:
        s = amounts.dropna()
        if s.empty:
            st.info("No award amounts.")
            return
        q_low, q_high = s.quantile(0.01), s.quantile(0.99)
        flags = df[(df["award_amount"] < q_low) | (df["award_amount"] > q_high)].copy()
        st.write(
            f"Rows below the 1st percentile ({q_low:,.0f} MDL) or above the 99th ({q_high:,.0f} MDL): "
            f"**{len(flags):,}**. Potential financial anomaly requiring further investigation."
        )
        cols = [c for c in ("ocid", "title", "buyer_name", "winner_name", "award_amount", "estimated_value", "cpv_primary") if c in flags.columns]
        interactive_table(flags[cols].sort_values("award_amount", ascending=False), key="fin_out", download_stem="financial_outliers")
