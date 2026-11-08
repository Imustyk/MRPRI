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
OUT_JSON = ROOT / "results" / "methodology" / "ansc_review_metrics.json"
OUT_MD = ROOT / "reports" / "ansc_review_metrics.md"

OUTCOMES = ("admitted", "partially_admitted", "rejected", "inadmissible",
            "withdrawn", "terminated", "unknown")

RE_MISLINK = re.compile(r"\bmislink\b", re.IGNORECASE)

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
    """Classify reviewer_outcome cells: valid / missing / invalid."""
    valid: list[dict] = []
    missing: list[dict] = []
    invalid: list[dict] = []
    for i, row in enumerate(rows, start=2):        # +1 header, +1 to 1-based
        raw = (row.get("reviewer_outcome") or "").strip()
        if not raw:
            missing.append({"line": i,
                            "decision_id": row.get("decision_id", ""),
                            "document_url": row.get("document_url", "")})
        elif raw not in OUTCOMES:
            invalid.append({"line": i, "value": raw,
                            "decision_id": row.get("decision_id", "")})
        else:
            valid.append(row)
    return {"total": len(rows), "valid": valid,
            "missing": missing, "invalid": invalid}


def compute_metrics(labeled: list[dict], layer_by_url: dict[str, str]
                    ) -> dict:
    """All quality metrics over fully labelled rows (pure function)."""
    truth = [(r.get("reviewer_outcome") or "").strip() for r in labeled]
    pred = [(r.get("extracted_outcome") or "").strip() for r in labeled]
    n = len(labeled) or 1

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

    split: dict[str, dict] = {}
    for bucket, want in (("text_layer", "1"), ("scan", "0")):
        idx = [i for i, r in enumerate(labeled)
               if layer_by_url.get(r.get("document_url", "")) == want]
        if not idx:
            split[bucket] = {"n": 0, "accuracy": None}
            continue
        correct = sum(1 for i in idx if truth[i] == pred[i])
        split[bucket] = {"n": len(idx),
                         "accuracy": round(correct / len(idx), 4)}
    unjoined = sum(1 for r in labeled
                   if r.get("document_url", "") not in layer_by_url)

    mislinks = [r for r in labeled
                if RE_MISLINK.search(r.get("reviewer_notes") or "")]
    return {
        "n_labeled": len(labeled),
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "confusion_matrix": matrix,
        "unknown_share_extracted": round(
            sum(1 for p in pred if p == "unknown") / n, 4),
        "unknown_share_reviewer": round(
            sum(1 for t in truth if t == "unknown") / n, 4),
        "mislink_share": round(len(mislinks) / n, 4),
        "mislink_rows": len(mislinks),
        "split_by_source_type": split,
        "rows_without_source_type_join": unjoined,
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
    lines += [
        "",
        "## Ограничения",
        "",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default=str(IN_SAMPLE))
    parser.add_argument("--outcomes", default=str(IN_OUTCOMES))
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

    labelrep = label_status(rows)
    if labelrep["invalid"]:
        print("invalid reviewer_outcome values (must be one of "
              + ", ".join(OUTCOMES) + "):", file=sys.stderr)
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
        "metrics": metrics,
        "manual_review_status": "complete",
        "note": "Agreement of the rule-based extractor with independent "
                "human labels; not a model evaluation, no scientific "
                "claim of model superiority.",
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
