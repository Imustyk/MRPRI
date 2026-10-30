#!/usr/bin/env python3
"""Third external label, step 1: the open-source case registry — MATCH (MTA-0016/0017).

Reads the human-curated registry ``data/external/case_registry.csv`` (schema:
``docs/case_registry_schema.md``) and matches its records to the MTender
corpus:

* by **IDNO** first (``entity_id_mtender`` vs ``winner_identifier`` /
  ``buyer_identifier`` depending on ``entity_type``) - ``idno_exact``;
* then by **exact normalised name** (``src/mtender/names.py``) -
  ``name_exact``;
* substring hits are carried only as **candidates** (``name_fuzzy``) and are
  ALWAYS ``match_confidence = low`` - they are never promoted to high and
  never enter the check label;
* a human-verified ``manual`` match uses the declared ``procedure_ids`` and is
  accepted only when ``verified_by_human = true``.

MTA-0017 additions (episode-level linking):
``link_basis`` says WHAT the source named for the procedure-level link -
``procedure_id_in_source`` (the source cites the procedure: resolved against
``ocid``/``tender_id``/its numeric suffix -> ``ocid_exact``),
``contract_number`` (the source cites the contract: resolved against a
read-only scan of ``data/raw/ocds_packages`` when ``--raw-scan`` is given,
otherwise against the declared ``procedure_ids`` -> ``contract_number``) or
``buyer_period_only`` (only the subject and a period -> the entity ladder
restricted to the episode's period window, ``match_method`` stays the entity
ladder). The three dates are stored separately: ``procedure_date``
(when the procurement happened), ``source_publication_date`` (when the source
document was published) and ``first_publication_date`` (when the case became
public - the temporal guard of ``scripts/39``).

LABEL RULE (MTA-0017 item 3): label-grade requires
``link_basis in {procedure_id_in_source, contract_number}`` AND
``match_confidence in {high, medium}`` AND ``evidence_level in {A, B, C}``.
``buyer_period_only`` rows enter the registry but NEVER the label; rows with
an empty ``link_basis`` are reported but are not label-grade either.

Rules enforced here (see the schema doc): records without a source
(``source_url_1`` + ``source_type_1`` + ``source_date_1``) are rejected with a
reason; ``evidence_level = D`` is matched and reported but never label-grade;
the registry's own ``match_*`` columns, when filled, are CROSS-CHECKED against
the recomputation and every discrepancy is listed (nothing is silently
overwritten).

MEASUREMENT ONLY - production stays v0, nothing is retrained, the registry is
never filled automatically, and no fabricated case is ever added. **No network
request is made, with or without --allow-network** (the flag exists so a future
enrichment step has a place to be switched on explicitly; this version performs
none). ``--raw-scan`` only READS the local ``data/raw/ocds_packages`` copies.

Outputs:
    results/methodology/case_registry_match.json   (gitignored, like results/)
    reports/case_registry_match.md

Usage:
    .venv/bin/python scripts/38_case_registry_match.py \
        [--registry data/external/case_registry.csv] [--features ...] \
        [--raw-scan] [--allow-network] [--out-json ...] [--out-md ...]
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mtender.config import DATA_FEATURES, DATA_RAW, RESULTS  # noqa: E402
from src.mtender.names import match_level, normalise_name  # noqa: E402

REGISTRY_CSV = ROOT / "data" / "external" / "case_registry.csv"
OUT_JSON = RESULTS / "methodology" / "case_registry_match.json"
OUT_MD = ROOT / "reports" / "case_registry_match.md"
#: Read-only raw OCDS packages; the contract-number index is built from them.
RAW_PACKAGES = DATA_RAW / "ocds_packages"
CONTRACT_INDEX_JSON = RESULTS / "methodology" / "contract_index.json"

REQUIRED_COLUMNS = [
    "case_id", "title_short", "entity_type", "entity_id_mtender",
    "entity_name_as_in_source", "source_url_1", "source_type_1",
    "source_date_1", "source_url_2", "source_type_2", "source_date_2",
    "evidence_level", "risk_type", "period_from", "period_to",
    "first_publication_date", "procedure_date", "source_publication_date",
    "link_basis", "procedure_ref_in_source",
    "match_method", "match_confidence", "n_procedures_matched",
    "procedure_ids", "verified_by_human", "notes",
]
ENTITY_TYPES = ("buyer", "supplier")
EVIDENCE_LEVELS = ("A", "B", "C", "D")
RISK_TYPES = ("collusion", "price_inflation", "fake_competition", "splitting",
              "short_deadline", "other")
MATCH_METHODS = ("idno_exact", "name_exact", "name_fuzzy", "manual",
                 "ocid_exact", "contract_number")
MATCH_CONFIDENCES = ("high", "medium", "low")
#: MTA-0017: how the source linked the episode to a procedure.
LINK_BASES = ("procedure_id_in_source", "contract_number", "buyer_period_only")
#: ...and only these two bases may ever form the check label.
LABEL_LINK_BASIS = ("procedure_id_in_source", "contract_number")
#: Evidence levels that can form the check label; D never does.
LABEL_EVIDENCE = ("A", "B", "C")
#: Match confidences that enter the headline check; low (fuzzy) never does.
LABEL_CONFIDENCE = ("high", "medium")
#: Tolerance (days) around a single-day episode period for the
#: ``buyer_period_only`` window: ``published_date`` is the publication of the
#: procedure, ``procedure_date`` the procurement date named in the source.
PERIOD_TOLERANCE_DAYS = 30
#: Reasons an episode can fail to link (scripts/41 writes them to
#: ``data/external/case_unmatched.csv``).
UNMATCHED_REASONS = ("вне корпуса", "нет идентификатора", "неоднозначно")

_IDNO_RE = re.compile(r"^\d{6,13}$")

DISCLAIMER = ("Индикатор потенциального риска, а не доказательство "
              "коррупции/нарушения. Требуется проверка компетентным органом.")
LIMITATIONS = [
    "Метка реестра смещена к крупным и громким случаям; сравнение с "
    "базовым ранжированием «только размер» обязательно.",
    "Журналистские материалы (уровень C) — не доказательство нарушения.",
    "Результат показывает приоритизацию, а не наличие коррупции.",
    DISCLAIMER,
]


def normalize_idno(value: object) -> str | None:
    """Bare digits of a Moldovan IDNO, matching ``features.csv`` storage.

    ``"MD-IDNO-1006601001182"``, ``"1006601001182"`` and ``" 1006601001182 "``
    all fold to ``"1006601001182"``; anything without 6-13 digits is None, so
    a garbage cell can never match every row.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    text = text.replace("MD-IDNO-", "").replace(" ", "")
    return text if _IDNO_RE.match(text) else None


def _filled(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip() not in ("", "nan", "None", "<NA>")


def _clean(value: object) -> str:
    return str(value).strip() if _filled(value) else ""


def _parse_date(value: object) -> str | None:
    """``YYYY-MM-DD`` when the cell parses, else None."""
    if not _filled(value):
        return None
    parsed = pd.to_datetime(str(value).strip(), errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def validate_registry(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Validate rows against the schema; return (frame with flags, counters).

    Hard rejections (the row never reaches the matcher): missing source
    (``source_url_1``/``source_type_1``/``source_date_1``), missing
    ``first_publication_date`` (the temporal protection needs it), unknown
    ``entity_type``/``evidence_level``/``risk_type``/``link_basis``, missing
    both entity identifiers, duplicate ``case_id``.

    ``link_basis`` MAY be empty (hand-written MTA-0016-style rows) - such rows
    are matched by the entity ladder but are never label-grade (MTA-0017
    item 3) and are counted separately.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    rejected: list[dict] = []
    reasons_by_case: dict[str, list[str]] = {}
    seen_ids: set[str] = set()

    valid = pd.Series(True, index=df.index)
    for idx, row in df.iterrows():
        case_id = _clean(row.get("case_id")) or f"<row {idx}>"
        reasons: list[str] = []
        if not _clean(row.get("case_id")):
            reasons.append("пустой case_id")
        elif case_id in seen_ids:
            reasons.append("дублирующийся case_id")
        seen_ids.add(case_id)
        if not all(_filled(row.get(c)) for c in
                   ("source_url_1", "source_type_1", "source_date_1")):
            reasons.append("нет источника (source_url_1/source_type_1/"
                           "source_date_1)")
        if not _filled(row.get("first_publication_date")):
            reasons.append("нет first_publication_date")
        if _clean(row.get("entity_type")) not in ENTITY_TYPES:
            reasons.append("entity_type вне "
                           f"{ENTITY_TYPES}: {row.get('entity_type')!r}")
        if _clean(row.get("evidence_level")) not in EVIDENCE_LEVELS:
            reasons.append("evidence_level вне "
                           f"{EVIDENCE_LEVELS}: {row.get('evidence_level')!r}")
        if _clean(row.get("risk_type")) not in RISK_TYPES:
            reasons.append(f"risk_type вне {RISK_TYPES}: {row.get('risk_type')!r}")
        if _filled(row.get("link_basis")) \
                and _clean(row.get("link_basis")) not in LINK_BASES:
            reasons.append(f"link_basis вне {LINK_BASES}: "
                           f"{row.get('link_basis')!r}")
        if not (_filled(row.get("entity_id_mtender"))
                or _filled(row.get("entity_name_as_in_source"))):
            reasons.append("нет ни IDNO, ни названия")
        for col in ("source_date_1", "source_date_2", "period_from",
                    "period_to", "first_publication_date", "procedure_date",
                    "source_publication_date"):
            if _filled(row.get(col)) and _parse_date(row.get(col)) is None:
                reasons.append(f"{col} не парсится как дата: {row.get(col)!r}")
        pf, pt = _parse_date(row.get("period_from")), _parse_date(row.get("period_to"))
        if pf and pt and pf > pt:
            reasons.append("period_from позже period_to")
        if reasons:
            valid.loc[idx] = False
            rejected.append({"case_id": case_id, "reasons": reasons})
            reasons_by_case[case_id] = reasons

    by_evidence: dict[str, dict] = {}
    ev_col = (df["evidence_level"].astype("string").str.strip()
              if "evidence_level" in df.columns
              else pd.Series("", index=df.index, dtype="string"))
    for level in EVIDENCE_LEVELS:
        mask = ev_col == level
        by_evidence[level] = {
            "records": int(mask.sum()),
            "valid": int((valid & mask).sum()),
        }
    by_link: dict[str, int] = {}
    link_col = (df["link_basis"].astype("string").fillna("").str.strip()
                if "link_basis" in df.columns
                else pd.Series("", index=df.index, dtype="string"))
    for basis in (*LINK_BASES, ""):
        by_link[basis or "(не указан)"] = int(
            (valid & (link_col == basis)).sum())
    validation = {
        "columns_missing": missing,
        "n_rows": int(len(df)),
        "n_valid": int(valid.sum()),
        "n_rejected": int((~valid).sum()),
        "rejected": rejected,
        "by_evidence_level": by_evidence,
        "by_link_basis": by_link,
        "n_evidence_D_in_label": 0,
        "evidence_D_note": "уровень D сопоставляется, но в метку проверки "
                           "не входит (scripts/39)",
        "link_basis_note": "в метку входят только procedure_id_in_source и "
                           "contract_number; buyer_period_only и пустой "
                           "link_basis — никогда (MTA-0017, п. 3)",
    }
    out = df.copy()
    out["_valid"] = valid.to_numpy()
    out["_case_id"] = (out["case_id"].astype("string").fillna("<row>")
                       if "case_id" in out.columns
                       else pd.Series("<row>", index=out.index,
                                      dtype="string")).to_numpy()
    return out, validation


def _entity_columns(entity_type: str) -> tuple[str, str]:
    if entity_type == "supplier":
        return "winner_identifier", "winner_name"
    return "buyer_identifier", "buyer_name"


def load_corpus(features_csv: Path | str) -> pd.DataFrame:
    """The identity columns of the corpus, kept as strings (IDNO safety)."""
    cols = ["ocid", "tender_id", "buyer_identifier", "buyer_id", "buyer_name",
            "winner_identifier", "winner_id", "winner_name", "published_date"]
    have = pd.read_csv(features_csv, nrows=0).columns
    df = pd.read_csv(features_csv, usecols=[c for c in cols if c in have],
                     dtype="string", low_memory=False)
    df["ocid"] = df["ocid"].astype("string")
    for col in ("buyer_identifier", "winner_identifier"):
        if col in df.columns:
            df[col] = df[col].map(normalize_idno)
    return df


def period_window(row) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Published-date window of a ``buyer_period_only`` episode.

    ``period_from``/``period_to`` when both are given; a SINGLE day (or a
    single bound, or ``procedure_date`` alone) expands by
    ``+/- PERIOD_TOLERANCE_DAYS`` because ``published_date`` is the
    publication of the procedure while the source names the procurement
    date. Returns None when the episode carries no temporal anchor at all.
    """
    delta = pd.Timedelta(days=PERIOD_TOLERANCE_DAYS)
    pf = pd.to_datetime(_parse_date(row.get("period_from")), errors="coerce")
    pt = pd.to_datetime(_parse_date(row.get("period_to")), errors="coerce")
    if pd.notna(pf) and pd.notna(pt):
        if pf == pt:
            return pf - delta, pt + delta
        return pf, pt
    anchor = pf if pd.notna(pf) else pt
    if pd.isna(anchor):
        anchor = pd.to_datetime(_parse_date(row.get("procedure_date")),
                                errors="coerce")
    if pd.isna(anchor):
        return None
    return anchor - delta, anchor + delta


def resolve_procedure_ref(ref: object,
                          corpus: pd.DataFrame) -> tuple[str | None, str, str]:
    """Resolve a procedure identifier named in a source to one ocid.

    Tries the exact ``ocid``, the exact ``tender_id``, then the bare numeric
    tender number (sources cite ``1539840280133`` while the corpus stores
    ``ocds-b3wdp1-MD-1539840280133``). Returns ``(ocid, status, detail)``
    with ``status`` in ``resolved`` / ``not_found`` / ``ambiguous`` /
    ``empty`` - ``ambiguous`` and ``not_found`` drive the
    ``data/external/case_unmatched.csv`` reasons.
    """
    text = _clean(ref).lower()
    if not text:
        return None, "empty", "procedure_ref_in_source пуст"
    ocid_str = corpus["ocid"].astype(str)
    tid_str = (corpus["tender_id"].astype(str)
               if "tender_id" in corpus.columns else ocid_str)
    exact = (ocid_str.str.lower() == text) | (tid_str.str.lower() == text)
    if exact.any():
        return str(ocid_str[exact].iloc[0]), "resolved", \
            f"точное совпадение {text!r}"
    numbers = set(re.findall(r"\d{10,}", text))
    if numbers:
        md_ocid = ocid_str.str.extract(r"-(\d{10,})$", expand=False)
        md_tid = tid_str.str.extract(r"-(\d{10,})$", expand=False)
        hits = sorted(set(ocid_str[md_ocid.isin(numbers)
                                  | md_tid.isin(numbers)]))
        if len(hits) == 1:
            return hits[0], "resolved", \
                f"номер процедуры {sorted(numbers)[0]} → {hits[0]}"
        if len(hits) > 1:
            return None, "ambiguous", (
                f"номер(а) {sorted(numbers)} найден в {len(hits)} процедурах "
                "корпуса — уточните идентификатор")
    return None, "not_found", (
        f"procedure_ref {ref!r} не найден в корпусе (ocid/tender_id/номер)")


def build_contract_index(raw_dir: Path | str = RAW_PACKAGES) -> dict[str, set[str]]:
    """contract identifier -> set(ocid), from the LOCAL raw OCDS packages.

    READ-ONLY scan of ``data/raw/ocds_packages/*.json.gz`` - no network,
    nothing is written to ``data/raw``. Keys: ``contracts[].contractNumber``
    and ``contracts[].id`` (lower-cased, plus their bare numeric tails),
    because sources cite either form. Deterministic (sorted file order).
    """
    index: dict[str, set[str]] = {}
    for path in sorted(Path(raw_dir).glob("*.json.gz")):
        ocid = path.name[:-len(".json.gz")]
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                pkg = json.load(fh)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        contracts: list[dict] = []
        for rec in pkg.get("records", []) or []:
            cr = rec.get("compiledRelease") or {}
            contracts.extend(cr.get("contracts", []) or [])
            for rel in rec.get("releases", []) or []:
                contracts.extend(rel.get("contracts", []) or [])
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            for key in (contract.get("contractNumber"), contract.get("id")):
                if not key or not isinstance(key, str):
                    continue
                text = key.strip().lower()
                index.setdefault(text, set()).add(ocid)
                tail = re.search(r"(\d{10,})$", text)
                if tail:
                    index.setdefault(tail.group(1), set()).add(ocid)
    return index


def load_contract_index(rebuild: bool = False,
                        raw_dir: Path | str = RAW_PACKAGES,
                        cache: Path | str = CONTRACT_INDEX_JSON
                        ) -> tuple[dict[str, set[str]], str]:
    """Cached ``build_contract_index``: reuse ``results/methodology`` JSON."""
    cache_path = Path(cache)
    if cache_path.exists() and not rebuild:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            return ({k: set(v) for k, v in payload.items()},
                    f"кэш {cache_path.name}")
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    index = build_contract_index(raw_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({k: sorted(v) for k, v in sorted(index.items())},
                   ensure_ascii=False), encoding="utf-8")
    return index, f"скан {raw_dir} (сохранён в {cache_path.name})"


def _entity_contradiction(row, matched: list[str], corpus: pd.DataFrame,
                          etype: str) -> str | None:
    """Note when the declared IDNO is absent from the matched procedures."""
    nid = normalize_idno(row.get("entity_id_mtender"))
    if not nid or not matched:
        return None
    id_col, _ = _entity_columns(etype)
    if id_col not in corpus.columns:
        return None
    ids = set(corpus.loc[corpus["ocid"].isin(matched), id_col]
              .dropna().astype(str))
    if ids and nid not in ids:
        return f"IDNO {nid} не входит в субъекты сопоставленных процедур"
    return None


def match_cases(registry: pd.DataFrame, corpus: pd.DataFrame,
                contract_index: dict[str, set[str]] | None = None,
                ) -> tuple[list[dict], pd.DataFrame, dict]:
    """Match every VALID registry row to corpus procedures.

    Resolution order (MTA-0016 ladder + MTA-0017 identifier links):

    1. a human-verified ``manual`` row uses its declared ``procedure_ids``;
    2. ``link_basis = procedure_id_in_source`` resolves
       ``procedure_ref_in_source`` to one ocid (``ocid_exact``);
    3. ``link_basis = contract_number`` resolves the contract number via
       ``contract_index`` (a read-only raw-OCDS scan, when provided) or via
       the declared ``procedure_ids`` (``contract_number``);
    4. otherwise (``buyer_period_only`` or an empty ``link_basis``) the
       entity ladder runs - IDNO -> exact name -> fuzzy candidate - and for
       ``buyer_period_only`` it is restricted to the episode's period
       window.

    Returns ``(per_case, procedure_matches, summary)``. Fuzzy candidates are
    marked ``label_grade = False`` and stay out of every downstream metric;
    ``buyer_period_only`` rows are NEVER label-grade (MTA-0017 item 3).
    Unmatched rows carry ``unmatched_reason`` in ``UNMATCHED_REASONS``.
    """
    by_name: dict[str, list[str]] = {}
    for key, group in corpus.assign(
            _key=corpus["winner_name"].map(normalise_name)).groupby("_key"):
        if key:
            by_name.setdefault(f"supplier::{key}", []).extend(
                group["ocid"].tolist())
    for key, group in corpus.assign(
            _key=corpus["buyer_name"].map(normalise_name)).groupby("_key"):
        if key:
            by_name.setdefault(f"buyer::{key}", []).extend(
                group["ocid"].tolist())
    supplier_keys = {k.split("::", 1)[1] for k in by_name if k.startswith("supplier::")}
    buyer_keys = {k.split("::", 1)[1] for k in by_name if k.startswith("buyer::")}

    ocid_set = set(corpus["ocid"].tolist())
    id_hits: dict[tuple[str, str], list[str]] = {}
    for etype in ENTITY_TYPES:
        id_col, _ = _entity_columns(etype)
        if id_col not in corpus.columns:
            continue
        for value, group in corpus.dropna(subset=[id_col]).groupby(id_col):
            id_hits[(etype, str(value))] = group["ocid"].tolist()

    def entity_ladder(row, etype: str, note: str
                      ) -> tuple[list[str], str, str, str, str, str]:
        """IDNO -> exact name -> fuzzy candidate; returns the MTA-0016 state
        plus the unmatched ``reason``/``detail`` (empty when matched)."""
        nid = normalize_idno(row.get("entity_id_mtender"))
        name_key = normalise_name(row.get("entity_name_as_in_source"))
        if not nid and not name_key:
            return [], "none", "", note, "нет идентификатора", \
                "нет ни IDNO, ни распознанного названия субъекта"
        if nid and (etype, nid) in id_hits:
            return id_hits[(etype, nid)], "idno_exact", "high", note, "", ""
        if nid:
            note = (note + "; " if note else "") + \
                f"IDNO {nid} не найден в корпусе — попытка по названию"
        exact_key = f"{etype}::{name_key}" if name_key else None
        if exact_key and exact_key in by_name:
            return sorted(set(by_name[exact_key])), "name_exact", "high", \
                note, "", ""
        if name_key:
            pool = supplier_keys if etype == "supplier" else buyer_keys
            cands = sorted(k for k in pool
                           if match_level(name_key, k) == "ambiguous")
            if cands:
                matched = sorted({o for k in cands
                                  for o in by_name[f"{etype}::{k}"]})
                note = (note + "; " if note else "") + \
                    ("неточное совпадение названия — ТОЛЬКО кандидат, "
                     "в метку не входит")
                return matched, "name_fuzzy", "low", note, "", ""
        detail = (f"субъект (IDNO {nid}) не найден в корпусе" if nid else
                  f"название {row.get('entity_name_as_in_source')!r} не "
                  "найдено в корпусе")
        return [], "none", "", note, "вне корпуса", detail

    per_case: list[dict] = []
    proc_rows: list[dict] = []
    for _, row in registry[registry["_valid"]].iterrows():
        case_id = _clean(row["case_id"])
        etype = _clean(row["entity_type"])
        evidence = _clean(row["evidence_level"])
        link = _clean(row.get("link_basis"))
        ref = _clean(row.get("procedure_ref_in_source"))
        declared_ids = [o.strip() for o in _clean(row.get("procedure_ids"))
                        .split(";") if o.strip()]
        declared_conf = _clean(row.get("match_confidence")).lower()
        declared_method = _clean(row.get("match_method")).lower()
        verified = _clean(row.get("verified_by_human")).lower() in ("true", "1", "yes")

        matched: list[str] = []
        method, confidence, note = "none", "", ""
        reason = detail = ""

        # 1) MTA-0016 human override: declared ids win when verified.
        if declared_method == "manual" and declared_ids and verified:
            matched = [o for o in declared_ids if o in ocid_set]
            method, confidence = "manual", (
                declared_conf if declared_conf in MATCH_CONFIDENCES else "medium")
            note = (f"объявлено вручную; {len(declared_ids) - len(matched)} "
                    "ocid не найдены в корпусе" if len(matched) != len(declared_ids)
                    else "объявлено вручную и подтверждено человеком")
        elif declared_method == "manual" and declared_ids and not verified:
            note = ("manual без verified_by_human=true — объявленные ocid "
                    "не принимаются, выполнено автосопоставление")

        # 2) MTA-0017 identifier links: the source names the procedure or
        #    the contract - the entity ladder is only a cross-check here.
        if method == "none" and link in LABEL_LINK_BASIS:
            if link == "procedure_id_in_source":
                ocid, status, res_detail = resolve_procedure_ref(ref, corpus)
                if status == "resolved":
                    matched, method, confidence = [ocid], "ocid_exact", "high"
                    note = res_detail
                elif status == "ambiguous":
                    reason, detail = "неоднозначно", res_detail
                elif status == "empty" and declared_ids:
                    matched = [o for o in declared_ids if o in ocid_set]
                    method, confidence = "ocid_exact", "high"
                    note = ("procedure_ref_in_source пуст — взяты объявленные "
                            "procedure_ids")
                elif status == "empty":
                    reason = "нет идентификатора"
                    detail = ("link_basis=procedure_id_in_source, но "
                              "procedure_ref_in_source пуст")
                else:
                    reason, detail = "вне корпуса", res_detail
            else:  # contract_number: the contract number lives in the ref cell
                cn = ref.lower()
                resolved: list[str] | None = None
                confidence = "high"
                if contract_index is not None and cn:
                    hits = sorted(o for o in contract_index.get(cn, set())
                                  if o in ocid_set)
                    if len(hits) == 1:
                        resolved = hits
                        note = f"номер договора найден в сырых OCDS: {hits[0]}"
                    elif len(hits) > 1:
                        if declared_ids:
                            resolved = [o for o in declared_ids
                                        if o in ocid_set]
                            note = (f"скан дал {len(hits)} кандидатов — "
                                    "взяты объявленные procedure_ids")
                        else:
                            reason = "неоднозначно"
                            detail = (f"номер договора {ref!r} найден в "
                                      f"{len(hits)} разных процедурах корпуса — "
                                      "уточните procedure_ref или подтвердите "
                                      "вручную")
                    elif declared_ids:
                        resolved = [o for o in declared_ids if o in ocid_set]
                        note = ("скан не нашёл номер договора — взяты "
                                "объявленные procedure_ids")
                    else:
                        reason = "вне корпуса"
                        detail = (f"номер договора {ref!r} не найден в сырых "
                                  "OCDS")
                elif declared_ids:
                    resolved = [o for o in declared_ids if o in ocid_set]
                    note = ("по объявленным procedure_ids (скан data/raw "
                            "отключён)")
                elif not cn:
                    reason = "нет идентификатора"
                    detail = ("link_basis=contract_number, но номер договора "
                              "не указан")
                else:
                    reason = "нет идентификатора"
                    detail = (f"номер договора {ref!r} не разрешён: скан "
                              "data/raw отключён (--raw-scan) и procedure_ids "
                              "не заполнены")
                if resolved is not None:
                    matched, method = resolved, "contract_number"
            if matched:
                contradiction = _entity_contradiction(row, matched, corpus,
                                                       etype)
                if contradiction:
                    if confidence == "high":
                        confidence = "medium"
                    note = (note + "; " if note else "") + contradiction
            elif reason:
                confidence = ""   # an unmatched row carries no confidence

        # 3) entity ladder: buyer_period_only (restricted to the episode's
        #    period) or a legacy row without link_basis (MTA-0016 rules).
        if method == "none" and link in ("buyer_period_only", "") and not reason:
            matched, method, confidence, note, ladder_reason, ladder_detail = \
                entity_ladder(row, etype, note)
            if matched and link == "buyer_period_only":
                window = period_window(row)
                if window is None:
                    matched, method, confidence = [], "none", ""
                    reason = "нет идентификатора"
                    detail = ("для link_basis=buyer_period_only нужен период "
                              "(period_from/period_to или procedure_date) — "
                              "привязка «название+период» невозможна")
                else:
                    start, end = window
                    published = pd.to_datetime(corpus["published_date"],
                                               utc=True,
                                               errors="coerce").dt.tz_localize(None)
                    in_win = (corpus["ocid"].isin(matched)
                              & published.between(start, end)).to_numpy()
                    if not in_win.any():
                        matched, method, confidence = [], "none", ""
                        reason = "вне корпуса"
                        detail = ("нет процедур субъекта в периоде эпизода "
                                  f"[{start.date()}; {end.date()}]"
                                  + (f"; кандидаты вне периода: {ladder_detail}"
                                     if ladder_detail else ""))
                    else:
                        matched = corpus.loc[in_win, "ocid"].astype(str).tolist()
                        note = (note + "; " if note else "") + (
                            f"привязка «название+период», окно "
                            f"[{start.date()}; {end.date()}]")
            elif not matched:
                reason, detail = ladder_reason, ladder_detail

        label_grade = (bool(matched) and link in LABEL_LINK_BASIS
                       and confidence in LABEL_CONFIDENCE
                       and evidence in LABEL_EVIDENCE)
        fuzzy = method == "name_fuzzy"
        declared_n = (_clean(row.get("n_procedures_matched")) or None)
        declared_n = int(float(declared_n)) if declared_n and \
            str(declared_n).replace(".", "", 1).isdigit() else None
        rec = {
            "case_id": case_id,
            "title_short": _clean(row.get("title_short")),
            "entity_type": etype,
            "entity_id_mtender": normalize_idno(row.get("entity_id_mtender")),
            "evidence_level": evidence,
            "risk_type": _clean(row.get("risk_type")),
            "first_publication_date": _parse_date(row.get("first_publication_date")),
            "procedure_date": _parse_date(row.get("procedure_date")),
            "source_publication_date": _parse_date(
                row.get("source_publication_date")),
            "link_basis": link or None,
            "procedure_ref_in_source": ref or None,
            "match_method": method,
            "match_confidence": confidence,
            "n_procedures_matched": len(matched),
            "procedure_ids": matched,
            "label_grade": bool(label_grade),
            "fuzzy_candidate": bool(fuzzy),
            "verified_by_human": verified,
            "unmatched_reason": reason or None,
            "unmatched_detail": detail or None,
            "note": note,
            "declared": {
                "match_method": declared_method or None,
                "match_confidence": declared_conf or None,
                "n_procedures_matched": declared_n,
                "procedure_ids": declared_ids or None,
                "verified_by_human": verified,
            },
        }
        per_case.append(rec)
        for ocid in matched:
            proc_rows.append({
                "case_id": case_id, "ocid": ocid, "match_method": method,
                "match_confidence": confidence, "evidence_level": evidence,
                "label_grade": bool(label_grade),
                "link_basis": link or None,
                "first_publication_date": rec["first_publication_date"],
            })

    label_cases = [r for r in per_case if r["label_grade"]]
    summary = {
        "n_records_valid": int(len(registry[registry["_valid"]])),
        "n_matched": sum(1 for r in per_case if r["n_procedures_matched"] > 0),
        "n_matched_label_grade": len(label_cases),
        "n_fuzzy_candidates": sum(1 for r in per_case if r["fuzzy_candidate"]),
        "n_unmatched": sum(1 for r in per_case if r["match_method"] == "none"),
        "by_match_method": {
            m: sum(1 for r in per_case if r["match_method"] == m)
            for m in (*MATCH_METHODS, "none")},
        "by_match_confidence": {
            c: sum(1 for r in per_case if r["match_confidence"] == c)
            for c in MATCH_CONFIDENCES},
        "by_link_basis": {
            (b or "(не указан)"): {
                "records": sum(1 for r in per_case
                               if (r["link_basis"] or "") == b),
                "matched": sum(1 for r in per_case
                               if (r["link_basis"] or "") == b
                               and r["n_procedures_matched"] > 0),
                "label_grade": sum(1 for r in per_case
                                   if (r["link_basis"] or "") == b
                                   and r["label_grade"]),
            } for b in (*LINK_BASES, "")},
        "n_unmatched_by_reason": {
            why: sum(1 for r in per_case if r["unmatched_reason"] == why)
            for why in UNMATCHED_REASONS},
        "by_evidence_level": {
            lv: {
                "records": sum(1 for r in per_case if r["evidence_level"] == lv),
                "matched": sum(1 for r in per_case
                               if r["evidence_level"] == lv
                               and r["n_procedures_matched"] > 0),
                "label_grade": sum(1 for r in per_case
                                   if r["evidence_level"] == lv
                                   and r["label_grade"]),
            } for lv in EVIDENCE_LEVELS},
        "n_label_cases": len(label_cases),
        "n_distinct_ocids_label_grade": len({
            o for r in label_cases for o in r["procedure_ids"]}),
        "n_verified_by_human": sum(1 for r in per_case
                                   if r["verified_by_human"]),
    }
    return per_case, pd.DataFrame(proc_rows), summary


def crosscheck_declared(per_case: list[dict]) -> list[dict]:
    """Discrepancies between the registry's own match_* cells and the
    recomputation. Reported, never silently overwritten."""
    diffs: list[dict] = []
    for rec in per_case:
        dec = rec["declared"]
        if dec["n_procedures_matched"] is not None and \
                dec["n_procedures_matched"] != rec["n_procedures_matched"]:
            diffs.append({"case_id": rec["case_id"],
                          "field": "n_procedures_matched",
                          "declared": dec["n_procedures_matched"],
                          "recomputed": rec["n_procedures_matched"]})
        if dec["procedure_ids"] is not None and \
                sorted(dec["procedure_ids"]) != sorted(rec["procedure_ids"]):
            diffs.append({"case_id": rec["case_id"], "field": "procedure_ids",
                          "declared": dec["procedure_ids"],
                          "recomputed": rec["procedure_ids"]})
        if dec["match_method"] and dec["match_method"] != rec["match_method"] \
                and dec["match_method"] != "manual":
            diffs.append({"case_id": rec["case_id"], "field": "match_method",
                          "declared": dec["match_method"],
                          "recomputed": rec["match_method"]})
        if dec["match_confidence"] and \
                dec["match_confidence"] != rec["match_confidence"] \
                and dec["match_method"] != "manual":
            diffs.append({"case_id": rec["case_id"],
                          "field": "match_confidence",
                          "declared": dec["match_confidence"],
                          "recomputed": rec["match_confidence"]})
    return diffs


def write_markdown(path: Path, validation: dict, summary: dict,
                   diffs: list[dict], registry_path: str) -> None:
    lines = [
        "# MTA-0016/MTA-0017: реестр случаев — сопоставление с MTender",
        "",
        f"Реестр: `{registry_path}`. Схема: `docs/case_registry_schema.md`. "
        f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
        "**Только измерение**: production остаётся v0, реестр не наполняется "
        "автоматически, сетевые запросы не выполняются (флаг "
        "`--allow-network` ничего не открывает в этой версии; `--raw-scan` "
        "только читает локальные `data/raw/ocds_packages`).",
        "",
        *sum(([f"- {t}"] for t in LIMITATIONS), []),
        "",
        "## 1. Записи",
        "",
        f"- всего строк: **{validation['n_rows']}**",
        f"- принято к сопоставлению: **{validation['n_valid']}**",
        f"- отклонено (без источника / без даты первой публикации / "
        f"нарушение enum): **{validation['n_rejected']}**",
    ]
    for rej in validation["rejected"]:
        lines.append(f"  - `{rej['case_id']}`: {'; '.join(rej['reasons'])}")
    lines += [
        "",
        "## 2. Сопоставление",
        "",
        f"- сопоставлено (любой метод): **{summary['n_matched']}** из "
        f"{summary['n_records_valid']}",
        f"- сопоставлено уровнем, пригодным для метки (A–C, high/medium): "
        f"**{summary['n_matched_label_grade']}** записей, "
        f"{summary['n_distinct_ocids_label_grade']} уникальных ocid",
        f"- только кандидаты (name_fuzzy, `low`, в метку не входят): "
        f"**{summary['n_fuzzy_candidates']}**",
        f"- не сопоставлено: **{summary['n_unmatched']}**",
        "",
        "| метод | записей |",
        "|---|---|",
        *[f"| {m} | {n} |" for m, n in summary["by_match_method"].items()],
        "",
        "| надёжность | записей |",
        "|---|---|",
        *[f"| {c} | {n} |" for c, n in summary["by_match_confidence"].items()],
        "",
        "| уровень доказательности | записей | сопоставлено | пригодно для метки |",
        "|---|---|---|---|",
        *[f"| {lv} | {b['records']} | {b['matched']} | {b['label_grade']} |"
          for lv, b in summary["by_evidence_level"].items()],
        "",
        "Уровень **D** сопоставляется, но в метку проверки никогда не входит "
        "(`scripts/39`, тест `test_evidence_d_never_in_label`). Записи "
        "`match_confidence = low` считаются отдельно и в основной расчёт не "
        "входят.",
        "",
        "### Basis привязки (MTA-0017)",
        "",
        "В метку входят только `procedure_id_in_source` и `contract_number` "
        "при `match_confidence` high/medium; `buyer_period_only` и пустой "
        "`link_basis` — никогда (тест "
        "`test_buyer_period_only_never_in_label`).",
        "",
        "| link_basis | записей | сопоставлено | пригодно для метки |",
        "|---|---|---|---|",
        *[f"| {b or '(не указан)'} | {v['records']} | {v['matched']} "
          f"| {v['label_grade']} |"
          for b, v in summary["by_link_basis"].items()],
        "",
        "## 3. Причины несопоставления",
        "",
        "| причина | записей |",
        "|---|---|",
        *[f"| {why} | {n} |"
          for why, n in summary["n_unmatched_by_reason"].items()],
        "",
        "Полный по-записный список причин и деталей — "
        "`results/methodology/case_registry_match.json` "
        "(`per_case[].unmatched_reason`); эпизоды скрипта `41` попадают в "
        "`data/external/case_unmatched.csv`.",
        "",
        "## 4. Сверка с объявленными столбцами реестра",
        "",
    ]
    if diffs:
        lines.append("Расхождения между столбцами `match_*` реестра и "
                     "пересчётом (пересчёт авторитетен, реестр не "
                     "перезаписывается):")
        lines.append("")
        lines.append("| case_id | поле | объявлено | пересчитано |")
        lines.append("|---|---|---|---|")
        for d in diffs:
            lines.append(f"| {d['case_id']} | {d['field']} | {d['declared']} "
                         f"| {d['recomputed']} |")
    else:
        lines.append("Расхождений нет (или столбцы `match_*` не заполнены — "
                     "их пересчитывает `scripts/38`).")
    lines += ["", "## 5. Артефакты", "",
              "`results/methodology/case_registry_match.json` (полная сводка, "
              "по-записный список сопоставлений, расхождения), этот отчёт. "
              "Следующий шаг — `scripts/39_case_registry_check.py`.",
              "", DISCLAIMER, ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default=str(REGISTRY_CSV))
    ap.add_argument("--features", default=str(DATA_FEATURES / "features.csv"))
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-md", default=str(OUT_MD))
    ap.add_argument("--raw-scan", action="store_true",
                    help="разрешить индекс номеров договоров из локальных "
                         "data/raw/ocds_packages (только чтение; без флага "
                         "link_basis=contract_number разрешается по "
                         "объявленным procedure_ids)")
    ap.add_argument("--rebuild-contract-index", action="store_true",
                    help="перестроить кэш results/methodology/"
                         "contract_index.json (подразумевает --raw-scan)")
    ap.add_argument("--allow-network", action="store_true",
                    help="зарезервировано: в этой версии сетевые запросы не "
                         "выполняются ни при каком значении флага")
    args = ap.parse_args()
    t0 = time.time()

    registry_path = Path(args.registry)
    if not registry_path.exists():
        print(f"реестр не найден: {registry_path}", file=sys.stderr)
        return 1
    raw = pd.read_csv(registry_path, dtype="string", keep_default_na=False)
    registry, validation = validate_registry(raw)
    if validation["columns_missing"]:
        print(f"в схеме нет столбцов: {validation['columns_missing']}",
              file=sys.stderr)
        return 1

    corpus = load_corpus(args.features)
    # Contract index is built lazily and only when a valid row actually
    # links by contract number: the raw scan of 150k+ packages is expensive.
    contract_index = None
    index_origin = "не строился (нет записей link_basis=contract_number)"
    needs_index = any(
        _clean(r.get("link_basis")) == "contract_number"
        for _, r in registry[registry["_valid"]].iterrows())
    if needs_index and (args.raw_scan or args.rebuild_contract_index):
        contract_index, index_origin = load_contract_index(
            rebuild=args.rebuild_contract_index)
    elif needs_index:
        index_origin = ("скан data/raw отключён — номера договоров "
                        "разрешаются по объявленным procedure_ids")
    per_case, proc_matches, summary = match_cases(
        registry, corpus, contract_index=contract_index)
    diffs = crosscheck_declared(per_case)

    payload = {
        "task": "MTA-0016/MTA-0017",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame": ("measurement only - production v0, no retraining, registry "
                  "never auto-filled, no network requests (reserved flag "
                  "opens nothing in this version; --raw-scan only reads "
                  "local data/raw/ocds_packages)"),
        "registry_path": str(registry_path.relative_to(ROOT)
                             if registry_path.is_relative_to(ROOT)
                             else registry_path),
        "contract_index": {"used": contract_index is not None,
                           "origin": index_origin},
        "corpus": {"features": str(args.features),
                   "n_procedures": int(len(corpus))},
        "validation": validation,
        "matching": summary,
        "per_case": per_case,
        "declared_vs_recomputed": diffs,
        "disclaimer": DISCLAIMER,
        "limitations": LIMITATIONS,
        "seconds": round(time.time() - t0, 3),
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    out_md = Path(args.out_md)
    write_markdown(out_md, validation, summary, diffs, payload["registry_path"])

    print(f"записей: {validation['n_rows']} (принято "
          f"{validation['n_valid']}, отклонено {validation['n_rejected']}); "
          f"сопоставлено {summary['n_matched']}, пригодно для метки "
          f"{summary['n_matched_label_grade']}, кандидатов (low) "
          f"{summary['n_fuzzy_candidates']}", flush=True)
    print(f"json  -> {out_json}", flush=True)
    print(f"report -> {out_md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
