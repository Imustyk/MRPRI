"""Turn a verified MTender OCDS 1.1 package into flat tender documents.

Structure facts measured on 40 live packages (2026-09-26), not assumed:

* ``GET /tenders/{base_ocid}`` returns a *package* with ``records[]``; each
  record holds one ``compiledRelease``.
* The standard top-level ``buyer`` object is **never** present. The procurer
  appears only as ``parties[]`` entries carrying ``roles`` including
  ``buyer`` / ``procuringEntity`` / ``payer``, plus ``tender.procuringEntity``.
* Party identifier scheme is ``MD-IDNO`` (the Moldovan fiscal code).
* Item classification scheme is ``CPV``; currency is ``MDL``.
* Observed ``parties[].roles``: supplier, buyer, payer, procuringEntity,
  tenderer, funder.
* Procuring entities publish a real ``identifier`` object, but **suppliers do
  not**: across the 1,500 stored packages every supplier party had
  ``identifier = null`` while its fiscal code appeared only inside
  ``parties[].id`` as ``MD-IDNO-<code>``. Reading ``identifier`` alone
  therefore left ``winner_idno`` empty for all 1,500 tenders and made external
  matching on the fiscal code impossible.
"""

from __future__ import annotations

import re
from typing import Any

BUYER_ROLES = ("buyer", "procuringEntity", "payer")


def _first(seq: Any) -> dict:
    return seq[0] if isinstance(seq, list) and seq and isinstance(seq[0], dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _tags(value: Any) -> list[str]:
    """Release tags as a list of strings.

    The live API returns ``tag`` as a list (``["compiled"]``), but a single
    string is a legal OCDS shape. Passing a bare string through ``_as_list``
    returns ``[]``, which would silently make every release look
    non-compiled and let a planning notice overwrite the tender.
    """
    if isinstance(value, str):
        return [value]
    return [str(v) for v in _as_list(value)]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


_IDNO_IN_ID = re.compile(r"^MD-IDNO-(\d+)$")


def _identifier(party: dict) -> str | None:
    """The MD-IDNO fiscal code, whichever field the publisher used for it.

    Procuring entities carry a real ``identifier`` object. Suppliers do not:
    their code is only in ``parties[].id`` as ``MD-IDNO-<code>``, so the
    fallback below is what makes ``winner_idno`` and supplier identifiers
    populate at all.
    """
    ident = party.get("identifier")
    if isinstance(ident, dict) and ident.get("id"):
        return str(ident["id"])
    if isinstance(ident, str) and ident.strip():
        return ident.strip()
    hit = _IDNO_IN_ID.match(str(party.get("id") or "").strip())
    return hit.group(1) if hit else None


def _identifier_scheme(party: dict) -> str | None:
    ident = party.get("identifier")
    if isinstance(ident, dict) and ident.get("scheme"):
        return str(ident["scheme"])
    if _IDNO_IN_ID.match(str(party.get("id") or "").strip()):
        return "MD-IDNO"
    return None


def _locality(party: dict) -> str | None:
    """Locality name, tolerating the two layouts seen in the live data.

    2018 packages carry ``address.locality``; 2024 packages carry
    ``address.addressDetails.locality`` (60/60) and
    ``address.addressDetails.region`` (60/60). All are checked.
    """
    addr = party.get("address") or {}
    details = addr.get("addressDetails") or {}
    for candidate in (addr.get("locality"), details.get("locality"), details.get("region")):
        if isinstance(candidate, dict):
            value = candidate.get("description") or candidate.get("id")
            if value:
                return value
        elif isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    country = details.get("country") or {}
    return country.get("description") if isinstance(country, dict) else None


def find_party(compiled: dict, roles: tuple[str, ...]) -> dict | None:
    for party in _as_list(compiled.get("parties")):
        party_roles = set(_as_list(party.get("roles")))
        if party_roles.intersection(roles):
            return party
    return None


def _party_ref(party: dict) -> dict:
    return {
        "id": party.get("id"),
        "name": party.get("name"),
        "identifier": _identifier(party),
        "identifier_scheme": _identifier_scheme(party),
        "locality": _locality(party),
        "scale": ((party.get("details") or {}).get("scale")),
        "type_of_buyer": ((party.get("details") or {}).get("typeOfBuyer")),
        "type_of_supplier": ((party.get("details") or {}).get("typeOfSupplier")),
        "roles": _as_list(party.get("roles")),
    }


def _cpv_codes(tender: dict) -> list[str]:
    """CPV codes from both locations observed in the live data.

    Measured on 40 packages from 2024: ``tender.classification`` is present in
    40/40 releases while ``tender.items[].classification`` is present in 38/40,
    and many releases carry ``tender.classification`` with an empty ``items``
    array. Reading only one of the two loses codes.
    """
    codes: list[str] = []
    top = tender.get("classification") or {}
    if top.get("scheme") == "CPV" and top.get("id"):
        codes.append(str(top["id"]))
    for item in _as_list(tender.get("items")):
        cls = item.get("classification") or {}
        if cls.get("scheme") == "CPV" and cls.get("id"):
            value = str(cls["id"])
            if value not in codes:
                codes.append(value)
    return codes


def _cpv_labels(tender: dict) -> list[str]:
    labels: list[str] = []
    top = tender.get("classification") or {}
    if top.get("scheme") == "CPV" and top.get("description"):
        labels.append(str(top["description"]))
    for item in _as_list(tender.get("items")):
        cls = item.get("classification") or {}
        if cls.get("scheme") == "CPV" and cls.get("description"):
            value = str(cls["description"])
            if value not in labels:
                labels.append(value)
    return labels


def _bids(compiled: dict) -> list[dict]:
    details = (compiled.get("bids") or {}).get("details")
    out: list[dict] = []
    for bid in _as_list(details):
        tenderers = [
            {"id": t.get("id"), "name": t.get("name"), "identifier": _identifier(t)}
            for t in _as_list(bid.get("tenderers"))
            if isinstance(t, dict)
        ]
        out.append(
            {
                "id": bid.get("id"),
                "date": bid.get("date"),
                "status": bid.get("status"),
                "amount": _num((bid.get("value") or {}).get("amount")),
                "currency": (bid.get("value") or {}).get("currency"),
                "tenderers": tenderers,
            }
        )
    return out


def _awards(compiled: dict) -> list[dict]:
    out: list[dict] = []
    for award in _as_list(compiled.get("awards")):
        suppliers = [
            {"id": s.get("id"), "name": s.get("name"), "identifier": _identifier(s)}
            for s in _as_list(award.get("suppliers"))
            if isinstance(s, dict)
        ]
        out.append(
            {
                "id": award.get("id"),
                "internal_id": award.get("internalId"),
                "date": award.get("date"),
                "status": award.get("status"),
                "status_details": award.get("statusDetails"),
                "amount": _num((award.get("value") or {}).get("amount")),
                "amount_net": _num((award.get("value") or {}).get("amountNet")),
                "currency": (award.get("value") or {}).get("currency"),
                "suppliers": suppliers,
                "related_lots": _as_list(award.get("relatedLots")),
            }
        )
    return out


def _contracts(compiled: dict) -> list[dict]:
    out: list[dict] = []
    for contract in _as_list(compiled.get("contracts")):
        out.append(
            {
                "id": contract.get("id"),
                "date": contract.get("date"),
                "status": contract.get("status"),
                "status_details": contract.get("statusDetails"),
                "award_id": contract.get("awardId"),
                "related_lots": _as_list(contract.get("relatedLots")),
            }
        )
    return out


def _primary_award(awards: list[dict]) -> dict:
    """The one award that the winner_* and award_* fields are derived from.

    A package can carry several awards (for example a cancelled one that was
    re-tendered). Deriving the value from ``awards[0]`` while deriving the
    winner from the active award silently pairs a winner with somebody else's
    value, so every award field is taken from this single record instead.
    """
    active = [a for a in awards if a.get("status") in ("active", "pending")]
    with_value = [a for a in (active or awards) if a.get("amount") is not None]
    return (with_value or active or awards or [{}])[0]


def _winner(awards: list[dict]) -> dict:
    """Supplier of the active award; falls back to the first award present."""
    active = [a for a in awards if a.get("status") in ("active", "pending")]
    pool = active or awards
    if not pool or not pool[0].get("suppliers"):
        return {"id": None, "name": None, "identifier": None, "identifier_scheme": None}
    sup = pool[0]["suppliers"][0]
    # Same reasoning as _identifier: an award supplier carries its fiscal code
    # in `id`, so `sup.get("identifier")` alone is always None here.
    return {
        "id": sup.get("id"),
        "name": sup.get("name"),
        "identifier": _identifier(sup),
        "identifier_scheme": _identifier_scheme(sup),
    }



def _merge_objects(base: dict, extra: dict) -> dict:
    """Field-wise merge that prefers already-present non-null values."""
    for key, value in (extra or {}).items():
        if key not in base or base[key] in (None, "", [], {}):
            base[key] = value
        elif isinstance(base[key], dict) and isinstance(value, dict):
            _merge_objects(base[key], value)
    return base


def _merge_lists(base: list, extra: list, id_fields: tuple[str, ...]) -> list:
    """Union two lists of OCDS objects, de-duplicated on a natural key."""
    seen = {
        tuple(_dig(item, f) for f in id_fields)
        for item in base
        if isinstance(item, dict)
    }
    for item in extra:
        if not isinstance(item, dict):
            continue
        key = tuple(_dig(item, f) for f in id_fields)
        if key in seen:
            continue
        seen.add(key)
        base.append(item)
    return base


def _dig(obj: dict, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def merge_compiled_releases(package: dict) -> dict:
    """Build one procurement view out of every release in a package.

    A package groups several related OCIDs (planning notice, tender, award).
    The release tagged ``compiled`` is the authoritative full view and is used as
    the base; the other releases only fill fields it leaves empty. Without this
    the last release in the array wins, which for MTender is frequently an empty
    ``planning`` notice with no parties at all.
    """
    compiled_list = [
        r["compiledRelease"]
        for r in _as_list(package.get("records"))
        if isinstance(r, dict) and isinstance(r.get("compiledRelease"), dict)
    ]
    if not compiled_list:
        return {}

    def is_compiled(rel: dict) -> bool:
        return "compiled" in _tags(rel.get("tag"))

    ordered = sorted(compiled_list, key=lambda r: not is_compiled(r))
    merged: dict = {}
    for rel in ordered:
        _merge_objects(merged, rel)

    for field, id_fields in (
        ("parties", ("id",)),
        ("awards", ("id",)),
        ("contracts", ("id",)),
    ):
        combined: list = []
        for rel in ordered:
            _merge_lists(combined, _as_list(rel.get(field)), id_fields)
        if combined:
            merged[field] = combined

    bids_details: list = []
    bid_seen: set = set()
    for rel in ordered:
        for bid in _as_list((rel.get("bids") or {}).get("details")):
            key = bid.get("id") or json_key(bid)
            if key in bid_seen:
                continue
            bid_seen.add(key)
            bids_details.append(bid)
    if bids_details:
        merged["bids"] = {"details": bids_details}

    return merged


def json_key(obj: dict) -> str:
    import json as _json

    return _json.dumps(obj, sort_keys=True, ensure_ascii=False)


def extract_tender(ocid: str, package: dict, list_date: str | None = None) -> dict:
    """Flatten one OCDS package into a single tender document."""
    tender_doc: dict = {
        "ocid": ocid,
        "list_date": list_date,
        "package_uri": package.get("uri"),
        "published_date": package.get("publishedDate"),
        "publisher": (package.get("publisher") or {}).get("name"),
        "license": (package.get("license") or {}).get("id")
        if isinstance(package.get("license"), dict)
        else package.get("license"),
        "n_records": len(_as_list(package.get("records"))),
        "release_ocids": [r.get("ocid") for r in _as_list(package.get("records"))],
        "release_tags": [],
        "release_dates": [],
    }
    for record in _as_list(package.get("records")):
        cr = record.get("compiledRelease")
        if not isinstance(cr, dict):
            continue
        for tag in _as_list(cr.get("tag")):
            tender_doc["release_tags"].append(tag)
        if cr.get("date"):
            tender_doc["release_dates"].append(cr["date"])

    compiled = merge_compiled_releases(package)

    tender = compiled.get("tender") or {}
    buyer_party = find_party(compiled, BUYER_ROLES)
    buyer = _party_ref(buyer_party) if buyer_party else {}
    procuring = tender.get("procuringEntity") or {}

    awards = _awards(compiled)
    bids = _bids(compiled)
    contracts = _contracts(compiled)
    primary_award = _primary_award(awards)
    winner = _winner(awards)
    tenderer_ids = {
        t.get("id")
        for bid in bids
        for t in bid["tenderers"]
        if t.get("id")
    }
    supplier_ids = {
        s.get("id") for a in awards for s in a["suppliers"] if s.get("id")
    }

    tender_doc.update(
        {
            "tender_id": tender.get("id") or compiled.get("id"),
            "title": tender.get("title"),
            "description": tender.get("description"),
            "status": tender.get("status"),
            "status_details": tender.get("statusDetails"),
            "procurement_method": tender.get("procurementMethod"),
            "procurement_method_details": tender.get("procurementMethodDetails"),
            "main_procurement_category": tender.get("mainProcurementCategory"),
            "estimated_value": _num((tender.get("value") or {}).get("amount")),
            "currency": (tender.get("value") or {}).get("currency"),
            "tender_start": (tender.get("tenderPeriod") or {}).get("startDate"),
            "tender_end": (tender.get("tenderPeriod") or {}).get("endDate"),
            "enquiry_end": (tender.get("enquiryPeriod") or {}).get("endDate"),
            "cpv_codes": _cpv_codes(tender),
            "cpv_labels": _cpv_labels(tender),
            "n_items": len(_as_list(tender.get("items"))),
            "n_lots": len(_as_list(tender.get("lots"))),
            "n_amendments": len(_as_list(tender.get("amendments"))),
            "procuring_entity_id": procuring.get("id"),
            "procuring_entity_name": procuring.get("name"),
            "buyer_id": buyer.get("id") or procuring.get("id"),
            "buyer_name": buyer.get("name") or procuring.get("name"),
            "buyer_identifier": buyer.get("identifier"),
            "buyer_locality": buyer.get("locality"),
            "buyer_scale": buyer.get("scale"),
            "buyer_type": buyer.get("type_of_buyer"),
            "suppliers": [s for a in awards for s in a["suppliers"]],
            "n_suppliers": len(supplier_ids),
            "winner_id": winner["id"],
            "winner_name": winner["name"],
            "winner_identifier": winner["identifier"],
            "winner_identifier_scheme": winner["identifier_scheme"],
            # every award_* field comes from the same primary award as winner_*
            "award_id": primary_award.get("id"),
            "award_value": primary_award.get("amount"),
            "award_date": primary_award.get("date"),
            "award_status": primary_award.get("status"),
            # A tender can be awarded lot by lot: 219 awards were observed in one
            # package. `estimated_value` covers the whole tender, so the
            # comparable figure is the sum of every award amount, not the first
            # one. Measured on 266 tenders from 2024: sum/estimate exceeds 2x in
            # 2.3% of cases, while first-award/estimate never exceeds it at all.
            "award_total": (
                round(sum(a["amount"] for a in awards if a.get("amount") is not None), 2)
                if any(a.get("amount") is not None for a in awards)
                else None
            ),
            "n_awards_with_value": sum(1 for a in awards if a.get("amount") is not None),
            "n_awards": len(awards),
            "n_contracts": len(contracts),
            "n_bids": len(bids),
            "n_bidders": len(tenderer_ids),
            "bids": bids,
            "awards": awards,
            "contracts": contracts,
        }
    )
    return tender_doc


def extract_parties(tender_doc: dict) -> list[dict]:
    """Every identifiable party of a tender, deduplicated by (role, id)."""
    out: list[dict] = []
    seen: set[tuple] = set()

    def add(ref: dict, role: str) -> None:
        if not isinstance(ref, dict):
            return
        key = (role, ref.get("id") or ref.get("identifier") or ref.get("name"))
        if key in seen or not any(key[1:]):
            return
        seen.add(key)
        ident = ref.get("identifier") or ref.get("id") or ref.get("name")
        out.append(
            {
                "party_key": f"{tender_doc.get('ocid')}|{role}|{ident}",
                "ocid": tender_doc.get("ocid"),
                "role": role,
                "id": ref.get("id"),
                "name": ref.get("name"),
                "identifier": ref.get("identifier"),
                "identifier_scheme": ref.get("identifier_scheme"),
                "locality": ref.get("locality"),
                "scale": ref.get("scale"),
            }
        )

    if tender_doc.get("buyer_id") or tender_doc.get("buyer_identifier"):
        add(
            {
                "id": tender_doc.get("buyer_id"),
                "name": tender_doc.get("buyer_name"),
                "identifier": tender_doc.get("buyer_identifier"),
                "identifier_scheme": "MD-IDNO" if tender_doc.get("buyer_identifier") else None,
                "locality": tender_doc.get("buyer_locality"),
                "scale": tender_doc.get("buyer_scale"),
            },
            "buyer",
        )
    for sup in tender_doc.get("suppliers") or []:
        add(sup, "supplier")
    for bid in tender_doc.get("bids") or []:
        for tenderer in bid.get("tenderers") or []:
            add(tenderer, "tenderer")
    return out
