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
    "v5_group_percentile": "процентиль внутри группы «полоса стоимости × тип "
                           "процедуры»: консенсус/κ идентичны v0 (меняется "
                           "только ранжирование); стабильность top-200 и PSI "
                           "выросли, размер-доминирование в топ-200 снижено "
                           "(≥50 млн: 11×→2,9×), но holdout AUC 0,425 с ДИ "
                           "[0,396; 0,452] целиком ниже 0,5 — v5 значимо "
                           "ранжирует метки AAP как менее рискованные "
                           "(условие 2 завершения не выполняется); кластерный "
                           "ДИ ΔAUC пересекает ноль — компромисс, не "
                           "принимается; прод остаётся v0",
    "v6_group_flags": "нормировка до флагов: флаг детектора = верхние 5% "
                      "внутри группы «полоса × тип», консенсус ≥ 3 голосов "
                      "(доля флагов ~5% в каждой группе по построению — риск "
                      "относителен внутри группы); первый вариант с C3 "
                      "(годовой разброс доли консенсуса 0,159→0,537 ≥ 0,25) и "
                      "κ выросла 0,250→0,299 (порог 0,40 не достигнут); аудит "
                      "на своих голосах: размер в high+ упал (≥50 млн "
                      "50,9%→14,6%, disparity 10,5×→3,23×), прямые закупки "
                      "в допустимой полосе (0,21→1,13), но всего вердиктов 41 "
                      "против 32 у v0; потеряно 50,8% v0-critical, C5-holdout "
                      "провален; AUC = v5 (ранжирование то же), holdout 0,425 — "
                      "значимо ниже 0,5; компромисс, не принимается; прод "
                      "остаётся v0",
}


#: the convergence threshold, fixed a priori and APPROVED by the author
#: in MTA-0007
CRIT_KAPPA = 0.40


def completion_status(variants: dict) -> dict:
    """The four closing conditions, computed from cycle_framework.json.

    (1) convergence: some version reaches mean pairwise kappa >= CRIT_KAPPA;
    (2) period stability: no version flips the sign of the external AUC
        between the tuning and holdout splits, AND no version is significantly
        NEGATIVE (a split whose AUC bootstrap CI lies entirely below 0.5):
        the author's MTA-0008 ruling - a stably negative association is
        stability of a wrong-direction association, not convergence, and is
        not credited to this condition;
    (3) circularity: section B (scripts/21) — fixed artefact, 7/7;
    (4) the holdout-AUC bootstrap CIs of every consecutive version pair
        overlap — a single broken link fails the condition (conservative
        reading; for the data-hygiene variants v4/v4b the literal reading
        is additionally inappropriate — their CIs overlap v0).
    """
    names = list(variants)
    kappa_max = max(b["agreement"]["mean_kappa"] for b in variants.values())

    def _flip(block):
        e = block["external"]
        return ((e["tuning_2018_2021"]["roc_auc"] - 0.5)
                * (e["holdout_2022_2024"]["roc_auc"] - 0.5) < 0)

    def _anti_splits(block) -> list[str]:
        """Splits whose AUC CI lies entirely below 0.5 (anti-correlated)."""
        e = block["external"]
        out = []
        for split in ("tuning_2018_2021", "holdout_2022_2024"):
            ci = e[split].get("roc_auc_ci")
            if ci and ci[1] < 0.5:
                out.append(split)
        return out

    flips = [n for n, b in variants.items() if _flip(b)]
    anti = {n: _anti_splits(b) for n, b in variants.items()
            if _anti_splits(b)}
    bad_pairs = []
    for a, b in zip(names, names[1:]):
        cia = variants[a]["external"]["holdout_2022_2024"]["roc_auc_ci"]
        cib = variants[b]["external"]["holdout_2022_2024"]["roc_auc_ci"]
        if not (cia[0] <= cib[1] and cib[0] <= cia[1]):
            bad_pairs.append(f"{a}–{b}")
    checks = {
        "сходимость (κ≥0.40)": kappa_max >= CRIT_KAPPA,
        "устойчивость и знак внешней связи по периодам (ДИ не ниже 0,5)":
            not flips and not anti,
        "круговая логика (scripts/21, 7/7)": True,
        "цепочка ДИ holdout последовательных версий": not bad_pairs,
    }
    return {"checks": checks, "passed": sum(checks.values()),
            "kappa_max": kappa_max, "sign_flips": flips,
            "anti_associated": anti, "bad_pairs": bad_pairs}


def completion_phrase(variants: dict) -> str:
    """Human-readable closing-criterion status from the artefacts only."""
    st = completion_status(variants)
    passed = ", ".join(k for k, ok in st["checks"].items() if ok)
    failed = ", ".join(k for k, ok in st["checks"].items() if not ok)
    anti_txt = "; ".join(f"{n} (ДИ ниже 0,5: {', '.join(s)})"
                         for n, s in st["anti_associated"].items()) or "—"
    return (f"статус — {st['passed']} из {len(st['checks'])}. Выполнены: "
            f"{passed or '—'}; не выполнены: {failed or '—'}. Данные: "
            f"максимальная κ {st['kappa_max']:.3f} (порог {CRIT_KAPPA:.2f} "
            f"утверждён автором, MTA-0007); знак AUC "
            f"меняется между 2018–2021 и 2022–2024: {', '.join(st['sign_flips']) or '—'}; "
            f"значимо отрицательная связь (ДИ AUC целиком ниже 0,5 — в условие 2 "
            f"не засчитывается, MTA-0008): {anti_txt}; "
            f"ДИ holdout без пересечения: {', '.join(st['bad_pairs'])} "
            f"(для вариантов гигиены данных v4/v4b сравнение с предыдущей "
            f"версией некорректно буквально — их ДИ пересекается с v0).")


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
        "данных: варианты v4 и v4b; цикл 5 — основной цикл по задаче автора "
        "MTA-0007, вариант v5; цикл 6 — по задаче автора MTA-0008, вариант "
        "v6; израсходовано 6 из 10); "
        "критерии остановки: C1 κ≥0.40, C2 Jaccard(top-200)≥0.60 и cv "
        "консенсуса ≤10%, C3 годовой разброс доли консенсуса ≥0.25, C5 правило "
        "порога бьёт «не флагировать ничего» при c_miss=200 в обоих периодах, "
        "C6 аудит смещения без невыполненных отклонений (раздел E; добавлен по "
        "требованию автора после остановки цикла, применён ретроактивно ко "
        "всем версиям — проваливают все: 24 нарушения + 8 предупреждений, "
        "`reports/bias_audit.md`).\n"
        "Критерий завершения шлифовки (закрывающее утверждение «модель сходится "
        "и согласуется с независимыми источниками» допустимо только при всех "
        "четырёх условиях): " + completion_phrase(variants) + " "
        "Индикаторы потенциального риска, а не доказательство коррупции.\n")
    REPORTS.mkdir(exist_ok=True)
    report_path = REPORTS / "cycle_dynamics.md"
    report_path.write_text("\n".join(md), encoding="utf-8")
    print(f"report -> {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
