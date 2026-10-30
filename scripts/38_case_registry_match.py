#!/usr/bin/env python3
"""Third external label, step 1: the open-source case registry — MATCH (MTA-0016).

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
none).

Outputs:
    results/methodology/case_registry_match.json   (gitignored, like results/)
    reports/case_registry_match.md

Usage:
    .venv/bin/python scripts/38_case_registry_match.py \
        [--registry data/external/case_registry.csv] [--features ...] \
        [--allow-network] [--out-json ...] [--out-md ...]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mtender.config import DATA_FEATURES, RESULTS  # noqa: E402
from src.mtender.names import match_level, normalise_name  # noqa: E402

REGISTRY_CSV = ROOT / "data" / "external" / "case_registry.csv"
OUT_JSON = RESULTS / "methodology" / "case_registry_match.json"
OUT_MD = ROOT / "reports" / "case_registry_match.md"

REQUIRED_COLUMNS = [
    "case_id", "title_short", "entity_type", "entity_id_mtender",
    "entity_name_as_in_source", "source_url_1", "source_type_1",
    "source_date_1", "source_url_2", "source_type_2", "source_date_2",
    "evidence_level", "risk_type", "period_from", "period_to",
    "first_publication_date", "match_method", "match_confidence",
    "n_procedures_matched", "procedure_ids", "verified_by_human", "notes",
]
ENTITY_TYPES = ("buyer", "supplier")
EVIDENCE_LEVELS = ("A", "B", "C", "D")
RISK_TYPES = ("collusion", "price_inflation", "fake_competition", "splitting",
              "short_deadline", "other")
MATCH_METHODS = ("idno_exact", "name_exact", "name_fuzzy", "manual")
MATCH_CONFIDENCES = ("high", "medium", "low")
#: Evidence levels that can form the check label; D never does.
LABEL_EVIDENCE = ("A", "B", "C")
#: Match confidences that enter the headline check; low (fuzzy) never does.
LABEL_CONFIDENCE = ("high", "medium")

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
    ``entity_type``/``evidence_level``/``risk_type``, missing both entity
    identifiers, duplicate ``case_id``.
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
        if not (_filled(row.get("entity_id_mtender"))
                or _filled(row.get("entity_name_as_in_source"))):
            reasons.append("нет ни IDNO, ни названия")
        for col in ("source_date_1", "source_date_2", "period_from",
                    "period_to", "first_publication_date"):
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
    for level in EVIDENCE_LEVELS:
        sub = df[df["evidence_level"].astype("string").str.strip() == level]
        by_evidence[level] = {
            "records": int(len(sub)),
            "valid": int((valid & (df["evidence_level"].astype("string")
                                   .str.strip() == level)).sum()),
        }
    validation = {
        "columns_missing": missing,
        "n_rows": int(len(df)),
        "n_valid": int(valid.sum()),
        "n_rejected": int((~valid).sum()),
        "rejected": rejected,
        "by_evidence_level": by_evidence,
        "n_evidence_D_in_label": 0,
        "evidence_D_note": "уровень D сопоставляется, но в метку проверки "
                           "не входит (scripts/39)",
    }
    out = df.copy()
    out["_valid"] = valid.to_numpy()
    out["_case_id"] = out["case_id"].astype("string").fillna(f"<row>").to_numpy()
    return out, validation


def _entity_columns(entity_type: str) -> tuple[str, str]:
    if entity_type == "supplier":
        return "winner_identifier", "winner_name"
    return "buyer_identifier", "buyer_name"


def load_corpus(features_csv: Path | str) -> pd.DataFrame:
    """The identity columns of the corpus, kept as strings (IDNO safety)."""
    cols = ["ocid", "buyer_identifier", "buyer_id", "buyer_name",
            "winner_identifier", "winner_id", "winner_name", "published_date"]
    have = pd.read_csv(features_csv, nrows=0).columns
    df = pd.read_csv(features_csv, usecols=[c for c in cols if c in have],
                     dtype="string", low_memory=False)
    df["ocid"] = df["ocid"].astype("string")
    for col in ("buyer_identifier", "winner_identifier"):
        df[col] = df[col].map(normalize_idno)
    return df


def match_cases(registry: pd.DataFrame,
                corpus: pd.DataFrame) -> tuple[list[dict], pd.DataFrame, dict]:
    """Match every VALID registry row to corpus procedures.

    Returns ``(per_case, procedure_matches, summary)``: one record per case,
    one procedure-level row per (case, ocid), and the counters the report
    prints. Fuzzy candidates are marked ``label_grade = False`` here and stay
    out of every downstream metric (tested).
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
        for value, group in corpus.dropna(subset=[id_col]).groupby(id_col):
            id_hits[(etype, str(value))] = group["ocid"].tolist()

    per_case: list[dict] = []
    proc_rows: list[dict] = []
    for _, row in registry[registry["_valid"]].iterrows():
        case_id = _clean(row["case_id"])
        etype = _clean(row["entity_type"])
        evidence = _clean(row["evidence_level"])
        declared_ids = [o.strip() for o in _clean(row.get("procedure_ids"))
                        .split(";") if o.strip()]
        declared_conf = _clean(row.get("match_confidence")).lower()
        declared_method = _clean(row.get("match_method")).lower()
        verified = _clean(row.get("verified_by_human")).lower() in ("true", "1", "yes")

        matched: list[str] = []
        method, confidence, note = "none", "", ""

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

        if method == "none":
            nid = normalize_idno(row.get("entity_id_mtender"))
            if nid and (etype, nid) in id_hits:
                matched = id_hits[(etype, nid)]
                method, confidence = "idno_exact", "high"
            else:
                if nid:
                    note = (note + "; " if note else "") + \
                        f"IDNO {nid} не найден в корпусе — попытка по названию"
                key = normalise_name(row.get("entity_name_as_in_source"))
                exact_key = f"{etype}::{key}" if key else None
                if exact_key and exact_key in by_name:
                    matched = sorted(set(by_name[exact_key]))
                    method, confidence = "name_exact", "high"
                elif key:
                    pool = supplier_keys if etype == "supplier" else buyer_keys
                    cands = sorted(k for k in pool
                                   if match_level(key, k) == "ambiguous")
                    if cands:
                        matched = sorted({o for k in cands
                                          for o in by_name[f"{etype}::{k}"]})
                        method, confidence = "name_fuzzy", "low"
                        note = (note + "; " if note else "") + \
                            ("неточное совпадение названия — ТОЛЬКО кандидат, "
                             "в метку не входит")

        label_grade = (method in ("idno_exact", "name_exact", "manual")
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
            "match_method": method,
            "match_confidence": confidence,
            "n_procedures_matched": len(matched),
            "procedure_ids": matched,
            "label_grade": bool(label_grade),
            "fuzzy_candidate": bool(fuzzy),
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
        "# MTA-0016: реестр случаев — сопоставление с MTender",
        "",
        f"Реестр: `{registry_path}`. Схема: `docs/case_registry_schema.md`. "
        f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
        "**Только измерение**: production остаётся v0, реестр не наполняется "
        "автоматически, сетевые запросы не выполняются (флаг "
        "`--allow-network` ничего не открывает в этой версии).",
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
        "## 3. Сверка с объявленными столбцами реестра",
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
    lines += ["", "## 4. Артефакты", "",
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
    per_case, proc_matches, summary = match_cases(registry, corpus)
    diffs = crosscheck_declared(per_case)

    payload = {
        "task": "MTA-0016",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame": ("measurement only - production v0, no retraining, registry "
                  "never auto-filled, no network requests (reserved flag "
                  "opens nothing in this version)"),
        "registry_path": str(registry_path.relative_to(ROOT)
                             if registry_path.is_relative_to(ROOT)
                             else registry_path),
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
