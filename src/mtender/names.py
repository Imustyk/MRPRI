"""Company-name folding for matching Moldovan legal entities across sources.

Used both by the AAP blacklist comparison (``scripts/09_external_validation.py``)
and by the blacklist loader (``scripts/11_load_blacklist.py``), so the same
company always folds to the same key no matter which script asks.

The rules are deliberately conservative: legal-form tokens carry no identity, so
they are dropped, and only a full equality after folding is ever called a match.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: Legal-form tokens carry no identity, so they are dropped before comparing.
LEGAL_FORMS = (
    "srl", "sa", "sc", "sp", "sca", "gmbh", "ltd", "llc", "plc", "inc",
    "societatea", "societate", "company", "grup", "group", "holding",
    "cu", "raspundere", "limitata", "nelimitata", "actiuni", "publica",
    "intreprinderea", "individuala", "cabinet", "individual",
)

#: Multi-word legal boilerplate, removed before the per-token filter so that a
#: spelled-out form folds to the same key as its abbreviation.
LEGAL_PHRASES = (
    "societatea cu raspundere limitata",
    "societatea cu raspundere nelimitata",
    "societatea pe actiuni",
    "societatea in nume propriu",
    "intreprinderea individuala",
    "cabinet individual de avocatura",
)


def normalise_name(value: Any) -> str | None:
    """Fold a company name to a comparison key.

    Strips diacritics, lowercases, removes punctuation and legal-form tokens,
    and collapses whitespace. Returns None when nothing comparable is left, so
    an empty or placeholder name can never match everything.
    """
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    # Collapse dotted abbreviations ("S.R.L.", "S. R. L.") into single tokens
    # first. Stripping punctuation up front would yield "s r l", which no longer
    # matches the legal-form list and would silently break real Moldovan names.
    while re.search(r"\.\s+[a-z]", text):
        text = re.sub(r"\.\s+", ".", text)
    text = re.sub(r"\b((?:[a-z]\.)+[a-z])\b", lambda m: m.group(1).replace(".", ""), text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    for phrase in LEGAL_PHRASES:
        text = re.sub(rf"\b{phrase}\b", " ", text)
    tokens = [t for t in text.split() if t and t not in LEGAL_FORMS]
    return " ".join(tokens) or None


def match_level(blacklisted: str | None, observed: str | None) -> str:
    if not blacklisted or not observed:
        return "none"
    if blacklisted == observed:
        return "exact_normalised"
    if blacklisted in observed or observed in blacklisted:
        return "ambiguous"
    return "none"
