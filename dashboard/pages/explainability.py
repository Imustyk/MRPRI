from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.pages.anomalies import _detail
from dashboard.utils.formatting import DISCLAIMER
from dashboard.utils.preprocessing import MODEL_SPECS
from src.mtender.features import FEATURE_COLUMNS, UNAVAILABLE


def render(df, bundle) -> None:
    st.title("Explainability")
    st.markdown(
        '<p class="story">Why did the tabular models treat some procedures as unusual? '
        "Global SHAP (Isolation Forest) plus per-row deviation from typical values.</p>",
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)

    expl = bundle.artefacts.get("explainability") or {}
    st.caption(expl.get("shap_status") or "SHAP status not in summary artefact.")
    if expl.get("grad_cam"):
        st.info(expl["grad_cam"])

    tab_global, tab_local, tab_missing = st.tabs(["Global attribution", "Selected procedure", "Unavailable indicators"])

    with tab_global:
        shap = bundle.artefacts.get("shap")
        if shap is not None and not shap.empty:
            charts.bar(
                shap.head(20),
                "mean_abs_shap",
                "feature",
                "Mean |SHAP| — Isolation Forest (pipeline sample)",
                "xai_shap",
                horizontal=True,
            )
            interactive_table_safe(shap, "xai_shap_tbl", "shap_feature_importance")
        else:
            st.warning("No `shap_feature_importance.csv`. Permutation importance is the fallback.")
        perm = bundle.artefacts.get("permutation")
        if perm is not None and not perm.empty:
            charts.bar(
                perm.head(20),
                "perm_importance_mean",
                "feature",
                "Permutation importance (Isolation Forest)",
                "xai_perm",
                horizontal=True,
            )
        prof = bundle.artefacts.get("feature_profiles")
        if prof is not None and not prof.empty:
            st.subheader("Flagged vs typical (consensus in the detection snapshot)")
            charts.bar(
                prof.head(15),
                "separation",
                "feature",
                "Absolute difference of means (flagged − typical)",
                "xai_sep",
                horizontal=True,
            )
            interactive_table_safe(prof, "xai_prof", "feature_profiles")

    with tab_local:
        scored = df[df["is_scored"] == True] if "is_scored" in df.columns else df.iloc[0:0]  # noqa: E712
        if scored.empty:
            st.info("Select filters that include scored procedures, then pick an OCID.")
        else:
            flagged = scored[scored["is_anomalous"] == True]  # noqa: E712
            pool = flagged if not flagged.empty else scored
            ocid = st.selectbox("Anomalous (or scored) procurement", pool["ocid"].astype(str).tolist()[:4000])
            row = pool[pool["ocid"].astype(str) == ocid].iloc[0]
            spec = MODEL_SPECS[1]
            _detail(row, spec, spec["score"])
            st.subheader("Why was it anomalous? (feature deviation)")
            st.caption(
                "Contribution here is (value − median of non-flagged rows in the current filter) "
                "for pipeline features. This is **not** a stored per-row SHAP value. "
                "Global SHAP is on the previous tab."
            )
            typical = df[df["is_anomalous"] == False] if "is_anomalous" in df.columns else df  # noqa: E712
            rows = []
            for col in FEATURE_COLUMNS:
                if col not in row.index:
                    continue
                val = pd.to_numeric(pd.Series([row[col]]), errors="coerce").iloc[0]
                med = pd.to_numeric(typical[col], errors="coerce").median() if col in typical.columns else None
                if pd.isna(val) or med is None or pd.isna(med):
                    continue
                rows.append(
                    {
                        "Feature": col,
                        "Value": val,
                        "Typical median": med,
                        "Contribution (value − typical)": val - med,
                    }
                )
            local = pd.DataFrame(rows)
            if not local.empty:
                local = local.sort_values("Contribution (value − typical)", key=lambda s: s.abs(), ascending=False)
                charts.bar(
                    local.head(12),
                    "Contribution (value − typical)",
                    "Feature",
                    "Largest deviations from typical",
                    "xai_local",
                    horizontal=True,
                )
                interactive_table_safe(local, "xai_local_tbl", "local_contributions")

    with tab_missing:
        st.write("Indicators that were **not** built, because the verified MTender payload does not support them:")
        miss = pd.DataFrame({"indicator": list(UNAVAILABLE.keys()), "reason": list(UNAVAILABLE.values())})
        interactive_table_safe(miss, "xai_unavail", "unavailable_indicators")


def interactive_table_safe(df, key, stem):
    from dashboard.components.tables import interactive_table

    interactive_table(df, key=key, download_stem=stem)
