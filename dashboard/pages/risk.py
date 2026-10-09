from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import DISCLAIMER
from dashboard.utils.preprocessing import FLAG_LABELS, indicator_badges


def render(df, bundle) -> None:
    st.title("Risk indicators")
    st.markdown(
        '<p class="story">Which calculated indicators co-occur — still as potential risk signals, not guilt?</p>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)

    flags = [c for c in FLAG_LABELS if c in df.columns]
    if not flags:
        st.info("No binary indicator columns in the snapshot.")
        return

    prev = (
        pd.DataFrame(
            {
                "indicator": flags,
                "label": [FLAG_LABELS[c] for c in flags],
                "count": [int(pd.to_numeric(df[c], errors="coerce").fillna(0).sum()) for c in flags],
                "share": [float(pd.to_numeric(df[c], errors="coerce").fillna(0).mean()) for c in flags],
            }
        )
        .sort_values("count", ascending=False)
    )
    charts.bar(prev, "count", "label", "Potential risk indicators in the current filter", "ri_bar", horizontal=True)

    arte = bundle.artefacts.get("red_flags")
    if arte is not None and not arte.empty:
        with st.expander("Pipeline red-flag prevalence (detection snapshot)", expanded=False):
            interactive_table(arte, key="ri_pipe", download_stem="red_flag_prevalence")

    st.subheader("Indicator co-occurrence")
    mat = df[flags].fillna(0).astype(int)
    # pairwise counts
    names = [FLAG_LABELS[c] for c in flags]
    z = []
    for a in flags:
        z.append([(int((mat[a] & mat[b]).sum()) if a != b else int(mat[a].sum())) for b in flags])
    charts.heatmap(z, names, names, "Co-occurrence counts (diagonal = prevalence)", "ri_heat")

    st.subheader("Procurer × supplier heatmap (repeat intensity)")
    awarded = df[df["winner_name"].notna() & df["buyer_name"].notna()]
    if awarded.empty:
        st.info("No named parties.")
    else:
        top_b = awarded["buyer_name"].value_counts().head(15).index
        top_s = awarded["winner_name"].value_counts().head(15).index
        sub = awarded[awarded["buyer_name"].isin(top_b) & awarded["winner_name"].isin(top_s)]
        share = sub.groupby(["buyer_name", "winner_name"]).size().unstack(fill_value=0)
        charts.heatmap(share.values, list(share.columns), list(share.index), "Award counts (frequent parties)", "ri_mat")
        st.caption("High cells mean repeated awards between the pair. That is a concentration indicator.")

    st.subheader("Rows with several indicators")
    work = df.copy()
    work["n_risk_indicators"] = mat.sum(axis=1)
    top = work.sort_values("n_risk_indicators", ascending=False).head(2000)
    top = top.copy()
    top["indicators"] = ["; ".join(indicator_badges(r)) for _, r in top.iterrows()]
    cols = [c for c in ("ocid", "title", "buyer_name", "winner_name", "award_amount", "n_bidders", "n_risk_indicators", "risk_band", "indicators") if c in top.columns]
    interactive_table(top[cols], key="ri_tbl", download_stem="risk_indicators")
