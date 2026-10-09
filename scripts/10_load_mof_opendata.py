"""Step 10 - load the Ministry of Finance open-data extracts into MongoDB.

The MoF publishes a monthly "Date din SIA RSAP (MTender)" extract on
dataset.gov.md. It is the same procurement data MTender publishes through OCDS,
but from the *national* register rather than one procurement at a time, and it
carries fields the OCDS record only exposes indirectly:

* ``IDNO`` - the procuring entity's fiscal code, for every row;
* ``PROCUREMENT_TYPE`` - the precise procedure type (``directAward``,
  ``smallValue``, ``microValue``, ``openTender``);
* ``TENDER_AMOUNT`` - the announced value, independent of the OCDS ``value``.

So this file is not a second copy of the corpus and it is not merged into
``raw_tenders``. It is an independent second source for the same population,
stored raw in ``raw_mof_procedures`` and used to cross-check the API extraction:
buyer fiscal code, announced value, and which OCIDs the API never served.

``CPID`` is the MTender OCID, which is what makes the join possible at all.

Usage:
    .venv/bin/python scripts/10_load_mof_opendata.py
    .venv/bin/python scripts/10_load_mof_opendata.py --no-crosscheck
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_RAW, MONGO_META  # noqa: E402
from src.mtender.mongo_client import (  # noqa: E402
    connect,
    ensure_indexes,
    make_run_id,
    upsert_many,
    utcnow_iso,
)
from src.mtender.mongo_schema import RAW_MOF_PROCEDURES, RAW_TENDERS  # noqa: E402

OPENDATA_DIR = DATA_RAW / "opendata"

#: The header is preceded by a title row and blank rows, and its position is not
#: guaranteed, so it is located by content instead of by a fixed row number.
HEADER_FIRST_COL = "CPID"

#: Source column -> stored field. The source misspells "category" and
#: "disclosure"; the stored names are spelled correctly and the original header
#: is kept in ``source_columns`` so the mapping stays auditable.
COLUMN_MAP = {
    "CPID": "ocid",
    "NAME": "authority_name",
    "IDNO": "buyer_idno",
    "PROCUREMENT_TYPE": "procurement_type",
    "DISCLOURE_DATE": "disclosure_date",
    "TITLE": "title",
    "CPV": "cpv",
    "PROCUREMENT_CATEFORY": "procurement_category",
    "TENDER_AMOUNT": "estimated_value",
    "AWARD_CRITERIA": "award_criteria",
    "NUMBER_OF_LOTS": "n_lots",
    "URL": "url",
}

ROMANIAN_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5,
    "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10,
    "noiembrie": 11, "decembrie": 12,
}

_PERIOD_RE = re.compile(
    r"pentru\s+luna\s+([a-zA-Zăâîîșşțţ]+)\s+(\d{4})", re.IGNORECASE
)


def parse_period(title: Any) -> str | None:
    """``'... pentru luna Iulie 2026'`` -> ``'2026-07'``.

    Falls back to the file name, because the sheet name in these workbooks has
    been observed to disagree with the title cell (``iulie-2026.xlsx`` holds a
    sheet called ``Iunie``).
    """
    text = str(title or "")
    hit = _PERIOD_RE.search(text)
    if hit:
        month = ROMANIAN_MONTHS.get(hit.group(1).lower())
        if month:
            return f"{int(hit.group(2)):04d}-{month:02d}"
    return None


def period_from_filename(path: Path) -> str | None:
    stem = path.stem.lower()
    for name, month in ROMANIAN_MONTHS.items():
        if name in stem:
            year = re.search(r"(20\d{2})", stem)
            if year:
                return f"{year.group(1)}-{month:02d}"
    return None


def read_workbook(path: Path) -> list[dict[str, Any]]:
    """Every data row of every sheet, as stored documents.

    All sheets are read: the workbook carries one sheet per report, and the
    period is taken from each sheet's own title cell.
    """
    book = pd.ExcelFile(path)
    docs: list[dict[str, Any]] = []
    for sheet in book.sheet_names:
        frame = book.parse(sheet, header=None, dtype=str)
        header_idx = None
        for idx in range(min(len(frame), 20)):
            if str(frame.iat[idx, 0]).strip() == HEADER_FIRST_COL:
                header_idx = idx
                break
        if header_idx is None:
            print(f"  {path.name}/{sheet}: no {HEADER_FIRST_COL!r} header, sheet skipped")
            continue
        title = frame.iat[0, 0] if len(frame) else ""
        period = parse_period(title) or period_from_filename(path)
        header = [str(c).strip() for c in frame.iloc[header_idx].tolist()]
        body = frame.iloc[header_idx + 1 :].copy()
        body.columns = header
        body = body.dropna(how="all")
        unknown = [c for c in header if c and c not in COLUMN_MAP and c != "Unnamed: 0"]
        if unknown:
            print(f"  {path.name}/{sheet}: unmapped source columns {unknown}")
        for row in body.to_dict("records"):
            doc: dict[str, Any] = {}
            for src, field in COLUMN_MAP.items():
                if src not in row:
                    continue
                value = row[src]
                doc[field] = None if pd.isna(value) else str(value).strip()
            ocid = doc.get("ocid")
            if not ocid or not ocid.startswith("ocds-"):
                continue
            doc["estimated_value"] = _number(doc.get("estimated_value"))
            doc["n_lots"] = _integer(doc.get("n_lots"))
            doc["period"] = period
            doc["source_file"] = path.name
            doc["source_sheet"] = sheet
            docs.append(doc)
    return docs


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def crosscheck(db, docs: list[dict]) -> dict[str, Any]:
    """Compare the two independent sources over the same OCIDs."""
    mof_by_ocid = {d["ocid"]: d for d in docs if d.get("ocid")}
    ocids = list(mof_by_ocid)
    if not ocids:
        return {"compared": 0}

    matched = idno_agree = idno_conflict = 0
    value_agree = value_conflict = 0
    type_agree = type_conflict = 0
    unmatched: list[str] = []
    conflicts: list[dict] = []
    types: dict[str, int] = {}

    for start in range(0, len(ocids), 2000):
        chunk = ocids[start : start + 2000]
        stored = {
            d["ocid"]: d
            for d in db[RAW_TENDERS].find(
                {"ocid": {"$in": chunk}},
                {"_id": 0, "ocid": 1, "buyer_identifier": 1, "estimated_value": 1,
                 "procurement_method_details": 1},
            )
        }
        for ocid in chunk:
            api = stored.get(ocid)
            if api is None:
                if len(unmatched) < 50:
                    unmatched.append(ocid)
                continue
            mof = mof_by_ocid[ocid]
            matched += 1
            if mof.get("procurement_type"):
                types[mof["procurement_type"]] = types.get(mof["procurement_type"], 0) + 1
            if mof.get("buyer_idno") and api.get("buyer_identifier"):
                if mof["buyer_idno"] == api["buyer_identifier"]:
                    idno_agree += 1
                else:
                    idno_conflict += 1
            if mof.get("procurement_type") and api.get("procurement_method_details"):
                if mof["procurement_type"] == api["procurement_method_details"]:
                    type_agree += 1
                else:
                    type_conflict += 1
            if (
                mof.get("estimated_value") is not None
                and api.get("estimated_value") is not None
            ):
                if abs(mof["estimated_value"] - api["estimated_value"]) < 0.01:
                    value_agree += 1
                else:
                    value_conflict += 1
                    if len(conflicts) < 50:
                        conflicts.append(
                            {
                                "ocid": ocid,
                                "mof_estimated_value": mof["estimated_value"],
                                "api_estimated_value": api["estimated_value"],
                                "difference": round(
                                    mof["estimated_value"] - api["estimated_value"], 2
                                ),
                            }
                        )
    return {
        "compared": matched,
        "mof_rows_without_api_record": len(ocids) - matched,
        "mof_rows_without_api_record_examples": unmatched,
        "buyer_idno_agree": idno_agree,
        "buyer_idno_conflict": idno_conflict,
        "procurement_type_agree": type_agree,
        "procurement_type_conflict": type_conflict,
        "estimated_value_agree": value_agree,
        "estimated_value_conflict": value_conflict,
        "procurement_type_distribution": types,
        "value_conflict_examples": conflicts,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(OPENDATA_DIR))
    ap.add_argument(
        "--no-crosscheck",
        action="store_true",
        help="skip the comparison against raw_tenders (useful mid-ingestion)",
    )
    args = ap.parse_args()

    _, db = connect()
    ensure_indexes(db)
    run_id = make_run_id("mof")
    started = utcnow_iso()

    files = sorted(Path(args.dir).glob("*.xlsx"))
    if not files:
        print(f"no .xlsx workbooks under {args.dir}")
        return 1
    print(f"reading {len(files)} workbook(s) from {args.dir}")
    docs: list[dict[str, Any]] = []
    for path in files:
        rows = read_workbook(path)
        print(f"  {path.name}: {len(rows):,} rows")
        docs.extend(rows)
    for doc in docs:
        doc["run_id"] = run_id
        doc["ingested_at"] = started

    inserted, skipped = upsert_many(db, RAW_MOF_PROCEDURES, docs, key="ocid", immutable=True)

    periods: dict[str, int] = {}
    authorities: set[str] = set()
    for doc in docs:
        if doc.get("period"):
            periods[doc["period"]] = periods.get(doc["period"], 0) + 1
        if doc.get("buyer_idno"):
            authorities.add(doc["buyer_idno"])

    check: dict[str, Any] = {"skipped": True}
    if not args.no_crosscheck:
        print("cross-checking against raw_tenders ...")
        check = crosscheck(db, docs)
        print(json.dumps({k: v for k, v in check.items() if k != "value_conflict_examples"},
                         indent=2, ensure_ascii=False))

    summary = {
        "run_id": run_id,
        "stage": "load_mof_opendata",
        "generated_at": started,
        "source_dir": args.dir,
        "source_files": [p.name for p in files],
        "source_columns": COLUMN_MAP,
        "rows_read": len(docs),
        "rows_inserted": inserted,
        "rows_skipped_existing": skipped,
        "periods": periods,
        "unique_authority_idnos": len(authorities),
        "stored_documents": db[RAW_MOF_PROCEDURES].count_documents({}),
        "crosscheck": check,
    }
    MONGO_META.mkdir(parents=True, exist_ok=True)
    out = MONGO_META / "mof_opendata_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "crosscheck"}, indent=2, ensure_ascii=False))
    print(f"\nsummary written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
