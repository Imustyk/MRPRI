from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import DISCLAIMER, UNAVAILABLE_AUTOENCODER
from dashboard.utils.preprocessing import MODEL_SPECS


def render(df, bundle) -> None:
    st.title("Model comparison")
    st.markdown(
        '<p class="story">Empirical differences between detectors on the same preprocessed feature matrix. '
        "No winner is declared.</p>",
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)
    st.warning(UNAVAILABLE_AUTOENCODER)

    scored = df[df["is_scored"] == True].copy() if "is_scored" in df.columns else pd.DataFrame()  # noqa: E712
    implemented = [m for m in MODEL_SPECS if m["implemented"]]

    tab_table, tab_scores, tab_overlap = st.tabs(["Summary table", "Score distributions", "Model agreement"])

    with tab_table:
        arte = bundle.artefacts.get("model_comparison")
        if arte is not None and not arte.empty:
            st.caption("Written by `scripts/06_detect_anomalies.py` (full detection run, not re-estimated in the UI).")
            interactive_table(arte, key="mc_arte", download_stem="model_comparison")
        if not scored.empty:
            rows = []
            for m in implemented:
                if m["flag"] not in scored.columns:
                    continue
                flags = pd.to_numeric(scored[m["flag"]], errors="coerce").fillna(0)
                scores = pd.to_numeric(scored[m["score"]], errors="coerce")
                rows.append(
                    {
                        "Model": m["label"],
                        "Anomalies (current filter)": int(flags.sum()),
                        "Mean score (filter)": float(scores.mean()) if scores.notna().any() else None,
                        "Runtime": "see pipeline logs — not re-run in the dashboard",
                        "Parameters": _params(bundle, m["key"]),
                    }
                )
            interactive_table(pd.DataFrame(rows), key="mc_live", download_stem="model_comparison_filter")
            fig_df = pd.DataFrame(rows)
            if not fig_df.empty:
                charts.bar(fig_df, "Model", "Anomalies (current filter)", "Flagged counts under the current filter", "mc_n")

    with tab_scores:
        if scored.empty:
            st.info("No scores in the current filter.")
        else:
            for m in implemented:
                if m["score"] in scored.columns:
                    charts.hist(scored[m["score"]].rename(m["label"]), m["label"], f"mc_h_{m['key']}")

    with tab_overlap:
        _agreement(scored, implemented)


def _params(bundle, key: str) -> str:
    det = bundle.artefacts.get("detection") or {}
    for item in det.get("models") or []:
        if item.get("model") == key:
            return str(item.get("params", ""))[:400]
    return "—"


def _agreement(scored: pd.DataFrame, implemented: list[dict]) -> None:
    st.subheader("Which procedures were flagged by several algorithms?")
    cols = [m["flag"] for m in implemented if m["flag"] in scored.columns]
    if not cols or scored.empty:
        st.info("Need scored rows with flag columns.")
        return
    flags = scored[cols].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
    labels = [m["label"] for m in implemented if m["flag"] in cols]

    # pairwise overlap matrix
    z = []
    for i, a in enumerate(cols):
        row = []
        for b in cols:
            inter = int(((flags[a] == 1) & (flags[b] == 1)).sum())
            row.append(inter)
        z.append(row)
    charts.heatmap(z, labels, labels, "Overlap counts (A and B both flag)", "mc_overlap")

    pattern = flags.astype(str).agg("".join, axis=1)
    pretty = pattern.map(lambda bits: _combo_name(bits, labels))
    counts = pretty.value_counts().rename_axis("combination").reset_index(name="n")
    charts.bar(counts.head(16), "n", "combination", "Flag combinations (UpSet-style counts)", "mc_combo", horizontal=True)
    interactive_table(counts, key="mc_combo_tbl", download_stem="model_agreement")
    st.caption(
        "Isolation Forest only / LOF only / … / all models are the bit-pattern groups above. "
        "The statistical baseline may flag few or no rows when binary indicators are excluded from MAD scoring."
    )


def _combo_name(bits: str, labels: list[str]) -> str:
    on = [labels[i] for i, b in enumerate(bits) if b == "1"]
    if not on:
        return "No detector"
    if len(on) == len(labels):
        return "All implemented models"
    if len(on) == 1:
        return f"{on[0]} only"
    short = {"Statistical (MAD z-score)": "MAD", "Isolation Forest": "IF", "Local Outlier Factor": "LOF", "One-Class SVM": "OCSVM"}
    return " + ".join(short.get(x, x) for x in on)
