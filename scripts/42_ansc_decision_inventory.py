#!/usr/bin/env python3
"""ANSC decision-document inventory (MTA-0018, steps 1-2).

MEASUREMENT ONLY - no model training, production stays v0, ``data/raw/**``
is read-only and nothing under it is written.

Audit posture (step 1): the script REUSES the existing MTA-0012 artefacts and
code instead of duplicating them -

* the candidate universe is ``results/tables/ansc_candidates.csv`` produced by
  ``scripts/29`` (strong ANSC candidates: ``documentType == complaints`` plus
  the author's keyword list);
* the complaint-procedure list is RECOUNTED from the raw OCDS through
  ``scripts/31.build_contested_label`` (the same code path that produced the
  MTA-0013 label), so the headline number is measured, not copied;
* PDF parsing / identifier regexes come from ``scripts/30``.

Inventory (step 2): every strong candidate URL is probed ONCE and recorded per
``(ocid, url)`` pair - availability, content type, format, text layer / OCR
need, decision number, decision date, and whether the document itself names
the procedure's tender id (an unambiguous document<->procedure link signal).

Network posture: the script refuses to run without the explicit
``--allow-network`` flag. Requests are sequential with at least
``--min-interval`` seconds between them (the storage answers 429 Too Many
Requests below ~1 s), a User-Agent that states the academic purpose,
timeouts, bounded retries with backoff on 429 (honouring ``Retry-After``),
an error journal, and an immediate stop on HTTP 403 or on a redirect leaving
``storage.mtender.gov.md``. No proxy, no rotation, no CAPTCHA bypass.

Downloaded files go to a sandbox OUTSIDE the repository (the script refuses a
``--sandbox`` inside the git worktree); the repository artefacts store only
parsed metadata, never document texts.

Outputs:
  results/tables/ansc_decision_inventory.csv     - one row per (ocid, url)
  results/methodology/ansc_decision_inventory.json - summary counters
  results/logs/ansc_fetch_errors.csv             - journal of failed requests
  reports/ansc_decision_inventory.md             - the step-2 report

Usage:
    .venv/bin/python scripts/42_ansc_decision_inventory.py [--allow-network]
        [--limit N] [--resume] [--min-interval 1.0] [--sandbox DIR] [--quiet]

Exit codes: 0 = ok, 2 = missing --allow-network (or sandbox inside repo),
3 = stopped by the server (403 / redirect off-host / persistent 429).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RAW_DIR = ROOT / "data" / "raw" / "ocds_packages"
CANDIDATES = ROOT / "results" / "tables" / "ansc_candidates.csv"
OUT_CSV = ROOT / "results" / "tables" / "ansc_decision_inventory.csv"
OUT_JSON = ROOT / "results" / "methodology" / "ansc_decision_inventory.json"
OUT_MD = ROOT / "reports" / "ansc_decision_inventory.md"
ERR_LOG = ROOT / "results" / "logs" / "ansc_fetch_errors.csv"

STORAGE_HOST = "storage.mtender.gov.md"
MIN_INTERVAL_DEFAULT = 1.0      # measured: 0.5 s -> 429, 1.0 s -> 20/20 OK
TIMEOUT = 30
MAX_RETRIES = 3                 # 429 only; 403 stops the whole run
MAX_BYTES = 60_000_000          # hard cap for one document
MIN_TEXT_CHARS = 50             # same threshold as scripts/30
RETRY_STATUS = (429, 500, 502, 503, 504)
STOP_STATUS = (403,)

CSV_FIELDS = [
    "ocid", "year", "level", "documentType", "title", "url", "keywords",
    "n_ocids_for_url", "link_ambiguous", "http_status", "content_type",
    "format", "bytes", "pages", "chars", "letters", "needs_ocr",
    "decision_numbers", "decision_date", "procurement_ids",
    "id_confirmed", "error", "fetched_at",
]

DISCLAIMER_RU = ("Индикатор потенциального риска, а не доказательство "
                 "коррупции/нарушения. Требуется проверка компетентным "
                 "органом.")
DISCLAIMER_EN = ("An upheld ANSC complaint indicates an administrative "
                 "procurement dispute outcome and does not constitute proof "
                 "of corruption.")


def _load_script(name: str):
    """Import a sibling script as a module (same trick as scripts/31)."""
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S30 = _load_script("30_ansc_sample_parse.py")   # USER_AGENT, extract_text, ...
S31 = _load_script("31_ansc_external_check.py")  # build_contested_label

RE_TENDER_ID = re.compile(r"\bMD-\d{9,16}\b", re.IGNORECASE)
RE_DECISION_DATE_LINE = re.compile(r"\b\d{2}\.\d{2}\.(?:19|20)\d{2}\b")


def url_host(url: str) -> str:
    try:
        return (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def load_universe(path: Path = CANDIDATES) -> dict[str, dict]:
    """Strong candidates grouped by URL: ``{url: {rows: [...], ocids: [...]}}``.

    A document URL attached to two procedures appears once here and is
    expanded back into per-``(ocid, url)`` rows on write, so the availability
    probe stays single-pass while the report can still flag ambiguous links.
    """
    if not path.exists():
        raise SystemExit(
            f"missing {path.relative_to(ROOT)} - run scripts/29 first "
            "(it is the local-only ANSC candidate scan)")
    by_url: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("strong") != "1":
                continue
            url = row.get("url") or ""
            if not url:
                continue
            entry = by_url.setdefault(url, {"rows": [], "ocids": []})
            entry["rows"].append(row)
            if row["ocid"] not in entry["ocids"]:
                entry["ocids"].append(row["ocid"])
    return by_url


def find_decision_date(text: str) -> str:
    """Date on the same line as an ANSC decision number, else ``''``."""
    for line in text.splitlines():
        if S30.RE_DECISION.search(line):
            m = RE_DECISION_DATE_LINE.search(line)
            if m:
                return m.group(0)
    return ""


def tender_id_of(ocid: str) -> str:
    m = RE_TENDER_ID.search(ocid)
    return m.group(0).upper() if m else ""


def row_base(entry: dict, url: str) -> dict:
    """Representative metadata for a URL (first candidate row)."""
    rep = entry["rows"][0]
    ocids = entry["ocids"]
    return {
        "ocid": rep["ocid"],
        "year": rep.get("year", ""),
        "level": rep.get("level", ""),
        "documentType": rep.get("documentType", ""),
        "title": (rep.get("title") or "")[:200],
        "url": url,
        "keywords": rep.get("keywords", ""),
        "n_ocids_for_url": len(ocids),
        "link_ambiguous": int(len(ocids) > 1),
    }


def fetch(session, url: str, sandbox: Path, log_writer) -> dict:
    """GET one document once; return its parsed inventory fields.

    Retries ONLY on 429/5xx with backoff (honouring ``Retry-After``); any
    other terminal status is recorded as-is. Raises ``Blocked`` when the run
    must stop (403, redirect off-host, retries exhausted on 429).
    """
    result: dict = {"http_status": None, "error": "", "content_type": "",
                    "format": "", "bytes": 0, "pages": None, "chars": None,
                    "letters": None, "needs_ocr": None,
                    "decision_numbers": "", "decision_date": "",
                    "procurement_ids": "", "fetched_at": ""}
    response = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=TIMEOUT, stream=True)
        except Exception as exc:                       # noqa: BLE001
            result["error"] = type(exc).__name__
            log_writer(url, "", result["error"])
            if attempt >= MAX_RETRIES:
                return result
            time.sleep(5 * (attempt + 1))
            continue
        # a later attempt succeeded: drop the stale error of a failed try so
        # a fully fetched document never carries a transient failure in the
        # ``error`` field (regression-tested in tests/test_ansc_inventory.py)
        result["error"] = ""
        if response.status_code in RETRY_STATUS:
            wait = 0.0
            try:
                wait = float(response.headers.get("Retry-After") or 0)
            except ValueError:
                wait = 0.0
            wait = wait or (20.0 * (attempt + 1))
            response.close()
            log_writer(url, response.status_code, f"retry in {wait:.0f}s")
            time.sleep(wait)
            continue
        break
    else:
        raise Blocked(f"persistent rate limit on {url}")
    assert response is not None

    status = response.status_code
    result["http_status"] = status
    result["fetched_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    if status in STOP_STATUS:
        response.close()
        raise Blocked(f"http {status} on {url}")
    if url_host(response.url) != STORAGE_HOST:
        response.close()
        raise Blocked(f"redirect off {STORAGE_HOST}: {response.url}")
    if status != 200:
        result["error"] = f"http {status}"
        response.close()
        log_writer(url, status, "non-200")
        return result

    ctype = response.headers.get("Content-Type", "")
    result["content_type"] = ctype
    chunks: list[bytes] = []
    size = 0
    try:
        for chunk in response.iter_content(65536):
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_BYTES:
                break
    except Exception as exc:                           # noqa: BLE001
        result["error"] = type(exc).__name__
        response.close()
        log_writer(url, status, result["error"])
        return result
    finally:
        response.close()
    blob = b"".join(chunks)
    result["bytes"] = len(blob)

    if blob[:5] == b"%PDF-":
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        (sandbox / f"{digest}.pdf").write_bytes(blob)
        result["format"] = "pdf"
        try:
            extracted = S30.extract_text(blob)
        except Exception as exc:                       # noqa: BLE001
            result["error"] = f"{type(exc).__name__} on parse"
            result["needs_ocr"] = True
            log_writer(url, status, result["error"])
            return result
        text = extracted["text"]
        result.update({
            "pages": extracted["pages"], "chars": extracted["chars"],
            "letters": extracted["letters"],
            "needs_ocr": int(extracted["needs_ocr"]),
        })
        result["decision_numbers"] = ";".join(
            S30.parse_decision_number(text))
        result["decision_date"] = find_decision_date(text)
        result["procurement_ids"] = ";".join(
            S30.parse_procurement_ids(text))[:300]
        if extracted["needs_ocr"]:
            log_writer(url, status, "text layer missing -> OCR needed")
    else:
        ext = (ctype.split(";")[0].strip().split("/")[-1] or "unknown")
        result["format"] = ext
        result["error"] = "not a PDF"
        log_writer(url, status, f"non-pdf ({ctype or 'no content-type'})")
    return result


class Blocked(RuntimeError):
    """The server asked us to stop (403 / off-host redirect / 429 loop)."""


def make_log_writer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    fh = open(path, "a", newline="", encoding="utf-8")

    def write(url: str, status, reason: str) -> None:
        csv.writer(fh).writerow([
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            status if status is not None else "", reason, url])
        fh.flush()

    if new:
        csv.writer(fh).writerow(["ts", "http_status", "reason", "url"])
        fh.flush()
    return write


def read_previous(path: Path) -> tuple[list[dict], set[str]]:
    """Rows of an earlier run plus the URLs already probed terminally."""
    if not path.exists():
        return [], set()
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    done = set()
    for row in rows:
        status = row.get("http_status") or ""
        if not status:
            continue
        try:
            code = int(status)
        except ValueError:
            continue
        if code not in RETRY_STATUS:
            done.add(row["url"])
    return rows, done


def recount_complaint_procedures() -> dict:
    """Recompute the complaint-procedure list from the raw OCDS (scripts/31)."""
    procs, stats = S31.build_contested_label(RAW_DIR)
    return {"procedures_with_complaint_doctype": stats["procedures"],
            "documents_rows": stats["documents_rows"],
            "documents_unique": stats["documents_unique"],
            "documents_removed_duplicate": stats["documents_removed_duplicate"],
            "pn_ocid_aliases_added": stats["pn_ocid_aliases_added"],
            "expected_from_mta0012": stats["expected_from_mta0012"],
            "ocids": procs}


def build_summary(rows: list[dict], universe_n: int, procs: dict,
                  fetched_urls: int, stopped: str, sandbox: Path,
                  elapsed: float) -> dict:
    urls = {r["url"] for r in rows}
    ocids = {r["ocid"] for r in rows}
    ok = [r for r in rows if r["http_status"] == "200"]
    pdfs = [r for r in ok if r["format"] == "pdf"]
    text_layer = [r for r in pdfs if r["needs_ocr"] == "0"]
    scanned = [r for r in pdfs if r["needs_ocr"] == "1"]
    unavailable = [r for r in rows
                   if r["http_status"] and r["http_status"] != "200"]
    unfetched = [r for r in rows if not r["http_status"]]
    with_decision = [r for r in ok if r["decision_numbers"]]
    dec_by_num: dict[str, set] = defaultdict(set)
    for r in with_decision:
        for num in r["decision_numbers"].split(";"):
            if num:
                dec_by_num[num.upper()].add(r["url"])
    dup_decisions = {k: sorted(v) for k, v in dec_by_num.items()
                     if len(v) > 1}
    ambiguous = [r for r in rows if r["link_ambiguous"] == "1"]
    confirmed = [r for r in ok if r["id_confirmed"] == "1"]
    # headers arrived (200) but the body never downloaded: 0 bytes, no file
    body_failed = [r for r in ok
                   if r["error"] in ("ConnectionError", "ChunkedEncodingError",
                                     "ConnectTimeout", "ReadTimeout")
                   and str(r.get("bytes") or "0") == "0"]

    def share(part: int, whole: int) -> str:
        return f"{part} ({part / whole:.1%})" if whole else f"{part} (n/a)"

    return {
        "task": "MTA-0018",
        "part": "2 - ANSC decision document inventory",
        "generated": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "reused": {
            "candidates_csv": str(CANDIDATES.relative_to(ROOT)),
            "candidate_scan": "scripts/29 (MTA-0012 part A)",
            "pdf_parser": "scripts/30 (MTA-0012 part B)",
            "complaint_label_code": "scripts/31.build_contested_label "
                                    "(MTA-0013)",
        },
        "universe": {
            "strong_candidate_urls": universe_n,
            "rows_written": len(rows),
            "rows_probed_this_run": fetched_urls,
            "distinct_urls_in_rows": len(urls),
            "distinct_ocids_in_rows": len(ocids),
        },
        "complaints_procedures_recounted": {k: v for k, v in procs.items()
                                            if k != "ocids"},
        "availability": {
            "available_200": len(ok),
            "unavailable_non200": len(unavailable),
            "not_probed": len(unfetched),
            "body_download_failed_0_bytes": len(body_failed),
            "available_share_of_probed": round(
                len(ok) / max(1, len(ok) + len(unavailable)), 4),
        },
        "formats": dict(Counter(r["format"] or "unknown"
                                for r in ok).most_common()),
        "text_layer": {
            "pdf_documents": len(pdfs),
            "with_text_layer": len(text_layer),
            "scanned_need_ocr": len(scanned),
            "text_layer_share_of_pdfs": round(
                len(text_layer) / max(1, len(pdfs)), 4),
            "non_pdf_documents": len(ok) - len(pdfs),
        },
        "decisions": {
            "documents_with_decision_number": len(with_decision),
            "procedures_with_decision_number": len(
                {r["ocid"] for r in with_decision}),
            "distinct_decision_numbers": len(dec_by_num),
            "decision_numbers_shared_by_several_urls": len(dup_decisions),
            "shared_decision_numbers": dup_decisions,
        },
        "linkage": {
            "ambiguous_rows_url_on_several_ocids": len(ambiguous),
            "ambiguous_urls": sorted({r["url"] for r in ambiguous}),
            # procedure-level view (a procedure = ocid): unambiguous when NONE
            # of its documents' URLs is shared with another procedure
            "procedures_unambiguous_link": len(
                ocids - {r["ocid"] for r in ambiguous}),
            "procedures_ambiguous_link": len(
                {r["ocid"] for r in ambiguous}),
            "documents_naming_own_tender_id": len(confirmed),
            "confirmed_share_of_probed": round(
                len(confirmed) / max(1, len(ok)), 4),
        },
        "stopped_reason": stopped,
        "sandbox_dir": str(sandbox),
        "outputs": {
            "csv": str(OUT_CSV.relative_to(ROOT)),
            "json": str(OUT_JSON.relative_to(ROOT)),
            "error_log": str(ERR_LOG.relative_to(ROOT)),
            "report": str(OUT_MD.relative_to(ROOT)),
        },
        "network": {"min_interval_seconds": MIN_INTERVAL_DEFAULT,
                    "timeout_seconds": TIMEOUT,
                    "max_retries_on_429": MAX_RETRIES,
                    "stop_on": list(STOP_STATUS)},
        "disclaimer_ru": DISCLAIMER_RU,
        "disclaimer_en": DISCLAIMER_EN,
        "seconds": round(elapsed, 1),
    }


def write_report(summary: dict) -> None:
    a = summary["availability"]
    t = summary["text_layer"]
    d = summary["decisions"]
    l = summary["linkage"]
    procs = summary["complaints_procedures_recounted"]
    probed = a["available_200"] + a["unavailable_non200"]

    def pct(part: int, whole: int) -> str:
        return f"{part / whole:.1%}" if whole else "n/a"

    lines = [
        "# Отчёт по инвентаризации документов решений ANSC (MTA-0018, шаг 2)",
        "",
        f"Сгенерировано: {summary['generated']}. Режим: только измерение; "
        "production v0 не меняется; `data/raw/**` — только чтение.",
        "",
        "## 1. Аудит существующей инфраструктуры (шаг 1)",
        "",
        "- `scripts/29` (MTA-0012 A) — локальный скан документов OCDS без "
        "сети; его выход `results/tables/ansc_candidates.csv` использован "
        "как вселенная кандидатов (сильные кандидаты: "
        "`documentType = complaints` + словарь автора). Дублирование кода "
        "скана исключено.",
        "- `scripts/30` (MTA-0012 B) — скачивание образца и разбор PDF "
        "(pypdf, regex для номеров решений/процедур); из него переиспользуются "
        "`USER_AGENT`, `extract_text`, `parse_decision_number`, "
        "`parse_procurement_ids`. Внутри песочницы MTA-0012 файлы уже "
        "удалены (0 файлов), локально PDF решений ANSC в репозитории нет — "
        "поэтому инвентаризация качает документы заново.",
        "- `scripts/31` (MTA-0013) — метка «процедура обжалована» "
        "(`documentType = complaints`); его `build_contested_label` "
        "пересчитан здесь для фактического числа процедур с жалобами.",
        "- Ссылки на документы хранятся в OCDS `documents[].url` четырёх "
        "уровней (tender/award/contract/planning) и указывают на "
        "`storage.mtender.gov.md/get/…`; идентификатор процедуры — `ocid` "
        "(`ocds-…-MD-<tender id>[-PN-…])`.",
        "",
        "## 2. Фактические количества",
        "",
        "| Показатель | Значение | Доля |",
        "|---|---:|---:|",
        f"| Процедур с документами жалоб (пересчёт из raw OCDS) | "
        f"{procs['procedures_with_complaint_doctype']} | ожидание MTA-0012: "
        f"{procs['expected_from_mta0012']} |",
        f"| Документов жалоб (строк → уникальных после дедупликации) | "
        f"{procs['documents_rows']} → {procs['documents_unique']} | "
        f"снято дублей: {procs['documents_removed_duplicate']} |",
        f"| Сильных кандидатов-URL (вселенная инвентаризации) | "
        f"{summary['universe']['strong_candidate_urls']} | — |",
        f"| Строк инвентаризации (ocid × url) | "
        f"{summary['universe']['rows_written']} | — |",
        f"| Доступных документов (HTTP 200) | {a['available_200']} | "
        f"{pct(a['available_200'], probed)} от опрошенных |",
        f"| Недоступных (не-200) | {a['unavailable_non200']} | "
        f"{pct(a['unavailable_non200'], probed)} от опрошенных |",
        f"| в т.ч. тело не скачалось (HTTP 200, 0 байт, содержимого нет) | "
        f"{a['body_download_failed_0_bytes']} | "
        f"{pct(a['body_download_failed_0_bytes'], probed)} от опрошенных |",
        f"| Не опрошено (прогон остановлен) | {a['not_probed']} | "
        f"{pct(a['not_probed'], summary['universe']['rows_written'])} |",
        f"| PDF с текстовым слоем | {t['with_text_layer']} | "
        f"{pct(t['with_text_layer'], t['pdf_documents'])} от PDF |",
        f"| Сканов (нужен OCR) | {t['scanned_need_ocr']} | "
        f"{pct(t['scanned_need_ocr'], t['pdf_documents'])} от PDF |",
        f"| Не сохранено как PDF в песочницу (не-PDF форматы + сбой "
        f"скачивания) | {t['non_pdf_documents']} | "
        f"{pct(t['non_pdf_documents'], a['available_200'])} от доступных |",
        f"| Строк с неоднозначной привязкой (URL на нескольких ocid) | "
        f"{l['ambiguous_rows_url_on_several_ocids']} | "
        f"{pct(l['ambiguous_rows_url_on_several_ocids'], summary['universe']['rows_written'])} |",
        f"| Процедур, однозначно связанных со своими документами | "
        f"{l['procedures_unambiguous_link']} | "
        f"{pct(l['procedures_unambiguous_link'], summary['universe']['distinct_ocids_in_rows'])} от процедур в инвентаризации |",
        f"| Процедур, неоднозначно связанных (URL общий с другой процедурой) | "
        f"{l['procedures_ambiguous_link']} | "
        f"{pct(l['procedures_ambiguous_link'], summary['universe']['distinct_ocids_in_rows'])} от процедур в инвентаризации |",
        f"| Документов с номером решения ANSC в тексте | "
        f"{d['documents_with_decision_number']} | "
        f"{pct(d['documents_with_decision_number'], a['available_200'])} от доступных |",
        f"| Процедур с найденным номером решения | "
        f"{d['procedures_with_decision_number']} | "
        f"{pct(d['procedures_with_decision_number'], procs['procedures_with_complaint_doctype'])} от процедур с жалобами |",
        f"| Документов, называющих свой tender id (подтверждённая привязка) | "
        f"{l['documents_naming_own_tender_id']} | "
        f"{l['confirmed_share_of_probed']} от опрошенных |",
        f"| Дубликатов решений (один номер на нескольких URL) | "
        f"{d['decision_numbers_shared_by_several_urls']} | — |",
        "",
        "Форматы доступных документов: "
        + ", ".join(f"{k} — {v}" for k, v in summary["formats"].items())
        + ".",
        "",
        "Остановка прогона: "
        + (summary["stopped_reason"] or "нет (прогон завершён полностью)")
        + ".",
        "",
        "## 3. Ограничения",
        "",
        "- Инвентаризация фиксирует доступность и текстовый слой в момент "
        "прогона; документы могут быть изменены или удалены издателем.",
        "- Номер решения извлекается только когда он есть в текстовом слое "
        "или в названии; для сканов без OCR поле пустое (это не «решение "
        "отсутствует», а «не извлечено»).",
        "- Привязка «документ → процедура» достоверна только когда URL "
        "принадлежит одному ocid либо документ называет tender id процедуры; "
        "остальные случаи помечены `link_ambiguous` и не считаются "
        "подтверждёнными.",
        "- Наличие документа жалобы или решения ничего не доказывает о "
        "нарушении: это инвентаризация источников, а не оценка поведения "
        "сторон.",
        "",
        f"> {DISCLAIMER_EN}",
        "",
        f"> {DISCLAIMER_RU}",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-network", action="store_true",
                        help="explicit opt-in; without it the script exits 2")
    parser.add_argument("--limit", type=int, default=0,
                        help="probe at most the first N URLs this run")
    parser.add_argument("--resume", action="store_true",
                        help="skip URLs already probed in OUT_CSV")
    parser.add_argument("--min-interval", type=float,
                        default=MIN_INTERVAL_DEFAULT,
                        help="minimum seconds between requests "
                             "(storage throttles below ~1 s)")
    parser.add_argument("--sandbox", default="",
                        help="download dir OUTSIDE the repo "
                             "(default: $TMPDIR/mtender_ansc_decisions)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    t0 = time.time()

    universe = load_universe()
    if not args.allow_network:
        if OUT_CSV.exists():
            # offline regeneration of the report from an existing probe
            with open(OUT_CSV, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            procs = recount_complaint_procedures()
            summary = build_summary(
                rows, len(universe), procs, 0,
                "offline: report rebuilt from existing probe CSV",
                Path(args.sandbox or "/nonexistent"), time.time() - t0)
            write_report(summary)
            OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False,
                                            indent=2), encoding="utf-8")
            print(f"offline: rebuilt {OUT_MD.relative_to(ROOT)} from "
                  f"{len(rows)} rows")
            return 0
        print("refusing to touch the network: pass --allow-network (no "
              "existing probe CSV to rebuild from)", file=sys.stderr)
        return 2

    import requests

    sandbox = Path(args.sandbox) if args.sandbox else \
        Path(tempfile_dir()) / "mtender_ansc_decisions"
    try:
        sandbox.resolve().relative_to(ROOT.resolve())
        print(f"refusing: --sandbox {sandbox} is inside the repository; "
              "downloaded documents must stay outside it", file=sys.stderr)
        return 2
    except ValueError:
        pass
    sandbox.mkdir(parents=True, exist_ok=True)

    previous_rows: list[dict] = []
    done: set[str] = set()
    if args.resume:
        previous_rows, done = read_previous(OUT_CSV)
        if not args.quiet:
            print(f"resume: {len(done)} URLs already probed", flush=True)

    session = requests.Session()
    session.headers.update({"User-Agent": S30.USER_AGENT})
    log_writer = make_log_writer(ERR_LOG)

    procs = recount_complaint_procedures()
    if not args.quiet:
        print(f"complaint procedures recounted from raw OCDS: "
              f"{procs['procedures_with_complaint_doctype']} "
              f"(expected {procs['expected_from_mta0012']}); universe "
              f"{len(universe)} strong URLs", flush=True)

    results: dict[str, dict] = {}
    stopped = ""
    order = sorted(universe)
    if args.limit:
        order = order[: args.limit]
    targets = [u for u in order if u not in done] if args.resume else order
    try:
        for i, url in enumerate(targets):
            if i:
                time.sleep(max(0.0, args.min_interval))
            entry = universe[url]
            data = fetch(session, url, sandbox, log_writer)
            data.update(row_base(entry, url))
            results[url] = data
            if not args.quiet and (i + 1) % 100 == 0:
                print(f"  probed {i + 1}/{len(targets)} URLs", flush=True)
    except Blocked as exc:
        stopped = str(exc)
        if not args.quiet:
            print(f"STOPPED by server policy: {stopped}", file=sys.stderr)

    # rows: previous (for URLs not re-probed) + this run
    rows: list[dict] = []
    written: set[tuple[str, str]] = set()
    for row in previous_rows:
        key = (row["url"], row.get("ocid", ""))
        if row["url"] not in results and key not in written:
            rows.append(row)
            written.add(key)
    for url in sorted(results):
        data = results[url]
        for ocid in universe[url]["ocids"]:
            row = dict(data)
            row["ocid"] = ocid
            if len(universe[url]["ocids"]) > 1:
                row["link_ambiguous"] = "1"
            rows.append(row)

    # id_confirmed needs the per-ocid tender id
    for row in rows:
        # in-memory rows carry ints (http_status, bytes, needs_ocr ...) while
        # resumed rows are strings from CSV - normalise so the summary and the
        # written file agree (regression-tested in tests/test_ansc_inventory)
        for key, value in list(row.items()):
            if isinstance(value, bool):
                row[key] = "1" if value else "0"
            elif isinstance(value, (int, float)):
                row[key] = str(value)
        tid = tender_id_of(row.get("ocid", ""))
        ids = (row.get("procurement_ids") or "").upper()
        row["id_confirmed"] = "1" if tid and tid in ids else \
            ("0" if ids else "")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})

    summary = build_summary(rows, len(universe), procs,
                            len(results), stopped, sandbox,
                            time.time() - t0)
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    write_report(summary)
    print(json.dumps({k: summary[k] for k in (
        "universe", "availability", "text_layer", "decisions", "linkage",
        "stopped_reason", "seconds")}, ensure_ascii=False, indent=1))
    print(f"written {OUT_CSV.relative_to(ROOT)}, "
          f"{OUT_JSON.relative_to(ROOT)}, {OUT_MD.relative_to(ROOT)}")
    return 3 if stopped else 0


def tempfile_dir() -> str:
    import tempfile
    return tempfile.gettempdir()


if __name__ == "__main__":
    sys.exit(main())
