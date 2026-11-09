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
              digits.  A row whose text layer names a FOREIGN procurement
              while its own digits are absent is flagged as a TECHNICAL
              ``mislink_candidate`` - a hint for the reviewer, never the
              human ``reviewer_link_verified`` value.  It NEVER copies a
              human label anywhere: reusing a value across rows still
              requires the reviewer to verify the identity of each file
              AND its link to the procedure.

  verify      independent check of a built pack: no outcome/prediction
              word in the machine-generated text (labels + OCR of the
              cover/headers), every page states the OCID and source page
              of its pilot row (manifest vs pilot CSV vs spec), and the
              page bodies match FRESH renders of exactly those source
              pages (pixel tolerance for JPEG re-encoding).

Contracts: the review CSVs are read-only (byte-identical after a run), no
``reviewer_*`` cell is written, production v0 / ETL 00-11 / backend /
frontend untouched.

Exit codes: 0 = ok, 4 = missing input file or rendering aid, 5 = missing,
inconsistent local PDF or verification failure.

Usage:
    .venv/bin/python scripts/49_ansc_review_pack.py pack [--out PDF]
    .venv/bin/python scripts/49_ansc_review_pack.py verify [--skip-ocr]
    .venv/bin/python scripts/49_ansc_review_pack.py duplicates
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import sys
import tempfile
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


def cover_lines(entries: list[dict], generated: str | None = None) -> list[str]:
    """Cover text: contents + disclaimers, identity only, no outcome.

    ``generated`` overrides the cover date (verification of a pack built on
    an earlier day); defaults to today."""
    lines = [
        "**MTA-0019 - evidence pack for the independent review",
        f"Pilot documents 2-10, original pages of the local PDF copies, "
        f"generated {generated or date.today().isoformat()} "
        f"(read-only, no network).",
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


def _digits(text: str) -> str:
    """All digits of ``text`` (OCR may inject spaces inside long numbers)."""
    return re.sub(r"\D+", "", text)


class PackError(Exception):
    """(exit code, message) for pack/verify input problems."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _collect_entries(pilot_path: Path, spec: dict) -> list[dict]:
    """Validate inputs and build the page entries of the pack (shared by
    ``pack`` and ``verify`` so the verification sees the same spec)."""
    if not pilot_path.is_file():
        raise PackError(4, f"missing {pilot_path}")
    with pilot_path.open(newline="", encoding="utf-8") as fh:
        pilot_rows = list(csv.DictReader(fh))

    entries: list[dict] = []
    for pilot_no in sorted(spec):
        if not 1 <= pilot_no <= len(pilot_rows):
            raise PackError(4, f"pilot row {pilot_no} missing in {pilot_path}")
        row = pilot_rows[pilot_no - 1]
        entry_spec = spec[pilot_no]
        pdf = Path(row["local_pdf_path"])
        if not pdf.is_file():
            raise PackError(5, f"missing local PDF for pilot No {pilot_no}: "
                               f"{pdf}")
        try:
            n_pages = _page_count(pdf)
        except RuntimeError as exc:
            raise PackError(4, str(exc)) from exc
        except Exception as exc:                      # noqa: BLE001
            raise PackError(5, f"unreadable PDF for pilot No {pilot_no}: "
                               f"{exc}") from exc
        row = dict(row, _pdf_pages=str(n_pages))
        for page_no, kind in entry_spec["pages"]:
            if page_no > n_pages:
                raise PackError(5, f"pilot No {pilot_no}: spec page "
                                   f"{page_no} > {n_pages} pages in "
                                   f"{pdf.name}")
            entries.append(dict(entry_spec, pages_kind=kind,
                                pilot_no=pilot_no, source_page=page_no,
                                row=row))
    return entries


def _compose_all(entries: list[dict],
                 cover_date: str | None = None) -> tuple[list, list]:
    """Render every entry once and compose cover + labelled pages.

    Returns ``(rendered, images)`` where ``rendered`` is the per-entry list
    ``(entry, page_image, label_lines)`` for the manifest and ``images``
    the full page list of the pack (cover first). ``cover_date`` overrides
    the cover generation date (verification of an older artefact)."""
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
    images = [_cover(cover_lines(entries, generated=cover_date),
                     max_w, max_h)]
    images += [_compose(img, lines, max_w, max_h)
               for _, img, lines in rendered]
    return rendered, images


def build_pack(pilot_path: Path, out_pdf: Path,
               manifest_path: Path) -> int:
    try:
        import pypdfium2  # noqa: F401                      # rendering aid
    except ImportError:
        print("pypdfium2 is required for pack (rendering aid)", file=sys.stderr)
        return 4

    try:
        entries = _collect_entries(pilot_path, PACK_SPEC)
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

    rendered, images = _compose_all(entries)

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


# --- verify -----------------------------------------------------------------
PIXEL_DIFF_MAX = 20.0      # mean grey-level difference allowed vs the
                           # source render (the pack PDF re-encodes images)


def manifest_errors(manifest_rows: list[dict], pilot_rows: list[dict],
                    spec: dict) -> list[str]:
    """Consistency of the manifest vs the pilot CSV and the pack spec.

    Checks per row: sequence order, pilot number range, the OCID stated on
    the page equals the pilot row's OCID, the source page and page kind
    equal the spec entry, the decision number equals the spec, the source
    page exists in the PDF, and no label carries an outcome/prediction
    word. Returns a list of human-readable errors (empty = consistent)."""
    errors: list[str] = []
    expected: list[tuple[int, int, str]] = []
    for pilot_no in sorted(spec):
        for page_no, kind in spec[pilot_no]["pages"]:
            expected.append((pilot_no, page_no, kind))
    if len(manifest_rows) != len(expected):
        errors.append(f"manifest has {len(manifest_rows)} rows, the spec "
                      f"expects {len(expected)}")
    for i, m in enumerate(manifest_rows):
        if i >= len(expected):
            break
        exp_pilot, exp_page, exp_kind = expected[i]
        if m.get("seq") and int(m["seq"]) != i + 1:
            errors.append(f"manifest row {i + 1}: seq {m['seq']} != {i + 1}")
        try:
            pilot_no = int(m.get("pilot_no") or "")
            source_page = int(m.get("source_page") or "")
        except ValueError:
            errors.append(f"manifest row {i + 1}: non-integer "
                          f"pilot_no/source_page")
            continue
        if (pilot_no, source_page, m.get("page_kind", "")) != \
                (exp_pilot, exp_page, exp_kind):
            errors.append(f"manifest row {i + 1}: "
                          f"{(pilot_no, source_page, m.get('page_kind', ''))} "
                          f"!= spec {(exp_pilot, exp_page, exp_kind)}")
        if not 1 <= pilot_no <= len(pilot_rows):
            errors.append(f"manifest row {i + 1}: pilot_no {pilot_no} out of "
                          f"range 1..{len(pilot_rows)}")
        else:
            ocid = (pilot_rows[pilot_no - 1].get("ocid") or "").strip()
            if (m.get("ocid") or "").strip() != ocid:
                errors.append(f"manifest row {i + 1}: stated OCID "
                              f"{m.get('ocid')!r} != pilot row OCID {ocid!r}")
        if (m.get("decision_id") or "") != spec[exp_pilot]["decision"]:
            errors.append(f"manifest row {i + 1}: decision "
                          f"{m.get('decision_id')!r} != spec "
                          f"{spec[exp_pilot]['decision']!r}")
        try:
            if source_page > int(m.get("pdf_pages") or 0):
                errors.append(f"manifest row {i + 1}: source page "
                              f"{source_page} > {m.get('pdf_pages')} pages")
        except ValueError:
            errors.append(f"manifest row {i + 1}: bad pdf_pages")
        for field in ("label_line1", "label_line2"):
            hits = forbidden_hits(m.get(field) or "")
            if hits:
                errors.append(f"manifest row {i + 1}: outcome/prediction "
                              f"word(s) {hits} in {field}")
    return errors


def _mean_diff(expected, actual) -> float:
    """Mean grey-level absolute difference of two same-ish sized images."""
    from PIL import ImageChops, ImageStat
    if expected.size != actual.size:
        w = min(expected.size[0], actual.size[0])
        h = min(expected.size[1], actual.size[1])
        expected = expected.crop((0, 0, w, h))
        actual = actual.crop((0, 0, w, h))
    stat = ImageStat.Stat(
        ImageChops.difference(expected.convert("L"), actual.convert("L")))
    return float(stat.mean[0])


def _ocr_text(img, tmp: Path, name: str) -> str:
    """OCR one rendered page with tesseract (stdout; UTF-8)."""
    import subprocess
    png = tmp / f"{name}.png"
    img.save(png)
    proc = subprocess.run(["tesseract", str(png), "stdout", "-l", "eng"],
                          capture_output=True)
    return proc.stdout.decode("utf-8", "replace")


def verify_pack(pilot_path: Path, pack_pdf: Path, manifest_path: Path,
                use_ocr: bool = True) -> int:
    """Independent verification of the built pack (read-only).

    Checks (reviewer instruction of 2026-11-09, item 5):
      1. no outcome / prediction / assistance word anywhere in the
         machine-generated text (labels via the manifest, cover + headers
         via OCR of the rendered pages);
      2. every page states the OCID of its pilot row and the source page
         and page kind of the spec (manifest vs pilot CSV vs spec);
      3. the pack's page bodies are pixel-identical (within JPEG
         tolerance) to FRESH renders of exactly those source pages;
      4. page count = cover + manifest rows.

    Exit codes: 0 = verified, 4 = missing input/rendering aid,
                5 = mismatch found (details on stdout)."""
    try:
        import pypdfium2  # noqa: F401                      # rendering aid
    except ImportError:
        print("pypdfium2 is required for verify (rendering aid)",
              file=sys.stderr)
        return 4
    for path in (pack_pdf, manifest_path):
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            return 4
    try:
        entries = _collect_entries(pilot_path, PACK_SPEC)
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

    with manifest_path.open(newline="", encoding="utf-8") as fh:
        manifest_rows = list(csv.DictReader(fh))
    with pilot_path.open(newline="", encoding="utf-8") as fh:
        pilot_rows = list(csv.DictReader(fh))
    errors = manifest_errors(manifest_rows, pilot_rows, PACK_SPEC)

    from pypdf import PdfReader
    n_pages = len(PdfReader(str(pack_pdf)).pages)
    if n_pages != len(manifest_rows) + 1:
        errors.append(f"pack has {n_pages} pages, expected "
                      f"{len(manifest_rows)} + 1 cover")

    # actual pages rendered at the pack's own scale (saved at 150 dpi)
    doc = pypdfium2.PdfDocument(str(pack_pdf))
    try:
        actual = [doc[i].render(scale=150 / 72).to_pil().convert("RGB")
                  for i in range(len(doc))]
    finally:
        doc.close()

    ocr_used = bool(use_ocr and shutil.which("tesseract"))
    if use_ocr and not ocr_used:
        print("tesseract not found - OCR checks skipped", file=sys.stderr)

    tmp = Path(tempfile.mkdtemp(prefix="ansc_pack_verify_"))
    diffs: list[float] = []
    try:
        # --- cover: forbidden words + generation date (for pixel rebuild)
        cover_date = None
        if ocr_used and actual:
            cover_ocr = _ocr_text(actual[0], tmp, "cover")
            hits = forbidden_hits(cover_ocr)
            if hits:
                errors.append(f"cover OCR carries outcome/prediction "
                              f"word(s) {hits}")
            m = re.search(r"generated (\d{4}-\d{2}-\d{2})", cover_ocr)
            if m:
                cover_date = m.group(1)

        rendered, expected = _compose_all(entries, cover_date=cover_date)

        # --- page bodies vs fresh renders of the exact source pages
        diffs: list[float] = []
        for i, (exp, act) in enumerate(zip(expected, actual), start=1):
            d = _mean_diff(exp, act)
            diffs.append(d)
            if d > PIXEL_DIFF_MAX:
                errors.append(f"pack page {i}: mean pixel diff {d:.1f} > "
                              f"{PIXEL_DIFF_MAX} - body differs from the "
                              f"source render")
        if len(expected) != len(actual):
            errors.append(f"page count mismatch: pack {len(actual)} vs "
                          f"expected {len(expected)}")

        # --- content headers via OCR: pilot no + OCID, no forbidden word
        if ocr_used:
            for i, m in enumerate(manifest_rows):
                if i + 1 >= len(actual):
                    break
                text = _ocr_text(actual[i + 1], tmp, f"p{i + 1}")
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                header_block = " ".join(lines[:4])
                hits = forbidden_hits(header_block)
                if hits:
                    errors.append(f"pack page {i + 2}: outcome/prediction "
                                  f"word(s) {hits} in the machine header")
                header = next((ln for ln in lines[:4]
                               if "MTA-0019" in ln and "pilot No" in ln),
                              None)
                if header is None:
                    errors.append(f"pack page {i + 2}: pilot header not "
                                  f"recognized by OCR")
                    continue
                mn = re.search(r"pilot No\s+(\d+)", header)
                if not mn or int(mn.group(1)) != int(m.get("pilot_no", -1)):
                    errors.append(f"pack page {i + 2}: OCR pilot number "
                                  f"{mn.group(1) if mn else '?'} != manifest "
                                  f"{m.get('pilot_no')}")
                need = _digits(m.get("ocid", ""))
                if need and need not in _digits(header):
                    errors.append(f"pack page {i + 2}: OCR header does not "
                                  f"carry the stated OCID digits "
                                  f"{need} ({header!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        print(f"verify: {len(errors)} problem(s) found", file=sys.stderr)
        return 5
    print(f"verify: {len(manifest_rows)} content pages + cover OK "
          f"-> {_rel(pack_pdf)}")
    print(f"  manifest vs pilot CSV vs spec: consistent "
          f"(OCID / source page / decision on every page)")
    if diffs:
        print(f"  page bodies vs fresh source renders: mean pixel diff "
              f"max {max(diffs):.2f} (threshold {PIXEL_DIFF_MAX})")
    print(f"  OCR header checks: {'ran' if ocr_used else 'skipped'} - "
          f"no outcome/prediction word in machine-generated text")
    return 0


# --- duplicates -------------------------------------------------------------
OCID_RX = re.compile(r"MD[-\s]*(\d{10,15})")


def text_fingerprint(text: str) -> str:
    """Whitespace/punctuation-insensitive fingerprint of a text layer."""
    compact = re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()
    if len(compact) < 500:
        return ""            # too short to identify a document reliably
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:12]


def link_facts(text: str, ocid: str) -> dict:
    """Link evidence of a TEXT LAYER vs the row's OCID (pure function).

    Returns ``ocid_digits_in_text`` (``yes`` / ``no`` / ``no_text_layer`` /
    ``no_ocid_digits``), ``md_numbers_in_text`` (procurement numbers with
    OCID context, foreign ones only for candidates) and
    ``mislink_candidate`` - a TECHNICAL hint (``yes``/``no``/``""`` when not
    decidable), never a human verdict."""
    compact = re.sub(r"\s+", "", text)
    # procurement numbers mentioned WITH OCID context ("MD-…" / "ocds-…-MD-…",
    # line wraps collapsed); bare digit runs are NOT counted (IDNO/company
    # or contract identifiers would fake candidates)
    md_numbers = sorted(set(re.findall(r"MD-?(\d{10,15})", compact, re.I)))
    out = {"ocid_digits_in_text": "", "md_numbers_in_text": ";".join(md_numbers),
           "mislink_candidate": ""}
    digits = OCID_RX.search(ocid or "")
    if not digits:
        out["ocid_digits_in_text"] = "no_ocid_digits"
        return out
    if len(compact) < 200:
        out["ocid_digits_in_text"] = "no_text_layer"
        return out
    if digits.group(1) in compact:
        out["ocid_digits_in_text"] = "yes"
        return out
    out["ocid_digits_in_text"] = "no"
    own = digits.group(1)
    # a mention that is only a TRUNCATION of the own digits (garbled layer)
    # is not foreign
    foreign = [n for n in md_numbers if n not in own and own not in n]
    out["mislink_candidate"] = "yes" if foreign else "no"
    if foreign:
        out["md_numbers_in_text"] = ";".join(foreign)
    return out


def pdf_facts(idx: int, row: dict, assist: dict | None) -> dict:
    pdf = Path(row.get("local_pdf_path") or "")
    facts = {"row_index": str(idx), "ocid": row.get("ocid", ""),
             "decision_ref": row.get("decision_id", ""),
             "pdf_sha256_12": "", "pdf_bytes": "", "pdf_pages": "",
             "text_fp_12": "", "ocid_digits_in_text": "missing_pdf",
             "md_numbers_in_text": "", "mislink_candidate": "",
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
    facts.update(link_facts(text, row.get("ocid", "")))
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
    mislink_cands = {f["row_index"]: f["md_numbers_in_text"]
                     for f in facts if f["mislink_candidate"] == "yes"}

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
    print(f"TECHNICAL mislink candidates (foreign number in text, own "
          f"digits absent - NOT a human verdict): {mislink_cands or 'none'}")
    print("identity hints only - a human value is NEVER copied between "
          "rows without verifying each file and its link")
    return 0


# --- main -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["pack", "verify", "duplicates"])
    ap.add_argument("--out", default=None,
                    help="pack PDF path (output for pack, input for verify)")
    ap.add_argument("--manifest", default=None,
                    help="manifest path (output for pack, input for verify)")
    ap.add_argument("--skip-ocr", action="store_true",
                    help="verify: skip the tesseract header/cover checks")
    args = ap.parse_args(argv)
    if args.mode == "pack":
        out = Path(args.out) if args.out else PACK_PDF
        man = Path(args.manifest) if args.manifest else PACK_MANIFEST
        return build_pack(PILOT_10, out, man)
    if args.mode == "verify":
        out = Path(args.out) if args.out else PACK_PDF
        man = Path(args.manifest) if args.manifest else PACK_MANIFEST
        return verify_pack(PILOT_10, out, man, use_ocr=not args.skip_ocr)
    return duplicates_check(REVIEW_50, DUP_CSV, ASSIST_CSV)


if __name__ == "__main__":
    sys.exit(main())
