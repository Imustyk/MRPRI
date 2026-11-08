#!/usr/bin/env python3
"""Technical assistance package for the 50-document ANSC manual review
(MTA-0019, step 7).

MEASUREMENT SUPPORT ONLY - production v0, ETL 00-11, backend and frontend
are untouched, and the script never touches the network (all PDFs come from
the local sandbox copies referenced by the review file).

INDEPENDENCE CONTRACT:
  * the review CSVs (``ansc_manual_review_50.csv`` /
    ``ansc_manual_review_pilot10.csv``) are READ-ONLY here - a single
    ``reviewer_*`` cell is never written;
  * the machine prediction of scripts/43/44
    (``extracted_outcome`` / ``extraction_method`` / ``confidence`` in
    ``ansc_review_sample_50.csv``) is NEVER read or copied - this file
    performs a FRESH pass over the PDFs instead;
  * everything produced here is a technical PRELIMINARY hint, never a human
    confirmation: the ``assistance_status`` column is always
    ``prepared_not_reviewed``. Two algorithms agreeing is not a review; the
    reviewer still decides each outcome from the document itself (guide).

Output (one separate technical file, as required by step 7):
    results/tables/ansc_review_assistance_50.csv

Reading aids: one PNG per document (the resolutory page when found, else the
last page) in ``results/ansc_review_pages/`` - rendered with pypdfium2 if it
is importable (optional aid dependency, skipped otherwise).

Columns: row_index, ocid, decision_id, document_url, local_pdf_path,
pdf_pages, text_layer (text|partial|garbled|scan), ocr_pages_done,
resolutory_page, resolutory_quote, resolution_anchor, complaint_count,
complaint_ids, decision_number, procedure_ids_in_doc, doc_type_hint,
fresh_outcome_hint, fresh_unknown_reason, link_hint, rendered_image,
mtender_card_url, in_pilot, assistance_status.

``fresh_outcome_hint`` follows the same formulation rules as the extraction
stage but is recomputed from the local PDF on every run; per the protocol it
must not be pasted into ``reviewer_*`` and must not be treated as expert
truth (``unknown`` stays ``unknown`` until a human establishes otherwise).

Usage:
    .venv/bin/python scripts/48_ansc_review_assistance.py
        [--no-render] [--limit N] [--quiet]

Exit codes: 0 = assistance file written, 4 = review file missing.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW_50 = ROOT / "data" / "external" / "ansc_manual_review_50.csv"
PILOT_10 = ROOT / "data" / "external" / "ansc_manual_review_pilot10.csv"
OUT_CSV = ROOT / "results" / "tables" / "ansc_review_assistance_50.csv"
IMG_DIR = ROOT / "results" / "ansc_review_pages"

OCR_BUDGET = 8          # max pages OCR-ed per document (identity + tail)
OCR_TAIL = 6            # trailing pages where the resolutory part usually is
RESOLUTION_WINDOW = 3000  # chars after the anchor scanned for complaints
QUOTE_MAX = 700

COMPLAINT_RX = re.compile(r"02\s*/\s*\d{1,4}\s*/\s*\d{2}")
DECISION_RX = re.compile(r"03\s*D\s*-\s*\d+\s*-\s*\d+", re.IGNORECASE)
PROCEDURE_RX = re.compile(r"md\s*-\s*(\d{10,15})", re.IGNORECASE)
DIACRITICS_RX = re.compile(r"[ăâîșțĂÂÎȘȚ]")
# scripts/43 lowercases when deaccenting - compare lowercase literals only:
ANSC_LETTERHEAD = "solutionarea contestatiilor"

HEADER = [
    "row_index", "ocid", "decision_id", "document_url", "local_pdf_path",
    "pdf_pages", "text_layer", "ocr_pages_done", "resolutory_page",
    "resolutory_quote", "resolution_anchor", "complaint_count",
    "complaint_ids", "decision_number", "procedure_ids_in_doc",
    "doc_type_hint", "fresh_outcome_hint", "fresh_unknown_reason",
    "link_hint", "rendered_image", "mtender_card_url", "in_pilot",
    "assistance_status",
]


def _load_script(name: str):
    """Import a sibling script as a module (same trick as scripts/31/42/44)."""
    path = Path(__file__).resolve().parent / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S43 = _load_script("43_ansc_outcome_extract.py")


# --- document pass -----------------------------------------------------------
def text_status(pages: list[str]) -> tuple[str, list[int]]:
    """``(text_layer, indices of pages without a usable text layer)``."""
    empty = [i for i, t in enumerate(pages, start=1)
             if len((t or "").strip()) < 200]
    joined = "".join(t for t in pages if t and t.strip())
    total = len(joined)
    if not pages or len(empty) == len(pages):
        status = "scan"
    elif total > 500 and not DIACRITICS_RX.search(joined):
        status = "garbled"       # OCR text layer without a single diacritic
    elif empty:
        status = "partial"
    else:
        status = "text"
    return status, empty


def ocr_plan(status: str, empty: list[int], n_pages: int) -> list[int]:
    """Pages worth OCR-ing (identity pages + trailing resolutory pages).

    * ``garbled`` - a text layer exists but has no diacritics at all (poor
      OCR export): re-OCR the first pages (letterhead / decision number) and
      the last ones (resolutory part);
    * ``scan``/``partial`` - only pages without a usable text layer.
    """
    if status == "garbled":
        picks = unique_ordered([str(i) for i in (1, 2, 3)
                                if i <= n_pages] +
                               [str(i) for i in (n_pages - 1, n_pages)
                                if i >= 1])
        return [int(p) for p in picks][:OCR_BUDGET]
    if not empty:
        return []
    picks_list: list[int] = []
    if 1 in empty:
        picks_list.append(1)
    tail = [i for i in empty if i != 1]
    tail = (tail[-OCR_TAIL:] if len(tail) > OCR_TAIL - (1 in empty)
            else tail)
    picks_list.extend(tail)
    return picks_list[:OCR_BUDGET]


def unique_ordered(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for it in items:
        seen.setdefault(it, None)
    return list(seen)


def assist_row(idx: int, row: dict, pilot_urls: set[str],
               render: bool, s43=S43) -> dict:
    out = {k: "" for k in HEADER}
    out.update({
        "row_index": str(idx),
        "ocid": row.get("ocid", ""),
        "decision_id": row.get("decision_id", ""),
        "document_url": row.get("document_url", ""),
        "local_pdf_path": row.get("local_pdf_path", ""),
        "complaint_count": "0",
        "doc_type_hint": "uncertain",
        "fresh_outcome_hint": "unknown",
        "link_hint": "uncertain",
        "in_pilot": "yes" if row.get("document_url") in pilot_urls else "no",
        "assistance_status": "prepared_not_reviewed",
    })
    pdf = Path(row.get("local_pdf_path") or "")
    if not pdf.is_file():
        out["fresh_unknown_reason"] = "missing local PDF"
        return out

    pages, error = s43.read_pdf_pages(pdf)
    if error or not pages:
        out["fresh_unknown_reason"] = f"unreadable PDF ({error or 'no pages'})"
        return out

    status, empty = text_status(pages)
    out["pdf_pages"] = str(len(pages))
    out["text_layer"] = status

    # OCR only pages without usable text (technical aid, never re-labelled
    # as an independent check).
    ocr_map: dict[int, str] = {}
    for pageno in ocr_plan(status, empty, len(pages)):
        text = s43.ocr_page(pdf, pageno, OCR_BUDGET)
        if text.strip():
            ocr_map[pageno] = text
    out["ocr_pages_done"] = ",".join(str(p) for p in sorted(ocr_map))

    fresh = s43.extract_outcome(pages, ocr_pages=ocr_map)
    out["resolutory_page"] = fresh.get("page_number", "")
    quote = (fresh.get("quote") or "").replace("\n", " ")
    out["resolutory_quote"] = " ".join(quote.split())[:QUOTE_MAX]
    out["resolution_anchor"] = " ".join(
        (fresh.get("resolution_anchor") or "").split())
    out["fresh_outcome_hint"] = fresh.get("outcome") or "unknown"
    out["fresh_unknown_reason"] = fresh.get("unknown_reason", "")

    # complaint / decision / procedure numbers over the resolutory window
    merged = "\n".join((t or "") + (ocr_map.get(i, "")) for i, t in
                       enumerate(pages, start=1))
    flat = s43.deaccent(merged)
    lo, _, _, _ = s43.locate_resolution(flat)
    window = flat[lo:lo + RESOLUTION_WINDOW] if lo is not None else flat
    complaints = unique_ordered([re.sub(r"\s+", "", c)
                                 for c in COMPLAINT_RX.findall(window)])
    out["complaint_ids"] = ";".join(complaints)
    out["complaint_count"] = str(len(complaints))
    decisions = unique_ordered([re.sub(r"\s+", "", d).upper() for d in
                                DECISION_RX.findall(flat)])
    out["decision_number"] = decisions[0] if decisions else ""
    procs = unique_ordered(PROCEDURE_RX.findall(flat))
    out["procedure_ids_in_doc"] = ";".join(f"MD-{p}" for p in procs[:5])

    # document-type hint (technical, mirrors the reviewer enum).
    # ``flat`` is lowercased by deaccent; strong anchors are the literals of
    # scripts/43 (``d e c i d e`` / ``decide`` / ``hotaraste`` / ``h o t a r``).
    letterhead = ANSC_LETTERHEAD in flat
    anchor_norm = s43.deaccent(out["resolution_anchor"] or "")
    strong_anchor = any(a in anchor_norm for a in s43.STRONG_ANCHORS)
    if letterhead and strong_anchor:
        out["doc_type_hint"] = "ansc_decision"
    elif letterhead:
        out["doc_type_hint"] = "other_document"   # ANSC letter, no resolutory
    elif status == "scan" and not ocr_map:
        out["doc_type_hint"] = "uncertain"         # unreadable - open the PDF
    elif status == "garbled" and not ocr_map:
        out["doc_type_hint"] = "uncertain"
    else:
        out["doc_type_hint"] = "other_document"   # readable, not ANSC-headed

    # document -> procedure link hint (digits of MD-... vs the row's OCID)
    ocid_digits = re.search(r"MD[-\s]*(\d{10,15})", row.get("ocid", ""))
    if procs and ocid_digits:
        out["link_hint"] = ("confirmed" if ocid_digits.group(1) in procs
                            else "rejected")
    elif procs:
        out["link_hint"] = "rejected"
    else:
        out["link_hint"] = "uncertain"

    # reading aid: one PNG of the resolutory (else last) page
    if render:
        page_no = int(out["resolutory_page"] or 0)
        if not (1 <= page_no <= len(pages)):
            page_no = len(pages)
        out["rendered_image"] = render_page(pdf, page_no, idx)

    ocid_md = re.search(r"ocds-b3wdp1-MD-\d+", row.get("ocid", ""))
    out["mtender_card_url"] = (f"https://mtender.gov.md/tenders/{ocid_md.group(0)}"
                               if ocid_md else "")
    return out


def render_page(pdf: Path, page_no: int, idx: int) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return ""
    try:
        doc = pdfium.PdfDocument(str(pdf))
        img = doc[page_no - 1].render(scale=2.0).to_pil()
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        path = IMG_DIR / f"row{idx:02d}_p{page_no}.png"
        img.save(path)
        doc.close()
        return str(path.relative_to(ROOT))
    except Exception:                                  # noqa: BLE001
        return ""


# --- main --------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-render", action="store_true",
                    help="skip PNG page rendering")
    ap.add_argument("--limit", type=int, default=0,
                    help="only process the first N rows ( debugging )")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not REVIEW_50.is_file():
        print(f"missing {REVIEW_50}", file=sys.stderr)
        return 4
    with REVIEW_50.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    pilot_urls: set[str] = set()
    if PILOT_10.is_file():
        with PILOT_10.open(newline="", encoding="utf-8") as fh:
            pilot_urls = {r["document_url"] for r in csv.DictReader(fh)}

    limit = args.limit or len(rows)
    rendered = 0
    out_rows = []
    for idx, row in enumerate(rows, start=1):
        if idx > limit:
            break
        rec = assist_row(idx, row, pilot_urls, render=not args.no_render)
        if rec["rendered_image"]:
            rendered += 1
        out_rows.append(rec)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(out_rows)

    if not args.quiet:
        scans = sum(1 for r in out_rows if r["text_layer"] == "scan")
        multi = sum(1 for r in out_rows if int(r["complaint_count"] or 0) > 1)
        types = {}
        hints = {}
        for r in out_rows:
            types[r["doc_type_hint"]] = types.get(r["doc_type_hint"], 0) + 1
            hints[r["fresh_outcome_hint"]] = hints.get(r["fresh_outcome_hint"], 0) + 1
        print(f"assistance rows: {len(out_rows)} -> "
              f"{OUT_CSV.relative_to(ROOT)}")
        print(f"  text_layer: scans={scans} | multi-complaint rows={multi}")
        print(f"  doc_type_hint: {types}")
        print(f"  fresh_outcome_hint: {hints}")
        print(f"  page images rendered: {rendered} -> "
              f"{IMG_DIR.relative_to(ROOT)}/")
        print("  assistance_status=prepared_not_reviewed (no human "
              "confirmation is stored here)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
