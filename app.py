"""MTender AI Risk Analytics — Streamlit dashboard.

Run from the repository root:

    .venv/bin/streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from dashboard.components import layout
from dashboard.components.filters import filtered, render_sidebar_filters
from dashboard.components.theme import CSS
from dashboard.pages import (
    analytics,
    anomalies,
    architecture,
    competition,
    data_quality,
    explainability,
    financial,
    models,
    overview,
    procurement_analysis,
    risk,
    suppliers,
    workspace,
)
from dashboard.utils.data_loader import load_bundle
from dashboard.utils.formatting import DISCLAIMER, fmt_int
from src.mtender import workspace as ws

st.set_page_config(
    page_title="MTender AI Risk Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CSS, unsafe_allow_html=True)

#: (group label, page label, renderer). The group headings keep a long page list
#: scannable in the sidebar without nesting the navigation itself.
PAGES: list[tuple[str, str, object]] = [
    ("Explore", "Overview", overview.render),
    ("Explore", "Distributions", analytics.render),
    ("Explore", "Procurement", procurement_analysis.render),
    ("Explore", "Suppliers", suppliers.render),
    ("Explore", "Competition", competition.render),
    ("Explore", "Financial", financial.render),
    ("Risk", "Anomalies", anomalies.render),
    ("Risk", "Risk indicators", risk.render),
    ("Risk", "Models", models.render),
    ("Risk", "Explainability", explainability.render),
    ("Workspace", "Cases & notes", workspace.render),
    ("Quality", "Data quality", data_quality.render),
    ("Quality", "Architecture", architecture.render),
]


def _sidebar(bundle) -> dict:
    layout.brand("Public procurement anomaly detection")
    st.sidebar.markdown(
        '<p style="font-size:.78rem;color:#a9bbcd;margin:.2rem 0 1rem">'
        "Decision support, not a verdict.</p>",
        unsafe_allow_html=True,
    )

    if bundle.demo:
        st.sidebar.error("⚠ DEMO DATA — NOT REAL PROCUREMENT DATA")
    else:
        st.sidebar.success(bundle.source_label)

    # --- navigation, grouped ---
    labels = [label for _, label, _ in PAGES]
    # The key lets Streamlit remember the selection across reruns; the heading
    # below names the group the current page belongs to.
    chosen = st.sidebar.radio("Dashboard", labels, index=0, label_visibility="collapsed", key="_nav")
    layout.nav_group(PAGES[labels.index(chosen)][0])
    st.sidebar.markdown('<div class="nav-group">Filters</div>', unsafe_allow_html=True)

    filters = render_sidebar_filters(bundle.tenders)
    return {"page": chosen, "filters": filters}


def main() -> None:
    bundle = load_bundle()
    state = _sidebar(bundle)
    view = filtered(bundle.tenders, state["filters"])

    st.sidebar.markdown("---")
    n_view = len(view)
    n_all = len(bundle.tenders)
    share = n_view / n_all if n_all else 0
    st.sidebar.markdown(
        '<div class="sidebar-stat">Showing <b>%s</b> of <b>%s</b> procedures<br>'
        '<span style="color:#a9bbcd">%.1f%% of the corpus</span></div>'
        % (fmt_int(n_view), fmt_int(n_all), share * 100),
        unsafe_allow_html=True,
    )

    counts = ws.summary()["counts"]
    if counts["cases"] or counts["annotations"] or counts["watchlists"]:
        st.sidebar.markdown(
            '<div class="sidebar-stat" style="margin-top:.5rem">'
            "Workspace · <b>%d</b> cases · <b>%d</b> notes</div>"
            % (counts["cases"], counts["annotations"]),
            unsafe_allow_html=True,
        )
    st.sidebar.caption(DISCLAIMER)

    if bundle.demo:
        st.markdown(
            '<div class="demo-banner">⚠ DEMO DATA — NOT REAL PROCUREMENT DATA</div>',
            unsafe_allow_html=True,
        )

    render = next(r for _, name, r in PAGES if name == state["page"])
    render(view, bundle)
    layout.footer(bundle.source_label, demo=bundle.demo)


main()
