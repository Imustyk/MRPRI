"""Normalisation and validation of ingested MTender OCDS data.

The MTender list carries at least one record with the placeholder date
``1970-01-19T23:36:18Z`` (Unix epoch 0), verified live on 2026-09-26, so date
sanity limits are part of normalisation rather than an optional cleanup.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

import numpy as np

EPOCH_PLACEHOLDER = "1970-01-19T23:36:18Z"
MIN_PLAUSIBLE = "2015-01-01T00:00:00Z"
MAX_PLAUSIBLE = "2030-12-31T23:59:59Z"

VALID_TENDER_STATUS = {"active", "complete", "cancelled", "unsuccessful", "planning"}
VALID_AWARD_STATUS = {"active", "pending", "cancelled", "unsuccessful"}

METHOD_DETAIL_CLEAN = lambda v: (  # noqa: E731
    str(v).strip().lower().replace(" ", "_") if isinstance(v, str) and v.strip() else None
)


def parse_dt(value: Any) -> dt.datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = dt.datetime.strptime(value[: len(fmt) + 2], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def sane_dt(value: Any) -> dt.datetime | None:
    """Parse and reject the epoch-0 placeholder and out-of-window dates."""
    parsed = parse_dt(value)
    if parsed is None:
        return None
    lo, hi = parse_dt(MIN_PLAUSIBLE), parse_dt(MAX_PLAUSIBLE)
    if lo and parsed < lo:
        return None
    if hi and parsed > hi:
        return None
    return parsed


def iso(value: dt.datetime | None) -> str | None:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def clean_text(value: Any, limit: int = 4000) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if text in ("", "-", "--", "N/A", "null", "None"):
        return None
    return text[:limit]


_IDNO_IN_ID = re.compile(r"^MD-IDNO-(\d+)$")


def _idno_from(party_id: Any) -> str | None:
    """The bare fiscal code from a party id of the form ``MD-IDNO-<code>``."""
    hit = _IDNO_IN_ID.match(str(party_id or "").strip())
    return hit.group(1) if hit else None


def normalize_tender(doc: dict) -> dict:
    tender_start = sane_dt(doc.get("tender_start"))
    tender_end = sane_dt(doc.get("tender_end"))
    # An end date before the start date is impossible. Drop it and flag the row
    # instead of silently feeding a negative duration into the features.
    period_inverted = bool(tender_start and tender_end and tender_end < tender_start)
    if period_inverted:
        tender_end = None
    award_date = sane_dt(doc.get("award_date"))
    list_date = sane_dt(doc.get("list_date"))
    published = sane_dt(doc.get("published_date"))

    est = doc.get("estimated_value")
    awd = doc.get("award_value")
    est = float(est) if isinstance(est, (int, float)) and not isinstance(est, bool) else None
    awd = float(awd) if isinstance(awd, (int, float)) and not isinstance(awd, bool) else None

    cpv = [str(c) for c in (doc.get("cpv_codes") or []) if c]
    status = doc.get("status")
    if status not in VALID_TENDER_STATUS:
        status = status if isinstance(status, str) else None

    n_bids = doc.get("n_bids") or 0
    n_bidders = doc.get("n_bidders") or 0

    return {
        "ocid": doc.get("ocid"),
        "tender_id": doc.get("tender_id"),
        "title": clean_text(doc.get("title"), 2000),
        "status": status,
        "status_details": METHOD_DETAIL_CLEAN(doc.get("status_details")),
        "procurement_method": doc.get("procurement_method"),
        "procurement_method_details": METHOD_DETAIL_CLEAN(doc.get("procurement_method_details")),
        "main_procurement_category": doc.get("main_procurement_category"),
        "estimated_value": est,
        "award_value": awd,
        # award_id/award_status are extracted per award and promoted to tender
        # level in ocds.py; dropping them here made the exported columns
        # permanently empty even though the raw documents carried them.
        "award_id": doc.get("award_id"),
        "award_status": doc.get("award_status"),
        "award_total": (float(doc["award_total"])
                        if isinstance(doc.get("award_total"), (int, float))
                        and not isinstance(doc.get("award_total"), bool) else awd),
        "n_awards_with_value": doc.get("n_awards_with_value") or 0,
        "currency": doc.get("currency") or "MDL",
        "tender_start": iso(tender_start),
        "tender_end": iso(tender_end),
        "enquiry_end": iso(sane_dt(doc.get("enquiry_end"))),
        "award_date": iso(award_date),
        "published_date": iso(published),
        "list_date": iso(list_date),
        "list_date_is_placeholder": bool(doc.get("list_date") == EPOCH_PLACEHOLDER),
        "cpv_codes": cpv,
        "cpv_primary": cpv[0] if cpv else None,
        "n_cpvs": len(cpv),
        "n_items": doc.get("n_items") or 0,
        "n_lots": doc.get("n_lots") or 0,
        "n_amendments": doc.get("n_amendments") or 0,
        "buyer_id": doc.get("buyer_id"),
        "buyer_name": clean_text(doc.get("buyer_name"), 500),
        "buyer_identifier": doc.get("buyer_identifier"),
        "buyer_locality": clean_text(doc.get("buyer_locality"), 200),
        "buyer_scale": doc.get("buyer_scale"),
        "buyer_type": clean_text(doc.get("buyer_type"), 200),
        "winner_id": doc.get("winner_id"),
        "winner_name": clean_text(doc.get("winner_name"), 500),
        # MTender publishes a supplier's fiscal code only inside parties[].id
        # as "MD-IDNO-<code>". The extractor now reads it there, but packages
        # stored before that fix carry the code in winner_id with a null
        # identifier, so recover it rather than reporting a published field as
        # missing.
        "winner_identifier": doc.get("winner_identifier") or _idno_from(doc.get("winner_id")),
        "winner_identifier_scheme": doc.get("winner_identifier_scheme")
        or ("MD-IDNO" if _idno_from(doc.get("winner_id")) else None),
        "n_suppliers": doc.get("n_suppliers") or 0,
        "n_bids": int(n_bids) if isinstance(n_bids, (int, float)) else 0,
        "n_bidders": int(n_bidders) if isinstance(n_bidders, (int, float)) else 0,
        "n_awards": doc.get("n_awards") or 0,
        "n_contracts": doc.get("n_contracts") or 0,
        "has_bid_data": bool(n_bids),
        "has_award_data": bool(doc.get("award_value") is not None),
        "period_inverted": period_inverted,
        "release_ocids": doc.get("release_ocids") or [],
        "release_tags": doc.get("release_tags") or [],
        "release_dates": doc.get("release_dates") or [],
        "n_records": doc.get("n_records") or 0,
        "publisher": doc.get("publisher"),
    }


def normalize_party(doc: dict) -> dict:
    return {
        "ocid": doc.get("ocid"),
        "role": doc.get("role"),
        "id": doc.get("id"),
        "name": clean_text(doc.get("name"), 500),
        "identifier": clean_text(doc.get("identifier"), 64),
        "identifier_scheme": doc.get("identifier_scheme"),
        "locality": clean_text(doc.get("locality"), 200),
        "scale": doc.get("scale"),
    }


#: Fields whose missing rate the report states. A tender counts as missing a
#: field when the field is absent, empty or an empty list.
MISSING_RATE_FIELDS = (
    "title",
    "estimated_value",
    "award_value",
    "award_id",
    "award_status",
    "buyer_id",
    "buyer_identifier",
    "cpv_primary",
    "winner_id",
    "award_date",
    "tender_start",
    "tender_end",
)


def validation_report(tenders: Iterable[dict], parties: Iterable[dict]) -> dict:
    """Descriptive statistics computed from the stored dataset only.

    Takes iterables and makes a single pass over each, so a full-history corpus
    is never held in memory as a list of documents. Everything that cannot be
    counted incrementally (the distinct identifier sets, the award values the
    percentiles are taken from) is accumulated into small collections of
    scalars instead.
    """
    n_tenders = 0
    n_missing = dict.fromkeys(MISSING_RATE_FIELDS, 0)
    methods: dict[str, int] = {}
    statuses: dict[str, int] = {}
    buyer_ids: set = set()
    buyer_identifiers: set = set()
    winner_ids: set = set()
    ocids: set = set()
    award_values: list[float] = []
    dates: list[str] = []
    n_epoch = n_inverted = n_bid = n_award = 0

    for t in tenders:
        n_tenders += 1
        for field in MISSING_RATE_FIELDS:
            if t.get(field) in (None, "", []):
                n_missing[field] += 1
        method = str(t.get("procurement_method"))
        methods[method] = methods.get(method, 0) + 1
        status = str(t.get("status"))
        statuses[status] = statuses.get(status, 0) + 1
        if t.get("buyer_id"):
            buyer_ids.add(t["buyer_id"])
        if t.get("buyer_identifier"):
            buyer_identifiers.add(t["buyer_identifier"])
        if t.get("winner_id"):
            winner_ids.add(t["winner_id"])
        if t.get("ocid"):
            ocids.add(t["ocid"])
        if isinstance(t.get("award_value"), (int, float)):
            award_values.append(float(t["award_value"]))
        if t.get("list_date"):
            dates.append(t["list_date"])
        n_epoch += 1 if t.get("list_date_is_placeholder") else 0
        n_inverted += 1 if t.get("period_inverted") else 0
        n_bid += 1 if t.get("has_bid_data") else 0
        n_award += 1 if t.get("has_award_data") else 0

    n_parties = 0
    parties_by_role: dict[str, int] = {}
    unique_ids: set[str] = set()
    for p in parties:
        n_parties += 1
        role = str(p.get("role"))
        parties_by_role[role] = parties_by_role.get(role, 0) + 1
        if p.get("identifier"):
            unique_ids.add(p["identifier"])

    values = np.array(award_values, dtype=float)
    return {
        "n_tenders": n_tenders,
        "n_parties": n_parties,
        "n_unique_procurers": len(buyer_ids),
        "n_unique_buyers_by_identifier": len(buyer_identifiers),
        "n_unique_winners": len(winner_ids),
        "n_unique_party_identifiers": len(unique_ids),
        "n_duplicate_ocids": n_tenders - len(ocids),
        "date_range": {
            "min": min(dates) if dates else None,
            "max": max(dates) if dates else None,
            "n_with_epoch_placeholder": n_epoch,
            "n_with_inverted_period": n_inverted,
        },
        "missing_rate": {
            field: (round(n_missing[field] / n_tenders, 4) if n_tenders else 0.0)
            for field in MISSING_RATE_FIELDS
        },
        "award_value_stats": {
            "n": int(values.size),
            "min": float(values.min()) if values.size else None,
            "p25": float(np.percentile(values, 25)) if values.size else None,
            "median": float(np.median(values)) if values.size else None,
            "p75": float(np.percentile(values, 75)) if values.size else None,
            "p95": float(np.percentile(values, 95)) if values.size else None,
            "max": float(values.max()) if values.size else None,
        },
        "procurement_method_distribution": methods,
        "status_distribution": statuses,
        "parties_by_role": parties_by_role,
        "coverage": {
            "pct_with_bid_data": round(n_bid / n_tenders, 4) if n_tenders else 0.0,
            "pct_with_award_data": round(n_award / n_tenders, 4) if n_tenders else 0.0,
        },
    }
