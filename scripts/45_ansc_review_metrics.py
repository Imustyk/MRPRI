#!/usr/bin/env python3
"""Quality metrics of the ANSC outcome extraction vs the MANUAL review
(MTA-0018, step 5).

MEASUREMENT ONLY - no training, production stays v0, ``data/raw/**`` is
untouched, no model is evaluated here: these numbers describe how well the
RULE-BASED extractor (scripts/43) agrees with the independent human labels
of ``data/external/ansc_review_sample_50.csv``. They are NOT model quality,
and the extractor's own ``confidence`` is NEVER substituted for the labels.

The script REFUSES to compute Accuracy, Precision, Recall, F1, Macro-F1 or
the confusion matrix while any ``reviewer_outcome`` cell of the sample is
empty or invalid: it then prints only labeling PROGRESS and exits 5 (this
behaviour is regression-tested). The manual review is performed by the
author; it is never imitated or pre-filled.

MTA-0019 extension: the BLIND review file
(``data/external/ansc_manual_review_50.csv``, scripts/46) is overlaid onto
the machine sample by URL, so the predictions stay machine-side and the
human labels stay in the review artefact. The review columns
(``reviewer_document_type``, ``reviewer_link_verified``) become REQUIRED
only when present in the header; outcome metrics are then computed on the
rows confirmed as ANSC decisions (others counted under document-type
detection), link errors, multi-complaint rows and a link-confirmed subset
are reported separately, and the report states that the stratified sample
is not necessarily representative.

When every row carries a valid label the script computes:
  * Accuracy, per-class Precision/Recall/F1, Macro-F1 (7 classes,
    zero-division -> 0);
  * the 7x7 confusion matrix (rows = reviewer truth, columns = extracted);
  * extracted ``unknown`` share (an abstention - NEVER a negative label);
  * doc -> procedure mislink share (rows whose notes begin with
    ``mislink:`` per the review protocol);
  * the split by source type: text-PDF vs scan (OCR).

Outputs:
  results/methodology/ansc_review_metrics.json
  reports/ansc_review_metrics.md

Usage:
    .venv/bin/python scripts/45_ansc_review_metrics.py

Exit codes: 0 = metrics computed, 4 = inputs missing,
            5 = reviewer labels missing (no metrics), 6 = invalid labels.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IN_SAMPLE = ROOT / "data" / "external" / "ansc_review_sample_50.csv"
IN_OUTCOMES = ROOT / "results" / "tables" / "ansc_outcomes.csv"
# MTA-0019: blind review file (scripts/46) - the human labels live here
IN_REVIEW = ROOT / "data" / "external" / "ansc_manual_review_50.csv"
OUT_JSON = ROOT / "results" / "methodology" / "ansc_review_metrics.json"
OUT_MD = ROOT / "reports" / "ansc_review_metrics.md"

OUTCOMES = ("admitted", "partially_admitted", "rejected", "inadmissible",
            "withdrawn", "terminated", "unknown")

# MTA-0019 §5: the blind review file adds document-type and link columns;
# required enums are derived from the columns actually PRESENT in the CSV
# header, so the legacy 10-column sample (MTA-0018) keeps its contract.
DOC_TYPES = ("ansc_decision", "other_document", "uncertain")
LINK_VALUES = ("confirmed", "rejected", "uncertain")
ENUMS = {"reviewer_outcome": OUTCOMES,
         "reviewer_document_type": DOC_TYPES,
         "reviewer_link_verified": LINK_VALUES}

# reviewer columns carried by the blind review file (scripts/46)
REVIEWER_FIELDS = ("reviewer_outcome", "reviewer_document_type",
                   "reviewer_link_verified", "reviewer_evidence_page",
                   "reviewer_evidence_quote", "reviewer_notes")

RE_MISLINK = re.compile(r"\bmislink\b", re.IGNORECASE)
RE_MULTI = re.compile(r"\bmultiple:", re.IGNORECASE)

DISCLAIMER_RU = ("Индикатор потенциального риска, а не доказательство "
                 "коррупции/нарушения. Требуется проверка компетентным "
                 "органом.")
DISCLAIMER_EN = ("An upheld ANSC complaint indicates an administrative "
                 "procurement dispute outcome and does not constitute proof "
                 "of corruption.")


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing {path}")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def label_status(rows: list[dict]) -> dict:
    """Classify the reviewer cells of every row: valid / missing / invalid.

    Required enums = only those enum fields that actually appear as columns
    in the rows (the legacy sample carries ``reviewer_outcome`` alone, the
    MTA-0019 review file also ``reviewer_document_type`` and
    ``reviewer_link_verified``). A row counts as labelled only when EVERY
    present enum column of that row holds a valid value.
    """
    present: set[str] = set()
    for r in rows:
        present.update(r.keys())
    required = [f for f in ENUMS if f in present]

    valid: list[dict] = []
    missing: list[dict] = []
    invalid: list[dict] = []
    for i, row in enumerate(rows, start=2):        # +1 header, +1 to 1-based
        row_ok = True
        for field in required:
            raw = (row.get(field) or "").strip()
            if not raw:
                missing.append({"line": i, "field": field,
                                "decision_id": row.get("decision_id", ""),
                                "document_url": row.get("document_url", "")})
                row_ok = False
            elif raw not in ENUMS[field]:
                invalid.append({"line": i, "field": field, "value": raw,
                                "decision_id": row.get("decision_id", "")})
                row_ok = False
        if row_ok:
            valid.append(row)
    return {"total": len(rows), "valid": valid, "required": required,
            "missing": missing, "invalid": invalid}


def _doc_type(row: dict) -> str:
    """Reviewer's document type; legacy rows (no column) count as ``""``."""
    return (row.get("reviewer_document_type") or "").strip()


def _link(row: dict) -> str:
    return (row.get("reviewer_link_verified") or "").strip()


def _pred_is_decision(row: dict) -> bool:
    """Machine side: the document looks like an ANSC decision when the
    extractor classified its resolutory part OR a decision number was found
    (an abstention with a printed decision number is still a decision)."""
    if (row.get("extracted_outcome") or "").strip() != "unknown":
        return True
    return bool((row.get("decision_id") or "").strip())


def _core(rows: list[dict]) -> dict:
    """Accuracy / per-class P-R-F1 / Macro-F1 / confusion over ``rows``."""
    truth = [(r.get("reviewer_outcome") or "").strip() for r in rows]
    pred = [(r.get("extracted_outcome") or "").strip() for r in rows]
    n = len(rows) or 1

    matrix = {t: {p: 0 for p in OUTCOMES} for t in OUTCOMES}
    for t, p in zip(truth, pred):
        if t in matrix and p in matrix[t]:
            matrix[t][p] += 1

    per_class: dict[str, dict] = {}
    for c in OUTCOMES:
        tp = matrix[c][c]
        fp = sum(matrix[t][c] for t in OUTCOMES if t != c)
        fn = sum(matrix[c][p] for p in OUTCOMES if p != c)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) else 0.0)
        per_class[c] = {"precision": round(precision, 4),
                        "recall": round(recall, 4),
                        "f1": round(f1, 4),
                        "support": sum(matrix[c].values()),
                        "predicted": tp + fp}
    accuracy = sum(matrix[c][c] for c in OUTCOMES) / n
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(OUTCOMES)
    return {
        "n": len(rows),
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "confusion_matrix": matrix,
        "unknown_share_extracted": round(
            sum(1 for p in pred if p == "unknown") / n, 4),
        "unknown_share_reviewer": round(
            sum(1 for t in truth if t == "unknown") / n, 4),
    }


def document_type_block(labeled: list[dict]) -> dict:
    """Quality of DOCUMENT-TYPE detection over ALL reviewed rows (MTA-0019
    §5): the machine's "is a decision" call vs the reviewer's
    ``reviewer_document_type``. ``uncertain`` rows are counted separately
    and never forced into the binary split."""
    reviewer_counts = {"ansc_decision": 0, "other_document": 0,
                       "uncertain": 0, "unfilled": 0}
    confusion = {k: {"decision": 0, "not_decision": 0}
                 for k in ("ansc_decision", "other_document", "uncertain",
                           "unfilled")}
    tp = fp = fn = tn = 0
    for r in labeled:
        dt = _doc_type(r) or "unfilled"
        if dt not in reviewer_counts:
            dt = "unfilled"          # defensive: never crash on a stray value
        reviewer_counts[dt] += 1
        bucket = "decision" if _pred_is_decision(r) else "not_decision"
        confusion[dt][bucket] += 1
        if dt == "ansc_decision":
            if bucket == "decision":
                tp += 1
            else:
                fn += 1
        elif dt == "other_document":
            if bucket == "decision":
                fp += 1
            else:
                tn += 1
    n_bin = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return {
        "n_labeled": len(labeled),
        "reviewer_counts": reviewer_counts,
        "confusion": confusion,
        "binary_n": n_bin,           # rows with a decisive reviewer type
        "accuracy": round((tp + tn) / n_bin, 4) if n_bin else None,
        "precision": round(precision, 4) if n_bin else None,
        "recall": round(recall, 4) if n_bin else None,
        "f1": round(f1, 4) if n_bin else None,
        "note": "non-ANSC-decision documents are excluded from the outcome "
                "metrics and counted here instead (MTA-0019 §4/§5)",
    }


def link_block(labeled: list[dict]) -> dict:
    """Frequency of wrong document->procedure links (MTA-0019 §5)."""
    counts = {"confirmed": 0, "rejected": 0, "uncertain": 0, "unfilled": 0}
    for r in labeled:
        v = _link(r)
        counts[v if v in counts else "unfilled"] += 1
    return counts


def compute_metrics(labeled: list[dict], layer_by_url: dict[str, str]
                    ) -> dict:
    """All quality metrics over fully labelled rows (pure function).

    MTA-0019 §4/§5: outcome metrics are computed on the EVALUATED set -
    rows the reviewer confirmed as ANSC decisions (legacy rows without a
    ``reviewer_document_type`` column are all evaluated). Document-type
    detection, link quality and the multi-complaint count cover ALL
    reviewed rows.
    """
    evaluated = [r for r in labeled if _doc_type(r) in ("", "ansc_decision")]
    excluded = [r for r in labeled if _doc_type(r) not in ("", "ansc_decision")]
    core = _core(evaluated)

    split: dict[str, dict] = {}
    for bucket, want in (("text_layer", "1"), ("scan", "0")):
        idx = [i for i, r in enumerate(evaluated)
               if layer_by_url.get(r.get("document_url", "")) == want]
        if not idx:
            split[bucket] = {"n": 0, "accuracy": None}
            continue
        truth = [(r.get("reviewer_outcome") or "").strip() for r in evaluated]
        pred = [(r.get("extracted_outcome") or "").strip() for r in evaluated]
        correct = sum(1 for i in idx if truth[i] == pred[i])
        split[bucket] = {"n": len(idx),
                         "accuracy": round(correct / len(idx), 4)}
    unjoined = sum(1 for r in evaluated
                   if r.get("document_url", "") not in layer_by_url)

    def mislinked(r: dict) -> bool:
        return bool(RE_MISLINK.search(r.get("reviewer_notes") or "")
                    or _link(r) == "rejected")

    mislinks = [r for r in labeled if mislinked(r)]
    confirmed = [r for r in evaluated if _link(r) == "confirmed"]
    confirmed_core = _core(confirmed) if confirmed else None

    return {
        "n_labeled": len(labeled),
        "n_evaluated": len(evaluated),
        "excluded_non_decision": {
            "n": len(excluded),
            "other_document": sum(1 for r in excluded
                                  if _doc_type(r) == "other_document"),
            "uncertain": sum(1 for r in excluded
                             if _doc_type(r) == "uncertain"),
        },
        "accuracy": core["accuracy"],
        "macro_f1": core["macro_f1"],
        "per_class": core["per_class"],
        "confusion_matrix": core["confusion_matrix"],
        "unknown_share_extracted": core["unknown_share_extracted"],
        "unknown_share_reviewer": core["unknown_share_reviewer"],
        "mislink_share": round(len(mislinks) / (len(labeled) or 1), 4),
        "mislink_rows": len(mislinks),
        "split_by_source_type": split,
        "rows_without_source_type_join": unjoined,
        "document_type_detection": document_type_block(labeled),
        "link_verification": link_block(labeled),
        "metrics_confirmed_decisions": (
            {"n": confirmed_core["n"],
             "accuracy": confirmed_core["accuracy"],
             "macro_f1": confirmed_core["macro_f1"],
             "per_class": confirmed_core["per_class"],
             "confusion_matrix": confirmed_core["confusion_matrix"]}
            if confirmed_core else {"n": 0, "accuracy": None,
                                    "macro_f1": None, "per_class": None,
                                    "confusion_matrix": None}),
        "multi_complaint_rows": sum(
            1 for r in labeled if RE_MULTI.search(r.get("reviewer_notes")
                                                  or "")),
        "sample_is_stratified_not_representative":
            "the 50-document stratified sample (min 3 per rare outcome) is "
            "NOT necessarily representative of the whole corpus; shares "
            "must be re-weighted before extrapolation",
    }


def build_progress(labelrep: dict) -> dict:
    return {
        "task": "MTA-0018",
        "part": "5 - quality metrics vs manual review",
        "generated": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "status": "awaiting_manual_review",
        "n_labeled": len(labelrep["valid"]),
        "n_total": labelrep["total"],
        "review_required_fields": labelrep.get("required", []),
        "missing_rows": labelrep["missing"],
        "invalid_rows": labelrep["invalid"],
        "metrics": None,
        "note": "Accuracy/Precision/Recall/F1/confusion matrix are NOT "
                "computed until every row of the sample carries an "
                "independent expert label (MTA-0018 §5); classifier "
                "confidence is never used as a substitute.",
        "disclaimer_ru": DISCLAIMER_RU,
        "disclaimer_en": DISCLAIMER_EN,
    }


def build_report(metrics: dict, sample_path: Path) -> str:
    pc = metrics["per_class"]
    try:
        shown_sample = str(sample_path.relative_to(ROOT))
    except ValueError:
        shown_sample = str(sample_path)
    lines = [
        "# Отчёт качества извлечения исходов ANSC против ручной проверки "
        "(MTA-0018, шаг 5)",
        "",
        f"Сгенерировано: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}. "
        f"Выборка: `{shown_sample}` "
        f"({metrics['n_labeled']} строк с экспертными метками).",
        "",
        "Эти числа описывают СОГЛАСОВАННОСТЬ правила (scripts/43) с "
        "независимой ручной разметкой — это НЕ качество модели; метрики "
        "считаются только после полной ручной проверки, confidence "
        "классификатора вместо меток не подставляется.",
        "",
        "## Метрики",
        "",
        "| Метрика | Значение |",
        "|---|---:|",
        f"| Accuracy | {metrics['accuracy']:.4f} |",
        f"| Macro-F1 (7 классов, zero-division=0) | {metrics['macro_f1']:.4f} |",
        f"| Доля `unknown` (извлечено) | {metrics['unknown_share_extracted']:.1%} |",
        f"| Доля `unknown` (ручная разметка) | {metrics['unknown_share_reviewer']:.1%} |",
        f"| Доля ошибок привязки документ→процедура (`mislink:` в notes) | "
        f"{metrics['mislink_share']:.1%} ({metrics['mislink_rows']}) |",
        "",
        "### По классам",
        "",
        "| Класс | Precision | Recall | F1 | Support | Предсказано |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in OUTCOMES:
        v = pc[c]
        lines.append(f"| `{c}` | {v['precision']:.4f} | {v['recall']:.4f} | "
                     f"{v['f1']:.4f} | {v['support']} | {v['predicted']} |")
    lines += [
        "",
        "### Матрица ошибок (строки — ручная разметка, столбцы — извлечено)",
        "",
        "| ↓ truth \\ extracted → | " + " | ".join(f"`{c}`" for c in OUTCOMES)
        + " |",
        "|---|" + "---:|" * len(OUTCOMES),
    ]
    for t in OUTCOMES:
        row = metrics["confusion_matrix"][t]
        lines.append(f"| `{t}` | " + " | ".join(str(row[p])
                                                for p in OUTCOMES) + " |")
    lines += [
        "",
        "### Разрыв по типу источника",
        "",
        "| Источник | N | Accuracy |",
        "|---|---:|---:|",
    ]
    for bucket, label in (("text_layer", "текстовый PDF"),
                          ("scan", "скан (OCR)")):
        v = metrics["split_by_source_type"][bucket]
        acc = "n/a" if v["accuracy"] is None else f"{v['accuracy']:.4f}"
        lines.append(f"| {label} | {v['n']} | {acc} |")
    if metrics["rows_without_source_type_join"]:
        lines += ["", f"Строк без сопоставления с типом источника: "
                      f"{metrics['rows_without_source_type_join']}."]

    # --- MTA-0019 §5 additions -------------------------------------------
    dt = metrics.get("document_type_detection") or {}
    rc = dt.get("reviewer_counts") or {}
    lines += [
        "",
        "### Тип документа (обнаружение типа, ВСЕ размеченные строки)",
        "",
        "| Тип по проверяющему | N | Машина: решение | Машина: не решение |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (("ansc_decision", "`ansc_decision`"),
                       ("other_document", "`other_document`"),
                       ("uncertain", "`uncertain`"),
                       ("unfilled", "не заполнено")):
        cf = (dt.get("confusion") or {}).get(key, {})
        lines.append(f"| {label} | {rc.get(key, 0)} | "
                     f"{cf.get('decision', 0)} | {cf.get('not_decision', 0)} |")
    if dt.get("binary_n"):
        lines += ["",
                  f"На документах с однозначным типом (n={dt['binary_n']}): "
                  f"Accuracy={dt['accuracy']:.4f}, "
                  f"Precision={dt['precision']:.4f}, "
                  f"Recall={dt['recall']:.4f}, F1={dt['f1']:.4f} "
                  f"(позитивный класс — «является решением ANSC»)."]
    ex = metrics.get("excluded_non_decision") or {}
    lines += ["",
              f"Исключены из оценки качества исходов (не `ansc_decision`): "
              f"{ex.get('n', 0)} "
              f"(other_document {ex.get('other_document', 0)}, "
              f"uncertain {ex.get('uncertain', 0)}); "
              f"оценка исходов построена на n={metrics['n_evaluated']} "
              f"подтверждённых решениях."]

    lv = metrics.get("link_verification") or {}
    lines += [
        "",
        "### Связь документ→процедура",
        "",
        "| Проверка связи | N |",
        "|---|---:|",
        f"| `confirmed` | {lv.get('confirmed', 0)} |",
        f"| `rejected` (ошибка привязки) | {lv.get('rejected', 0)} |",
        f"| `uncertain` | {lv.get('uncertain', 0)} |",
        f"| не заполнено / нет колонки | {lv.get('unfilled', 0)} |",
        "",
        f"Частота неправильных связей (`mislink:` в notes или "
        f"`rejected`): {metrics['mislink_share']:.1%} "
        f"({metrics['mislink_rows']} из {metrics['n_labeled']}).",
    ]

    conf = metrics.get("metrics_confirmed_decisions") or {}
    lines += ["", "### Метрики ТОЛЬКО на документах, подтверждённых как "
                  "решения ANSC (связь `confirmed`)", ""]
    if conf.get("n"):
        lines += ["| Метрика | Значение |",
                  "|---|---:|",
                  f"| N | {conf['n']} |",
                  f"| Accuracy | {conf['accuracy']:.4f} |",
                  f"| Macro-F1 | {conf['macro_f1']:.4f} |"]
    else:
        lines += ["Нет ни одной строки со связью `confirmed` — метрики по "
                  "этому подмножеству не вычисляются."]

    lines += [
        "",
        f"### Несколько жалоб в одном документе: "
        f"{metrics.get('multi_complaint_rows', 0)} строк(и) с маркером "
        f"`multiple:` — разбираются отдельно, не сводятся к одной "
        f"бинарной метке.",
        "",
        "## Ограничения",
        "",
        "- **стратифицированная выборка 50 документов не обязательно "
        "репрезентативна для всего корпуса** (минимум 3 на редкий класс); "
        "доли нужно взвешивать перед экстраполяцией;",
        "- выборка из 50 документов относится к опрошенным документам ANSC "
        "(выборочная ошибка немалая для редких классов);",
        "- возможны ошибки привязки документ→процедура и апелляционное "
        "смещение (решения, обжалованные повторно, представлены иначе);",
        "- OCR искажает румынские диакритики — часть расхождений на сканах "
        "объясняется качеством распознавания, а не правилом;",
        "- решение ANSC — результат административного спора, а не "
        "доказательство нарушения; возможны судебные изменения;",
        "- это оценка ИЗВЛЕЧЕНИЯ по правилу, а не сравнение моделей: "
        "никаких научных выводов о превосходстве моделей на данном этапе "
        "не делается.",
        "",
        f"> {DISCLAIMER_EN}",
        "",
        f"> {DISCLAIMER_RU}",
        "",
    ]
    return "\n".join(lines)


def merge_review(rows: list[dict], review_path: Path | None
                 ) -> tuple[list[dict], int, int]:
    """Overlay the BLIND review file onto the machine sample by URL.

    The review file (scripts/46) is the human artefact: where it has a row
    for a sampled URL, its non-empty ``reviewer_*`` cells win and its
    columns become REQUIRED (empty cells block the metrics - exit 5).
    Returns ``(rows, n_matched, n_review_only)``; sample rows without a
    review match keep their own (legacy) columns.
    """
    review_rows: dict[str, dict] = {}
    if review_path is not None and review_path.exists():
        for r in load_rows(review_path):
            review_rows.setdefault(r.get("document_url", ""), r)
    if not review_rows:
        return rows, 0, 0
    matched = 0
    sample_urls = {r.get("document_url", "") for r in rows}
    for row in rows:
        rr = review_rows.get(row.get("document_url", ""))
        if rr is None:
            continue
        matched += 1
        for f in REVIEWER_FIELDS:
            row.setdefault(f, "")
            if (rr.get(f) or "").strip():
                row[f] = rr.get(f)          # the human artefact wins
    unmatched_review = sum(1 for u in review_rows if u not in sample_urls)
    return rows, matched, unmatched_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default=str(IN_SAMPLE))
    parser.add_argument("--outcomes", default=str(IN_OUTCOMES))
    parser.add_argument("--review", default=str(IN_REVIEW),
                        help="blind review file with the human labels "
                             "(MTA-0019); pass '' to disable the overlay")
    args = parser.parse_args(argv)

    sample_path = Path(args.sample)
    try:
        rows = load_rows(sample_path)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 4
    if not rows:
        print(f"empty sample: {sample_path}", file=sys.stderr)
        return 4

    review_path = Path(args.review) if args.review else None
    rows, matched, review_only = merge_review(rows, review_path)

    labelrep = label_status(rows)
    if labelrep["invalid"]:
        print("invalid reviewer values (enums: "
              + "; ".join(f"{k}={'|'.join(v)}" for k, v in ENUMS.items())
              + "):", file=sys.stderr)
        for bad in labelrep["invalid"]:
            print(f"  line {bad['line']}: {bad['value']!r} "
                  f"({bad['decision_id']})", file=sys.stderr)
        payload = build_progress(labelrep)
        payload["status"] = "invalid_labels"
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        return 6

    if labelrep["missing"]:
        payload = build_progress(labelrep)
        payload["review_file"] = str(review_path) if review_path else None
        payload["review_rows_matched"] = matched
        payload["review_rows_unmatched"] = review_only
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(json.dumps({"status": payload["status"],
                          "n_labeled": payload["n_labeled"],
                          "n_total": payload["n_total"],
                          "n_missing": len(payload["missing_rows"]),
                          "metrics": None}, ensure_ascii=False, indent=1))
        print("refusing to compute metrics: the manual review is "
              "incomplete (see the JSON for the list of rows).",
              file=sys.stderr)
        return 5

    layer_by_url: dict[str, str] = {}
    outcomes_path = Path(args.outcomes)
    if outcomes_path.exists():
        for r in load_rows(outcomes_path):
            layer_by_url.setdefault(r.get("url", ""),
                                    r.get("text_layer", ""))
    metrics = compute_metrics(labelrep["valid"], layer_by_url)

    payload = {
        "task": "MTA-0018",
        "part": "5 - quality metrics vs manual review",
        "generated": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "status": "metrics_computed",
        "sample_csv": str(sample_path),
        "review_file": str(review_path) if review_path else None,
        "review_rows_matched": matched,
        "metrics": metrics,
        "manual_review_status": "complete",
        "note": "Agreement of the rule-based extractor with independent "
                "human labels; not a model evaluation, no scientific "
                "claim of model superiority. Outcome metrics cover only "
                "rows confirmed as ANSC decisions; document-type and link "
                "quality cover every reviewed row (MTA-0019 §4/§5).",
        "disclaimer_ru": DISCLAIMER_RU,
        "disclaimer_en": DISCLAIMER_EN,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(build_report(metrics, sample_path), encoding="utf-8")
    print(json.dumps({"status": "metrics_computed",
                      "n_labeled": metrics["n_labeled"],
                      "accuracy": metrics["accuracy"],
                      "macro_f1": metrics["macro_f1"],
                      "unknown_share_extracted":
                          metrics["unknown_share_extracted"],
                      "mislink_share": metrics["mislink_share"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
