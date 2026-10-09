from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import charts
from dashboard.components.metrics import kpi_row
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import fmt_int, fmt_pct


KEY_FIELDS = [
    "ocid",
    "title",
    "buyer_id",
    "buyer_identifier",
    "winner_id",
    "winner_identifier",
    "estimated_value",
    "award_value",
    "award_total",
    "tender_start",
    "tender_end",
    "award_date",
    "published_date",
    "cpv_primary",
    "n_bidders",
]


def render(df, bundle) -> None:
    st.title("Data quality")
    st.markdown(
        '<p class="story">Research quality: coverage, missingness, duplicates, and impossible dates — from the actual snapshot.</p>',
        unsafe_allow_html=True,
    )

    val = bundle.artefacts.get("validation") or {}
    n = len(df)
    dup = int(df["ocid"].duplicated().sum()) if "ocid" in df.columns else 0
    dates = df["event_date"] if "event_date" in df.columns else pd.Series(dtype="datetime64[ns, UTC]")
    inverted = 0
    if "tender_start" in df.columns and "tender_end" in df.columns:
        inverted = int((df["tender_end"] < df["tender_start"]).fillna(False).sum())

    kpi_row(
        [
            ("Records in filter", fmt_int(n), None),
            ("Duplicate OCIDs", fmt_int(dup), "Should be 0 if the snapshot is one row per procedure."),
            (
                "Coverage period",
                _span(dates),
                "Min–max of published_date / tender_start.",
            ),
            ("Inverted tender periods", fmt_int(inverted), "endDate before startDate."),
        ]
    )

    if val:
        with st.expander("Full-corpus validation report (unfiltered pipeline)", expanded=False):
            st.json(
                {
                    "n_tenders": val.get("n_tenders"),
                    "n_unique_procurers": val.get("n_unique_procurers"),
                    "n_unique_winners": val.get("n_unique_winners"),
                    "date_range": val.get("date_range"),
                    "missing_rate": val.get("missing_rate"),
                    "coverage": val.get("coverage"),
                }
            )

    miss_rows = []
    for col in KEY_FIELDS:
        if col not in df.columns:
            miss_rows.append({"field": col, "missing": n, "share": 1.0, "note": "column absent"})
            continue
        s = df[col]
        missing = int(s.isna().sum() + (s.astype(str).str.strip().isin(("", "nan", "None"))).sum()) if s.dtype == object else int(s.isna().sum())
        if col in ("winner_id", "winner_identifier"):
            missing = int(s.isna().sum())
        miss_rows.append({"field": col, "missing": missing, "share": missing / max(n, 1), "note": ""})
    miss = pd.DataFrame(miss_rows)
    charts.bar(miss, "share", "field", "Missingness share (current filter)", "dq_miss", horizontal=True)
    interactive_table(miss, key="dq_miss_tbl", download_stem="missingness")

    st.subheader("Missing identifiers")
    kpi_row(
        [
            ("Missing procurer IDs", fmt_int(_missing(df, "buyer_id")), None),
            ("Missing supplier IDs", fmt_int(_missing(df, "winner_id")), "Often legitimate: no award published."),
            ("Missing financial award", fmt_int(_missing(df, "award_amount")), None),
            ("Missing CPV", fmt_int(_missing(df, "cpv_primary")), None),
        ]
    )

    if "award_amount" in df.columns:
        amt = pd.to_numeric(df["award_amount"], errors="coerce")
        st.subheader("Financial sanity")
        st.write(
            f"Min {amt.min():,.2f} · median {amt.median():,.2f} · 99th {amt.quantile(0.99):,.2f} · max {amt.max():,.2f} MDL. "
            "A max far above the 99th percentile is a **potential financial anomaly requiring further investigation** "
            "(data error or genuine mega-contract)."
        )

    bl = bundle.artefacts.get("blacklist")
    if bl is not None and not bl.empty:
        with st.expander("External debarment list matches (MOF)", expanded=False):
            st.caption("match_level `none` means the listed entity was not found in this snapshot — shown honestly.")
            interactive_table(bl, key="dq_bl", download_stem="blacklist_matches")


def _missing(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return len(df)
    return int(pd.isna(df[col]).sum())


def _span(dates: pd.Series) -> str:
    d = dates.dropna()
    if d.empty:
        return "—"
    return f"{d.min().date()} → {d.max().date()}"
