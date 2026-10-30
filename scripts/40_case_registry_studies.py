#!/usr/bin/env python3
"""Third external label, step 3: CASE STUDIES from the registry (MTA-0016).

For every registry record with ``evidence_level`` A or B and **>= 5 matched
procedures** (label-grade matches: high/medium confidence - fuzzy candidates
never appear here), writes a plain-language case study to
``reports/case_studies.md``:

* the four detector percentile ranks and the vote count per matched procedure
  (the FIXED production artefacts - never recomputed);
* SHAP top-3 (IsolationForest, exact tree-path attribution) and LIME top-3
  (model-agnostic, stochastic - one run, fixed seed) around the SAME
  explained function, as ``scripts/24`` does;
* a RAG explanation: BM25 retrieval over the frozen local legal corpus
  (``src/mtender/rag.py``) with act / article / verbatim quote.

Wording rule (pre-registered): every case is described as «упоминается /
фигурирует в источнике X», never as «нарушитель» - the registry records a
MENTION in an open source, not an established violation.

Per case at most ``--max-procedures`` procedures are explained (ordered by
``max_score``) and the truncation is stated in the report. MEASUREMENT ONLY:
production stays v0, nothing is retrained, no network is used.

Outputs:
    reports/case_studies.md

Usage:
    .venv/bin/python scripts/40_case_registry_studies.py \
        [--registry ...] [--features ...] [--scores ...] [--max-procedures 10]
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mtender.config import DATA_FEATURES, MODELS, TABLES  # noqa: E402

REGISTRY_CSV = ROOT / "data" / "external" / "case_registry.csv"
OUT_MD = ROOT / "reports" / "case_studies.md"

SEED = 42
MIN_PROCEDURES = 5           # a case needs >=5 matched procedures to be studied
STUDY_EVIDENCE = ("A", "B")  # C is aggregate-only, D never enters
LIME_SAMPLES = 5000

DISCLAIMER = ("Индикатор потенциального риска, а не доказательство "
              "коррупции/нарушения. Требуется проверка компетентным органом.")

DETECTOR_COLS = [
    ("score_statistical_mad_zscore", "MAD-z"),
    ("score_isolation_forest", "IF"),
    ("score_local_outlier_factor", "LOF"),
    ("score_one_class_svm", "SVM"),
]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S38 = _load_script("38_case_registry_match.py")
S17 = _load_script("17_explain_ocid.py")
S24 = _load_script("24_xai_consistency.py")


def band_of(votes: int) -> str:
    return "critical" if votes >= 3 else {2: "high", 1: "medium",
                                          0: "low"}[votes]


def build_explainers(bundle_path: Path) -> dict | None:
    """Scaled corpus + TreeExplainer + LIME template; None when the model
    artefact is missing (the study then says so instead of inventing SHAP)."""
    if not bundle_path.exists():
        return None
    import joblib
    bundle = joblib.load(bundle_path)
    iso, scaler = bundle["isolation_forest"], bundle["scaler"]
    feature_columns: list[str] = list(bundle["feature_columns"])
    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    X = (df[feature_columns].apply(pd.to_numeric, errors="coerce")
         .fillna(0.0).to_numpy(dtype=float))
    xs_all = scaler.transform(X)

    import shap
    explainer = shap.TreeExplainer(iso)
    expected = float(np.asarray(explainer.expected_value).ravel()[0])

    def f_model(z: np.ndarray) -> np.ndarray:
        """The exact function TreeExplainer decomposes (the scripts/24 rule:
        LIME wraps THIS so both methods explain the same target)."""
        z2 = np.atleast_2d(z)
        sv = np.asarray(explainer.shap_values(z2))
        if isinstance(sv, list):
            sv = sv[0]
        return expected + sv.sum(axis=1)

    out = {"scaler": scaler, "feature_columns": feature_columns,
           "features_df": df, "shap": explainer, "f_model": f_model}
    try:
        from lime.lime_tabular import LimeTabularExplainer
        out["lime"] = LimeTabularExplainer(
            xs_all, feature_names=feature_columns, mode="regression",
            discretize_continuous=False, sample_around_instance=True,
            random_state=SEED)
    except Exception as exc:  # noqa: BLE001 - LIME is optional at runtime
        out["lime"] = None
        out["lime_error"] = str(exc)
    return out


def explain_row(ctx: dict, ocid: str) -> dict:
    """SHAP/LIME top-3 of one procedure in the units of scripts/17 and 24."""
    row = ctx["features_df"][ctx["features_df"]["ocid"] == ocid]
    if row.empty:
        return {"error": "ocid не найден в features.csv"}
    feature_columns = ctx["feature_columns"]
    x = row.iloc[0][feature_columns].apply(pd.to_numeric,
                                           errors="coerce").fillna(0.0)
    zs = ctx["scaler"].transform(x.to_numpy().reshape(1, -1))
    import shap
    sv = np.asarray(ctx["shap"].shap_values(zs))
    if isinstance(sv, list):
        sv = sv[0]
    sv = sv.ravel()
    top3 = np.argsort(-np.abs(sv))[:3]
    # scripts/17 convention: NEGATIVE SHAP = MORE anomalous for
    # IsolationForest (verified empirically against iso.score_samples).
    shap_top = [{
        "feature": feature_columns[j],
        "label": S17.FEATURE_TEXT["ru"].get(feature_columns[j],
                                            feature_columns[j]),
        "value": x.iloc[j],
        "shap": round(float(sv[j]), 4),
        "direction": "более аномально" if sv[j] < 0 else "более типично",
    } for j in top3]

    if ctx.get("lime") is None:
        reason = ctx.get("lime_error") or "нет lime"
        return {"shap_top3": shap_top, "lime_top3": None,
                "lime_note": f"LIME недоступен: {reason}"}
    try:
        weights, r2 = S24.lime_weights(ctx["lime"], zs.ravel(),
                                       ctx["f_model"], SEED)
        top = np.argsort(-np.abs(weights))[:3]
        lime_top = [{
            "feature": feature_columns[j],
            "label": S17.FEATURE_TEXT["ru"].get(feature_columns[j],
                                                feature_columns[j]),
            "value": x.iloc[j],
            "weight": round(float(weights[j]), 4),
        } for j in top]
        note = (f"LIME, {LIME_SAMPLES} сэмплов, одно прогонирование "
                f"(r² = {r2:.3f}); LIME стохастичен — воспроизводим только "
                "с тем же сидом")
    except Exception as exc:  # noqa: BLE001
        lime_top, note = None, f"LIME недоступен: {exc}"
    return {"shap_top3": shap_top, "lime_top3": lime_top, "lime_note": note}


def build_rag_index():
    """BM25 over the frozen local legal corpus; (index, note)."""
    try:
        from src.mtender.rag import BM25Index, load_corpus
        chunks = load_corpus()
        if not chunks:
            return None, "RAG-корпус пуст (data/legal/raw отсутствует)"
        return BM25Index(chunks), (f"BM25-индекс по {len(chunks)} фрагментам "
                                   "локального нормативного корпуса (без сети)")
    except Exception as exc:  # noqa: BLE001 - degraded mode is documented
        return None, f"RAG-корпус недоступен: {exc}"


def rag_hits(index, query: str, k: int = 2) -> list[dict] | None:
    if index is None:
        return None
    from src.mtender.rag import relevant_hits
    return [{"act": c.act_title, "unit": c.unit, "unit_id": c.unit_id,
             "quote": c.text[:400], "score": round(s, 3)}
            for c, s in relevant_hits(index, query, k=k)]


def _pct(row, col: str) -> str:
    value = row.get(col)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):.3f}"


def _rel_to_publication(row, cutoff: pd.Timestamp) -> str:
    pub = pd.to_datetime(row.get("published_date"), utc=True, errors="coerce")
    if pd.isna(pub) or pd.isna(cutoff):
        return "дата неизвестна"
    return ("до публикации" if pub.tz_localize(None) < cutoff
            else "после публикации")


def case_section(rec: dict, sub: pd.DataFrame, ctx: dict | None, index,
                 rag_note: str, cutoff: pd.Timestamp,
                 truncated: bool) -> list[str]:
    lines = [
        f"## Кейс {rec['case_id']}: {rec['title_short'] or 'без названия'}",
        "",
        "- случай **упоминается** в открытом источнике (уровень "
        f"доказательности {rec['evidence_level']}, тип риска "
        f"`{rec['risk_type']}`); это не приговор и не доказательство "
        "нарушения;",
        f"- сопоставление: `{rec['match_method']}`, надёжность "
        f"`{rec['match_confidence']}`; субъект: {rec['entity_type']}"
        + (f", IDNO {rec['entity_id_mtender']}" if rec["entity_id_mtender"]
           else "") + ";",
        f"- сопоставлено процедур: {rec['n_procedures_matched']}"
        + (f", разобраны первые {len(sub)} по v0-оценке (усечение)"
           if truncated else "") + ";",
        f"- примечание сопоставления: {rec['note'] or '—'}",
        "",
        "| ocid | опубликована | до/после первой публикации случая | "
        "голосов | полоса | MAD-z | IF | LOF | SVM | max_score |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, row in sub.iterrows():
        votes = row.get("n_models_flagging")
        votes = int(votes) if pd.notna(votes) else None
        lines.append(
            f"| {row['ocid']} | {str(row.get('published_date'))[:10]} "
            f"| {_rel_to_publication(row, cutoff)} "
            f"| {votes if votes is not None else '—'} "
            f"| {band_of(votes) if votes is not None else '—'} "
            + " ".join(f"| {_pct(row, c)}" for c, _ in DETECTOR_COLS)
            + f" | {_pct(row, 'max_score')} |")
    lines.append("")

    for _, row in sub.iterrows():
        lines += [f"### Разбор {row['ocid']}", ""]
        title = str(row.get("title") or "")
        if title and title.lower() != "nan":
            lines.append(f"Процедура: {title[:150]}.")
        if ctx is None:
            lines.append("SHAP/LIME: артефакт модели отсутствует "
                         "(`results/models/anomaly_models.joblib`) — разбор "
                         "недоступен, числа не выдумываются.")
        else:
            expl = explain_row(ctx, row["ocid"])
            if "error" in expl:
                lines.append(f"SHAP/LIME: {expl['error']}")
            else:
                lines.append("**SHAP-топ-3** (IsolationForest; вклад в "
                             "аномальность строки относительно типичной "
                             "процедуры корпуса):")
                for f in expl["shap_top3"]:
                    lines.append(f"- {f['label']} = {f['value']} → "
                                 f"{f['direction']} (вклад {f['shap']:+})")
                if expl["lime_top3"]:
                    lines += ["", f"**LIME-топ-3** ({expl['lime_note']}):"]
                    for f in expl["lime_top3"]:
                        lines.append(f"- {f['label']} = {f['value']} → "
                                     f"вес {f['weight']:+}")
                elif expl["lime_note"]:
                    lines += ["", expl["lime_note"]]
        query = " ".join(filter(None, [
            rec["title_short"], rec["risk_type"], rec["entity_type"],
            "achizitie publica procedura"])) or "achizitie publica"
        hits = rag_hits(index, query, k=2)
        lines.append("")
        if hits is None:
            lines.append(f"RAG: {rag_note} — цитаты не приведены.")
        else:
            lines.append("**RAG-пояснение** (нормативный корпус, цитаты "
                         "дословно):")
            for h in hits:
                lines.append(f"- {h['act']}, {h['unit']} ({h['unit_id']}): "
                             f"«{h['quote'][:250]}…» (релевантность "
                             f"{h['score']})")
        lines += ["",
                  "Формулировка: процедура упоминается в контексте случая; "
                  "высокий балл означает лишь несходство с типичной "
                  "процедурой корпуса.",
                  ""]
    lines += [
        "**Источники случая** фиксируются в реестре "
        "(`data/external/case_registry.csv`, столбцы `source_url_1/2`). "
        "Формулировка: «случай упоминается в публикации источника», не "
        "«нарушитель».",
        "",
        DISCLAIMER,
        "",
    ]
    return lines


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default=str(REGISTRY_CSV))
    ap.add_argument("--features", default=str(DATA_FEATURES / "features.csv"))
    ap.add_argument("--scores", default=str(TABLES / "tender_anomaly_scores.csv"))
    ap.add_argument("--models", default=str(MODELS / "anomaly_models.joblib"))
    ap.add_argument("--out-md", default=str(OUT_MD))
    ap.add_argument("--max-procedures", type=int, default=10)
    args = ap.parse_args()
    t0 = time.time()

    raw = pd.read_csv(args.registry, dtype="string", keep_default_na=False)
    registry, validation = S38.validate_registry(raw)
    corpus = S38.load_corpus(args.features)
    per_case, _proc, match_summary = S38.match_cases(registry, corpus)

    score_cols = ["ocid", "max_score", "n_models_flagging",
                  *[c for c, _ in DETECTOR_COLS]]
    scores = pd.read_csv(args.scores, usecols=score_cols,
                         dtype={"ocid": "string"}, low_memory=False)
    if "title" in pd.read_csv(args.features, nrows=0).columns:
        titles = pd.read_csv(args.features, usecols=["ocid", "title"],
                             dtype={"ocid": "string"}, low_memory=False)
    else:  # minimal/corpus-truncated features file - studies run without titles
        titles = pd.DataFrame({"ocid": pd.Series(dtype="string"),
                               "title": pd.Series(dtype="string")})

    studies = [r for r in per_case
               if r["evidence_level"] in STUDY_EVIDENCE
               and r["label_grade"]
               and r["n_procedures_matched"] >= MIN_PROCEDURES]

    ctx = build_explainers(Path(args.models))
    index, rag_note = build_rag_index()

    lines = [
        "# MTA-0016: разборы случаев реестра (case studies)",
        "",
        f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. Только "
        "измерение: production остаётся v0, оценки не пересчитываются, "
        "ничего не переобучается, сеть не используется.",
        "",
        "**Формулировка:** записи реестра означают, что случай «упоминается "
        "/ фигурирует в открытом источнике», а не что субъект признан "
        "нарушителем. Уровень C (журналистские материалы) в разборы не "
        "входит — он рассматривался только в агрегатной проверке "
        "`scripts/39`; уровень D не входит никогда.",
        "",
        f"- порог включения записи: `evidence_level` A или B и ≥ "
        f"{MIN_PROCEDURES} сопоставленных процедур (надёжность high/medium);",
        f"- на кейс разбираются первые {args.max_procedures} процедур по "
        "убыванию v0-оценки (усечение указано явно);",
        f"- {rag_note};",
        "- SHAP — точная атрибуция путей дерева (IsolationForest); LIME — "
        "стохастический, одно прогонирование с фиксированным сидом; вклад "
        "отдельного признака для LOF и One-Class SVM не определён и не "
        "вымышляется.",
        "",
        DISCLAIMER,
        "",
    ]

    if not studies:
        lines += [
            "## Результат",
            "",
            f"Записей уровня A/B с ≥ {MIN_PROCEDURES} сопоставленными "
            f"процедурами: **0** (всего записей реестра: "
            f"{validation['n_rows']}, принято: {validation['n_valid']}; "
            f"пригодно для метки: {match_summary['n_matched_label_grade']}). "
            "Сейчас реестр — шаблон без записей "
            "(`data/external/case_registry.csv`), поэтому разборы пусты. "
            "Файл создан, чтобы разборы появлялись автоматически при "
            "наполнении реестра.",
            "",
            DISCLAIMER,
            "",
        ]
    else:
        for rec in studies:
            matched = set(rec["procedure_ids"])
            sub = (corpus[corpus["ocid"].isin(matched)]
                   .merge(scores, on="ocid", how="left")
                   .merge(titles, on="ocid", how="left"))
            sub = sub.sort_values("max_score", ascending=False)
            truncated = len(sub) > args.max_procedures
            sub = sub.head(args.max_procedures)
            cutoff = pd.to_datetime(rec["first_publication_date"],
                                    errors="coerce")
            lines += case_section(rec, sub, ctx, index, rag_note, cutoff,
                                  truncated)

    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"записей A/B с >= {MIN_PROCEDURES} процедурами: {len(studies)}; "
          f"SHAP/LIME: {'готовы' if ctx else 'нет артефакта модели'}; "
          f"RAG: {rag_note}", flush=True)
    print(f"report -> {out_md} ({time.time() - t0:.1f} s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
