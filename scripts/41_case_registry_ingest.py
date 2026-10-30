#!/usr/bin/env python3
"""Third external label, step 0: the case-registry INGEST of episodes (MTA-0017).

Turns the AUTHOR-PROVIDED source list and the extracted episodes into
registry rows and runs the ``scripts/38`` matcher on them:

* ``data/external/case_sources.csv``   - one row per source document
  (``source_id, url, source_type, publication_date, evidence_level, title,
  notes``);
* ``data/external/case_episodes_raw.csv`` - one row per extracted episode
  (``episode_id, source_id, location, entity_type, buyer, supplier,
  entity_id, procedure_ref, contract_number, procedure_date, risk_type,
  essence, quote``);
* ``data/external/case_registry.csv``  - matched episodes are UPSERTED here
  (never deleted, human columns preserved);
* ``data/external/case_unmatched.csv`` - episodes that did not link get a
  reason (``вне корпуса`` / ``нет идентификатора`` / ``неоднозначно``).

``link_basis`` is DERIVED, never invented:

* ``procedure_ref`` filled            -> ``procedure_id_in_source``
* else ``contract_number`` filled     -> ``contract_number``
* else                                -> ``buyer_period_only``

and an episode carrying BOTH identifiers is rejected (the source must name
one procedure/contract unambiguously). Quotes longer than 25 words are
rejected to the report (not to the unmatched table): they are an extraction
defect, not a linking failure.

Dates are stored separately: ``procedure_date`` (the procurement, also the
episode's ``period_from``/``period_to`` - the matcher widens a single day by
+/-30 days), ``source_publication_date`` and ``first_publication_date`` (both
the source's publication date here; the author may lower
``first_publication_date`` manually if an earlier publication is found -
it is the temporal guard of ``scripts/39``).

Every ingested row gets ``verified_by_human = false``; the author marks rows
manually and ``scripts/39`` reports metrics twice (all A–C, verified only).

MEASUREMENT ONLY - production stays v0, nothing is retrained, the corpus and
``data/raw/**`` are read-only, **no network request is made**; ``--raw-scan``
only READS the local ``data/raw/ocds_packages`` copies to resolve contract
numbers (cached in ``results/methodology/contract_index.json``).

Outputs:
    results/methodology/case_registry_ingest.json
    reports/case_registry_ingest.md

Usage:
    .venv/bin/python scripts/41_case_registry_ingest.py \
        [--sources ...] [--episodes ...] [--registry ...] [--unmatched ...] \
        [--raw-scan] [--rebuild-contract-index] [--out-json ...] [--out-md ...]
"""
from __future__ import annotations

import argparse
import importlib.util
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

SOURCES_CSV = ROOT / "data" / "external" / "case_sources.csv"
EPISODES_CSV = ROOT / "data" / "external" / "case_episodes_raw.csv"
REGISTRY_CSV = ROOT / "data" / "external" / "case_registry.csv"
UNMATCHED_CSV = ROOT / "data" / "external" / "case_unmatched.csv"
OUT_JSON = RESULTS / "methodology" / "case_registry_ingest.json"
OUT_MD = ROOT / "reports" / "case_registry_ingest.md"

SOURCE_COLUMNS = ["source_id", "url", "source_type", "publication_date",
                  "evidence_level", "title", "notes"]
EPISODE_COLUMNS = ["episode_id", "source_id", "location", "entity_type",
                   "buyer", "supplier", "entity_id", "procedure_ref",
                   "contract_number", "procedure_date", "risk_type",
                   "essence", "quote"]
UNMATCHED_COLUMNS = EPISODE_COLUMNS + ["reason", "detail"]
#: A quote is an ESSENCE, not a transcript (MTA-0017 extraction rule).
MAX_QUOTE_WORDS = 25

DISCLAIMER = ("Индикатор потенциального риска, а не доказательство "
              "коррупции/нарушения. Требуется проверка компетентным органом.")
LIMITATIONS = [
    "Реестр наполняется только из списка источников, предоставленного "
    "автором; ничего не добавляется «похожим».",
    "Эпизод — единица извлечения (источник, страница/пункт), а не "
    "юридическое установление события.",
    "Цитата ≤25 слов — пересказ сути, а не дословный документ.",
    "Строки ingest перезаписываются при повторном запуске (служебные "
    "столбцы), human-столбцы (verified_by_human, match_*, source_*_2) "
    "сохраняются; ручные правки вне этих столбцов фиксируйте в notes "
    "вручную после запуска.",
    "В метку проверки входят только записи с link_basis ∈ "
    "{procedure_id_in_source, contract_number} (scripts/39, п. 3).",
    DISCLAIMER,
]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S38 = _load_script("38_case_registry_match.py")

#: Columns the ingest OWNS (rewritten on every run) vs HUMAN columns
#: (never touched on update).
OWNED_COLUMNS = [
    "title_short", "entity_type", "entity_id_mtender",
    "entity_name_as_in_source", "source_url_1", "source_type_1",
    "source_date_1", "evidence_level", "risk_type", "period_from",
    "period_to", "first_publication_date", "procedure_date",
    "source_publication_date", "link_basis", "procedure_ref_in_source",
    "notes",
]
HUMAN_COLUMNS = ["source_url_2", "source_type_2", "source_date_2",
                 "match_method", "match_confidence", "n_procedures_matched",
                 "procedure_ids", "verified_by_human"]
_NOTES_MARKER_RE = re.compile(
    r"^episode_id=[^;]*; source_id=[^;]*; location=[^;]*;?\s*")


# ---------------------------------------------------------------------------
# validation of the two input tables
# ---------------------------------------------------------------------------

def _filled(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip() not in ("", "nan", "None", "<NA>")


def _clean(value: object) -> str:
    return str(value).strip() if _filled(value) else ""


def load_sources(path: Path) -> tuple[dict[str, dict], dict]:
    """Read + validate ``case_sources.csv`` -> ({id: row}, validation)."""
    if not path.exists():
        return {}, {"n_rows": 0, "n_valid": 0, "n_rejected": 0,
                    "rejected": [], "error": f"файл не найден: {path}"}
    df = pd.read_csv(path, dtype="string", keep_default_na=False)
    missing = [c for c in SOURCE_COLUMNS if c not in df.columns]
    if missing:
        return {}, {"n_rows": int(len(df)), "n_valid": 0,
                    "n_rejected": int(len(df)), "rejected": [],
                    "columns_missing": missing}
    out: dict[str, dict] = {}
    rejected: list[dict] = []
    seen: set[str] = set()
    for idx, row in df.iterrows():
        rid = _clean(row.get("source_id"))
        reasons: list[str] = []
        if not rid:
            reasons.append("пустой source_id")
        elif rid in seen:
            reasons.append("дублирующийся source_id")
        seen.add(rid)
        for col in ("url", "source_type", "publication_date", "evidence_level"):
            if not _filled(row.get(col)):
                reasons.append(f"пустой {col}")
        if _filled(row.get("evidence_level")) and \
                _clean(row.get("evidence_level")) not in S38.EVIDENCE_LEVELS:
            reasons.append(f"evidence_level вне {S38.EVIDENCE_LEVELS}: "
                           f"{row.get('evidence_level')!r}")
        if _filled(row.get("publication_date")) and \
                S38._parse_date(row.get("publication_date")) is None:
            reasons.append(f"publication_date не парсится: "
                           f"{row.get('publication_date')!r}")
        if reasons:
            rejected.append({"row": int(idx), "source_id": rid or f"<row {idx}>",
                             "reasons": reasons})
            continue
        out[rid] = {c: _clean(row.get(c)) for c in SOURCE_COLUMNS}
    validation = {"n_rows": int(len(df)), "n_valid": len(out),
                  "n_rejected": len(rejected), "rejected": rejected}
    return out, validation


def load_episodes(path: Path, sources: dict[str, dict]
                  ) -> tuple[list[dict], dict]:
    """Read + validate ``case_episodes_raw.csv`` -> ([rows], validation)."""
    if not path.exists():
        return [], {"n_rows": 0, "n_valid": 0, "n_rejected": 0,
                    "rejected": [], "error": f"файл не найден: {path}"}
    df = pd.read_csv(path, dtype="string", keep_default_na=False)
    missing = [c for c in EPISODE_COLUMNS if c not in df.columns]
    if missing:
        return [], {"n_rows": int(len(df)), "n_valid": 0,
                    "n_rejected": int(len(df)), "rejected": [],
                    "columns_missing": missing}
    out: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for idx, row in df.iterrows():
        ep = {c: _clean(row.get(c)) for c in EPISODE_COLUMNS}
        eid = ep["episode_id"]
        reasons: list[str] = []
        if not eid:
            reasons.append("пустой episode_id")
        elif eid in seen:
            reasons.append("дублирующийся episode_id")
        seen.add(eid)
        if not ep["source_id"]:
            reasons.append("пустой source_id")
        elif ep["source_id"] not in sources:
            reasons.append(f"source_id {ep['source_id']!r} отсутствует в "
                           "case_sources.csv")
        if ep["entity_type"] not in S38.ENTITY_TYPES:
            reasons.append(f"entity_type вне {S38.ENTITY_TYPES}: "
                           f"{ep['entity_type']!r}")
        if ep["risk_type"] not in S38.RISK_TYPES:
            reasons.append(f"risk_type вне {S38.RISK_TYPES}: "
                           f"{ep['risk_type']!r}")
        if not ep["essence"]:
            reasons.append("пустой essence (суть жалобы/эпизода)")
        if not (ep["buyer"] or ep["supplier"] or ep["entity_id"]):
            reasons.append("нет субъекта (ни buyer, ни supplier, ни entity_id)")
        if ep["procedure_ref"] and ep["contract_number"]:
            reasons.append("procedure_ref и contract_number заполнены "
                           "одновременно — источник должен называть один "
                           "идентификатор")
        if ep["procedure_date"] and S38._parse_date(ep["procedure_date"]) is None:
            reasons.append(f"procedure_date не парсится: "
                           f"{ep['procedure_date']!r}")
        n_words = len(ep["quote"].split()) if ep["quote"] else 0
        if n_words > MAX_QUOTE_WORDS:
            reasons.append(f"цитата {n_words} слов (> {MAX_QUOTE_WORDS}) — "
                           "дефект извлечения, не ошибка привязки")
        if reasons:
            rejected.append({"row": int(idx), "episode_id": eid or f"<row {idx}>",
                             "reasons": reasons})
            continue
        out.append(ep)
    validation = {"n_rows": int(len(df)), "n_valid": len(out),
                  "n_rejected": len(rejected), "rejected": rejected,
                  "n_quotes_over_limit": sum(
                      1 for r in rejected
                      if any("цитата" in x for x in r["reasons"]))}
    return out, validation


def derive_link_basis(ep: dict) -> str:
    """``procedure_ref`` > ``contract_number`` > ``buyer_period_only``."""
    if ep.get("procedure_ref"):
        return "procedure_id_in_source"
    if ep.get("contract_number"):
        return "contract_number"
    return "buyer_period_only"


def build_candidates(episodes: list[dict], sources: dict[str, dict]
                     ) -> tuple[list[dict], dict[str, dict]]:
    """Registry-shaped rows for every accepted episode (keyed by episode_id)."""
    rows: list[dict] = []
    by_id: dict[str, dict] = {}
    for ep in episodes:
        src = sources[ep["source_id"]]
        link = derive_link_basis(ep)
        ref_cell = (ep["procedure_ref"] if link == "procedure_id_in_source"
                    else ep["contract_number"] if link == "contract_number"
                    else "")
        notes = (f"episode_id={ep['episode_id']}; source_id={ep['source_id']}; "
                 f"location={ep['location'] or '—'}")
        row = {
            "case_id": ep["episode_id"],
            "title_short": ep["essence"][:120],
            "entity_type": ep["entity_type"],
            "entity_id_mtender": ep["entity_id"],
            "entity_name_as_in_source": (ep["supplier"]
                                         if ep["entity_type"] == "supplier"
                                         else ep["buyer"]),
            "source_url_1": src["url"],
            "source_type_1": src["source_type"],
            "source_date_1": src["publication_date"],
            "source_url_2": "",
            "source_type_2": "",
            "source_date_2": "",
            "evidence_level": src["evidence_level"],
            "risk_type": ep["risk_type"],
            "period_from": ep["procedure_date"],
            "period_to": ep["procedure_date"],
            "first_publication_date": src["publication_date"],
            "procedure_date": ep["procedure_date"],
            "source_publication_date": src["publication_date"],
            "link_basis": link,
            "procedure_ref_in_source": ref_cell,
            "match_method": "",
            "match_confidence": "",
            "n_procedures_matched": "",
            "procedure_ids": "",
            "verified_by_human": "false",
            "notes": notes,
        }
        rows.append(row)
        by_id[ep["episode_id"]] = {**ep, "_row": row}
    return rows, by_id


# ---------------------------------------------------------------------------
# upserts (never delete, human columns preserved)
# ---------------------------------------------------------------------------

def upsert_registry(existing: pd.DataFrame, rows: list[dict]
                    ) -> tuple[pd.DataFrame, dict, list[dict]]:
    """Insert/update candidate rows; return (frame, counts, collisions)."""
    counts = {"added": 0, "updated": 0}
    collisions: list[dict] = []
    columns = list(S38.REQUIRED_COLUMNS)
    frame = existing.copy() if len(existing) else pd.DataFrame(columns=columns)
    if len(frame):
        frame = frame.reindex(columns=columns)
    else:
        frame = pd.DataFrame(columns=columns)
    index = {cid: i for i, cid in
             enumerate(frame["case_id"].astype("string").fillna("").tolist())}
    for row in rows:
        cid = row["case_id"]
        if cid in index:
            i = index[cid]
            old = frame.iloc[i]
            owned_old = _clean(old.get("notes"))
            # an ingest-owned row carries the episode marker; a hand-written
            # row with the same case_id must never be overwritten
            if f"episode_id={cid}" not in owned_old \
                    and _clean(old.get("case_id")) == cid \
                    and _filled(old.get("source_url_1")):
                collisions.append({
                    "case_id": cid,
                    "reason": ("case_id занят рукописной записью без пометки "
                               f"episode_id={cid} — строка не перезаписана"),
                })
                continue
            new = dict(old)
            new.update({c: row[c] for c in OWNED_COLUMNS})
            # human notes text (beyond the marker) survives the rewrite
            human_part = _NOTES_MARKER_RE.sub("", owned_old).strip("; ").strip()
            if human_part:
                new["notes"] = f"{row['notes']}; {human_part}"
            for c in HUMAN_COLUMNS:
                new[c] = old.get(c, "")
            frame.iloc[i] = pd.Series(new, dtype="string")
            counts["updated"] += 1
        else:
            frame = pd.concat([frame, pd.DataFrame([row],
                                                   columns=columns)],
                              ignore_index=True)
            index[cid] = len(frame) - 1
            counts["added"] += 1
    return frame, counts, collisions


def upsert_unmatched(path: Path, rows: list[dict], matched_ids: set[str]
                     ) -> dict:
    """Write unmatched episodes (keyed by episode_id); resolve matched ones."""
    counts = {"added": 0, "updated": 0, "resolved": 0}
    if path.exists():
        df = pd.read_csv(path, dtype="string", keep_default_na=False)
        missing = [c for c in UNMATCHED_COLUMNS if c not in df.columns]
        if missing:
            df = pd.DataFrame(columns=UNMATCHED_COLUMNS)
    else:
        df = pd.DataFrame(columns=UNMATCHED_COLUMNS)
    keep_mask = ~df["episode_id"].astype("string").fillna("").isin(matched_ids)
    counts["resolved"] = int((~keep_mask).sum())
    df = df.loc[keep_mask].reset_index(drop=True)
    index = {cid: i for i, cid in enumerate(
        df["episode_id"].astype("string").fillna("").tolist())}
    for row in rows:
        payload = {c: row.get(c, "") for c in EPISODE_COLUMNS}
        payload["reason"] = row.get("unmatched_reason") or ""
        payload["detail"] = row.get("unmatched_detail") or ""
        if payload["episode_id"] in index:
            df.iloc[index[payload["episode_id"]]] = pd.Series(payload,
                                                              dtype="string")
            counts["updated"] += 1
        else:
            df = pd.concat([df, pd.DataFrame([payload],
                                             columns=UNMATCHED_COLUMNS)],
                           ignore_index=True)
            index[payload["episode_id"]] = len(df) - 1
            counts["added"] += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    return counts


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def write_markdown(path: Path, payload: dict) -> None:
    v = payload["validation"]
    ep, src = v["episodes"], v["sources"]
    m = payload["matching"]
    up = payload["upsert"]
    lines = [
        "# MTA-0017: наполнение реестра случаев — ingest эпизодов",
        "",
        f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
        "**Только измерение**: production остаётся v0, ничего не "
        "переобучается, сеть не используется (`--raw-scan` только читает "
        "локальные `data/raw/ocds_packages`). Порядок: "
        "`41 → 38 → 39 → 40`.",
        "",
        *sum(([f"- {t}"] for t in LIMITATIONS), []),
        "",
        "## 1. Извлечено",
        "",
        f"- источников (`case_sources.csv`): **{src['n_rows']}**, "
        f"принято {src['n_valid']}, отклонено {src['n_rejected']};",
        f"- эпизодов (`case_episodes_raw.csv`): **{ep['n_rows']}**, "
        f"принято {ep['n_valid']}, отклонено {ep['n_rejected']} "
        f"(из них цитата >{MAX_QUOTE_WORDS} слов: "
        f"{ep.get('n_quotes_over_limit', 0)});",
        f"- кандидатов в реестр: **{len(payload['candidates'])}** "
        f"(по link_basis: "
        + ", ".join(f"{k} — {n}" for k, n in
                    payload["derived_by_link_basis"].items()) + ");",
    ]
    for rej in ep["rejected"] + src["rejected"]:
        lines.append(f"  - `{rej.get('episode_id') or rej.get('source_id')}`: "
                     f"{'; '.join(rej['reasons'])}")
    lines += [
        "",
        "## 2. Сопоставлено (пересчёт scripts/38)",
        "",
        f"- записей прошло валидацию реестра: {m['n_records_valid']};",
        f"- сопоставлено: **{m['n_matched']}**;",
        f"- пригодно для метки (link_basis ∈ "
        f"{{procedure_id_in_source, contract_number}} + A–C + high/medium): "
        f"**{m['n_matched_label_grade']}**;",
        f"- не сопоставлено: **{m['n_unmatched']}** "
        + "("
        + ", ".join(f"{k}: {n}" for k, n in m["n_unmatched_by_reason"].items())
        + ")",
        "",
        "| link_basis | записей | сопоставлено | пригодно для метки |",
        "|---|---|---|---|",
        *[f"| {k} | {b['records']} | {b['matched']} | {b['label_grade']} |"
          for k, b in m["by_link_basis"].items()],
        "",
        "## 3. Записано",
        "",
        f"- `case_registry.csv`: +{up['registry']['added']} новых, "
        f"обновлено {up['registry']['updated']}, коллизий "
        f"{len(up['collisions'])} (строки не перезаписаны);",
        f"- `case_unmatched.csv`: +{up['unmatched']['added']}, обновлено "
        f"{up['unmatched']['updated']}, разрешено (теперь сопоставлены) "
        f"{up['unmatched']['resolved']};",
        "",
        "Все новые строки: `verified_by_human = false` — автор подтверждает "
        "вручную; `scripts/39` считает метрики в двух версиях (все A–C и "
        "только подтверждённые).",
        "",
        "## 4. Не прошло",
        "",
    ]
    if m["n_unmatched"]:
        lines += ["| episode_id | суть | причина | детали |",
                  "|---|---|---|---|"]
        for rec in payload["unmatched_rows"]:
            lines.append(f"| {rec['episode_id']} | {rec['essence'] or '—'} | "
                         f"{rec['reason']} | {rec['detail'] or '—'} |")
        lines.append("")
    else:
        lines += ["Эпизодов без привязки нет.", ""]
    if up["collisions"]:
        lines += ["Коллизии case_id (строка реестра не тронута):", ""]
        lines += [f"- `{c['case_id']}`: {c['reason']}" for c in up["collisions"]]
        lines.append("")
    lines += [
        "## 5. Артефакты",
        "",
        "`results/methodology/case_registry_ingest.json`, этот отчёт. "
        "Дальше: `scripts/38_case_registry_match.py` → "
        "`scripts/39_case_registry_check.py` → "
        "`scripts/40_case_registry_studies.py`.",
        "",
        DISCLAIMER, "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sources", default=str(SOURCES_CSV))
    ap.add_argument("--episodes", default=str(EPISODES_CSV))
    ap.add_argument("--registry", default=str(REGISTRY_CSV))
    ap.add_argument("--unmatched", default=str(UNMATCHED_CSV))
    ap.add_argument("--features", default=str(DATA_FEATURES / "features.csv"))
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-md", default=str(OUT_MD))
    ap.add_argument("--raw-scan", action="store_true",
                    help="индекс номеров договоров из локальных "
                         "data/raw/ocds_packages (только чтение)")
    ap.add_argument("--rebuild-contract-index", action="store_true",
                    help="перестроить кэш results/methodology/"
                         "contract_index.json (подразумевает --raw-scan)")
    args = ap.parse_args()
    t0 = time.time()

    sources, src_val = load_sources(Path(args.sources))
    episodes, ep_val = load_episodes(Path(args.episodes), sources)
    candidates, by_id = build_candidates(episodes, sources)

    registry_path = Path(args.registry)
    if registry_path.exists():
        existing = pd.read_csv(registry_path, dtype="string",
                               keep_default_na=False)
        missing = [c for c in S38.REQUIRED_COLUMNS if c not in existing.columns]
        if missing:
            print(f"в реестре нет столбцов: {missing}", file=sys.stderr)
            return 1
        existing = existing.reindex(columns=S38.REQUIRED_COLUMNS)
    else:
        existing = pd.DataFrame(columns=S38.REQUIRED_COLUMNS)

    cand_frame, cand_val = S38.validate_registry(
        pd.DataFrame(candidates, columns=S38.REQUIRED_COLUMNS))
    # a candidate failing the registry schema is a rejection, not a match miss
    bad_ids = {r["case_id"] for r in cand_val["rejected"]}
    if bad_ids:
        ep_val["rejected"] = ep_val["rejected"] + [
            {"episode_id": cid, "reasons": [r for r in cand_val["rejected"]
                                            if r["case_id"] == cid][0]["reasons"]}
            for cid in sorted(bad_ids)]
        ep_val["n_rejected"] += len(bad_ids)
        ep_val["n_valid"] -= len(bad_ids)
        keep = [r for r in candidates if r["case_id"] not in bad_ids]
        cand_frame, cand_val = S38.validate_registry(
            pd.DataFrame(keep, columns=S38.REQUIRED_COLUMNS))
        candidates = keep

    corpus = S38.load_corpus(args.features)
    contract_index = None
    index_origin = "не строился (нет записей link_basis=contract_number)"
    needs_index = any(r["link_basis"] == "contract_number" for r in candidates)
    if needs_index and (args.raw_scan or args.rebuild_contract_index):
        contract_index, index_origin = S38.load_contract_index(
            rebuild=args.rebuild_contract_index)
    elif needs_index:
        index_origin = ("скан data/raw отключён — номера договоров "
                        "разрешаются по объявленным procedure_ids")
    per_case, _proc, match_summary = S38.match_cases(
        cand_frame, corpus, contract_index=contract_index)

    matched = [r for r in per_case if r["n_procedures_matched"] > 0]
    unmatched = [r for r in per_case if r["n_procedures_matched"] == 0]
    matched_ids = {r["case_id"] for r in matched}
    # the unmatched CSV keeps the RAW episode columns + the match failure
    unmatched_rows: list[dict] = []
    for rec in unmatched:
        ep = by_id.get(rec["case_id"], {})
        payload_row = {c: ep.get(c, "") for c in EPISODE_COLUMNS}
        payload_row["episode_id"] = rec["case_id"]
        payload_row["unmatched_reason"] = rec["unmatched_reason"]
        payload_row["unmatched_detail"] = rec["unmatched_detail"]
        unmatched_rows.append(payload_row)

    new_frame, reg_counts, collisions = upsert_registry(
        existing, [r for r in candidates if r["case_id"] in matched_ids])
    if reg_counts["added"] or reg_counts["updated"] or collisions:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        new_frame.to_csv(registry_path, index=False, encoding="utf-8")
    unmatched_path = Path(args.unmatched)
    un_counts = upsert_unmatched(unmatched_path, unmatched_rows, matched_ids)

    derived = {}
    for r in candidates:
        derived[r["link_basis"]] = derived.get(r["link_basis"], 0) + 1

    payload = {
        "task": "MTA-0017",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame": ("measurement only - production v0, no retraining, no "
                  "network; --raw-scan only reads local data/raw"),
        "paths": {"sources": args.sources, "episodes": args.episodes,
                  "registry": args.registry, "unmatched": args.unmatched},
        "contract_index": {"used": contract_index is not None,
                           "origin": index_origin},
        "validation": {"sources": src_val, "episodes": ep_val,
                       "candidates": cand_val},
        "candidates": candidates,
        "derived_by_link_basis": derived,
        "matching": match_summary,
        "unmatched_rows": [{"episode_id": r["episode_id"],
                            "essence": r["essence"],
                            "reason": r["unmatched_reason"],
                            "detail": r["unmatched_detail"]}
                           for r in unmatched_rows],
        "upsert": {"registry": reg_counts, "unmatched": un_counts,
                   "collisions": collisions},
        "verified_by_human_default": False,
        "disclaimer": DISCLAIMER,
        "limitations": LIMITATIONS,
        "seconds": round(time.time() - t0, 3),
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    out_md = Path(args.out_md)
    write_markdown(out_md, payload)

    print(f"эпизодов: {ep_val['n_rows']} (принято {ep_val['n_valid']}, "
          f"отклонено {ep_val['n_rejected']}); сопоставлено "
          f"{match_summary['n_matched']}, в метку "
          f"{match_summary['n_matched_label_grade']}, без привязки "
          f"{match_summary['n_unmatched']}", flush=True)
    print(f"реестр: +{reg_counts['added']}, обновлено "
          f"{reg_counts['updated']}; unmatched: +{un_counts['added']}, "
          f"обновлено {un_counts['updated']}, разрешено "
          f"{un_counts['resolved']}", flush=True)
    print(f"json  -> {out_json}", flush=True)
    print(f"report -> {out_md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
