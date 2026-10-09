"""Plotly chart helpers.

Two families live here:

* the original single-purpose wrappers (bar / donut / hist / box / scatter / heatmap)
  which the existing pages depend on, and
* distribution + correlation charts (ECDF, Q-Q, violin, correlation matrix,
  marginal scatter, log-log outlier map, composition treemap) used by the
  analytics page.

Every helper degrades to an inline notice instead of raising when the current
filter yields no data, so a page never dies on an empty selection.
"""

from __future__ import annotations

import inspect
from statistics import NormalDist

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.theme import (
    DIVERGING,
    GOLD,
    GREEN,
    MUTED_SAFE,
    NAVY,
    NAVY_DEEP,
    PLOTLY_LAYOUT,
    RED,
    SEQUENTIAL,
)

#: Above this many points a scatter/line trace becomes unreadable and slow.
MAX_POINTS = 12_000

_NO_DATA = "No observations for this chart under the current filter."


def _plotly_kwargs() -> dict:
    """Support both the new width= and the deprecated use_container_width= APIs."""
    try:
        params = inspect.signature(st.plotly_chart).parameters
    except (TypeError, ValueError):
        return {}
    if "width" in params:
        return {"width": "stretch"}
    return {"use_container_width": True}


def _numeric(series) -> pd.Series:
    return pd.to_numeric(pd.Series(series), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _sample(df: pd.DataFrame, key: str, max_points: int = MAX_POINTS) -> pd.DataFrame:
    if len(df) > max_points:
        return df.sample(n=max_points, random_state=42)
    return df


def show(fig, key: str | None = None, height: int | None = None) -> None:
    fig.update_layout(**PLOTLY_LAYOUT)
    if height:
        fig.update_layout(height=height)
    fig.update_layout(autosize=True)
    st.plotly_chart(
        fig,
        key=key,
        config={"displaylogo": False, "responsive": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
        **_plotly_kwargs(),
    )


# --------------------------------------------------------------------------
# original wrappers
# --------------------------------------------------------------------------
def line_count_value(ts: pd.DataFrame, y: str, title: str, y_title: str, key: str) -> None:
    if ts.empty or y not in ts.columns:
        st.info(_NO_DATA)
        return
    frame = ts.dropna(subset=[y])
    if frame.empty:
        st.info(_NO_DATA)
        return
    fig = px.line(frame, x="period", y=y, markers=True, title=title)
    fig.update_traces(line_color=NAVY, line_width=2.2, marker_size=5)
    fig.update_yaxes(title=y_title, tickformat=",.0f" if y != "period" else None)
    fig.update_xaxes(title="Time")
    show(fig, key)


def bar(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    key: str,
    horizontal: bool = False,
    color=NAVY,
) -> None:
    if df.empty or x not in df.columns or y not in df.columns:
        st.info(_NO_DATA)
        return
    if horizontal:
        fig = px.bar(df, x=x, y=y, orientation="h", title=title)
        fig.update_traces(marker_color=color)
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
    else:
        fig = px.bar(df, x=x, y=y, title=title)
        fig.update_traces(marker_color=color)
    show(fig, key)


def donut(df: pd.DataFrame, names: str, values: str, title: str, key: str) -> None:
    if df.empty or names not in df.columns or values not in df.columns:
        st.info(_NO_DATA)
        return
    fig = px.pie(df, names=names, values=values, hole=0.45, title=title)
    fig.update_traces(textposition="inside", textinfo="percent+label", marker=dict(line=dict(width=1.5, color="#fffdf8")))
    show(fig, key)


def hist(series: pd.Series, title: str, key: str, nbins: int = 40, color=NAVY) -> None:
    s = _numeric(series)
    if s.empty:
        st.info("No numeric values for this distribution under the current filter.")
        return
    fig = px.histogram(s, nbins=nbins, title=title)
    fig.update_traces(marker_color=color, marker_line=dict(width=0.5, color="#fffdf8"))
    fig.update_layout(showlegend=False, bargap=0.04)
    fig.update_xaxes(title=series.name or "value")
    fig.update_yaxes(title="Count")
    show(fig, key)


def box(series: pd.Series, title: str, key: str) -> None:
    s = _numeric(series)
    if s.empty:
        st.info("No numeric values for this box plot under the current filter.")
        return
    fig = go.Figure()
    fig.add_trace(go.Box(y=s, name=series.name or "value", marker_color=NAVY, boxpoints="outliers"))
    fig.update_layout(title=title, showlegend=False)
    show(fig, key)


def scatter(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    key: str,
    color: str | None = None,
    hover: list | None = None,
) -> None:
    if df.empty or x not in df.columns or y not in df.columns:
        st.info(_NO_DATA)
        return
    frame = _sample(df, key)
    fig = px.scatter(
        frame,
        x=x,
        y=y,
        color=color,
        hover_data=hover,
        title=title,
        color_discrete_map={
            0: MUTED_SAFE,
            1: RED,
            False: MUTED_SAFE,
            True: RED,
            "normal": GREEN,
            "anomalous": RED,
        },
    )
    fig.update_traces(marker=dict(size=6, opacity=0.65, line=dict(width=0.4, color="#fffdf8")))
    show(fig, key)


def heatmap(z, x, y, title: str, key: str) -> None:
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x,
            y=y,
            colorscale="YlOrRd",
            xgap=1,
            ygap=1,
            colorbar=dict(title="count", thickness=12, outlinewidth=0),
        )
    )
    fig.update_layout(title=title)
    show(fig, key)


# --------------------------------------------------------------------------
# distributions
# --------------------------------------------------------------------------
def ecdf(series: pd.Series, title: str, key: str, unit: str = "", log_x: bool = False) -> None:
    """Empirical cumulative distribution — a non-parametric view of a distribution."""
    s = _numeric(series)
    if s.empty:
        st.info("No numeric values for this distribution under the current filter.")
        return
    if log_x:
        s = s[s > 0]
        if s.empty:
            st.info("No positive values to plot on a log axis.")
            return
    s = s.sort_values()
    y = np.arange(1, len(s) + 1) / len(s)
    fig = go.Figure(
        go.Scatter(
            x=s.to_numpy(),
            y=y,
            mode="lines",
            line=dict(color=NAVY, width=2.4, shape="hv"),
            name=unit or (series.name or "value"),
            hovertemplate=f"{html_escape(series.name or 'value')}: %{{x:,.2f}}<br>cumulative: %{{y:.1%}}<extra></extra>",
        )
    )
    for q in (0.25, 0.5, 0.75, 0.9):
        vq = s.quantile(q)
        fig.add_vline(x=vq, line=dict(color=GOLD, width=1, dash="dot"))
        fig.add_annotation(x=vq, y=q, text=f"p{int(q * 100)}", showarrow=False, font=dict(size=10, color=GOLD), yshift=8)
    fig.update_layout(title=title, showlegend=False)
    fig.update_xaxes(title=f"{series.name or 'value'}{' (log10)' if log_x else ''}")
    fig.update_yaxes(title="Cumulative share", tickformat=".0%")
    if log_x:
        fig.update_xaxes(type="log")
    show(fig, key)


def html_escape(text: str) -> str:
    import html as _html

    return _html.escape(str(text))


def normal_quantile(p) -> np.ndarray:
    """Standard-normal quantiles via the stdlib, so no scipy dependency is needed."""
    nd = NormalDist()
    return np.array([nd.inv_cdf(float(min(max(v, 1e-12), 1 - 1e-12))) for v in p])


def qq_plot(series: pd.Series, title: str, key: str) -> None:
    """Normal Q-Q plot: curvature away from the reference line = non-normal shape."""
    s = _numeric(series)
    if s.empty:
        st.info("No numeric values for this distribution under the current filter.")
        return
    s = s.sort_values()
    n = len(s)
    probs = (np.arange(1, n + 1) - 0.5) / n
    theoretical = normal_quantile(probs)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=theoretical,
            y=s.to_numpy(),
            mode="markers",
            marker=dict(size=4, color=NAVY, opacity=0.5, line=dict(width=0)),
            name="observed",
            hovertemplate="theoretical: %{x:.2f}<br>observed: %{y:,.2f}<extra></extra>",
        )
    )
    lo = float(np.nanmin(theoretical))
    hi = float(np.nanmax(theoretical))
    fig.add_trace(
        go.Scatter(
            x=[lo, hi],
            y=[lo, hi],
            mode="lines",
            line=dict(color=RED, width=1.6, dash="dash"),
            name="normal reference",
            hoverinfo="skip",
        )
    )
    fig.update_layout(title=title)
    fig.update_xaxes(title="Theoretical normal quantile")
    fig.update_yaxes(title=str(series.name or "observed value"))
    show(fig, key)


def _iqr_outlier_share(s: pd.Series) -> float:
    if s.empty:
        return 0.0
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return 0.0
    return float(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).mean())


def violin(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    key: str,
    color: str | None = None,
    max_categories: int = 12,
) -> None:
    """Violin (distribution + density) per category, with an inner box."""
    if df.empty or x not in df.columns or y not in df.columns:
        st.info(_NO_DATA)
        return
    frame = df[[x, y]].dropna()
    frame[y] = pd.to_numeric(frame[y], errors="coerce")
    frame = frame.dropna()
    if frame.empty:
        st.info(_NO_DATA)
        return
    counts = frame[x].value_counts()
    keep = counts[counts >= 5].head(max_categories).index
    frame = frame[frame[x].isin(keep)]
    if frame.empty:
        st.info("Not enough observations per category (needs ≥5 rows each).")
        return
    fig = px.violin(
        frame,
        x=x,
        y=y,
        color=color or x,
        box=True,
        points="outliers",
        title=title,
    )
    fig.update_traces(meanline_visible=True, marker=dict(size=4, opacity=0.5, line=dict(width=0)))
    fig.update_layout(showlegend=False, violinmode="overlay" if color else "group")
    fig.update_yaxes(title=y)
    fig.update_xaxes(title=None, tickangle=-25)
    show(fig, key)


def box_group(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    key: str,
    color: str | None = None,
    max_categories: int = 14,
) -> None:
    """Box plot per category — the robust alternative to a mean bar chart."""
    if df.empty or x not in df.columns or y not in df.columns:
        st.info(_NO_DATA)
        return
    frame = df[[c for c in (x, y, color) if c and c in df.columns]].dropna(subset=[x, y])
    if frame.empty:
        st.info(_NO_DATA)
        return
    counts = frame[x].value_counts()
    keep = counts[counts >= 5].head(max_categories).index
    frame = frame[frame[x].isin(keep)]
    if frame.empty:
        st.info("Not enough observations per category (needs ≥5 rows each).")
        return
    fig = px.box(
        frame,
        x=x,
        y=y,
        color=color,
        points="outliers",
        title=title,
        color_discrete_sequence=[NAVY, GOLD, GREEN, TEAL_SAFE, RED],
    )
    fig.update_traces(marker=dict(size=4, opacity=0.55, line=dict(width=0)))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title=y)
    fig.update_xaxes(title=None, tickangle=-25)
    show(fig, key)


TEAL_SAFE = "#2a7f8f"


def hist_compare(series_map: dict, title: str, key: str, nbins: int = 45, log_x: bool = False) -> None:
    """Overlaid distributions for 2-4 groups, normalised to percent."""
    fig = go.Figure()
    drawn = 0
    for name, values in series_map.items():
        s = _numeric(values)
        if s.empty:
            continue
        if log_x:
            s = s[s > 0]
        if s.empty:
            continue
        counts, edges = np.histogram(s.to_numpy(), bins=nbins)
        centres = (edges[:-1] + edges[1:]) / 2
        width = (edges[1] - edges[0])
        pct = counts / max(counts.sum(), 1) * 100
        fig.add_trace(go.Bar(x=centres, y=pct, width=width * 0.92, name=str(name), opacity=0.62))
        drawn += 1
    if not drawn:
        st.info("No overlapping numeric values for this comparison under the current filter.")
        return
    fig.update_layout(title=title, barmode="overlay", bargap=0.02)
    fig.update_xaxes(title="value (share of group, %)", type="log" if log_x else None)
    fig.update_yaxes(title="% of group")
    show(fig, key)


def marginal_scatter(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    key: str,
    color: str | None = None,
    hover: list | None = None,
    log_x: bool = False,
    log_y: bool = False,
) -> None:
    """Scatter with marginal distribution subplots on both axes."""
    if df.empty or x not in df.columns or y not in df.columns:
        st.info(_NO_DATA)
        return
    # Dedup while preserving order: a hover column is often also the axis (e.g.
    # hovering award_amount on an award_amount-vs-estimate plot), and selecting
    # it twice makes frame[x] a DataFrame, which to_numeric then rejects.
    wanted: list[str] = []
    for col in (x, y, color, *hover):
        if col and col in df.columns and col not in wanted:
            wanted.append(col)
    frame = df[wanted].copy()
    frame[x] = pd.to_numeric(frame[x], errors="coerce")
    frame[y] = pd.to_numeric(frame[y], errors="coerce")
    frame = frame.dropna(subset=[x, y])
    if log_x:
        frame = frame[frame[x] > 0]
    if log_y:
        frame = frame[frame[y] > 0]
    if frame.empty:
        st.info("No paired positive values for this plot under the current filter.")
        return
    fig = px.scatter(
        _sample(frame, key),
        x=x,
        y=y,
        color=color,
        hover_data=hover,
        marginal_x="histogram",
        marginal_y="box",
        title=title,
        color_discrete_map={0: MUTED_SAFE, 1: RED, False: MUTED_SAFE, True: RED},
    )
    fig.update_traces(marker=dict(size=5, opacity=0.55, line=dict(width=0)), selector=dict(mode="markers"))
    fig.update_xaxes(type="log" if log_x else None, title_text=x)
    fig.update_yaxes(type="log" if log_y else None, title_text=y)
    show(fig, key)


# --------------------------------------------------------------------------
# correlations
# --------------------------------------------------------------------------
def corr_heatmap(
    df: pd.DataFrame,
    columns: list,
    title: str,
    key: str,
    method: str = "pearson",
    show_values: bool = True,
    min_abs: float = 0.0,
) -> pd.DataFrame:
    """Correlation matrix on a diverging scale centred at zero.

    Returns the matrix so pages can list the strongest pairs as text.
    """
    cols = [c for c in columns if c in df.columns]
    if len(cols) < 2:
        st.info("Need at least two numeric columns for a correlation matrix.")
        return pd.DataFrame()
    num = df[cols].apply(pd.to_numeric, errors="coerce")
    num = num.replace([np.inf, -np.inf], np.nan)
    # drop columns with too little data in the current filter
    keep = [c for c in cols if num[c].notna().sum() >= 30]
    if len(keep) < 2:
        st.info("Fewer than two columns have enough non-missing values in the current filter.")
        return pd.DataFrame()
    num = num[keep]
    corr = num.corr(method=method, min_periods=30)
    if min_abs > 0:
        mask = corr.abs() < min_abs
        corr = corr.mask(mask)

    z = corr.to_numpy()
    text = None
    if show_values:
        text = np.where(
            np.isnan(z),
            "",
            np.where(np.abs(z) >= 0.995, "1.00", np.char.mod("%.2f", z)),
        )
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=keep,
            y=keep,
            zmin=-1,
            zmax=1,
            colorscale=DIVERGING,
            xgap=2,
            ygap=2,
            text=text,
            texttemplate="%{text}" if show_values else None,
            textfont=dict(size=10),
            hovertemplate="%{y} × %{x}<br>r = %{z:.3f}<extra></extra>",
            colorbar=dict(title="r", thickness=12, outlinewidth=0, len=0.85),
        )
    )
    fig.update_layout(title=title, height=max(430, 42 * len(keep) + 150))
    fig.update_xaxes(showgrid=False, tickangle=-35, side="bottom", ticks="")
    fig.update_yaxes(showgrid=False, autorange="reversed", ticks="")
    show(fig, key)
    return corr


def strongest_pairs(corr: pd.DataFrame, n: int = 12, drop_diagonal: bool = True) -> pd.DataFrame:
    """Flatten a correlation matrix into a ranked pair table."""
    if corr.empty:
        return pd.DataFrame(columns=["Feature A", "Feature B", "r", "|r|", "Direction"])
    long = corr.stack().reset_index()
    long.columns = ["Feature A", "Feature B", "r"]
    long = long[long["r"].notna()]
    if drop_diagonal:
        long = long[long["Feature A"] != long["Feature B"]]
    long["|r|"] = long["r"].abs()
    long["Direction"] = np.where(long["r"] > 0, "positive", "negative")
    return long.sort_values("|r|", ascending=False).head(n).reset_index(drop=True)


def corr_pair_scatter(
    df: pd.DataFrame,
    a: str,
    b: str,
    title: str,
    key: str,
    color: str | None = None,
    log_a: bool = False,
    log_b: bool = False,
) -> None:
    """Focused scatter for one correlated pair, with a least-squares fit line."""
    if df.empty or x not in df.columns or y not in df.columns:
        st.info(_NO_DATA)
        return
    wanted = []
    for col in (a, b, color):
        if col and col in df.columns and col not in wanted:
            wanted.append(col)
    frame = df[wanted].copy()
    frame[a] = pd.to_numeric(frame[a], errors="coerce")
    frame[b] = pd.to_numeric(frame[b], errors="coerce")
    frame = frame.dropna()
    if log_a:
        frame = frame[frame[a] > 0]
    if log_b:
        frame = frame[frame[b] > 0]
    if len(frame) < 10:
        st.info("Not enough paired observations to fit a trend line.")
        return
    fig = px.scatter(
        _sample(frame, key),
        x=a,
        y=b,
        color=color,
        trendline="ols" if len(frame) >= 30 and not color else None,
        title=title,
        color_discrete_map={0: MUTED_SAFE, 1: RED, False: MUTED_SAFE, True: RED},
    )
    fig.update_traces(marker=dict(size=5, opacity=0.5, line=dict(width=0)), selector=dict(mode="markers"))
    fig.update_xaxes(type="log" if log_a else None, title_text=a)
    fig.update_yaxes(type="log" if log_b else None, title_text=b)
    show(fig, key)


# --------------------------------------------------------------------------
# composition
# --------------------------------------------------------------------------
def treemap(df: pd.DataFrame, labels, parents, values, title: str, key: str, color: str | None = None) -> None:
    if df.empty:
        st.info(_NO_DATA)
        return
    fig = go.Figure(
        go.Treemap(
            labels=labels,
            parents=parents,
            values=values,
            marker=dict(colorscale=SEQUENTIAL, line=dict(width=1, color="#fffdf8")),
            textinfo="label+value",
            hovertemplate="%{label}<br>%{value:,.0f}<br>%{percentParent}<extra></extra>",
        )
    )
    if color and color in df.columns:
        fig.update_traces(marker=dict(colors=df[color], colorscale=SEQUENTIAL, line=dict(width=1, color="#fffdf8")))
    fig.update_layout(title=title, margin=dict(l=8, r=8, t=52, b=8))
    show(fig, key, height=max(430, 26 * len(labels) + 120))


def stacked_pct_bar(df: pd.DataFrame, x: str, color: str, title: str, key: str, top: int = 20) -> None:
    """100% stacked bar — composition of each category without absolute-value bias."""
    if df.empty or x not in df.columns or color not in df.columns:
        st.info(_NO_DATA)
        return
    counts = df[[x, color]].dropna()
    if counts.empty:
        st.info(_NO_DATA)
        return
    ct = pd.crosstab(counts[x], counts[color])
    ct = ct.loc[ct.sum(axis=1).sort_values(ascending=False).index[:top]]
    pct = ct.div(ct.sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * 100
    pct = pct.reset_index().melt(id_vars=x, var_name=color, value_name="share")
    fig = px.bar(pct, x=x, y="share", color=color, title=title)
    fig.update_traces(marker_line_width=0.4, marker_line_color="#fffdf8")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title=None, tickangle=-30)
    fig.update_yaxes(title="Share of category (%)", range=[0, 100])
    show(fig, key)


def funnel(stages: list, values: list, title: str, key: str) -> None:
    """Simple labelled funnel for coverage / conversion style comparisons."""
    if not values or max(values) == 0:
        st.info(_NO_DATA)
        return
    fig = go.Figure(
        go.Funnel(
            y=[str(s) for s in stages],
            x=list(values),
            textinfo="value+percent initial",
            marker=dict(color=[NAVY_DEEP, NAVY, "#4a7099", GOLD][: len(stages)]),
        )
    )
    fig.update_layout(title=title)
    show(fig, key)


def risk_band_area(ts: pd.DataFrame, key: str, title: str = "Risk bands over time") -> None:
    """Stacked area of the risk-band mix per period — shows drift, not just totals."""
    if ts.empty or "period" not in ts.columns:
        st.info(_NO_DATA)
        return
    fig = px.area(ts, x="period", y=[c for c in ts.columns if c != "period"], title=title)
    fig.update_layout(xaxis=dict(title="Time"), yaxis=dict(title="Procedures"))
    show(fig, key)
