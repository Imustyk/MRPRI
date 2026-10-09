from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.metrics import kpi_row
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import DISCLAIMER, UNAVAILABLE_AUTOENCODER, fmt_int, fmt_pct, fmt_score
from dashboard.utils.preprocessing import MODEL_SPECS, indicator_badges


def render(df, bundle) -> None:
    st.title("Anomaly detection")
    st.markdown(
        '<p class="story">What looks unusual according to the detectors actually fitted in scripts/06?</p>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)

    scored = df[df["is_scored"] == True].copy() if "is_scored" in df.columns else df.iloc[0:0]  # noqa: E712
    if scored.empty:
        st.warning("No detector scores in the current filter. The score table covers the detection snapshot only.")
        return

    labels = [m["label"] for m in MODEL_SPECS]
    choice = st.radio("Select model", labels, horizontal=True, key="ad_model")
    spec = next(m for m in MODEL_SPECS if m["label"] == choice)
    if not spec["implemented"]:
        st.warning(UNAVAILABLE_AUTOENCODER)
        spec = MODEL_SPECS[1]

    flag_col, score_col = spec["flag"], spec["score"]
    if flag_col not in scored.columns:
        st.error(f"Column {flag_col} is missing from the score artefact.")
        return

    flags = pd.to_numeric(scored[flag_col], errors="coerce").fillna(0).astype(int)
    n = len(scored)
    n_anom = int(flags.sum())
    kpi_row(
        [
            ("Total observations (scored)", fmt_int(n), "Rows with detector output under the filter."),
            ("Normal observations", fmt_int(n - n_anom), f"Not flagged by {spec['label']}."),
            ("Anomalous observations", fmt_int(n_anom), "Statistical outlier flag, not a corruption label."),
            ("Anomaly percentage", fmt_pct(n_anom / max(n, 1)), "Contamination in the pipeline was set to 5% for IF/LOF/SVM."),
        ]
    )

    tab_score, tab_rank, tab_pca, tab_detail = st.tabs(
        ["Score distribution", "Anomaly ranking", "PCA scatter", "Procedure detail"]
    )

    with tab_score:
        charts.hist(scored[score_col].rename("anomaly_score"), f"Anomaly score — {spec['label']}", "ad_hist")
        st.caption("Score scales differ by model (LOF can be huge; SVM decision scores can be negative). Compare ranks, not raw units.")

    with tab_rank:
        ranked = scored.copy()
        ranked["_flag"] = flags
        ranked = ranked.sort_values([flag_col, score_col], ascending=[False, False])
        ranked["Rank"] = range(1, len(ranked) + 1)
        risk_src = ranked.apply(lambda r: "; ".join(indicator_badges(r)[:6]), axis=1)
        show = pd.DataFrame(
            {
                "Rank": ranked["Rank"],
                "Procurement": ranked.get("title"),
                "OCID": ranked.get("ocid"),
                "Supplier": ranked.get("winner_name"),
                "Procurer": ranked.get("buyer_name"),
                "Value": ranked.get("award_amount"),
                "Anomaly score": ranked[score_col],
                "Models flagging": ranked.get("n_models_flagging"),
                "Risk indicators": risk_src,
            }
        )
        q = st.text_input("Filter ranking table", key="ad_q")
        if q.strip():
            qq = q.strip().lower()
            mask = False
            for col in ("Procurement", "OCID", "Supplier", "Procurer"):
                mask = mask | show[col].fillna("").astype(str).str.lower().str.contains(qq, regex=False)
            show = show[mask]
        interactive_table(show.head(3000), key="ad_rank", download_stem="anomaly_ranking")

    with tab_pca:
        if "pc1" not in scored.columns or scored["pc1"].isna().all():
            st.info("PCA coordinates come from `results/tables/pca_projection.csv` and are missing here.")
        else:
            plot = scored.dropna(subset=["pc1", "pc2"]).copy()
            plot["anomaly_status"] = flags.reindex(plot.index).map({1: "anomalous", 0: "normal"})
            hover = [c for c in ("ocid", "winner_name", "buyer_name", "award_amount", score_col, "title") if c in plot.columns]
            charts.scatter(
                plot,
                "pc1",
                "pc2",
                "PCA projection of the scored feature space",
                "ad_pca",
                color="anomaly_status",
                hover=hover,
            )
            det = bundle.artefacts.get("detection") or {}
            ev = det.get("pca_explained_variance")
            if ev:
                st.caption(f"Explained variance (pipeline run): PC1 {ev[0]:.1%}, PC2 {ev[1]:.1%}.")

    with tab_detail:
        options = scored["ocid"].dropna().astype(str).tolist()
        selected = st.selectbox("Select a procurement (OCID)", options[:5000] if options else [])
        if selected:
            row = scored[scored["ocid"].astype(str) == selected].iloc[0]
            _detail(row, spec, score_col)


def _detail(row: pd.Series, spec: dict, score_col: str) -> None:
    st.subheader(row.get("title") or row.get("ocid"))
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**General**")
        st.write(f"Tender / OCID: `{row.get('tender_id') or row.get('ocid')}`")
        st.write(f"Procurer: {row.get('buyer_name') or '—'}")
        st.write(f"Supplier: {row.get('winner_name') or '—'}")
        st.write(f"Date: {row.get('event_date')}")
        st.write(f"Procedure: {row.get('procurement_method_details') or row.get('procurement_method')}")
        st.write(f"Status: {row.get('status')}")
    with c2:
        st.markdown("**Financial**")
        st.write(f"Estimated: {fmt_score(row.get('estimated_value'), 0)} MDL")
        st.write(f"Awarded (primary): {fmt_score(row.get('award_value'), 0)} MDL")
        st.write(f"Award total: {fmt_score(row.get('award_amount'), 0)} MDL")
        st.markdown("**Competition**")
        st.write(f"Distinct bidders: {row.get('n_bidders')}")
        st.caption("Lot-level bid records are not shown as bidder counts.")
    with c3:
        st.markdown("**ML**")
        st.write(f"Model view: {spec['label']}")
        st.write(f"Score: {fmt_score(row.get(score_col))}")
        st.write(f"Flagged by this model: {'yes' if int(row.get(spec['flag']) or 0) == 1 else 'no'}")
        st.write(f"Detectors flagging: {row.get('n_models_flagging')}")
        st.write(f"Risk band: {row.get('risk_band')}")
    badges = indicator_badges(row)
    st.markdown("**Potential risk indicators (from calculated flags)**")
    if badges:
        html = "".join(f'<span class="badge risk">{b}</span>' for b in badges)
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.write("No binary indicator flags are set on this row.")
    st.caption("Requires additional investigation. Not a determination of corruption.")
