#!/usr/bin/env python3
"""ANSC decision outcome extraction (MTA-0018, step 3).

MEASUREMENT ONLY - no training, production stays v0, ``data/raw/**`` is
untouched. The script reads the inventory produced by ``scripts/42`` and the
PDFs it downloaded into the sandbox OUTSIDE the repository; it performs no
network requests at all (regression-tested).

Two-stage extraction (author's MTA-0018 rules):

STAGE 1 - locate the resolutory part:
  * STRONG structural anchors are tried first: ``HOTĂRĂȘTE``, ``DECIDE``
    and their OCR-garbled spellings (``d e c i d e``, ``h o t a r ...``);
  * WEAK anchors (``temeiul``, ``inadmisibil``, ``retragere``, ``anulează``)
    are auxiliary only - a weak anchor opens the resolutory part ONLY when a
    full resolutory formulation actually follows it;
  * candidates are evaluated from the END of the document by TYPE and
    CONTEXT: the last anchor is never taken blindly - an anchor whose
    following context carries no formulation is skipped and the previous
    candidate is tried;
  * no reliable resolutory part -> ``unknown`` (never a guess).

STAGE 2 - classify by FULL legal formulations inside the located part only
(``se admite parțial contestația``, ``se respinge contestația``,
``declară contestația inadmisibilă``, ``retragerea contestației``,
``încetează soluționarea contestației``, ...):
  * never a single stray word; sentences that cite another decision or
    restate the complainant's claims (motivational part) are ignored;
  * contradictory formulations (admission + rejection without an explicit
    partial marker), or different outcomes for different complaints ->
    ``unknown``;
  * categories: ``admitted``, ``partially_admitted``, ``rejected``,
    ``inadmissible``, ``withdrawn``, ``terminated``, ``unknown``;
  * the evidence quote is sliced from the ORIGINAL text - offsets come from
    ``deaccent()``, which is length-preserving by construction; the
    normalised copy is never used as evidence;
* OCR runs ONLY where the text layer is missing/unusable, page by page from
  the LAST page backwards (the resolutory part comes last), stopping as soon
  as a classifiable anchor shows up, at most ``--ocr-max-pages`` pages;
* every record keeps: outcome, the exact resolutory quote, the page, the
  extraction method, the confidence and the source URL.

Outputs:
  results/tables/ansc_outcomes.csv           - one row per probed (ocid, url)
  results/methodology/ansc_outcome_extraction.json - summary
  reports/ansc_outcome_extraction.md         - step-3 report

Usage:
    .venv/bin/python scripts/43_ansc_outcome_extract.py [--limit N] [--quiet]

Exit codes: 0 = ok, 4 = sandbox/inventory missing.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INV_CSV = ROOT / "results" / "tables" / "ansc_decision_inventory.csv"
INV_JSON = ROOT / "results" / "methodology" / "ansc_decision_inventory.json"
OUT_CSV = ROOT / "results" / "tables" / "ansc_outcomes.csv"
OUT_JSON = ROOT / "results" / "methodology" / "ansc_outcome_extraction.json"
OUT_MD = ROOT / "reports" / "ansc_outcome_extraction.md"

MIN_TEXT_CHARS = 50          # below this the layer counts as unusable
OCR_MAX_PAGES_DEFAULT = 3    # pages OCR'd per scanned document (from the end)
QUOTE_MAX_CHARS = 320
RESOLUTION_MAX_CHARS = 60000  # classification never looks further than this

OUTCOMES = ("admitted", "partially_admitted", "rejected", "inadmissible",
            "withdrawn", "terminated", "unknown")

CSV_FIELDS = [
    "ocid", "url", "title", "year", "decision_numbers", "decision_date",
    "outcome", "evidence_quote", "page_number", "extraction_method",
    "confidence", "document_present", "text_layer", "needs_ocr",
    "resolution_anchor", "unknown_reason", "error",
]

DISCLAIMER_RU = ("Индикатор потенциального риска, а не доказательство "
                 "коррупции/нарушения. Требуется проверка компетентным "
                 "органом.")
DISCLAIMER_EN = ("An upheld ANSC complaint indicates an administrative "
                 "procurement dispute outcome and does not constitute proof "
                 "of corruption.")


# --- helper: length-preserving normalisation --------------------------------
def deaccent(text: str) -> str:
    """Lowercase and strip combining marks (``contestația`` -> ``contestatia``).

    LENGTH-PRESERVING by construction: every input character maps to exactly
    one output character, so offsets computed on the deaccented copy stay
    valid for the original text (the evidence quote is sliced from the
    original). Regression-tested in tests/test_ansc_outcomes.py.
    """
    out: list[str] = []
    for ch in str(text):
        decomposed = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposed
                       if not unicodedata.combining(c)).lower()
        if len(base) != 1:
            # e.g. 'İ'.lower() -> two chars; keep one char to hold the line
            lowered = ch.lower()
            base = lowered if len(lowered) == 1 else ch
        out.append(base)
    return "".join(out)


# --- STAGE 1: structural anchors -------------------------------------------
# Anchors are matched on the deaccented, lowercased copy (OCR variants such
# as "d e c i d e" and "h o t a r ..." are separate literals).
STRONG_ANCHORS = ("d e c i d e", "decide", "hotaraste", "h o t a r")
WEAK_ANCHORS = ("temeiul", "inadmisibil", "retragere", "anuleaza",
                "inceteaza", "ridica exceptia")

_ANCHOR_RX: dict[str, re.Pattern[str]] = {}


def _anchor_rx(kind: str) -> re.Pattern[str]:
    if kind not in _ANCHOR_RX:
        anchors = STRONG_ANCHORS if kind == "strong" else WEAK_ANCHORS
        alts = sorted(anchors, key=len, reverse=True)
        _ANCHOR_RX[kind] = re.compile("|".join(re.escape(a) for a in alts))
    return _ANCHOR_RX[kind]


# --- STAGE 2: FULL resolutory formulations (on deaccented text) -------------
# Tight by design: body claims ("contestatorul solicită admiterea
# contestației"), subjunctive wishes ("să se admită" -> "sa se admita") and
# past-tense citations ("a fost admisă contestația") do NOT match.
# ``contestati*`` (contestația / contestației / contestații) deliberately
# excludes ``contestator*`` - "cererea contestatorului se respinge" is not a
# rejection of the complaint.
RE_F_PARTIAL = re.compile(
    r"\bse admite par[t]?ial"
    r"|\badmite par[t]?ial contestati\w*"
    r"|\bcontestati\w*[^.;\n]{0,60}se admite par[t]?ial"
    r"|\badm\w*[^.;\n]{0,60}in parte\b[^.;\n]{0,40}contestati\w*"
)
RE_F_ADMIT = re.compile(
    r"\bse admite contestati\w*"
    r"|\badmite contestati\w*"
    r"|\bcontestati\w*[^.;\n]{0,60}se admite\b"
)
RE_F_REJECT = re.compile(
    r"\bse respinge contestati\w*"
    r"|\brespinge contestati\w*"
    r"|\bcontestati\w*[^.;\n]{0,60}se respinge\b"
)
RE_F_INADMISSIBLE = re.compile(
    r"\bdeclar\w*[^.;\n]{0,60}contestati\w*[^.;\n]{0,40}inadmisibil\w*"
    r"|\bcontestati\w*[^.;\n]{0,60}declar\w*[^.;\n]{0,40}inadmisibil\w*"
    r"|\bdeclar\w*[^.;\n]{0,40}inadmisibil\w*[^.;\n]{0,40}contestati\w*"
    r"|\bse ridica excepti\w+ de inadmisibilitate"
    r"|\bridica excepti\w+ de inadmisibilitate"
)
RE_F_WITHDRAWN = re.compile(
    r"\bse ia act de retrager\w*[^.;\n]{0,50}contestati\w*"
    r"|\bretrager\w*[^.;\n]{0,50}contestati\w*"
    r"|\bretrag\w*[^.;\n]{0,50}contestati\w*"
    r"|\bcontestati\w*[^.;\n]{0,50}retr(?:as|ag)\w*"
    r"|\brenuntarea la contestati\w*"
    r"|\brenunt\w*[^.;\n]{0,40}contestati\w*"
)
RE_F_TERMINATED = re.compile(
    r"\bse constata incetar\w*[^.;\n]{0,60}contestati\w*"
    r"|\binceteaz\w*[^.;\n]{0,60}solutionar\w*[^.;\n]{0,60}contestati\w*"
    r"|\binceteaza solutionarea contestatiei"
    r"|\bdispare obiectul contestatiei"
)

# complaint/decision number inside an item ("nr. 02/739/19") - used to tell
# "admission + rejection of DIFFERENT complaints" (-> unknown) apart from the
# usual single-complaint "se admite parțial ... în rest se respinge"
RE_COMPLAINT_ID = re.compile(r"\bnr\.?\s*([0-9][0-9/]*)")

FORMULATION_RULES = (
    ("partially_admitted", RE_F_PARTIAL),
    ("admitted", RE_F_ADMIT),
    ("rejected", RE_F_REJECT),
    ("inadmissible", RE_F_INADMISSIBLE),
    ("withdrawn", RE_F_WITHDRAWN),
    ("terminated", RE_F_TERMINATED),
)

# sentences that restate ANOTHER decision (citation) - never an own outcome
RE_CITATION = re.compile(
    r"conform decizi|potrivit decizi|in conformitate cu decizia"
    r"|\bprin decizia nr|dupa decizia|vezi decizia|ca rezultat al deciziei"
    r"|\ba fost admis|\ba fost respins"
)
RE_NEG_ADMIT = re.compile(r"nu (?:se |a fost )?adm\w+|nu adm\w+")


def _context_window(flat: str, pos: int, lo: int) -> str:
    """Line window around ``pos`` (bounded), on the deaccented copy."""
    left = flat.rfind("\n", 0, pos)
    if left < lo:
        left = lo
    right = flat.find("\n", pos)
    if right < 0:
        right = len(flat)
    left = max(left, pos - 400)
    right = min(right, pos + 300)
    return flat[left:right]


def _findings(flat: str, lo: int, hi: int) -> list[tuple[str, int]]:
    """``(outcome, absolute_offset)`` of FULL formulations in ``[lo, hi)``.

    Citation sentences and negated admissions are dropped; a partial
    admission suppresses a plain admission match in the same clause (both
    rules match "se admite parțial contestația").
    """
    sub = flat[lo:hi]
    raw: list[tuple[str, int]] = []
    for outcome, rx in FORMULATION_RULES:
        for m in rx.finditer(sub):
            pos = lo + m.start()
            window = _context_window(flat, pos, lo)
            if RE_CITATION.search(window):
                continue
            if outcome == "admitted" and RE_NEG_ADMIT.search(window):
                continue
            raw.append((outcome, pos))
    kept: list[tuple[str, int]] = []
    for outcome, pos in raw:
        if outcome == "admitted" and any(
                o == "partially_admitted" and abs(p - pos) < 80
                for o, p in raw):
            continue
        kept.append((outcome, pos))
    kept.sort(key=lambda t: t[1])
    return kept


def locate_resolution(flat: str) -> tuple[int | None, int, str, str]:
    """STAGE 1: find the resolutory part on the deaccented document.

    Returns ``(lo, anchor_len, kind, fail_reason)``. Candidates are examined
    from the END; STRONG structural anchors are evaluated before WEAK ones;
    a candidate is accepted only when a full resolutory formulation follows
    it (within ``RESOLUTION_MAX_CHARS``) - so the last anchor in the
    document is never accepted blindly, and a weak anchor (``temeiul``,
    ``inadmisibil``, ``retragere``, ``anulează``) with only motivational or
    citation text after it cannot open the section. ``lo`` is ``None`` when
    no reliable resolutory part exists -> the caller must return ``unknown``.
    """
    hits = {kind: list(_anchor_rx(kind).finditer(flat))
            for kind in ("strong", "weak")}
    for kind in ("strong", "weak"):
        for m in reversed(hits[kind]):
            lo = m.start()
            hi = min(len(flat), lo + RESOLUTION_MAX_CHARS)
            if _findings(flat, lo, hi):
                return lo, len(m.group(0)), kind, ""
    total = len(hits["strong"]) + len(hits["weak"])
    if total == 0:
        return None, 0, "", ("no structural anchor in the document "
                             "(not a decision text or unreadable)")
    return None, 0, "", (f"{total} anchor candidate(s) found but no full "
                         "resolutory formulation follows them (cited/"
                         "motivational text only, or unreadable resolutory "
                         "part)")


def _item_end(flat: str, pos: int) -> int:
    """End of the dispositive item holding ``pos`` (``;`` / next item)."""
    candidates = []
    semi = flat.find(";", pos)
    if semi >= 0:
        candidates.append(semi)
    m_item = RE_ITEM_START.search(flat, pos)
    if m_item:
        candidates.append(m_item.start())
    end = min(candidates) if candidates else len(flat)
    if end - pos > 400:
        end = pos + 400
    return end


def classify_findings(findings: list[tuple[str, int]], flat: str
                      ) -> tuple[str, str, int]:
    """STAGE 2: aggregate formulation findings into one outcome.

    Returns ``(outcome, reason, evidence_offset)``. Conservative: anything
    that is not a single unambiguous outcome (or an explicit partial
    admission with the usual "in rest" rejection of the SAME complaint) is
    ``unknown`` - the classifier never forces a choice. Complaint numbers
    (``nr. 02/739/19``) distinguish "partial admission + rejection of the
    same complaint" (``partially_admitted``) from "decision A admitted one
    complaint, decision B rejected another" (``unknown``).
    """
    if not findings:
        return ("unknown",
                "no full resolutory formulation in the located part", -1)
    outcomes = {o for o, _ in findings}

    def first_of(name: str) -> int:
        return next(p for o, p in findings if o == name)

    def id_of(pos: int) -> str:
        m = RE_COMPLAINT_ID.search(flat[pos:_item_end(flat, pos)])
        return m.group(1) if m else ""

    if outcomes == {"admitted", "rejected"}:
        return ("unknown",
                "conflicting resolutory formulations (admission + rejection) "
                "without an explicit partial marker - possibly different "
                "complaints/claims", findings[0][1])
    if "partially_admitted" in outcomes and outcomes <= {
            "partially_admitted", "rejected"}:
        pos = first_of("partially_admitted")
        pid = id_of(pos)
        for other, opos in findings:
            if other != "rejected":
                continue
            oid = id_of(opos)
            if pid and oid and pid != oid:
                return ("unknown",
                        "different complaints in the resolutory part: "
                        f"partial admission nr. {pid} vs rejection nr. {oid}",
                        pos)
        return ("partially_admitted",
                "explicit partial admission in the resolutory part", pos)
    if len(outcomes) == 1:
        only = next(iter(outcomes))
        return only, f"single resolutory outcome: {only}", findings[0][1]
    return ("unknown",
            "multiple different outcomes for different claims/complaints: "
            + ", ".join(sorted(outcomes)), findings[0][1])


RE_ITEM_START = re.compile(r"\n\s*\d{1,2}\s*[.)]")


def _quote_at(text: str, pos: int) -> str:
    """Evidence quote: ORIGINAL text around ``pos`` (offsets are valid on it).

    Left boundary: the previous line start or item separator (``;``). Right
    boundary: the item separator or the start of the NEXT numbered item -
    a bare newline is NOT a boundary, because resolutory items are wrapped
    across lines. Only newlines are folded to spaces so the CSV stays one
    line - wording is untouched and accents are preserved (the deaccented
    copy is never used as evidence).
    """
    if pos >= len(text):
        pos = max(0, len(text) - 1)
    left = max(text.rfind("\n", 0, pos), text.rfind(";", 0, pos))
    if left < 0:
        left = 0
    rights = []
    semi = text.find(";", pos)
    if semi >= 0:
        rights.append(semi + 1)
    m_item = RE_ITEM_START.search(text, pos)
    if m_item:
        rights.append(m_item.start())
    right = min(rights) if rights else min(len(text), pos + 500)
    if right - left > 1200:
        left, right = max(0, pos - 100), min(len(text), pos + 400)
    quote = re.sub(r"[ \t]*\n[ \t]*", " ", text[left:right])
    quote = quote.strip()
    if len(quote) > QUOTE_MAX_CHARS:
        cut = quote[:QUOTE_MAX_CHARS]
        quote = cut[: cut.rfind(" ")] + " ..."
    return quote


def extract_outcome(pages: list[str], *, ocr_pages: dict[int, str] | None = None
                    ) -> dict:
    """Two-stage classification of a document from its per-page texts.

    ``ocr_pages`` maps 1-based page numbers to OCR text and is appended after
    the native text of the same page (only ever filled for pages whose text
    layer was missing).
    """
    ocr_pages = ocr_pages or {}
    merged: list[tuple[int, str]] = []
    for idx, native in enumerate(pages, start=1):
        text = native or ""
        if idx in ocr_pages:
            text = (text + "\n" + ocr_pages[idx]).strip()
        if text:
            merged.append((idx, text))
    if not merged:
        return {"outcome": "unknown", "quote": "", "page_number": "",
                "extraction_method": "none", "confidence": "none",
                "resolution_anchor": "", "unknown_reason":
                "no extractable text (missing or unusable document)",
                "error": ""}

    full = "\n".join(t for _, t in merged)
    flat = deaccent(full)
    used_ocr = any(idx in ocr_pages for idx, _ in merged)

    # ---- STAGE 1: locate the resolutory part ----
    lo, anchor_len, kind, fail = locate_resolution(flat)
    if lo is None:
        method = ("ocr_" if used_ocr else "") + "no_resolutory_part"
        return {"outcome": "unknown", "quote": "", "page_number": "",
                "extraction_method": method, "confidence": "none",
                "resolution_anchor": "", "unknown_reason": fail, "error": ""}

    # ---- STAGE 2: classify by full formulations inside the part ----
    hi = min(len(full), lo + RESOLUTION_MAX_CHARS)
    findings = _findings(flat, lo, hi)
    outcome, reason, ev_pos = classify_findings(findings, flat)

    anchor_display = " ".join(full[lo:lo + anchor_len].split())
    quote = _quote_at(full, ev_pos) if ev_pos >= 0 else ""

    # page holding the decisive formulation
    page_no = ""
    seen = 0
    for idx, text in merged:
        if seen + len(text) >= ev_pos:
            page_no = str(idx)
            break
        seen += len(text) + 1
    if not page_no:
        page_no = str(merged[-1][0])

    method = ("ocr_" if used_ocr else "") + f"resolutory_{kind}_anchor"
    if kind == "strong":
        confidence = "medium" if used_ocr else "high"
    else:
        confidence = "low" if used_ocr else "medium"
    if outcome == "unknown":
        confidence = "none"

    return {"outcome": outcome, "quote": quote, "page_number": page_no,
            "extraction_method": method, "confidence": confidence,
            "resolution_anchor": anchor_display,
            "unknown_reason": "" if outcome != "unknown" else reason,
            "error": ""}


# --- document loading -------------------------------------------------------
def load_inventory(path: Path = INV_CSV) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing {path.relative_to(ROOT)} - run scripts/42")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def sandbox_dir() -> Path | None:
    if not INV_JSON.exists():
        return None
    meta = json.loads(INV_JSON.read_text(encoding="utf-8"))
    raw = meta.get("sandbox_dir") or ""
    path = Path(raw)
    return path if path.is_dir() else None


def read_pdf_pages(path: Path) -> tuple[list[str], str]:
    """Per-page native text of a PDF; returns ``(pages, error)``."""
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
    except Exception as exc:                           # noqa: BLE001
        return [], f"{type(exc).__name__} on open"
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:                              # noqa: BLE001
            pages.append("")
    return pages, ""


def ocr_page(path: Path, page_index: int, max_pages: int) -> str:
    """OCR one page (1-based) by extracting its embedded images.

    Only ever called for pages whose text layer is missing. Tesseract is
    invoked on a temp file outside the repository; nothing is executed from
    the document.
    """
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
        page = reader.pages[page_index - 1]
        images = list(page.images)
    except Exception:                                  # noqa: BLE001
        return ""
    chunks = []
    for image in images[:3]:
        try:
            data = image.data
        except Exception:                              # noqa: BLE001
            continue
        suffix = Path(image.name or "img.jpg").suffix or ".jpg"
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix,
                                             delete=False) as fh:
                fh.write(data)
                tmp = fh.name
            run = subprocess.run(
                ["tesseract", tmp, "stdout", "-l", "eng", "--psm", "3"],
                capture_output=True, timeout=90)
            chunks.append(run.stdout.decode("utf-8", "ignore"))
        except (subprocess.TimeoutExpired, OSError):
            continue
        finally:
            if tmp:
                Path(tmp).unlink(missing_ok=True)
    return "\n".join(chunks)


def process_document(row: dict, sandbox: Path, ocr_max_pages: int) -> dict:
    """Full extraction pipeline for one inventory row."""
    import hashlib
    digest = hashlib.sha1(row["url"].encode("utf-8")).hexdigest()[:16]
    pdf = sandbox / f"{digest}.pdf"
    out = {k: row.get(k, "") for k in
           ("ocid", "url", "title", "year", "decision_numbers",
            "decision_date")}
    out.update({"outcome": "unknown", "quote": "", "page_number": "",
                "extraction_method": "none", "confidence": "none",
                "document_present": "0", "text_layer": "",
                "needs_ocr": row.get("needs_ocr", ""), "resolution_anchor": "",
                "unknown_reason": "", "error": ""})
    if row.get("http_status") != "200" or row.get("format") != "pdf":
        out["error"] = "document not fetched or not a PDF"
        return out
    if not pdf.exists():
        out["error"] = "document file absent from sandbox"
        return out
    out["document_present"] = "1"

    pages, err = read_pdf_pages(pdf)
    if err:
        out["error"] = err
        return out
    letters = sum(1 for t in pages for c in t if c.isalpha())
    usable = letters >= MIN_TEXT_CHARS
    out["text_layer"] = "1" if usable else "0"

    ocr_pages: dict[int, str] = {}
    if not usable:
        # OCR from the END backwards, stop once a classifiable anchor shows
        last = len(pages)
        for idx in range(last, max(0, last - ocr_max_pages), -1):
            text = ocr_page(pdf, idx, ocr_max_pages)
            if text:
                ocr_pages[idx] = text
            fj = deaccent("\n".join(ocr_pages.values()))
            if (_anchor_rx("strong").search(fj)
                    and _findings(fj, 0, len(fj))):
                break
        if not ocr_pages:
            out["error"] = "no text layer and OCR produced nothing"
            # still fall through: extract_outcome handles empty text

    result = extract_outcome(pages, ocr_pages=ocr_pages)
    out.update(result)
    return out


def _unknown_reason(row: dict) -> str:
    return (row.get("unknown_reason") or row.get("error")
            or "not classified")


def build_summary(rows: list[dict], elapsed: float) -> dict:
    probed = [r for r in rows if r.get("document_present") == "1"]
    native = [r for r in probed if r.get("text_layer") == "1"]
    scanned = [r for r in probed if r.get("text_layer") == "0"]
    outcomes = Counter(r["outcome"] for r in rows)
    by_method = Counter(r["extraction_method"] for r in rows)
    by_conf = Counter(r["confidence"] for r in rows)
    reasons = Counter(_unknown_reason(r) for r in rows
                      if r["outcome"] == "unknown")

    def block(subset: list[dict]) -> dict:
        c = Counter(r["outcome"] for r in subset)
        return {"n": len(subset),
                "outcomes": {k: c.get(k, 0) for k in OUTCOMES},
                "unknown_share": round(c.get("unknown", 0) / len(subset), 4)
                if subset else None}

    return {
        "task": "MTA-0018",
        "part": "3 - outcome extraction",
        "generated": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "policy": {
            "stage1": "locate the resolutory part: STRONG structural anchors "
                      "(HOTĂRĂȘTE/DECIDE/'d e c i d e') first, weak anchors "
                      "(temeiul/inadmisibil/retragere/anulează) auxiliary "
                      "only; candidates evaluated from the end by type and "
                      "context, never the last anchor blindly",
            "stage2": "classify by FULL legal formulations inside the located "
                      "part only; citations of other decisions and "
                      "applicant claims ignored",
            "no_resolution_rule": "no reliable resolutory part -> unknown",
            "never_single_word": True,
            "contradiction_rule": "admite + respinge contestația without an "
                                  "explicit partial marker -> unknown",
            "multi_claim_rule": "different outcomes for different "
                                "complaints/claims -> unknown",
            "unknown_is_negative_label": False,
            "quote_source": "original text; deaccent() is length-preserving "
                            "so offsets remain valid",
            "ocr": "only when the text layer is missing/unusable; last pages "
                   "first; bounded by --ocr-max-pages",
            "outcomes": list(OUTCOMES),
        },
        "documents": {
            "rows": len(rows),
            "present": len(probed),
            "absent": len(rows) - len(probed),
            "with_text_layer": len(native),
            "scanned": len(scanned),
        },
        "outcomes": {k: outcomes.get(k, 0) for k in OUTCOMES},
        "extraction_methods": dict(by_method.most_common()),
        "confidence": dict(by_conf.most_common()),
        "unknown_reasons": dict(reasons.most_common()),
        "all_rows": block(rows),
        "text_layer_rows": block(native),
        "scanned_rows": block(scanned),
        "disclaimer_ru": DISCLAIMER_RU,
        "disclaimer_en": DISCLAIMER_EN,
        "seconds": round(elapsed, 1),
    }


def write_report(summary: dict) -> None:
    d = summary["documents"]
    o = summary["outcomes"]
    total = d["rows"] or 1
    lines = [
        "# Отчёт об извлечении исходов решений ANSC (MTA-0018, шаг 3)",
        "",
        f"Сгенерировано: {summary['generated']}. Только измерение; "
        "production v0 не меняется; `data/raw/**` не трогается.",
        "",
        "## Метод (двухэтапный)",
        "",
        "- **этап 1 — локация резолютивной части**: сначала сильные "
        "структурные якоря (`HOTĂRĂȘTE`, `DECIDE`, OCR-вариант `d e c i d e`), "
        "затем только слабые (`temeiul`, `inadmisibil`, `retragere`, "
        "`anulează`) как вспомогательные; кандидаты проверяются с конца "
        "документа по типу и контексту — последний якорь не принимается "
        "вслепую; слабый якорь открывает часть только если за ним следует "
        "полная формулировка;",
        "- **этап 2 — классификация по полной юридической формулировке** "
        "внутри найденной части (`se admite parțial contestația`, "
        "`se respinge contestația`, `declară contestația inadmisibilă`, "
        "`retragerea contestației`, …); цитаты чужих решений и требования "
        "заявителя в мотивировочной части игнорируются;",
        "- без достоверной резолютивной части — `unknown`; разные исходы по "
        "разным жалобам/требованиям без явного `parțial` — `unknown`; "
        "противоречие (`admite` + `respinge contestația` без `parțial`) — "
        "`unknown`; решение никогда не классифицируется по одному слову;",
        "- OCR — только при отсутствии/непригодности текстового слоя, со "
        "последних страниц, с ограничением числа страниц;",
        "- цитата-доказательство берётся из ОРИГИНАЛЬНОГО текста "
        "(нормализованная копия не используется как улика), для каждой "
        "записи: исход, точная цитата, страница, метод, уверенность, "
        "ссылка на первоисточник.",
        "",
        "## Фактические числа",
        "",
        "| Показатель | Значение |",
        "|---|---:|",
        f"| Строк инвентаризации | {d['rows']} |",
        f"| Документ присутствует в песочнице | {d['present']} |",
        f"| Документ отсутствует / не PDF | {d['absent']} |",
        f"| С текстовым слоем | {d['with_text_layer']} |",
        f"| Сканов (OCR) | {d['scanned']} |",
        "",
        "| Исход | Всего | Доля | С текстовым слоем | Сканы |",
        "|---|---:|---:|---:|---:|",
    ]
    tl = summary["text_layer_rows"]["outcomes"]
    sc = summary["scanned_rows"]["outcomes"]
    for key in OUTCOMES:
        lines.append(f"| `{key}` | {o[key]} | {o[key] / total:.1%} | "
                     f"{tl.get(key, 0)} | {sc.get(key, 0)} |")
    lines += [
        "",
        "Методы извлечения: "
        + ", ".join(f"`{k}` — {v}" for k, v in
                    summary["extraction_methods"].items())
        + ".",
        "",
        "Уверенность: "
        + ", ".join(f"`{k}` — {v}" for k, v in
                    summary["confidence"].items())
        + ".",
        "",
        "## Причины `unknown`",
        "",
        "| Причина | Записей |",
        "|---|---:|",
    ]
    for reason, n in summary["unknown_reasons"].items():
        lines.append(f"| {reason} | {n} |")
    lines += [
        "",
        "## Ограничения",
        "",
        "- `unknown` означает «исход не установлен надёжно» и НИКОГДА не "
        "является отрицательной меткой (жалоба не «отклонена»); это "
        "правило закреплено тестом;",
        "- OCR использует модель `eng` (румынские диакритики могут "
        "искажаться) — записи с методом `ocr_*` имеют пониженную "
        "уверенность;",
        "- извлечение — техническая операция над документом; корректность "
        "классификации подтверждается только ручной проверкой "
        "(шаг 4), метрики качества (шаг 5) до неё не считаются;",
        "- возможные ошибки сопоставления документа с процедурой и "
        "апелляционное смещение выборки не устраняются извлечением;",
        "- исход решения по жалобе — результат административного спора, а "
        "не доказательство нарушения; решение может быть изменено судом.",
        "",
        f"> {DISCLAIMER_EN}",
        "",
        f"> {DISCLAIMER_RU}",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ocr-max-pages", type=int,
                        default=OCR_MAX_PAGES_DEFAULT)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    t0 = time.time()

    sandbox = sandbox_dir()
    if sandbox is None:
        print("sandbox directory unknown/missing: run scripts/42 with "
              "--allow-network first", file=sys.stderr)
        return 4

    rows_in = load_inventory()
    if args.limit:
        rows_in = rows_in[: args.limit]

    results: list[dict] = []
    for i, row in enumerate(rows_in):
        results.append(process_document(row, sandbox, args.ocr_max_pages))
        if not args.quiet and (i + 1) % 200 == 0:
            print(f"  processed {i + 1}/{len(rows_in)}", flush=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    summary = build_summary(results, time.time() - t0)
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    write_report(summary)
    print(json.dumps({k: summary[k] for k in
                      ("documents", "outcomes", "extraction_methods",
                       "confidence", "unknown_reasons", "seconds")},
                     ensure_ascii=False, indent=1))
    def _show(path: Path) -> str:
        try:
            return str(path.relative_to(ROOT))
        except ValueError:
            return str(path)

    print(f"written {_show(OUT_CSV)}, {_show(OUT_JSON)}, {_show(OUT_MD)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
