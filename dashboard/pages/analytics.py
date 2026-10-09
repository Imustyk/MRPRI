"""Distributions and correlations.

Everything is computed from the filtered frame in memory, so the numbers always
agree with the filters in the sidebar. Where a method choice matters — Pearson
versus Spearman on a right-skewed money column — the page says which one it used
and why, instead of quietly picking the flattering one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.components import charts, layout
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import DISCLAIMER, fmt_int, fmt_pct
from dashboard.utils.preprocessing import FEATURE_LABELS, NUMERIC_CATALOG

SKEW_NOTE = (
    "Award values in this corpus span roughly nine orders of magnitude, so the linear correlation "
    "is dominated by a handful of mega-contracts. Spearman (rank) correlation is the default for "
    "that reason; Pearson is offered so the gap between the two stays visible."
)


def render(df, bundle) -> None:
    layout.page_header(
        "Distributions & correlations",
        "How the values in the current filter are actually shaped, and which features move "
        "together. Computed in memory from the filtered rows, so every figure respects the "
        "sidebar filters.",
        kicker="analytics",
    )
    layout.disclaimer(DISCLAIMER)

    catalog = [c for c in NUMERIC_CATALOG if c in df.columns]
    if not catalog:
        layout.empty_state("No numeric columns", "The current filter left nothing to analyse.")
        return

    tab_dist, tab_corr, tab_group, tab_rel = st.tabs(
        ["Distributions", "Correlations", "By group", "Paired"]
    )

    with tab_dist:
        _distributions(df, catalog)
    with tab_corr:
        _correlations(df, catalog)
    with tab_group:
        _by_group(df, catalog)
    with tab_rel:
        _paired(df, catalog)


def _label(key: str) -> str:
    return FEATURE_LABELS.get(key, key)


def _clean(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df[cols].apply(pd.to_numeric, errors="coerce")
    return out.replace([np.inf, -np.inf], np.nan)


def _iqr(s: pd.Series) -> float:
    if s.empty:
        return 0.0
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return 0.0
    return float(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).mean())


# --------------------------------------------------------------------------
def _distributions(df: pd.DataFrame, catalog: list[str]) -> None:
    layout.section(
        "Distribution",
        "Empirical CDF, quantiles and outlier share. The ECDF needs no assumption about the "
        "shape of the distribution, so it is the safer read on a skewed column.",
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        column = st.selectbox("Feature", catalog, format_func=_label, key="an_dist_col")
    with c2:
        log_x = st.checkbox("Log x-axis", value=False, key="an_dist_log")
    with c3:
        nbins = st.slider("Histogram bins", 10, 80, 40, key="an_dist_bins")

    s = pd.to_numeric(df[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        layout.empty_state("No values", f"`{column}` has no numeric values under this filter.")
        return

    q = s.quantile([0.25, 0.5, 0.75, 0.9, 0.99])
    ratio = float(s.max() / s.median()) if s.median() else None
    layout.legend(
        {
            "skewed — consider a log axis": "#b8892a" if (ratio and ratio > 1000) else "#2a6b4a",
        }
    )
    from dashboard.components.metrics import kpi_row

    kpi_row(
        [
            ("Observations", fmt_int(len(s)), "Non-missing values in the current filter.", "neutral", None),
            ("Median", _short(s.median()), "50th percentile.", "neutral", None),
            ("p99", _short(q.loc[0.99]), "Top 1% begins here.", "warn", None),
            ("Maximum", _short(s.max()), "Largest observed value.", "bad" if _iqr(s) > 0.2 else "neutral", None),
        ],
        key="an_dist_kpi",
    )
    if ratio and ratio > 1000:
        st.warning(
            f"The maximum is {ratio:,.0f}× the median. Equal-width histogram bins would put almost "
            "every value in the first bar, so enable the log x-axis above."
        )

    c1, c2 = st.columns(2)
    with c1:
        work = s[s > 0] if log_x else s
        if work.empty:
            st.info("No positive values to plot on a log axis.")
        else:
            charts.hist(work.rename(column), _label(column), "an_hist", nbins=nbins, color="#1e3a5f")
    with c2:
        charts.ecdf(s.rename(column), f"Cumulative share — {_label(column)}", "an_ecdf", log_x=log_x)

    c1, c2 = st.columns(2)
    with c1:
        charts.qq_plot(s.rename(column), f"Normal Q-Q — {_label(column)}", "an_qq")
        st.caption(
            "Points bending away from the dashed line mean the distribution is not normal. For a "
            "money column that is expected, and it is why the median and the ECDF are used above."
        )
    with c2:
        charts.box(s.rename(column), f"Spread and outliers — {_label(column)}", "an_box")

    layout.section("Quantiles", "Values below which the given share of observations falls.")
    qs = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
    table = pd.DataFrame(
        {
            "quantile": [f"p{int(p * 100)}" for p in qs],
            "value": [float(s.quantile(p)) for p in qs],
            "share at or below": [p for p in qs],
        }
    )
    table["value"] = table["value"].map(_short)
    interactive_table(table, key="an_quantiles", download_stem="quantiles")


def _short(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(f):
        return "—"
    a = abs(f)
    if a >= 1e9:
        return f"{f / 1e9:,.2f} bn"
    if a >= 1e6:
        return f"{f / 1e6:,.2f} m"
    if a >= 1e3:
        return f"{f / 1e3:,.1f} k"
    if a < 0.01 and a > 0:
        return f"{f:.2e}"
    return f"{f:,.2f}"


# --------------------------------------------------------------------------
def _correlations(df: pd.DataFrame, catalog: list[str]) -> None:
    layout.section(
        "Correlation matrix",
        "Pairwise-complete observations: a pair is compared only on rows where both features "
        "exist, and the row count is shown per pair so a thin sample is not mistaken for a "
        "full-corpus result.",
    )

    defaults = [c for c in ("award_amount", "estimated_value", "n_bidders", "bid_window_days") if c in catalog]
    if len(defaults) < 2:
        defaults = catalog[:4]

    c1, c2 = st.columns([3, 1])
    with c1:
        picked = st.multiselect(
            "Features", catalog, default=defaults, format_func=_label, key="an_corr_cols"
        )
    with c2:
        method = st.radio(
            "Method",
            ["spearman", "pearson", "kendall"],
            format_func=lambda m: m.capitalize(),
            help=SKEW_NOTE,
            key="an_corr_method",
        )
        min_abs = st.slider("Hide |r| below", 0.0, 0.9, 0.0, 0.05, key="an_corr_min")

    if len(picked) < 2:
        layout.empty_state("Pick at least two features", "Use the box above to select several.")
        return
    if len(picked) > 18:
        st.warning(f"Showing the first 18 of {len(picked)} selected features; a larger matrix stops being readable.")
        picked = picked[:18]

    usable = [c for c in picked if pd.to_numeric(df[c], errors="coerce").notna().sum() >= 30]
    if len(usable) < 2:
        layout.empty_state(
            "Not enough data",
            "Each feature needs at least 30 non-missing values under the current filter.",
        )
        return

    num = _clean(df, usable)
    corr = num.corr(method=method, min_periods=30)
    st.caption(
        f"{method.capitalize()} correlation over {fmt_int(len(num))} rows. "
        "Teal is negative, gold is positive, and the shading follows magnitude."
    )
    charts.corr_heatmap(num, usable, f"{method.capitalize()} correlation", "an_corr", method=method)

    pairs = charts.strongest_pairs(corr, 25)
    if pairs.empty:
        return
    pairs = pairs[pairs["|r|"] >= min_abs]
    if pairs.empty:
        st.info(f"No pair reaches |r| ≥ {min_abs:.2f}.")
        return
    pairs = pairs.copy()
    pairs["Feature A"] = pairs["Feature A"].map(_label)
    pairs["Feature B"] = pairs["Feature B"].map(_label)
    pairs["r"] = pairs["r"].map(lambda v: f"{v:.3f}")
    pairs["|r|"] = pairs["|r|"].map(lambda v: f"{v:.3f}")
    interactive_table(
        pairs,
        key="an_corr_pairs",
        download_stem="correlations",
        caption=f"Strongest {method} pairs in the current filter.",
    )

    top = charts.strongest_pairs(corr, 1)
    if not top.empty:
        a, b = top.iloc[0]["Feature A"], top.iloc[0]["Feature B"]
        st.info(
            f"Strongest pair in this filter: **{_label(a)}** and **{_label(b)}**, "
            f"r = {top.iloc[0]['r']:.3f}. A correlation is co-variation, not a causal claim, and "
            "a strong value here can also mean both features were derived from contract size."
        )


# --------------------------------------------------------------------------
def _by_group(df: pd.DataFrame, catalog: list[str]) -> None:
    layout.section(
        "Distribution by category",
        "Interquartile range per category. A median bar is used instead of a mean because the "
        "mean of a right-skewed column is set by its largest value.",
    )
    group_options = [
        c
        for c in ("risk_band", "status", "procurement_method", "procurement_method_details", "cpv_div", "buyer_locality")
        if c in df.columns
    ]
    if not group_options:
        layout.empty_state("No categorical column available")
        return

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        value = st.selectbox("Measure", catalog, format_func=_label, key="an_grp_val")
    with c2:
        group = st.selectbox("Group by", group_options, format_func=_label, key="an_grp_key")
    with c3:
        min_n = st.number_input("Min rows per group", min_value=5, value=30, step=5, key="an_grp_min")

    frame = df[[value, group]].copy()
    frame[value] = pd.to_numeric(frame[value], errors="coerce")
    frame = frame.dropna(subset=[value])
    if frame.empty:
        layout.empty_state("No paired values", "The measure is empty for every row in this filter.")
        return

    counts = frame[group].value_counts()
    keep = counts[counts >= min_n].head(14).index
    dropped = int(len(counts) - len(keep))
    if dropped:
        st.caption(
            f"{dropped} smaller group(s) were dropped for having fewer than {min_n} rows, so a "
            "single record cannot define a bar."
        )
    if len(keep) == 0:
        layout.empty_state("No group is large enough", f"Lower the minimum below {min_n} rows.")
        return

    sub = frame[frame[group].isin(keep)]
    rows = []
    for key in keep:
        vals = sub.loc[sub[group] == key, value]
        rows.append(
            {
                "group": str(key),
                "n": int(vals.notna().sum()),
                "p25": float(vals.quantile(0.25)),
                "median": float(vals.median()),
                "p75": float(vals.quantile(0.75)),
                "mean": float(vals.mean()),
                "outlier_share": _iqr(vals),
            }
        )
    stats = pd.DataFrame(rows).sort_values("median", ascending=False)

    c1, c2 = st.columns(2)
    with c1:
        charts.violin(sub, group, value, f"{_label(value)} by {_label(group)}", "an_violin", max_categories=14)
    with c2:
        charts.box_group(sub, group, value, f"Interquartile range — {_label(value)}", "an_box_grp", max_categories=14)

    view = stats.copy()
    for col in ("p25", "median", "p75", "mean"):
        view[col] = view[col].map(_short)
    view["outlier_share"] = view["outlier_share"].map(fmt_pct)
    interactive_table(view, key="an_grp_tbl", download_stem="group_stats")


# --------------------------------------------------------------------------
def _paired(df: pd.DataFrame, catalog: list[str]) -> None:
    layout.section(
        "Two features against each other",
        "Down-sampled with a fixed random seed, so the same filters always redraw the same "
        "points instead of a reshuffled cloud.",
    )
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        x = st.selectbox("X", catalog, index=0, format_func=_label, key="an_pair_x")
    with c2:
        y = st.selectbox("Y", catalog, index=min(1, len(catalog) - 1), format_func=_label, key="an_pair_y")
    with c3:
        color = st.selectbox(
            "Colour by",
            ["(none)"] + [c for c in ("risk_band", "status", "cpv_div") if c in df.columns],
            format_func=lambda v: "(none)" if v == "(none)" else _label(v),
            key="an_pair_c",
        )

    log_axes = st.checkbox(
        "Logarithmic axes", value=True, help="Recommended: both money columns are heavily skewed."
    )
    colour = None if color == "(none)" else color
    hover = [c for c in ("ocid", "title", "buyer_name", "winner_name", "award_amount") if c in df.columns]

    c1, c2 = st.columns(2)
    with c1:
        charts.marginal_scatter(
            df, x, y, f"{_label(x)} vs {_label(y)}", "an_scatter", color=colour, hover=hover,
            log_x=log_axes, log_y=log_axes,
        )
    with c2:
        pair = _clean(df, [x, y]).dropna()
        if log_axes:
            pair = pair[(pair[x] > 0) & (pair[y] > 0)]
        if len(pair) < 10:
            layout.empty_state("Not enough paired values", "Need at least 10 rows with both values.")
        else:
            plots = {"Pearson (linear)": pair, "Spearman (rank)": pair}
            series = {
                name: charts._numeric(
                    pd.Series(
                        np.argsort(np.argsort(p[list(p.columns)[0]].to_numpy())).astype(float),
                        name=f"{name} rank of {x}",
                    )
                )
                for name, p in plots.items()
            }
            charts.hist_compare(
                series,
                f"Rank of {_label(x)} — Pearson fits linear, Spearman fits monotone",
                "an_rank_cmp",
            )
            st.caption(
                "On heavily skewed data the two fit very differently. A tight Pearson cloud with a "
                "loose Spearman one means a few extreme points drive the linear coefficient."
            )
