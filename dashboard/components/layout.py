"""Structural UI helpers: page headers, sections, empty states, legends, footer."""

from __future__ import annotations

import html
from typing import Iterable

import streamlit as st

from dashboard.components.theme import PAPER, TONES
from dashboard.utils.formatting import DISCLAIMER

_TONE_CLASS = {
    "neutral": "badge",
    "info": "badge info",
    "good": "badge ok",
    "warn": "badge warn",
    "bad": "badge risk",
    "muted": "badge muted",
    "solid": "badge solid",
}


def page_header(title: str, subtitle: str = "", kicker: str = "") -> None:
    bits = ['<div class="page-head">']
    if kicker:
        bits.append(f'<div class="kicker">{html.escape(kicker)}</div>')
    bits.append(f"<h1>{html.escape(title)}</h1>")
    if subtitle:
        bits.append(f'<p class="sub">{subtitle}</p>')
    bits.append("</div>")
    st.markdown("".join(bits), unsafe_allow_html=True)


def story(text: str) -> None:
    st.markdown(f'<p class="story">{text}</p>', unsafe_allow_html=True)


def disclaimer(text: str = DISCLAIMER) -> None:
    st.markdown(f'<div class="disclaimer">{text}</div>', unsafe_allow_html=True)


def section(title: str, note: str = "") -> None:
    """Visual section header. Pass `note` for the smaller explainer line."""
    block = f'<div class="section-title">{title}</div>'
    if note:
        block += f'<div class="section-note">{note}</div>'
    st.markdown(block, unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="section-note">{text}</div>', unsafe_allow_html=True)


def rule() -> None:
    st.markdown('<hr class="rule">', unsafe_allow_html=True)


def empty_state(title: str, message: str = "") -> None:
    body = f'<div class="empty"><div class="empty-title">{html.escape(title)}</div>'
    if message:
        body += f"<div>{message}</div>"
    body += "</div>"
    st.markdown(body, unsafe_allow_html=True)


def badges(labels: Iterable[str], tone: str = "neutral") -> None:
    cls = _TONE_CLASS.get(tone, "badge")
    chips = "".join(f'<span class="{cls}">{html.escape(str(x))}</span>' for x in labels)
    if chips:
        st.markdown(chips, unsafe_allow_html=True)


def badges_html(pairs: Iterable[tuple]) -> str:
    """Inline HTML for a mixed-tone badge row, e.g. [("open", "info"), ("high", "bad")]."""
    chips = []
    for label, tone in pairs:
        cls = _TONE_CLASS.get(tone, "badge")
        chips.append(f'<span class="{cls}">{html.escape(str(label))}</span>')
    return "".join(chips)


def legend(entries: dict) -> None:
    """Inline colour key, e.g. {'critical': '#b4232c', ...}."""
    items = "".join(
        f'<span class="legend-key"><span class="legend-swatch" style="background:{c}"></span>{html.escape(str(k))}</span>'
        for k, c in entries.items()
    )
    st.markdown(f'<div class="legend-row">{items}</div>', unsafe_allow_html=True)


def swatch(color: str) -> str:
    return f'<span class="legend-swatch" style="background:{color}"></span>'


def tone_color(tone: str) -> str:
    return TONES.get(tone, TONES["neutral"])


def footer(source: str, demo: bool = False) -> None:
    flag = (
        '<span class="badge risk">demo data</span>' if demo else f'<span class="badge info">{html.escape(source)}</span>'
    )
    st.markdown(
        '<div class="app-footer">'
        f'<span>{flag}</span>'
        "<span>MTender AI Risk Analytics · decision support, not a verdict</span>"
        "</div>",
        unsafe_allow_html=True,
    )


def stat_sidebar(label: str, value: str) -> str:
    return f'<div class="sidebar-stat">{label}: <b>{html.escape(str(value))}</b></div>'


def nav_group(label: str) -> None:
    st.sidebar.markdown(f'<div class="nav-group">{html.escape(label)}</div>', unsafe_allow_html=True)


def brand(subtitle: str) -> None:
    st.sidebar.markdown(
        '<div class="brand">'
        '<div class="brand-mark">◧</div>'
        '<div><div class="brand-text">MTender AI</div>'
        f'<div class="brand-sub">{html.escape(subtitle)}</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )


def two_col(left, right, gap: str = "horizontal_gap") -> None:
    a, b = st.columns(2, gap=gap)
    with a:
        left()
    with b:
        right()


def chart_grid(items, columns: int = 2) -> None:
    """Lay out chart callables in a responsive column grid."""
    items = list(items)
    for start in range(0, len(items), columns):
        chunk = items[start : start + columns]
        for col, fn in zip(st.columns(len(chunk)), chunk):
            with col:
                fn()
        if start + columns < len(items):
            st.markdown("<div style='height:.4rem'></div>", unsafe_allow_html=True)
