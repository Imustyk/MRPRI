from __future__ import annotations

import streamlit as st

from dashboard.utils.formatting import DISCLAIMER


IMPLEMENTED = [
    ("MTender public OCDS API", "Verified in docs/API_INVESTIGATION_REPORT.md (`public.mtender.gov.md`)."),
    ("Data collection", "scripts/01a_scan_ocids.py, 01b_fetch_records.py → MongoDB raw_*."),
    ("Raw JSON archive", "data/raw/ocds_packages and ocid_inventory.jsonl."),
    ("Validation", "scripts/08_data_dictionary.py, results/validation_report.json."),
    ("Cleaning / normalisation", "scripts/02_normalize_mongo.py → norm_tenders / norm_parties."),
    ("Feature engineering", "scripts/03_features_mongo.py, src/mtender/features.py."),
    ("ML models", "Isolation Forest, LOF, One-Class SVM, MAD z-score in scripts/06_detect_anomalies.py."),
    ("Anomaly detection store", "results/tables/tender_anomaly_scores.csv (+ Mongo anomaly_scores when the detect job writes it)."),
    ("XAI / SHAP", "TreeExplainer on Isolation Forest in scripts/07_explainability.py; permutation importance fallback."),
    ("Risk indicators", "Binary flags in FEATURE_COLUMNS + model-agreement bands."),
    ("Interactive dashboard", "This Streamlit app (`app.py`) and the existing React/FastAPI prototype."),
]

PROPOSED = [
    ("Convolutional / Grad-CAM stack", "Not applicable to tabular OCDS features; recorded as a limitation."),
    ("Autoencoder detector", "Specified as a comparison option; not fitted in the executed pipeline."),
    ("Winning-margin / bid-spread indicators", "Blocked by unpublished per-bidder prices for most procedures."),
    ("Coordinate map of procurers", "No lat/lon in the payload; locality names only."),
    ("Court-labelled corruption outcomes", "No public ground-truth label; precision/recall only on the synthetic lab experiment."),
]


def render(df, bundle) -> None:
    st.title("Architecture")
    st.markdown(
        '<p class="story">How the research pipeline feeds this dashboard — implemented vs proposed.</p>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)

    st.code(
        """
MTender API
     ↓
Data Collection
     ↓
Raw JSON / Mongo raw_*
     ↓
Data Validation
     ↓
Data Cleaning / normalisation
     ↓
Feature Engineering
     ↓
ML Models (IF, LOF, OCSVM, MAD)
     ↓
Anomaly Detection
     ↓
XAI / SHAP (Isolation Forest)
     ↓
Risk Indicators
     ↓
Interactive Dashboard
        """.strip(),
        language="text",
    )

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Implemented")
        for title, note in IMPLEMENTED:
            st.markdown(f"**{title}**  \n{note}")
    with c2:
        st.subheader("Proposed / not executed")
        for title, note in PROPOSED:
            st.markdown(f"**{title}**  \n{note}")

    det = bundle.artefacts.get("detection") or {}
    feat = bundle.artefacts.get("features_summary") or {}
    st.subheader("This snapshot")
    st.write(
        {
            "feature_rows": feat.get("n_inserted") or len(df),
            "detection_rows_in_summary": det.get("n_rows"),
            "contamination_assumption": det.get("contamination_assumption"),
            "demo_mode": bundle.demo,
            "source": bundle.source_label,
        }
    )
