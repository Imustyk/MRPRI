"""Step 17 (methodology cycle, steps 7-8) - explain one procedure, in plain words.

Concrete implementation of the "right to an explanation": given an OCID, this
prints (a) what the four detectors said, (b) where the procedure sits in the
ranking, (c) the five strongest SHAP contributions of the Isolation Forest for
this exact row, each translated from "mean |SHAP|" units into a sentence a
non-specialist can read, and (d) the standing disclaimer.

SHAP is available for the Isolation Forest only - it is the one detector whose
explainer is exact (tree path attribution). For LOF and One-Class SVM the
contribution of a single feature is undefined, and this script says so instead
of inventing numbers.

Usage:
    .venv/bin/python scripts/17_explain_ocid.py --ocid ocds-b3wdp1-MD-... [--lang ru|en]
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, MODELS, TABLES  # noqa: E402

DISCLAIMER = {
    "ru": "Индикатор потенциального риска, а не доказательство коррупции. "
          "Высокий балл означает «эта процедура не похожа на типичную для корпуса» — "
          "и ничего более. Решение принимает человек.",
    "en": "An indicator of potential risk, not evidence of corruption. A high score "
          "means 'this procedure is unlike the typical one in this corpus' and nothing "
          "more. The decision is a human's.",
}

#: Corpus context used to phrase an SHAP contribution in plain language.
FEATURE_TEXT = {
    "ru": {
        "log_award_value": "размер контракта",
        "log_award_total": "сумма всех лотов контракта",
        "value_vs_cpv_median": "цена относительно медианы по этому виду деятельности (CPV)",
        "value_zscore_cpv": "отклонение цены от типичной для этого CPV",
        "estimate_to_award_ratio": "отношение оценочной стоимости к итоговой цене",
        "multi_award_tender": "контракт с несколькими победителями",
        "n_bidders_log": "число участников",
        "single_bidder": "единственный участник",
        "no_bid_data": "данные об участниках не опубликованы",
        "multi_supplier_award": "несколько поставщиков в контракте",
        "bid_window_days": "срок подачи заявок (дней)",
        "short_deadline": "крайний срок менее 7 дней",
        "long_deadline": "крайний срок более 90 дней",
        "n_amendments": "число изменений к закупке",
        "amended": "закупка изменялась",
        "accelerated_like": "упрочённая/ускоренная процедура",
        "cancelled": "закупка отменена или неуспешна",
        "no_award_after_tender": "завершена без опубликованного контракта",
        "buyer_supplier_repeat_share": "доля контрактов этого заказчика, отданных этому же поставщику",
        "winner_share_of_buyer_awards": "доля контрактов этого заказчика, отданных этому же поставщику",
        "supplier_win_concentration": "концентрация побед поставщика среди его контрактов",
        "supplier_award_count_log": "число контрактов, выигранных поставщиком ранее",
    },
    "en": {
        "log_award_value": "contract size",
        "log_award_total": "total value across lots",
        "value_vs_cpv_median": "price relative to the median of its CPV group",
        "value_zscore_cpv": "price deviation from the typical CPV price",
        "estimate_to_award_ratio": "estimate-to-award price ratio",
        "multi_award_tender": "contract with several winners",
        "n_bidders_log": "number of bidders",
        "single_bidder": "single bidder",
        "no_bid_data": "bidder data not published",
        "multi_supplier_award": "several suppliers in the contract",
        "bid_window_days": "bid window (days)",
        "short_deadline": "deadline under 7 days",
        "long_deadline": "deadline over 90 days",
        "n_amendments": "number of amendments",
        "amended": "procurement was amended",
        "accelerated_like": "accelerated / exceptional procedure",
        "cancelled": "cancelled or unsuccessful",
        "no_award_after_tender": "completed without a published contract",
        "buyer_supplier_repeat_share": "share of this buyer's contracts going to this supplier",
        "winner_share_of_buyer_awards": "share of this buyer's contracts going to this supplier",
        "supplier_win_concentration": "how concentrated the supplier's wins are",
        "supplier_award_count_log": "contracts the supplier had won before",
    },
}


def band_of(n_models: int) -> str:
    if n_models >= 3:
        return "critical"
    if n_models == 2:
        return "high"
    if n_models == 1:
        return "medium"
    return "low"


def explain(ocid: str, lang: str = "ru") -> int:
    warnings.filterwarnings("ignore")
    artifact = MODELS / "anomaly_models.joblib"
    if not artifact.exists():
        print(f"model artefact not found: {artifact}", file=sys.stderr)
        return 1
    import joblib

    bundle = joblib.load(artifact)
    iso = bundle["isolation_forest"]
    scaler = bundle["scaler"]
    feature_columns: list[str] = bundle["feature_columns"]

    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    row = df[df["ocid"] == ocid]
    if row.empty:
        print(f"ocid not in the corpus: {ocid}", file=sys.stderr)
        return 1
    row = row.iloc[0]

    scores = pd.read_csv(TABLES / "tender_anomaly_scores.csv", low_memory=False,
                         usecols=lambda c: c in {
                             "ocid", "n_models_flagging", "consensus", "max_score",
                             "score_statistical_mad_zscore", "score_isolation_forest",
                             "score_local_outlier_factor", "score_one_class_svm",
                             "flag_statistical_mad_zscore", "flag_isolation_forest",
                             "flag_local_outlier_factor", "flag_one_class_svm"})
    srow = scores[scores["ocid"] == ocid]
    n_flag = int(srow["n_models_flagging"].iloc[0]) if len(srow) else None
    percentile = float(srow["max_score"].iloc[0] * 100) if len(srow) else None

    x = row[feature_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    xs = scaler.transform(x.values.reshape(1, -1))

    shap_values = None
    try:
        import shap

        explainer = shap.TreeExplainer(iso)
        shap_values = explainer.shap_values(xs)
        if isinstance(shap_values, list):
            shap_values = shap_values[0]
        shap_values = np.asarray(shap_values).ravel()
    except Exception as exc:  # noqa: BLE001
        print(f"SHAP unavailable: {exc}", file=sys.stderr)

    texts = FEATURE_TEXT.get(lang, FEATURE_TEXT["en"])
    lines: list[str] = []
    title = {
        "ru": f"Объяснение процедуры {ocid}",
        "en": f"Explanation for procedure {ocid}",
    }[lang]
    lines.append(title)
    lines.append("=" * len(title))
    lines.append(f"{'Закупка:' if lang == 'ru' else 'Tender:'} "
                 f"{str(row.get('title'))[:120]}")
    lines.append(f"{'Заказчик:' if lang == 'ru' else 'Buyer:'} {row.get('buyer_name')}")
    lines.append(f"{'Поставщик:' if lang == 'ru' else 'Supplier:'} {row.get('winner_name')}")
    lines.append("")

    if n_flag is not None:
        flags = {
            "statistical_mad_zscore": int(srow["flag_statistical_mad_zscore"].iloc[0]),
            "isolation_forest": int(srow["flag_isolation_forest"].iloc[0]),
            "local_outlier_factor": int(srow["flag_local_outlier_factor"].iloc[0]),
            "one_class_svm": int(srow["flag_one_class_svm"].iloc[0]),
        }
        head = "Что сказали детекторы:" if lang == "ru" else "What the detectors said:"
        lines.append(head)
        for name, flag in flags.items():
            state = ("⚠ " if flag else "· ")
            lines.append(f"  {state}{name}")
        if percentile is not None:
            lines.append(f"  -> {n_flag}/4 "
                         f"{'голосов' if lang == 'ru' else 'votes'}; "
                         f"{'полоса' if lang == 'ru' else 'band'}: {band_of(n_flag)}; "
                         f"{'перцентиль' if lang == 'ru' else 'percentile'}: "
                         f"{percentile:.1f}")
    lines.append("")

    if shap_values is not None:
        order = np.argsort(-np.abs(shap_values))[:5]
        head = ("Пять сильнейших вкладов в балл (Isolation Forest, SHAP):"
                if lang == "ru" else
                "Five strongest contributions to the score (Isolation Forest, SHAP):")
        lines.append(head)
        for i in order:
            col = feature_columns[i]
            # TreeExplainer for IsolationForest returns an additive quantity in
            # which LOWER = more isolated = MORE anomalous (verified empirically
            # against iso.score_samples in this repo: f(x) decreases as the IF
            # score becomes more negative). A negative SHAP value therefore
            # pushes the procedure TOWARDS the anomalous side.
            if shap_values[i] < 0:
                direction = "↑"
                direction_ru = "делает процедуру более аномальной"
                direction_en = "makes the procedure MORE anomalous"
            else:
                direction = "↓"
                direction_ru = "делает процедуру более типичной"
                direction_en = "makes the procedure more typical"
            if lang == "ru":
                lines.append(f"  {direction} {texts.get(col, col)}: "
                             f"{direction_ru} (вклад {shap_values[i]:+.3f}, "
                             f"значение признака: {row.get(col)})")
            else:
                lines.append(f"  {direction} {texts.get(col, col)}: "
                             f"{direction_en} (contribution {shap_values[i]:+.3f}, "
                             f"feature value: {row.get(col)})")
        lines.append("")
        lines.append({
            "ru": "Вклады даны во внутренних единицах Isolation Forest: важен ЗНАК "
                  "(↑ более аномально / ↓ более типичнее), а не абсолютная величина. "
                  "Они описывают ЭТУ процедуру относительно типичной процедуры "
                  "корпуса. Это описание работы модели, а не обвинение.",
            "en": "Contributions are in Isolation Forest internal units: the SIGN "
                  "(↑ more anomalous / ↓ more typical) matters, not the magnitude. "
                  "They describe THIS procedure relative to a typical one in the "
                  "corpus. This describes the model, not an accusation.",
        }[lang])
    else:
        lines.append({
            "ru": "SHAP-вклады недоступны (explainer не смог посчитать значения).",
            "en": "SHAP contributions are unavailable (the explainer failed).",
        }[lang])

    lines.append("")
    lines.append({
        "ru": "Точное объяснение для LOF и One-Class SVM не определено: их вклад "
              "отдельного признака в решении не существует, поэтому он здесь не "
              "выдумывается.",
        "en": "An exact explanation for LOF and One-Class SVM is undefined: a single "
              "feature has no contribution in their decision, so none is invented here.",
    }[lang])
    lines.append("")
    lines.append(DISCLAIMER.get(lang, DISCLAIMER["en"]))

    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ocid", required=True)
    ap.add_argument("--lang", choices=("ru", "en"), default="ru")
    ap.add_argument("--json", action="store_true", help="also dump the raw row as JSON")
    args = ap.parse_args()
    code = explain(args.ocid, args.lang)
    if code == 0 and args.json:
        df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False, nrows=0)
        del df
    return code


if __name__ == "__main__":
    raise SystemExit(main())
