"""KPI cards.

`st.metric` cannot be toned per card, so the dashboard renders its own cards to
keep the accent-colour language consistent with badges and callouts. The public
`kpi_row(items)` signature is backwards compatible: it accepts the original
`(label, value, help)` tuples as well as the richer 4-field form
`(label, value, help, tone)`.
"""

from __future__ import annotations

import html
from typing import Any

import streamlit as st

from dashboard.components.theme import TONES
from dashboard.utils.formatting import fmt_int, fmt_mdl, fmt_pct


def _card(label: str, value: str, help_text: str | None, tone: str, delta: str | None) -> str:
    accent = TONES.get(tone, TONES["neutral"])
    small = " sm" if len(value) > 12 else ""
    parts = [f'<div class="kpi-card" style="--kpi-accent:{accent}">']
    parts.append(f'<div class="kpi-label">{html.escape(str(label))}</div>')
    parts.append(f'<div class="kpi-value{small}">{html.escape(str(value))}</div>')
    if delta:
        parts.append(f'<div class="kpi-delta {html.escape(delta[1])}">{html.escape(delta[0])}</div>')
    if help_text:
        parts.append(f'<div class="kpi-help">{html.escape(str(help_text))}</div>')
    parts.append("</div>")
    return "".join(parts)


def _delta(value: Any, *, invert: bool = False, digits: int = 1) -> tuple[str, str] | None:
    """Format a relative change as (text, css_class)."""
    try:
        if value is None:
            return None
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    pct = n * 100
    text = f"{'+' if pct >= 0 else ''}{pct:.{digits}f}%"
    if abs(pct) < 0.05:
        return (text, "flat")
    rising_is_bad = not invert
    cls = "up" if (pct > 0) == rising_is_bad else "down"
    return (text, cls)


def kpi_row(
    items: list[tuple],
    *,
    columns: int = 4,
    key: str | None = None,
) -> None:
    """Render a responsive grid of KPI cards.

    items entries are tuples of (label, value, help) or (label, value, help, tone).
    A 5th element may be a (text, css_class) delta tuple produced by `_delta`.
    """
    if not items:
        return
    cards = [_card(*_normalise(i)) for i in items]
    html_block = (
        f'<div class="kpi-grid" style="grid-template-columns:repeat({columns},minmax(0,1fr))">'
        + "".join(cards)
        + "</div>"
    )
    st.markdown(html_block, unsafe_allow_html=True)


def _normalise(item: tuple) -> tuple[str, str, str | None, str, tuple | None]:
    label = str(item[0]) if len(item) > 0 else "—"
    value = str(item[1]) if len(item) > 1 else "—"
    help_text = item[2] if len(item) > 2 else None
    tone = item[3] if len(item) > 3 and isinstance(item[3], str) else "neutral"
    delta = item[4] if len(item) > 4 and isinstance(item[4], tuple) else None
    return label, value, help_text, tone, delta


def overview_kpis(df) -> None:
    n = len(df)
    value = df["award_amount"].sum(min_count=1) if "award_amount" in df.columns else None
    procurers = df["buyer_id"].nunique(dropna=True) if "buyer_id" in df.columns else 0
    if procurers == 0 and "buyer_name" in df.columns:
        procurers = df["buyer_name"].nunique(dropna=True)
    suppliers = df["winner_id"].nunique(dropna=True) if "winner_id" in df.columns else 0
    if suppliers == 0 and "winner_name" in df.columns:
        suppliers = df["winner_name"].nunique(dropna=True)
    awarded = df["award_amount"].dropna() if "award_amount" in df.columns else None
    avg = awarded.mean() if awarded is not None and len(awarded) else None
    anomalous = int(df["is_anomalous"].sum()) if "is_anomalous" in df.columns else 0
    high = int(df["is_high_risk"].sum()) if "is_high_risk" in df.columns else 0
    scored = int(df["is_scored"].sum()) if "is_scored" in df.columns else 0
    median = awarded.median() if awarded is not None and len(awarded) else None

    kpi_row(
        [
            ("Total procedures", fmt_int(n), "Count of procurement procedures in the current filter.", "neutral", None),
            ("Total award value", fmt_mdl(value), "Sum of award_total (fallback: award_value). Missing awards are skipped.", "neutral", None),
            ("Unique procurers", fmt_int(procurers), "Distinct buyer_id / buyer_name.", "info", None),
            ("Unique suppliers", fmt_int(suppliers), "Distinct winner_id / winner_name among awarded rows.", "info", None),
        ]
    )
    kpi_row(
        [
            ("Average award value", fmt_mdl(avg), "Mean of published award amounts only — sensitive to outliers.", "muted", None),
            ("Median award value", fmt_mdl(median), "Robust to the extreme values that skew the mean.", "muted", None),
            (
                "Anomalous procedures",
                fmt_int(anomalous),
                f"Flagged by ≥1 detector, out of {fmt_int(scored)} scored rows.",
                "warn" if anomalous else "good",
                None,
            ),
            (
                "Potential risk indicators (high)",
                fmt_int(high),
                "Flagged by two or more detectors (agreement band high/critical).",
                "bad" if high else "good",
                None,
            ),
        ]
    )


def band_kpis(df, column: str, title: str, order: list[str], key: str) -> None:
    """KPI cards for a categorical split, e.g. risk band or status."""
    if column not in df.columns or df.empty:
        return
    counts = df[column].value_counts()
    total = max(len(df), 1)
    items = []
    for band in order:
        if band not in counts.index:
            continue
        n = int(counts[band])
        tone = {"critical": "bad", "high": "bad", "medium": "warn", "low": "good"}.get(band, "neutral")
        items.append((band, fmt_int(n), f"{n / total:.1%} of the current filter", tone, None))
    if items:
        kpi_row(items[:4], key=key)


def scored_coverage_kpis(df, key: str) -> None:
    """Honesty cards: how much of the filter actually has detector output."""
    total = len(df)
    scored = int(df["is_scored"].sum()) if "is_scored" in df.columns else 0
    kpi_row(
        [
            ("Rows in filter", fmt_int(total), "Procedures passing the current filters.", "neutral", None),
            ("Scored by detectors", fmt_int(scored), "Rows present in tender_anomaly_scores.csv.", "info", None),
            (
                "Unscored rows",
                fmt_int(total - scored),
                "Shown as unscored — never as 'normal'.",
                "warn" if (total - scored) else "good",
                None,
            ),
            (
                "Scored coverage",
                fmt_pct(scored / max(total, 1)),
                "Share of the filter that has model output.",
                "muted" if scored else "bad",
                None,
            ),
        ],
        key=key,
    )
