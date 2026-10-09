"""Load Open Contracting Data Standard (OCDS) JSON releases into a tender table.

Expected shape: a JSON array of OCDS releases, or an object with a
``releases`` array (as published by many national portals).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _first(seq, default=None):
    return seq[0] if seq else default


def _party(parties: list, role: str) -> dict:
    for p in parties or []:
        if role in (p.get("roles") or []):
            return p
    return {}


def load_ocds(path: Path) -> pd.DataFrame:
    raw = json.loads(path.read_text(encoding="utf-8"))
    releases = raw.get("releases", raw) if isinstance(raw, dict) else raw
    if not isinstance(releases, list):
        raise ValueError("OCDS file must be a list of releases or an object with 'releases'.")

    rows = []
    for rel in releases:
        tender = rel.get("tender") or {}
        awards = rel.get("awards") or [{}]
        award = awards[0] if awards else {}
        parties = rel.get("parties") or []
        buyer = (rel.get("buyer") or {}) or _party(parties, "buyer")
        supplier = _first(award.get("suppliers") or [], {}) or _party(parties, "supplier")
        items = tender.get("items") or award.get("items") or [{}]
        item = items[0] if items else {}
        classif = _first(item.get("classification") and [item.get("classification")] or [], {}) or {}
        value = (award.get("value") or tender.get("value") or {}) or {}
        period = tender.get("tenderPeriod") or {}
        bids = (rel.get("bids") or {}).get("details") or []

        bid_rows = []
        for b in bids:
            tenderers = b.get("tenderers") or [{}]
            t0 = tenderers[0] if tenderers else {}
            bid_rows.append(
                {
                    "bidder_id": t0.get("id") or "unknown",
                    "bidder_name": t0.get("name") or "Unknown",
                    "idno": t0.get("identifier", {}).get("id") if isinstance(t0.get("identifier"), dict) else "",
                    "price": (b.get("value") or {}).get("amount"),
                    "is_winner": False,
                }
            )

        published = (period.get("startDate") or rel.get("date") or "")[:10]
        deadline = (period.get("endDate") or "")[:10]
        rows.append(
            {
                "tender_id": rel.get("ocid") or rel.get("id"),
                "ocid": rel.get("ocid") or rel.get("id"),
                "title": tender.get("title") or award.get("title") or "Untitled",
                "buyer_id": buyer.get("id") or "unknown-buyer",
                "buyer_name": buyer.get("name") or "Unknown buyer",
                "buyer_locality": (buyer.get("address") or {}).get("locality") or "",
                "buyer_type": "unknown",
                "cpv_code": classif.get("id") or "00000000-0",
                "cpv_label": classif.get("description") or "Unclassified",
                "procedure": (tender.get("procurementMethod") or "open"),
                "status": tender.get("status") or award.get("status") or "unknown",
                "published_at": published or "2023-01-01",
                "bid_deadline": deadline or published or "2023-01-15",
                "award_date": (award.get("date") or deadline or published or "2023-01-20")[:10],
                "bid_window_days": 14,
                "n_bids": len(bid_rows) or len(tender.get("tenderers") or []) or 1,
                "estimated_value_mdl": value.get("amount") or 0,
                "award_value_mdl": (award.get("value") or {}).get("amount") or value.get("amount") or 0,
                "currency": value.get("currency") or "MDL",
                "winner_id": supplier.get("id") or "unknown-winner",
                "winner_name": supplier.get("name") or "Unknown supplier",
                "winner_idno": (supplier.get("identifier") or {}).get("id") if isinstance(supplier.get("identifier"), dict) else "",
                "winner_locality": (supplier.get("address") or {}).get("locality") or "",
                "winner_founding_year": 2015,
                "winner_phone": "",
                "winner_address": "",
                "bids_json": json.dumps(bid_rows, ensure_ascii=False),
                "planted_pattern": "unknown",
                "is_planted_anomaly": False,
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        pub = pd.to_datetime(df["published_at"], errors="coerce")
        dead = pd.to_datetime(df["bid_deadline"], errors="coerce")
        df["bid_window_days"] = (dead - pub).dt.days.fillna(14).clip(lower=1).astype(int)
    return df
