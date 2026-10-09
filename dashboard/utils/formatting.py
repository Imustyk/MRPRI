"""Display helpers. Never invent numbers — only format values that exist."""

from __future__ import annotations

from typing import Any

import pandas as pd

DISCLAIMER = (
    "Anomaly scores and risk indicators are decision-support signals. "
    "They are **not** a finding of corruption and do not accuse a procurer, "
    "supplier, or procedure. Unusual patterns require additional investigation."
)

UNAVAILABLE_WINNING_MARGIN = (
    "Winning-margin (winning bid vs next-best bid) is not implemented: "
    "MTender awards do not expose a per-supplier split of the award value, "
    "and bid-level prices are published only for a minority of procedures."
)

UNAVAILABLE_AUTOENCODER = (
    "An autoencoder was not part of the executed research pipeline. "
    "The compared detectors are statistical MAD z-score, Isolation Forest, "
    "Local Outlier Factor, and One-Class SVM."
)

UNAVAILABLE_GEO_COORDS = (
    "No latitude/longitude is published in the verified MTender OCDS payload. "
    "Locality names (`buyer_locality`) are shown as a frequency chart instead "
    "of a map, so coordinates are not invented."
)


def fmt_int(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_mdl(value: Any, decimals: int = 0) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(n):
        return "—"
    if abs(n) >= 1_000_000_000:
        return f"{n / 1_000_000_000:,.{decimals + 1}f} bn MDL"
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:,.{decimals + 1}f} m MDL"
    return f"{n:,.{decimals}f} MDL"


def fmt_pct(value: Any, already_ratio: bool = True) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if already_ratio:
        n *= 100
    return f"{n:.1f}%"


def fmt_score(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def safe_name(value: Any, fallback: str = "(not published)") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    text = str(value).strip()
    return text or fallback
