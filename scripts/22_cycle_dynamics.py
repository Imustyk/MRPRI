"""Step 22 - cross-cycle dynamics: the "cycle -> metrics" summary of the addendum.

Reads ``results/methodology/cycle_framework.json`` (produced by
scripts/20 for every version of the iterative cycle) and renders

  * ``results/figures/cycle_dynamics.png`` - ROC-AUC on the tuning split and on
    the holdout split for every version, with the bootstrap confidence
    intervals, plus the consensus load,
  * ``reports/cycle_dynamics.md`` - the same numbers as a table with the
    per-cycle one-line verdicts.

The plot and the table are the "сводная таблица динамики метрик по циклам"
required by section D of the addendum. Decisions inside a cycle are made on
the tuning split only; the holdout column is reported, never used to pick a
version.

Usage:
    .venv/bin/python scripts/22_cycle_dynamics.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import FIGURES, RESULTS  # noqa: E402

REPORTS = RESULTS.parent / "reports"

#: one honest line per cycle; filled from the cycle reports, kept next to the
#: numbers so that a reader sees why a version was or was not adopted
CYCLE_VERDICTS = {
    "v0_baseline": "референс: прод-конфигурация, воспроизведена точно "
                   "(Jaccard рефита к выгрузке 1.0)",
    "v1_merge_duplicate": "дубликат-колонка объединена: внешний AUC вырос "
                          "в пределах ДИ, число консенсусов упало на 21% — "
                          "не принимается автоматически, вопрос автору",
    "v2_mean_rank": "смена правила ранжирования max→mean: на tuning "
                    "деградация за пределами ДИ — отклонено по протоколу",
    "v3_drop_behavioural": "удаление поведенческой группы: внешний AUC растёт, "
                           "но рушится согласованность ансамбля — "
                           "не принимается, фиксируется как свойство данных",
    "v4_datafix": "авторский замер артефактов данных (нормализация id, потолки "
                  "сумм, чистка плейсхолдеров) + дубликат удалён как в v1: "
                  "внешние метрики не изменились в пределах ДИ",
    "v4b_datafix_keep_duplicate": "те же артефакты данных, но с сохранённым "
                                  "дубликатом: отделяет эффект исправлений "
                                  "данных от эффекта дубликата",
}


def main() -> int:
    payload = json.loads(
        (RESULTS / "methodology" / "cycle_framework.json").read_text(encoding="utf-8"))
    variants = payload["variants"]

    rows = []
    for name, block in variants.items():
        ext = block["external"]
        rows.append({
            "version": name,
            "features": block["n_features"],
            "consensus_n": block["bands"]["consensus_n"],
            "auc_tuning": ext["tuning_2018_2021"]["roc_auc"],
            "auc_tuning_ci": ext["tuning_2018_2021"].get("roc_auc_ci"),
            "auc_holdout": ext["holdout_2022_2024"]["roc_auc"],
            "auc_holdout_ci": ext["holdout_2022_2024"].get("roc_auc_ci"),
            "consensus_precision_tuning":
                ext["tuning_2018_2021"]["consensus_precision"],
            "consensus_precision_holdout":
                ext["holdout_2022_2024"]["consensus_precision"],
            "mean_kappa": block["agreement"]["mean_kappa"],
            "top200_jaccard": block["stability"]["top_n_jaccard_mean"],
            "stop_criteria": f"{block['stop_criteria_passed']}/{len(block['stop_criteria'])}",
            "delta_auc_vs_v0_tuning": (block.get("paired_delta_vs_v0_tuning") or {})
                .get("delta"),
            "delta_ci": ([(block["paired_delta_vs_v0_tuning"]["ci_lo"],
                           block["paired_delta_vs_v0_tuning"]["ci_hi"])]
                         if "paired_delta_vs_v0_tuning" in block else None),
            "verdict": CYCLE_VERDICTS.get(name, ""),
        })
    table = pd.DataFrame(rows)

    # ---- figure: cycle -> AUC with CIs -----------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    x = range(len(table))
    for ax, col, ci_col, color, label in (
        (ax1, "auc_tuning", "auc_tuning_ci", "tab:blue", "tuning 2018–2021"),
        (ax1, "auc_holdout", "auc_holdout_ci", "tab:orange", "holdout 2022–2024"),
    ):
        y = table[col].astype(float)
        err_lo = [v - ci[0] if ci else 0 for v, ci in zip(y, table[ci_col])]
        err_hi = [ci[1] - v if ci else 0 for v, ci in zip(y, table[ci_col])]
        ax.errorbar(list(x), y, yerr=[err_lo, err_hi], marker="o", capsize=4,
                    color=color, label=label)
    ax1.axhline(0.5, color="grey", lw=1, ls="--")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(table["version"], rotation=25, ha="right", fontsize=8)
    ax1.set_ylabel("ROC-AUC (внешняя метка AAP)")
    ax1.set_title("Внешний AUC по версиям, ДИ 95% (бутстрап)")
    ax1.legend(fontsize=8)

    ax2.bar(list(x), table["consensus_n"].astype(int), color="tab:green", alpha=0.6,
            label="консенсус, шт")
    ax2b = ax2.twinx()
    ax2b.plot(list(x), table["mean_kappa"].astype(float), marker="s", color="tab:red",
              label="средний kappa")
    ax2b.axhline(0.4, color="red", lw=1, ls=":")
    ax2b.set_ylabel("средний попарный kappa")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(table["version"], rotation=25, ha="right", fontsize=8)
    ax2.set_ylabel("консенсус, шт")
    ax2.set_title("Нагрузка полосы и согласованность ансамбля")
    fig.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig_path = FIGURES / "cycle_dynamics.png"
    fig.savefig(fig_path, dpi=140)
    print(f"figure -> {fig_path}")

    # ---- markdown summary -------------------------------------------------
    md = ["# Динамика метрик по циклам итеративной валидации\n",
          "Генерится `scripts/22_cycle_dynamics.py` из "
          "`results/methodology/cycle_framework.json`. Решения принимаются по "
          "колонке **tuning (2018–2021)**; holdout (2022–2024) приводится только "
          "для оценки и не участвует в выборе версии. Полосы консенсуса = "
          "«≥3 детектора из 4», правило фиксировано априори.\n",
          "| версия | фич | консенсус | AUC tuning (ДИ) | AUC holdout (ДИ) | "
          "precision консенсуса tuning / holdout | κ | top-200 J | критерии остановки | "
          "ΔAUC vs v0 (tuning) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ci_t = f" [{r['auc_tuning_ci'][0]}, {r['auc_tuning_ci'][1]}]" \
            if r["auc_tuning_ci"] else ""
        ci_h = f" [{r['auc_holdout_ci'][0]}, {r['auc_holdout_ci'][1]}]" \
            if r["auc_holdout_ci"] else ""
        delta = ""
        if r["delta_auc_vs_v0_tuning"] is not None:
            delta = (f"{r['delta_auc_vs_v0_tuning']:+.4f} "
                     f"[{r['delta_ci'][0][0]:+.4f}, {r['delta_ci'][0][1]:+.4f}]")
        md.append(
            f"| {r['version']} | {r['features']} | {r['consensus_n']:,} | "
            f"{r['auc_tuning']}{ci_t} | {r['auc_holdout']}{ci_h} | "
            f"{r['consensus_precision_tuning']} / {r['consensus_precision_holdout']} | "
            f"{r['mean_kappa']} | {r['top200_jaccard']} | {r['stop_criteria']} | {delta} |")
    md.append("\n![динамика](../results/figures/cycle_dynamics.png)\n")
    md.append("## Вердикты по циклам\n")
    for r in rows:
        md.append(f"- **{r['version']}** — {r['verdict']}.")
    md.append(
        "\nПротокол: одно изменение за цикл, журнал — `cycle_log.md`; "
        "остановка по протоколу после 3 циклов подряд без улучшения за "
        "пределами ДИ (цикл 4 — дополнительный авторский замер артефактов "
        "данных: варианты v4 и v4b, израсходовано 4 из 10); "
        "критерии остановки: C1 κ≥0.40, C2 Jaccard(top-200)≥0.60 и cv "
        "консенсуса ≤10%, C3 годовой разброс доли консенсуса ≥0.25, C5 правило "
        "порога бьёт «не флагировать ничего» при c_miss=200 в обоих периодах, "
        "C6 аудит смещения без невыполненных отклонений (раздел E; добавлен по "
        "требованию автора после остановки цикла, применён ретроактивно ко "
        "всем версиям — проваливают все: 24 нарушения + 8 предупреждений, "
        "`reports/bias_audit.md`).\n"
        "Критерий завершения шлифовки (закрывающее утверждение «модель сходится "
        "и согласуется с независимыми источниками» допустимо только при всех "
        "четырёх условиях): сходимость (κ≥0.40), устойчивость по сидам/бутстрапу/"
        "периодам, круговая логика проверена, holdout-метрики двух последних "
        "версий стабильны. На конец цикла 3 статус — 2 из 4: выполнены круговая "
        "логика и стабильность holdout между последними версиями (v2 0.544 "
        "[0.516, 0.570] и v3 0.580 [0.558, 0.601] — ДИ пересекаются), не "
        "выполнены сходимость (κ 0.186–0.250) и устойчивость периодов (знак AUC "
        "меняется между 2018–2021 и 2022–2024 во всех версиях). После цикла 4 "
        "статус — 1 из 4 (консервативная трактовка условия «две последние "
        "версии»: ДИ holdout v3 [0.558, 0.601] и v4 [0.504, 0.554] не "
        "пересекаются; для вариантов гигиены данных (v4, v4b) буквальная "
        "трактовка некорректна — их ДИ пересекается с v0 [0.490, 0.544], "
        "v4b [0.488, 0.541]). "
        "Индикаторы потенциального риска, а не доказательство коррупции.\n")
    REPORTS.mkdir(exist_ok=True)
    report_path = REPORTS / "cycle_dynamics.md"
    report_path.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
