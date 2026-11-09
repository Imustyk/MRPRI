#!/usr/bin/env python3
"""Evidence pack + duplicate check for the ANSC manual review (MTA-0019).

Two modes, both READ-ONLY on the review files, no network, and the machine
sample ``ansc_review_sample_50.csv`` is NEVER opened (the reviewer must not
see any automatic prediction):

  pack        one PDF of the ORIGINAL pages an independent reviewer has to
              see for pilot documents 2-10: the resolutory pages of the ANSC
              decisions and, for the non-decision documents 5, 7, 9 and 10,
              the pages that establish the document type.  Every page is
              labelled with the pilot number, OCID, decision number (when
              the document has one) and the source page.  Document type and
              link to the procedure are stated SEPARATELY - a document that
              is not an ANSC decision is not thereby mislinked (reviewer
              instruction of 2026-11-09, item 1).  No outcome word, no
              extraction result, no assistance hint enters the pack.

  duplicates  technical identity check of the 50-row sample: content
              hashes, repeated OCIDs, repeated decision numbers, and
              whether each document actually contains its own procedure
              digits.  It NEVER copies a human label anywhere: reusing a
              value across rows still requires the reviewer to verify the
              identity of each file AND its link to the procedure.

Contracts: the review CSVs are read-only (byte-identical after a run), no
``reviewer_*`` cell is written, production v0 / ETL 00-11 / backend /
frontend untouched.

Exit codes: 0 = ok, 4 = missing input file or rendering aid, 5 = missing or
inconsistent local PDF.

Usage:
    .venv/bin/python scripts/49_ansc_review_pack.py pack [--out PDF]
    .venv/bin/python scripts/49_ansc_review_pack.py duplicates
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PILOT_10 = ROOT / "data" / "external" / "ansc_manual_review_pilot10.csv"
REVIEW_50 = ROOT / "data" / "external" / "ansc_manual_review_50.csv"
ASSIST_CSV = ROOT / "results" / "tables" / "ansc_review_assistance_50.csv"
PACK_PDF = ROOT / "results" / "ansc_review_pages" / "ansc_pilot_2-10_evidence_pack.pdf"
PACK_MANIFEST = ROOT / "results" / "tables" / "ansc_evidence_pack_manifest.csv"
DUP_CSV = ROOT / "results" / "tables" / "ansc_sample_duplicates.csv"

# --- blindness: these words must not appear anywhere in the pack ------------
FORBIDDEN_IN_PACK = (
    "admitted", "partially", "rejected", "inadmissible", "withdrawn",
    "terminated", "unknown", "prediction", "confidence", "extracted",
)

# pilot_no -> pages of the ORIGINAL pdf (1-based) + verified identity facts.
# Decision numbers were verified on page 1 of each PDF by the agent and are
# NOT taken from any extraction output. Non-decision documents (5, 7, 9, 10)
# contribute their document-type pages instead of a resolutory page.
PACK_SPEC: dict[int, dict] = {
    2: {"pages": ((15, "resolutory page"),),
        "decision": "03D-355-20", "what": ""},
    3: {"pages": ((7, "resolutory page"),),
        "decision": "03D-884-20", "what": ""},
    4: {"pages": ((9, "resolutory page"),),
        "decision": "03D-541-20", "what": ""},
    5: {"pages": ((1, "document-type page"),),
        "decision": "",
        "what": "ANSC letter nr. 05/795/21 of 14.04.2021"},
    6: {"pages": ((11, "resolutory page"),),
        "decision": "03D-94-19", "what": ""},
    7: {"pages": ((1, "document-type page"), (2, "document-type page")),
        "decision": "",
        "what": "ASP (Public Services Agency) letter on award results"},
    8: {"pages": ((27, "resolutory page"),),
        "decision": "03D-704-19", "what": ""},
    9: {"pages": ((1, "document-type page"),),
        "decision": "",
        "what": "contracting-authority decision nr. 5D of 13.12.2021"},
    10: {"pages": ((1, "document-type page"),),
         "decision": "",
         "what": "ASP working-group minutes PV 413/22 of 01.11.2022"},
}

FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
LINE_H = 30
PAD = 14
DISCLAIMER_EN = ("An upheld ANSC complaint indicates an administrative "
                 "procurement dispute outcome and does not constitute "
                 "proof of corruption.")
DISCLAIMER_RU = ("Индикатор потенциального риска, а не доказательство "
                 "коррупции/нарушения. Требуется проверка компетентным "
                 "органом.")


def forbidden_hits(text: str) -> list[str]:
    """Words of FORBIDDEN_IN_PACK present in ``text`` (case-insensitive)."""
    low = text.lower()
    return [w for w in FORBIDDEN_IN_PACK if w in low]


def _rel(path: Path) -> str:
    """Path relative to the repo root when possible (tests use tmp dirs)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _font(size: int):
    from PIL import ImageFont
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def label_lines(pilot_no: int, row: dict, page_no: int,
                entry: dict) -> tuple[str, str]:
    """The two header lines of one pack page - identity only, no outcome."""
    total = row.get("_pdf_pages", "")
    line1 = f"MTA-0019 pilot No {pilot_no} | OCID {row.get('ocid', '')}"
    if entry["decision"]:
        line1 += f" | decision {entry['decision']}"
    line2 = f"source page {page_no}/{total} | {entry['pages_kind']}"
    if entry["what"]:
        line2 += f" | {entry['what']}"
    hits = forbidden_hits(line1 + " " + line2)
    if hits:                                   # pragma: no cover - guard
        raise AssertionError(f"outcome/prediction word in pack label: {hits}")
    return line1, line2


# --- pack -------------------------------------------------------------------
def _open(pdf: Path):
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:                 # pragma: no cover
        raise RuntimeError("pypdfium2 is required for the pack") from exc
    return pdfium.PdfDocument(str(pdf))


def _page_count(pdf: Path) -> int:
    doc = _open(pdf)
    try:
        return len(doc)
    finally:
        doc.close()


def _render(pdf: Path, page_no: int):
    doc = _open(pdf)
    try:
        n = len(doc)
        if not 1 <= page_no <= n:
            raise ValueError(f"page {page_no} out of range 1..{n} for {pdf}")
        return doc[page_no - 1].render(scale=2.0).to_pil().convert("RGB")
    finally:
        doc.close()


def _compose(page_img, lines: list[str], canvas_w: int,
             canvas_h: int):
    from PIL import Image, ImageDraw
    header_h = PAD * 2 + LINE_H * len(lines)
    canvas = Image.new("RGB", (canvas_w, header_h + canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    y = PAD
    for text in lines:
        size = 26
        font = _font(size)
        while draw.textlength(text, font=font) > canvas_w - 2 * PAD and size > 14:
            size -= 2
            font = _font(size)
        draw.text((PAD, y), text, font=font, fill="black")
        y += LINE_H
    draw.line([(0, header_h - 1), (canvas_w, header_h - 1)],
              fill=(170, 170, 170), width=2)
    w, h = page_img.size
    canvas.paste(page_img, ((canvas_w - w) // 2,
                            header_h + (canvas_h - h) // 2))
    return canvas


def _cover(lines: list[str], canvas_w: int, canvas_h: int):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    y = PAD
    for raw in lines:
        bold = raw.startswith("**")
        text = raw[2:] if bold else raw
        size = 24 if bold else 20
        font = _font(size)
        # naive wrap on spaces
        words, cur, wrapped = text.split(), "", []
        for word in words:
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=font) > canvas_w - 2 * PAD:
                wrapped.append(cur)
                cur = word
            else:
                cur = trial
        wrapped.append(cur)
        for chunk in wrapped:
            if y + LINE_H > canvas_h - PAD:
                break
            draw.text((PAD, y), chunk, font=font, fill="black")
            y += LINE_H
        y += 6
    return canvas


def cover_lines(entries: list[dict]) -> list[str]:
    """Cover text: contents + disclaimers, identity only, no outcome."""
    lines = [
        "**MTA-0019 - evidence pack for the independent review",
        f"Pilot documents 2-10, original pages of the local PDF copies, "
        f"generated {date.today().isoformat()} (read-only, no network).",
        "No automatic outcome or extraction result is included in this pack.",
        "**Contents:",
    ]
    for entry in entries:
        row = entry["row"]
        head = (f"No {entry['pilot_no']} | "
                f"source page {entry['source_page']}/{row['_pdf_pages']} | "
                f"{entry['pages_kind']} | OCID {row['ocid']}")
        if entry["decision"]:
            head += f" | decision {entry['decision']}"
        else:
            head += " | no ANSC decision number"
        lines.append(head)
    lines += [
        "",
        "Decide every document yourself from the page shown; write the "
        "reviewer_* values only after your own decision "
        "(docs/ANSC_REVIEW_GUIDE.md). Document type and procedure link are "
        "judged separately.",
        "",
        DISCLAIMER_EN,
        DISCLAIMER_RU,
    ]
    hits = [ln for ln in lines if forbidden_hits(ln)]
    if hits:                                   # pragma: no cover - guard
        raise AssertionError(f"forbidden word in cover text: {hits[:1]}")
    return lines


def build_pack(pilot_path: Path, out_pdf: Path,
               manifest_path: Path) -> int:
    try:
        import pypdfium2  # noqa: F401                      # rendering aid
    except ImportError:
        print("pypdfium2 is required for pack (rendering aid)", file=sys.stderr)
        return 4
    if not pilot_path.is_file():
        print(f"missing {pilot_path}", file=sys.stderr)
        return 4

    with pilot_path.open(newline="", encoding="utf-8") as fh:
        pilot_rows = list(csv.DictReader(fh))

    entries: list[dict] = []
    for pilot_no in sorted(PACK_SPEC):
        if not 1 <= pilot_no <= len(pilot_rows):
            print(f"pilot row {pilot_no} missing in {pilot_path}",
                  file=sys.stderr)
            return 4
        row = pilot_rows[pilot_no - 1]
        spec = PACK_SPEC[pilot_no]
        pdf = Path(row["local_pdf_path"])
        if not pdf.is_file():
            print(f"missing local PDF for pilot No {pilot_no}: {pdf}",
                  file=sys.stderr)
            return 5
        try:
            n_pages = _page_count(pdf)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 4
        except Exception as exc:                      # noqa: BLE001
            print(f"unreadable PDF for pilot No {pilot_no}: {exc}",
                  file=sys.stderr)
            return 5
        row = dict(row, _pdf_pages=str(n_pages))
        for page_no, kind in spec["pages"]:
            if page_no > n_pages:
                print(f"pilot No {pilot_no}: spec page {page_no} > "
                      f"{n_pages} pages in {pdf.name}", file=sys.stderr)
                return 5
            entry = dict(spec, pages_kind=kind, pilot_no=pilot_no,
                         source_page=page_no, row=row)
            entries.append(entry)

    # render every page once, then compose on a common canvas
    rendered: list[tuple[dict, object, list[str]]] = []
    max_w = max_h = 0
    for entry in entries:
        row = entry["row"]
        img = _render(Path(row["local_pdf_path"]), entry["source_page"])
        lines = list(label_lines(entry["pilot_no"], row,
                                 entry["source_page"], entry))
        rendered.append((entry, img, lines))
        max_w = max(max_w, img.size[0])
        max_h = max(max_h, img.size[1])

    # cover: identity + disclaimers only (module-level guard applies)
    images = [_cover(cover_lines(entries), max_w, max_h)]
    images += [_compose(img, lines, max_w, max_h)
               for _, img, lines in rendered]

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out_pdf, "PDF", save_all=True,
                   append_images=images[1:], resolution=150)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["seq", "pilot_no", "source_page", "pdf_pages",
                         "page_kind", "ocid", "decision_id",
                         "label_line1", "label_line2"])
        for seq, (entry, _, lines) in enumerate(rendered, start=1):
            row = entry["row"]
            writer.writerow([seq, entry["pilot_no"], entry["source_page"],
                             row["_pdf_pages"], entry["pages_kind"],
                             row["ocid"], entry["decision"],
                             lines[0], lines[1]])
    print(f"pack: {len(rendered)} original pages -> "
          f"{_rel(out_pdf)}")
    print(f"manifest: {_rel(manifest_path)}")
    print("  no outcome / no prediction / no assistance hint in the pack")
    return 0


# --- duplicates -------------------------------------------------------------
OCID_RX = re.compile(r"MD[-\s]*(\d{10,15})")


def text_fingerprint(text: str) -> str:
    """Whitespace/punctuation-insensitive fingerprint of a text layer."""
    compact = re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()
    if len(compact) < 500:
        return ""            # too short to identify a document reliably
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:12]


def pdf_facts(idx: int, row: dict, assist: dict | None) -> dict:
    pdf = Path(row.get("local_pdf_path") or "")
    facts = {"row_index": str(idx), "ocid": row.get("ocid", ""),
             "decision_ref": row.get("decision_id", ""),
             "pdf_sha256_12": "", "pdf_bytes": "", "pdf_pages": "",
             "text_fp_12": "", "ocid_digits_in_text": "missing_pdf",
             "decision_fresh": "", "note": ""}
    if not pdf.is_file():
        facts["note"] = "missing local PDF"
        return facts
    data = pdf.read_bytes()
    facts["pdf_sha256_12"] = hashlib.sha256(data).hexdigest()[:12]
    facts["pdf_bytes"] = str(len(data))
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf))
        facts["pdf_pages"] = str(len(reader.pages))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as exc:                          # noqa: BLE001
        facts["note"] = f"unreadable PDF ({exc})"
        return facts
    facts["text_fp_12"] = text_fingerprint(text)
    digits = OCID_RX.search(row.get("ocid", ""))
    if not digits:
        facts["ocid_digits_in_text"] = "no_ocid_digits"
    elif len(re.sub(r"\s+", "", text)) < 200:
        facts["ocid_digits_in_text"] = "no_text_layer"
    else:
        facts["ocid_digits_in_text"] = (
            "yes" if digits.group(1) in re.sub(r"\s+", "", text) else "no")
    if assist:
        facts["decision_fresh"] = assist.get("decision_number", "")
        if not facts["decision_ref"]:
            facts["decision_ref"] = facts["decision_fresh"]
    return facts


def group_ids(rows: list[dict], key: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for r in rows:
        value = r.get(key) or ""
        if value:
            groups.setdefault(value, []).append(r["row_index"])
    return {k: v for k, v in groups.items() if len(v) > 1}


def duplicates_check(review_path: Path, out_csv: Path,
                     assist_path: Path | None = None) -> int:
    if not review_path.is_file():
        print(f"missing {review_path}", file=sys.stderr)
        return 4
    with review_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assist_by_url: dict[str, dict] = {}
    if assist_path and assist_path.is_file():
        with assist_path.open(newline="", encoding="utf-8") as fh:
            assist_by_url = {r["document_url"]: r
                             for r in csv.DictReader(fh)}

    facts = [pdf_facts(i, r, assist_by_url.get(r.get("document_url", "")))
             for i, r in enumerate(rows, start=1)]

    by_file = group_ids(facts, "pdf_sha256_12")
    by_text = group_ids(facts, "text_fp_12")
    by_ocid = group_ids(facts, "ocid")
    by_dec = group_ids(facts, "decision_ref")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(facts[0]))
        writer.writeheader()
        writer.writerows(facts)

    cross_ocid = {d: rs for d, rs in by_dec.items()
                  if len({f["ocid"] for f in facts
                          if f["row_index"] in rs}) > 1}
    no_digits = [f["row_index"] for f in facts
                 if f["ocid_digits_in_text"] in ("no", "no_ocid_digits")]
    no_layer = [f["row_index"] for f in facts
                if f["ocid_digits_in_text"] == "no_text_layer"]

    print(f"rows: {len(facts)} -> {_rel(out_csv)}")
    print(f"byte-identical PDFs: {len(by_file)} group(s) {by_file or ''}")
    print(f"identical text layers: {len(by_text)} group(s) {by_text or ''}")
    print(f"repeated OCIDs: {len(by_ocid)} group(s) {by_ocid or ''}")
    print(f"repeated decision numbers: {len(by_dec)} group(s) {by_dec or ''}")
    print(f"  ...of which across different OCIDs: {cross_ocid or 'none'}")
    print(f"text-layer rows lacking their own procedure digits: "
          f"{no_digits or 'none'}")
    print(f"rows without a usable text layer (link via OCR only): "
          f"{no_layer or 'none'}")
    print("identity hints only - a human value is NEVER copied between "
          "rows without verifying each file and its link")
    return 0


# --- main -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["pack", "duplicates"])
    ap.add_argument("--out", default=None,
                    help="override the pack PDF output path (tests)")
    ap.add_argument("--manifest", default=None,
                    help="override the manifest output path (tests)")
    args = ap.parse_args(argv)
    if args.mode == "pack":
        out = Path(args.out) if args.out else PACK_PDF
        man = Path(args.manifest) if args.manifest else PACK_MANIFEST
        return build_pack(PILOT_10, out, man)
    return duplicates_check(REVIEW_50, DUP_CSV, ASSIST_CSV)


if __name__ == "__main__":
    sys.exit(main())
