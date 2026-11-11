"""Write the three reports from the measured JSON files.

The prose states what was counted. It does not rank the detectors and it does
not call a current snapshot a historical certificate.

    .venv/bin/python scripts/58_write_reports.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "results" / "mta0024_stage_periods" / "quality.json"
SUMMARY_PATH = ROOT / "results" / "mta0024_stage_periods" / "summary.json"
EXPERIMENT = ROOT / "results" / "mta0025_closed_experiment" / "experiment_summary.json"
REPORTS = ROOT / "reports"

DRAFT_HASHES = {
    "src/mtender/stage_periods.py": "882d0ac29d7f7c526c518b39fec7daf597720201367133b7b49372669fa4462c",
    "tests/test_stage_periods.py": "60096e34da844dbb4e5c5ec373b53d169790eff422eab32983b5023b5d4084b5",
    "scripts/55_stage_period_export.py": "cf5e257c806c2c6803ba331398c1f8b02ff95b25c64216b09bc21dcbeb06cc3b",
}

METHOD_LABELS = {
    "mad": "MAD",
    "isolation_forest": "Isolation Forest",
    "lof": "LOF",
    "one_class_svm": "One-Class SVM",
    "ensemble": "ансамбль",
    "simple_indicators": "простые индикаторы",
}

ARM_LABELS = {
    "legacy": "Legacy",
    "stage_consistent": "Stage-consistent",
    "ablation": "Ablation",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def nfmt(value: int | float) -> str:
    return f"{int(round(float(value))):,}".replace(",", " ")


def pfmt(part: float, whole: float) -> str:
    if not whole:
        return "0%"
    return f"{100.0 * part / whole:.2f}%"


def rfmt(value) -> str:
    if value is None:
        return "н/о"
    return f"{float(value):.3f}"


def sfmt(value) -> str:
    if value is None:
        return "н/о"
    return f"{float(value):.1f}"


def gfmt(value) -> str:
    if value is None:
        return "н/о"
    return f"{float(value):.3f}"


def _pair(experiment: dict, left: str, right: str, method: str) -> dict:
    for row in experiment["pairwise"]:
        if row["left"] == left and row["right"] == right and row["method"] == method:
            return row
    raise KeyError((left, right, method))


def _stability(value) -> str:
    if value is None:
        return "Корреляция рангов не определена."
    magnitude = abs(float(value))
    if magnitude >= 0.9:
        band = "высокая"
    elif magnitude >= 0.7:
        band = "умеренная"
    else:
        band = "низкая"
    return f"Устойчивость ранжирования {band} (Спирмен {rfmt(value)})."


def _bins_table(bins: dict) -> str:
    labels = [
        ("missing", "нет значения"),
        ("0", "0"),
        ("1_to_6", "1–6"),
        ("7_to_14", "7–14"),
        ("15_to_29", "15–29"),
        ("30", "ровно 30"),
        ("31_to_90", "31–90"),
        ("91_to_365", "91–365"),
        ("366_to_3650", "366–3650"),
        ("above_3650", "больше 3650"),
    ]
    lines = ["| Интервал, сутки | Число процедур |", "|---:|---:|"]
    for key, label in labels:
        lines.append(f"| {label} | {nfmt(bins.get(key, 0))} |")
    return "\n".join(lines)


def _method_table(experiment: dict) -> str:
    lines = [
        "| Метод | Legacy, флаги | Stage-consistent, флаги | Ablation, флаги |",
        "|---|---:|---:|---:|",
    ]
    for method, label in METHOD_LABELS.items():
        cells = []
        for arm in ("legacy", "stage_consistent", "ablation"):
            payload = experiment["arms"][arm]["methods"][method]
            cells.append(f"{nfmt(payload['n_flagged'])} ({payload['pct_flagged']:.2f}%)")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _seconds_table(experiment: dict) -> str:
    lines = [
        "| Метод | Legacy, с | Stage-consistent, с | Ablation, с |",
        "|---|---:|---:|---:|",
    ]
    for method, label in METHOD_LABELS.items():
        cells = [
            f"{float(experiment['arms'][arm]['methods'][method]['seconds']):.3f}"
            for arm in ("legacy", "stage_consistent", "ablation")
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    totals = [f"{float(experiment['arms'][arm]['seconds_total']):.3f}" for arm in ("legacy", "stage_consistent", "ablation")]
    lines.append("| Все методы рукава | " + " | ".join(totals) + " |")
    return "\n".join(lines)


def _pairwise_table(experiment: dict, left: str, right: str) -> str:
    lines = [
        f"| Метод | Спирмен | Жаккар флагов | Top-100 | Top-1000 | Медиана \\|Δ перцентиля\\| |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for method, label in METHOD_LABELS.items():
        row = _pair(experiment, left, right, method)
        top100 = row["topk"]["100"]["overlap"]
        top1000 = row["topk"]["1000"]["overlap"]
        lines.append(
            f"| {label} | {rfmt(row['spearman'])} | {rfmt(row['jaccard'])} | "
            f"{rfmt(top100)} | {rfmt(top1000)} | {gfmt(row['median_abs_percentile_gap'])} |"
        )
    return "\n".join(lines)


def _within_table(experiment: dict, arm: str) -> str:
    lines = ["| Пара | Спирмен | Жаккар флагов |", "|---|---:|---:|"]
    for row in experiment["within_arm"]:
        if row["arm"] != arm:
            continue
        left = METHOD_LABELS[row["left"]]
        right = METHOD_LABELS[row["right"]]
        lines.append(f"| {left} × {right} | {rfmt(row['spearman'])} | {rfmt(row['jaccard'])} |")
    return "\n".join(lines)


def _rate(experiment: dict, arm: str, method: str) -> str:
    payload = experiment["arms"][arm]["methods"][method]
    return f"{nfmt(payload['n_flagged'])} ({payload['pct_flagged']:.2f}%)"


def _simple_tie_lines(score_dir: Path) -> str:
    import pandas as pd

    lines = []
    for arm in ("legacy", "stage_consistent", "ablation"):
        values = pd.read_csv(
            score_dir / f"scores_{arm}.csv.gz", usecols=["score_simple_indicators"]
        )["score_simple_indicators"]
        top = float(values.max())
        lines.append(
            f"- {ARM_LABELS[arm]}: {int(values.nunique())} различных значений, "
            f"максимум {top:.0f}, строк с максимумом {nfmt(int((values == top).sum()))}."
        )
    return "\n".join(lines)


def _mad_line(experiment: dict, arm: str) -> str:
    params = experiment["arms"][arm]["methods"]["mad"]["params"]
    scored = ", ".join(params["scored_features"]) or "нет"
    spiked = ", ".join(params["spike_like_features_excluded"]) or "нет"
    constant = ", ".join(params["constant_features_excluded"]) or "нет"
    binary = ", ".join(params["binary_features_excluded"]) or "нет"
    return (
        f"- {ARM_LABELS[arm]}: в z-score вошли `{scored}`. "
        f"Исключены как spike-like: `{spiked}`. "
        f"Исключены как константы: `{constant}`. "
        f"Бинарные, не входящие в z-score: `{binary}`."
    )


def _changed_table(experiment: dict) -> str:
    lines = [
        "| Метод | Спирмен на изменившихся | Спирмен на неизменных | Медиана \\|Δ\\| на изменившихся | Медиана \\|Δ\\| на неизменных |",
        "|---|---:|---:|---:|---:|",
    ]
    for method, label in METHOD_LABELS.items():
        row = _pair(experiment, "legacy", "stage_consistent", method)
        lines.append(
            f"| {label} | {rfmt(row['spearman_where_period_changed'])} | "
            f"{rfmt(row['spearman_where_period_unchanged'])} | "
            f"{gfmt(row['median_abs_percentile_gap_changed'])} | "
            f"{gfmt(row['median_abs_percentile_gap_unchanged'])} |"
        )
    return "\n".join(lines)


def write_feature_report(quality: dict, export_summary: dict) -> str:
    n = quality["join"]["comparable_ocids"]
    observed = quality["evaluation_window_observed"]
    missing = quality["evaluation_window_missing"]
    cross = quality["legacy_cross_stage"]
    filled = quality["value_30_in_legacy_feature"]
    window = quality["observed_stage_window"]
    flags = quality["deadline_flags"]
    dates = quality["reproduced_merge_versus_features"]
    non_cross = quality["evaluation_complete_not_cross_stage"]
    orphan = quality.get("cross_stage_without_evaluation_window", [])
    blank_complete = quality.get("blank_legacy_days_among_evaluation_complete")
    status = quality["submission_window_status"]
    non_cross_lines = "\n".join(
        f"- `{row['ocid']}`: обе границы из `{row['legacy_start_stage']}`, "
        f"stage-consistent {row['bid_window_days']} суток, legacy-признак {row['legacy_bid_window_days']} суток."
        for row in non_cross
    )
    orphan_lines = "\n".join(
        f"- `{row['ocid']}`: статус `{row['submission_window_status']}`, "
        f"старт `{row['legacy_start_stage']}`, конец `{row['legacy_end_stage']}`, "
        f"legacy-признак {row['legacy_bid_window_days']} суток, stage-consistent окно отсутствует."
        for row in orphan
    ) or "- Таких строк нет."
    return f"""# MTA-0024 — исправление периода подачи предложений

Дата расчёта: 2026-11-11. Источник читался только из `/Users/imustyk/Diplom`. Все новые файлы записаны в рабочий каталог, потому что запись в дерево Diplom из этой среды возвращает `Operation not permitted`. Production `features.csv`, `tenders.json` и scores не изменялись. `run_pipeline.sh` не запускался. Повторной загрузки MTender не было. Команды `git reset`, `git clean` и `git checkout --` не выполнялись. Коммит в Diplom не создавался.

## 1. Вопрос

В текущем снимке `merge_compiled_releases` оставляет первое непустое значение. На этом корпусе старт `tenderPeriod` часто берётся из planning notice, а конец — из evaluation notice. Это разные стадии одной процедуры. `engineer_features` затем заменяет отсутствующее число суток константой 30 и ограничивает интервал отрезком [0, 3650]. `short_deadline` и `long_deadline` считаются уже после этой замены.

MTA-0024 отделяет современное stage-consistent извлечение от исторически сертифицированного значения. Сертификат публикации по-прежнему отсутствует: MTA-0022 получил 0/8 подтверждённых t0. Новая таблица описывает текущие compiled releases. Поле `historically_certified` равно 0 в каждой из {nfmt(n)} строк.

## 2. Восстановленный код и контрольные суммы

Отдельного прежнего файла-манифеста с SHA-256 этих черновиков на диске не найдено. Ниже хеши файлов, найденных в рабочем каталоге `mta0024/`, и они побайтово совпали с копиями в `mta_0024_0025/`:

| Файл | SHA-256 |
|---|---|
| `src/mtender/stage_periods.py` | `{DRAFT_HASHES['src/mtender/stage_periods.py']}` |
| `tests/test_stage_periods.py` | `{DRAFT_HASHES['tests/test_stage_periods.py']}` |
| `scripts/55_stage_period_export.py` | `{DRAFT_HASHES['scripts/55_stage_period_export.py']}` |

Пути ввода и вывода переданы аргументами командной строки. Текст трёх файлов для этого не менялся.

SHA-256 прочитанного `data/features/features.csv`: `{quality['features_sha256']}`. Это тот же хеш, который MTA-0022 сверил с `results/mongo/export_manifest.json`. Строк в файле: {nfmt(quality['features_rows'])}.

## 3. Правило извлечения

Окно подачи записывается только тогда, когда в compiled releases есть ровно одна полная пара `tenderPeriod.startDate` и `tenderPeriod.endDate` со стадии evaluation и её длина неотрицательна. Конфликтующие пары, неполная пара, отрицательная длина и отсутствие evaluation record оставляют окно пустым. Пустое значение не заменяется на 30. Planning start не подставляется вместо evaluation start. Длина считается как `floor((end − start) в сутках)` через разбор UTC, то есть так же, как `Series.dt.days`.

Отдельно, только как диагноз старого снимка, воспроизводится прежнее слияние: compiled tag идёт первым, пустые поля заполняются из остальных releases. Если старт и конец после слияния принадлежат разным стадиям, строка помечается `legacy_cross_stage`. Отрицательная длина этого смешанного окна не записывается как срок и не заменяется тридцатью.

Признак для детекторов обрезается сверху значением 3650, как в действующей формуле. На этом корпусе таких строк {nfmt(quality['windows_clipped_at_3650'])}. Необрезанная длина сохранена отдельно. Обрезка не является подстановкой 30.

## 4. Восемь процедур MTA-0022

Все восемь реальных пакетов прочитаны из `data/raw/ocds_packages`. У каждого старт снимка совпал с PN.start, конец смешанного окна совпал с EV.end, а stage-consistent длина совпала с ранее посчитанной EV-only длиной. `historically_certified` у всех восьми равен 0. Эти строки фиксируют ошибку смешения и её исправление на текущем снимке. Они не восстанавливают срок на момент первой публикации.

## 5. Весь корпус

Прочитано пакетов: {nfmt(export_summary['rows_written'])}. Ошибок чтения: {nfmt(export_summary['read_errors'])}. Пересечение с `features.csv` по OCID: {nfmt(n)}. Строк только в одном из источников: {nfmt(quality['join']['features_only'] + quality['join']['periods_only'])}.

| Статус stage-consistent окна | Процедур |
|---|---:|
| `evaluation_complete` | {nfmt(status.get('evaluation_complete', 0))} |
| `no_evaluation_record` | {nfmt(status.get('no_evaluation_record', 0))} |
| `evaluation_incomplete` | {nfmt(status.get('evaluation_incomplete', 0))} |
| `evaluation_conflict` | {nfmt(status.get('evaluation_conflict', 0))} |
| `inverted` | {nfmt(status.get('inverted', 0))} |
| `unparseable` | {nfmt(status.get('unparseable', 0))} |

Наблюдаемое evaluation-окно есть у {nfmt(observed)} процедур ({pfmt(observed, n)}). У {nfmt(missing)} процедур ({pfmt(missing, n)}) его нет. Других статусов экспорт не дал: в этом снимке у evaluation record либо есть одна неотрицательная полная пара, либо evaluation record нет.

Смешанное legacy-окно: {nfmt(cross)} строк ({pfmt(cross, n)}). Из {nfmt(observed)} полных evaluation-окон смешанными являются все, кроме {nfmt(len(non_cross))}. Эти исключения:

{non_cross_lines}

Ещё одна смешанная строка не имеет полного evaluation-окна:

{orphan_lines}

Там конец принадлежит base, а не evaluation. Stage-consistent окно оставлено пустым, хотя legacy-признак равен 30.

Там, где наблюдаются оба числа, смешанное окно длиннее evaluation-окна в {nfmt(export_summary['legacy_longer_than_evaluation'])} процедурах, короче в {nfmt(export_summary['legacy_shorter_than_evaluation'])} и равно ему в {nfmt(export_summary['windows_equal'])}. Совместных наблюдений: {nfmt(export_summary['both_windows_observed'])}.

У {nfmt(blank_complete)} процедур с полным evaluation-окном воспроизведённая смешанная длина пуста. Это отрицательный span после слияния: экспорт не записывает отрицательное число суток. В `features.csv` у всех этих строк нет `tender_end` (расхождений конца, где конец есть в снимке и отсутствует в воспроизведении, {nfmt(quality['date_mismatch']['end_mismatch_reproduced_missing'])}). Действующая нормализация обнуляет конец, если он раньше старта, а следующая формула подставляет 30. Stage-consistent длина при этом существует и в таблицу 30 не пишется.

Совпадение воспроизведённого слияния со снимком `features.csv`: старт совпал в {nfmt(dates['start_dates_equal'])} строках из {nfmt(n)} (расхождений {nfmt(quality['date_mismatch']['start_mismatch'])}), конец совпал в {nfmt(dates['end_dates_equal'])} (расхождений {nfmt(quality['date_mismatch']['end_mismatch'])}). Там, где воспроизведённая длина числовая, она совпала с `bid_window_days` снимка в {nfmt(dates['legacy_days_equal_where_reproduced_numeric'])} строках из {nfmt(dates['reproduced_numeric'])}. Legacy-рукав эксперимента использует сам `features.csv`, а не заново вычисленную длину. Расхождения оставлены в учёте и не подгонялись.

## 6. Константа 30 и короткие сроки

В снимке значение ровно 30 имеют {nfmt(filled['rows'])} процедур ({pfmt(filled['rows'], n)}).

| Группа среди legacy = 30 | Процедур |
|---|---:|
| Stage-consistent окна нет | {nfmt(filled['stage_missing'])} |
| Stage-consistent окно тоже 30 суток | {nfmt(filled['stage_also_30'])} |
| Stage-consistent окно есть и оно другое | {nfmt(filled['stage_other_observed_value'])} |

Все {nfmt(missing)} процедур без evaluation record входят в группу «окна нет». Ни одна строка со stage-consistent окном ровно 30 суток не хранится в снимке как 30. Таких настоящих тридцатидневных evaluation-окон {nfmt(quality['bins_stage_clipped_window']['30'])}. Их legacy-значения лежат в других корзинах:

{_bins_table(quality['stage_30_legacy_feature_bins'])}

Следовательно, литерал 30 в `bid_window_days` этого снимка не является множеством тридцатидневных сроков подачи. {nfmt(filled['stage_missing'])} строк — подстановка отсутствующего периода. Остальные {nfmt(filled['stage_other_observed_value'])} — другое наблюдаемое evaluation-окно, которое после смешения стадий или после обнуления отрицательного конца стало числом 30. Их stage-consistent длины:

{_bins_table(quality['legacy_30_but_stage_other_bins'])}

Распределение самого снимка:

{_bins_table(quality['bins_legacy_feature_bid_window'])}

Распределение stage-consistent окна. Пустая ячейка остаётся пустой:

{_bins_table(quality['bins_stage_clipped_window'])}

У наблюдаемых evaluation-окон минимум {window['min']:.0f}, нижний квартиль {window['p25']:.0f}, медиана {window['median']:.0f}, среднее {window['mean']:.2f}, верхний квартиль {window['p75']:.0f}, максимум {window['max']:.0f} суток.

`short_deadline` в снимке равен 1 у {nfmt(flags['legacy_short'])} процедур ({pfmt(flags['legacy_short'], n)}). Среди наблюдаемых evaluation-окон срок короче 7 суток имеют {nfmt(flags['stage_short_among_observed'])} процедур, то есть {pfmt(flags['stage_short_among_observed'], observed)} наблюдаемых окон. `long_deadline` в снимке равен 1 у {nfmt(flags['legacy_long'])} процедур, а среди наблюдаемых evaluation-окон длиннее 90 суток только {nfmt(flags['stage_long_among_observed'])}.

Короткий срок после исправления — центр наблюдаемого распределения, а не редкий хвост. Прежняя редкость `short_deadline` получена после подстановки 30 и после смешения стадий. Это свойство формулы, а не измеренная редкость короткой подачи.

Число строк, в которых stage-consistent значение отличается от legacy-признака или отсутствует при заполненном legacy-признаке: {nfmt(quality['period_value_differs_from_legacy_feature'])}. Совпадают {nfmt(n - quality['period_value_differs_from_legacy_feature'])} строк. Строк, где отсутствующее окно записано числом: {nfmt(quality['missing_window_stored_as_number'])}. Строк с `historically_certified` = 1: {nfmt(quality['historically_certified_rows'])}.

## 7. Что именно сохранено

Новая таблица — `results/mta0024_stage_periods/stage_feature_table.csv.gz`. В ней прежние непериодные признаки скопированы, а `bid_window_days`, `short_deadline` и `long_deadline` заменены stage-consistent значениями. Рядом лежат статус, необрезанная длина, флаг наблюдения, нулевой флаг исторической сертификации и копия legacy-признаков. Копия нужна для сравнения. Она не объявляет legacy-снимок сертификатом t0.

Для детекторов MTA-0025 матрица stage-consistent рукава строится отдельно от таблицы. Пропуск непрерывной длины внутри этой матрицы заменяется медианой наблюдаемых окон, и добавляется индикатор пропуска. Медиана на этом корпусе равна {window['median']:.0f} суткам. Это вход модели для {nfmt(missing)} строк без измерения. В таблицу признаков эта медиана не записывается, и константа 30 для этого заполнения не используется.

## 8. Чего этот расчёт не показывает

Современное evaluation-окно не является сроком на момент первой публикации. Поправки notice, поздний EV и отсутствие исходного payload остаются в силе так, как их описал MTA-0022. Отсутствие evaluation record не доказывает, что срока не публиковали: в пакете нет соответствующей compiled record. Совпадение или расхождение с ANSC здесь не считалось. Преимущество какого-либо детектора не утверждается.
"""


def write_experiment_report(quality: dict, experiment: dict, score_dir: Path) -> str:
    n = experiment["protocol"]["n_ocids"]
    changed = experiment["protocol"]["period_values_changed"]
    unchanged = experiment["protocol"]["period_values_unchanged"]
    stage_info = experiment["preprocess"]["stage_consistent"]
    median = stage_info["median_observed_window"]
    legacy_stage = _pair(experiment, "legacy", "stage_consistent", "ensemble")
    legacy_ablation = _pair(experiment, "legacy", "ablation", "ensemble")
    stage_ablation = _pair(experiment, "stage_consistent", "ablation", "ensemble")
    return f"""# MTA-0025 — закрытое сравнение Legacy, Stage-consistent и Ablation

Дата расчёта: 2026-11-11. Сравнение выполнено после MTA-0024 на одной и той же совокупности OCID. Внешние метки ANSC не использовались. Ни один метод не объявляется лучшим: ниже измерены согласие, устойчивость порядка, пересечение top-K, сдвиг результатов и время счёта.

## 1. Совокупность и три рукава

В сравнение вошли {nfmt(n)} OCID, внутреннее соединение `features.csv` и экспорта периодов, отсортированное по OCID. Строк вне соединения нет. Период отличается от legacy-признака или отсутствует при заполненном legacy-значении у {nfmt(changed)} процедур. Неизменных значений периода: {nfmt(unchanged)}.

| Рукав | Что подано детекторам | Столбцов |
|---|---|---:|
| Legacy | Снимок `features.csv`, включая уже заполненное окно | {experiment['arms']['legacy']['n_columns']} |
| Stage-consistent | Те же непериодные признаки; окно только из одной evaluation-пары; пропуск в таблице пуст | {experiment['arms']['stage_consistent']['n_columns']} |
| Ablation | Те же строки без `bid_window_days`, `short_deadline`, `long_deadline` | {experiment['arms']['ablation']['n_columns']} |

Stage-consistent матрица содержит на один столбец больше, потому что к ней добавлен `submission_window_missing`. Медиана наблюдаемых окон, подставленная только внутрь этой матрицы, равна {median:.0f} суткам. С константой 30 она совпадает: {"да" if stage_info["median_equals_legacy_constant_30"] else "нет"}. Пропусков окна: {nfmt(stage_info["n_missing_window"])}. Наблюдаемых окон: {nfmt(stage_info["n_observed_window"])}. В сохранённой таблице признаков эти пропуски остаются пустыми.

Ablation убирает всё семейство периода. Этот рукав показывает, насколько порядок держится на остальных признаках. Он не является третьим способом измерить срок.

## 2. Протокол

Протокол повторяет `scripts/06_detect_anomalies.py`.

- Зерно 42. Доля contamination и `nu` равна 0.05. Это допущение протокола, не оценённая доля нарушений.
- MAD: максимум устойчивого z-score. Порог флага z > 5. Бинарные столбцы, столбцы с MAD = 0 и spike-like столбцы в z-score не входят.
- Isolation Forest: 300 деревьев, `contamination` 0.05, то же зерно.
- LOF: 20 соседей, `novelty=True`. Обучение на {nfmt(experiment['arms']['legacy']['fit_rows'])} случайных строках без возвращения. Префикс выборки не используется: OCID упорядочены по времени публикации.
- One-Class SVM: RBF, `nu` 0.05, `gamma=scale`, та же обучающая выборка.
- Ансамбль: флаг — не меньше трёх из четырёх детекторов. Оценка для ранжирования — среднее внутрирукавных перцентильных рангов этих четырёх. Флаг и оценка отвечают на разные вопросы.
- Простые индикаторы: число выбранных бинарных признаков, равных 1. Пропуск срока не увеличивает счёт. Индикатор отсутствия окна в счёт не входит. Флаг — ровно верхние 5% после разрешения ничьих по OCID. Это соглашение для сопоставимости с допущением 0.05, не проверенный порог решения.
- Препроцессинг геометрических моделей: `StandardScaler` на строках рукава. Legacy и Ablation дополнительно заменяют оставшиеся пропуски нулём, как действующий скрипт. Окно Legacy к этому моменту уже заполнено тридцатью внутри исторического снимка.

Одинаковое зерно и одинаковый порядок OCID делают обучающую выборку LOF и SVM одной и той же по позициям. Состав признаков у рукавов разный, поэтому это не одна и та же геометрическая выборка.

## 3. Размер флагов

Доли не интерпретируются как точность. У простых индикаторов доля флага задана правилом 5%. У MAD порог z > 5 может отметить иную долю. У леса и LOF доля близка к 5%, потому что contamination задаёт порог на обучающей выборке. У SVM параметр nu — заявленная граница доли ошибок обучения; на рукаве Ablation фактическая доля на обучающей выборке эту границу превышает. Разбор дан ниже и в MTA-0026.

{_method_table(experiment)}

Какие столбцы MAD оставил в z-score:

{_mad_line(experiment, 'legacy')}
{_mad_line(experiment, 'stage_consistent')}
{_mad_line(experiment, 'ablation')}

`bid_window_days` не входит в z-score ни одного рукава. В Legacy и Stage-consistent столбец исключён как константа: MAD равен нулю, потому что больше половины строк несут одно и то же число. В Legacy это масса значений 30. В Stage-consistent медианное заполнение ставит {quality['observed_stage_window']['median']:.0f} суток в каждую строку без измерения, и таких строк больше половины. Ablation этого столбца не содержит. Совпадение флагов MAD между рукавами поэтому не измеряет влияние срока. Правило MAD эту длину отбросило. Геометрические модели по-прежнему видят столбец после `StandardScaler`, потому что нулевой MAD не означает нулевую дисперсию.

One-Class SVM отметил {_rate(experiment, 'legacy', 'one_class_svm')} в Legacy, {_rate(experiment, 'stage_consistent', 'one_class_svm')} в Stage-consistent и {_rate(experiment, 'ablation', 'one_class_svm')} в Ablation. Проверка MTA-0026 на тех же зерне и матрице показала долю флага 4,97% на обучающих 20 000 строках Legacy и 23,03% на обучающих строках Ablation; полный корпус Ablation даёт ту же величину, {_rate(experiment, 'ablation', 'one_class_svm')}. Скачок находится внутри обучения. Доля опорных векторов остаётся около nu. Верхняя граница nu на ошибки обучения в Ablation этим RBF-решением не достигнута. Флаг совпадает со знаком decision_function. Это свойство решателя, а не сравнение качества. Ансамбль требует трёх детекторов, поэтому широкий флаг SVM сам по себе консенсус не расширяет.

## 4. Согласие методов внутри рукава

Пары ниже — четыре детектора одного рукава, без ансамбля и без простого счёта. Высокий Жаккар означает, что методы отмечают близкие множества. Низкий Жаккар означает, что общее имя «аномалия» собирает разные множества. Это не выбирает победителя.

### Legacy

{_within_table(experiment, 'legacy')}

### Stage-consistent

{_within_table(experiment, 'stage_consistent')}

### Ablation

{_within_table(experiment, 'ablation')}

## 5. Сравнение рукавов

Спирмен считается по оценкам. Жаккар считается по флагам. Top-K считается по оценкам, ничья разрешается меньшим OCID. Медиана абсолютного разрыва — по внутрирукавным перцентильным рангам, поэтому шкалы разных моделей можно ставить рядом. Разрыв 0,10 означает сдвиг на 10 перцентильных пунктов.

### Legacy и Stage-consistent

{_stability(legacy_stage['spearman'])} Для ансамбля Жаккар флагов {rfmt(legacy_stage['jaccard'])}: вместе отмечены {nfmt(legacy_stage['both'])} процедур, только Legacy — {nfmt(legacy_stage['only_left'])}, только Stage-consistent — {nfmt(legacy_stage['only_right'])}.

{_pairwise_table(experiment, 'legacy', 'stage_consistent')}

У LOF пересечение top-100 между Legacy и Stage-consistent равно {rfmt(_pair(experiment, 'legacy', 'stage_consistent', 'lof')['topk']['100']['overlap'])} при медиане перцентильного разрыва {gfmt(_pair(experiment, 'legacy', 'stage_consistent', 'lof')['median_abs_percentile_gap'])}. Крайняя сотня процедур разошлась, тогда как сдвиг основной массы рангов остался малым.

### Legacy и Ablation

{_stability(legacy_ablation['spearman'])} Жаккар флагов ансамбля {rfmt(legacy_ablation['jaccard'])}: вместе {nfmt(legacy_ablation['both'])}, только Legacy {nfmt(legacy_ablation['only_left'])}, только Ablation {nfmt(legacy_ablation['only_right'])}.

{_pairwise_table(experiment, 'legacy', 'ablation')}

### Stage-consistent и Ablation

{_stability(stage_ablation['spearman'])} Жаккар флагов ансамбля {rfmt(stage_ablation['jaccard'])}: вместе {nfmt(stage_ablation['both'])}, только Stage-consistent {nfmt(stage_ablation['only_left'])}, только Ablation {nfmt(stage_ablation['only_right'])}.

{_pairwise_table(experiment, 'stage_consistent', 'ablation')}

Полные пересечения для K = 50, 100, 200, 500 и 1000 лежат в `results/mta0025_closed_experiment/topk_overlap.csv`. Первые 100 OCID каждого метода и рукава — в `top100.csv`.

Простой счёт принимает мало целых значений, поэтому высокий Спирмен совместим с маленьким top-100. Верхние позиции внутри одной и той же суммы разрешаются порядком OCID, а не дополнительной непрерывной оценкой.

{_simple_tie_lines(score_dir)}

Отрицательный Спирмен внутри рукава, там где он есть в таблице согласия, означает противоположное направление двух шкал. Он не выбирает из двух методов более правильный.

## 6. Сдвиг там, где изменился период, и там, где не изменился

Модели каждого рукава обучены заново на всей матрице. Поэтому оценка может сдвинуться и у процедуры, чей собственный период не изменился: меняются масштаб, состав столбцов и геометрия выборки. Таблица разделяет эти два множества. Она не приписывает каждый сдвиг ранга конкретной процедуре её новому сроку.

Изменившихся строк: {nfmt(changed)}. Неизменных: {nfmt(unchanged)}. Подмножество из {nfmt(unchanged)} строк мало, поэтому Спирмен на нём описывает эту группу, а не второй корпус.

{_changed_table(experiment)}

Наблюдаемое evaluation-окно имеет медиану {quality['observed_stage_window']['median']:.0f} суток. В Legacy-снимке {nfmt(quality['value_30_in_legacy_feature']['rows'])} строк хранят ровно 30, и ни одна из них не является stage-consistent окном той же длины. Короткий срок в снимке отмечен у {nfmt(quality['deadline_flags']['legacy_short'])} процедур, а среди наблюдаемых evaluation-окон короче 7 суток {nfmt(quality['deadline_flags']['stage_short_among_observed'])}. Простой счёт видит эту разницу только как изменение двух бинарных слагаемых. Остальные бинарные индикаторы в Legacy и Stage-consistent одинаковы.

## 7. Время

Время — настенные секунды одного прогона на этой машине, включая обучение и оценку всех {nfmt(n)} строк. Это не асимптотическая сложность и не сравнение реализаций между собой. Ансамбль не обучает новую модель: его секунды уходят на ранги уже посчитанных оценок.

{_seconds_table(experiment)}

Сумма трёх рукавов: {sfmt(experiment['seconds_total'])} с.

## 8. Чего сравнение не устанавливает

Согласие с Legacy не подтверждает Legacy. Расхождение со Legacy не доказывает, что новый порядок ближе к нарушению. Ablation не показывает, что период бесполезен или полезен: она показывает, какая часть порядка выживает без этого семейства. Доля флагов не является распространённостью нарушений. Метки ANSC, жалобы и решения в этот прогон не входили, поэтому ROC-AUC и precision at K по внешнему исходу здесь не определены. Историческая доступность признаков на t0 по-прежнему не сертифицирована.
"""


def write_chapter(quality: dict, experiment: dict) -> str:
    n = experiment["protocol"]["n_ocids"]
    observed = quality["evaluation_window_observed"]
    missing = quality["evaluation_window_missing"]
    filled = quality["value_30_in_legacy_feature"]["rows"]
    window = quality["observed_stage_window"]
    legacy_stage = _pair(experiment, "legacy", "stage_consistent", "ensemble")
    return f"""# Экспериментальные результаты: период подачи и устойчивость детекторов

Этот текст фиксирует измеренные результаты MTA-0024 и MTA-0025. Его можно перенести в экспериментальную главу. Он не заменяет описание корпуса, правовых источников и ограничений внешней валидации, уже изложенные в MTA-0019, MTA-0021 и MTA-0022.

## Постановка

Детекторы обучаются без меток нарушения. Оценка показывает необычность процедуры относительно остальных строк корпуса, а не установленный факт. В действующем снимке длина периода подачи входит в три столбца: `bid_window_days`, `short_deadline` и `long_deadline`. Два последних являются пороговыми преобразованиями первого, поэтому семейство несёт не три независимых измерения, а одно, плюс выбранные пороги 7 и 90 суток.

Длина в снимке получена после слияния compiled releases и после замены пропуска константой 30. Слияние может соединить старт planning notice с концом evaluation notice. Константа 30 делает пропуск неотличимым от измеренного месяца. Оба шага уже были описаны в коде и в MTA-0022. Здесь они посчитаны на всех {nfmt(n)} процедурах снимка и проведены через тот же протокол детектирования.

Отдельно удерживаются два статуса значения. Stage-consistent столбец — свойство текущего пакета. Исторически сертифицированное значение требовало бы первичного notice, проверяемого t0 и версии полей на этот момент. Таких сертификатов этот расчёт не создаёт. `historically_certified` равен 0 для каждой строки.

## Данные и граница чтения

Считаны локальные пакеты `data/raw/ocds_packages`: {nfmt(n)} файлов, ошибок чтения {nfmt(json.loads((ROOT / 'results' / 'mta0024_stage_periods' / 'summary.json').read_text())['read_errors'])}. Признаки взяты из `data/features/features.csv`, SHA-256 `{quality['features_sha256']}`, тот же, что в манифесте экспорта, сверенном MTA-0022. Соединение по OCID полное: {nfmt(n)} против {nfmt(n)}. Новый корпус не скачивался. Дерево Diplom не изменялось.

Восемь процедур, уже разобранных в MTA-0022, повторены на исходных JSON. У каждой смешанное окно соединяет PN.start с EV.end, а окно одной evaluation record совпадает с ранее опубликованной диагностической длиной. Это проверка извлечения, не восстановление t0.

## Исправление периода

Полное evaluation-окно найдено у {nfmt(observed)} процедур ({pfmt(observed, n)}). У {nfmt(missing)} процедур ({pfmt(missing, n)}) evaluation record в пакете нет, и новое окно оставлено пустым. Конфликтующих, неполных, отрицательных и неразборных evaluation-пар на этом снимке нет.

Почти каждое полное evaluation-окно в старом слиянии смешано со стартом другой стадии: исключений {nfmt(len(quality['evaluation_complete_not_cross_stage']))}. Ещё одна смешанная строка соединяет planning и base и полного evaluation-окна не имеет. Там, где можно сравнить два неотрицательных числа, старое окно длиннее нового в {nfmt(json.loads((ROOT / 'results' / 'mta0024_stage_periods' / 'summary.json').read_text())['legacy_longer_than_evaluation'])} процедурах, короче в {nfmt(json.loads((ROOT / 'results' / 'mta0024_stage_periods' / 'summary.json').read_text())['legacy_shorter_than_evaluation'])} и совпадает в {nfmt(json.loads((ROOT / 'results' / 'mta0024_stage_periods' / 'summary.json').read_text())['windows_equal'])}.

Значение ровно 30 суток стоит в legacy-признаке у {nfmt(filled)} процедур. Все процедуры без evaluation record входят в это множество. Ни одно stage-consistent окно длиной 30 суток в этом множестве не находится. Наблюдаемые новые окна имеют медиану {window['median']:.0f} суток и межквартильный размах от {window['p25']:.0f} до {window['p75']:.0f}. Короче семи суток {nfmt(quality['deadline_flags']['stage_short_among_observed'])} наблюдаемых окон против {nfmt(quality['deadline_flags']['legacy_short'])} единиц `short_deadline` в снимке. Длиннее 90 суток — {nfmt(quality['deadline_flags']['stage_long_among_observed'])} наблюдаемых окон против {nfmt(quality['deadline_flags']['legacy_long'])} в снимке.

Отсюда следует узкое утверждение. В текущем снимке литерал 30 в основном кодирует отсутствие evaluation-окна либо иное измеренное окно после смешения, а порог «короткий срок» отсекает редкий хвост только до исправления. После извлечения одной стадии короткий срок оказывается типичной наблюдаемой длиной. Утверждение не переносится на дату первой публикации и не говорит, какой срок предписан процедуре законом.

{nfmt(quality.get('blank_legacy_days_among_evaluation_complete', 0))} полных evaluation-окон имеют отрицательную длину именно у смешанной пары. Действующий снимок в этих строках теряет конец и затем подставляет 30. Новая таблица сохраняет неотрицательную evaluation-длину и не подставляет 30.

## Протокол сравнения

Сравниваются три матрицы на тех же {nfmt(n)} OCID. Legacy подаёт снимок как есть. Stage-consistent заменяет три столбца периода и добавляет индикатор пропуска; медиана наблюдаемых окон ({window['median']:.0f} суток) используется только внутри матрицы детектора. Ablation удаляет три столбца периода. Зерно, contamination, число деревьев, размер обучающей выборки LOF и SVM и порог MAD взяты из действующего скрипта детектирования. Ансамбль отмечает строку, если не меньше трёх из четырёх детекторов дали флаг, и ранжирует по среднему перцентильному рангу. Простой индикатор считает бинарные признаки и для сопоставимости отмечает верхние 5% счёта. Это правило отчёта, не калиброванный порог.

Внешняя выборка ANSC в прогон не входила. Поэтому эксперимент отвечает на вопрос устойчивости, а не на вопрос обнаружения подтверждённых нарушений.

## Что изменилось в порядке

Для ансамбля Спирмен между Legacy и Stage-consistent равен {rfmt(legacy_stage['spearman'])}, Жаккар флагов равен {rfmt(legacy_stage['jaccard'])}. Вместе отмечено {nfmt(legacy_stage['both'])} процедур, только старым правилом — {nfmt(legacy_stage['only_left'])}, только новым — {nfmt(legacy_stage['only_right'])}. Пересечение top-100 равно {rfmt(legacy_stage['topk']['100']['overlap'])}, top-1000 равно {rfmt(legacy_stage['topk']['1000']['overlap'])}. Медиана абсолютного перцентильного разрыва равна {gfmt(legacy_stage['median_abs_percentile_gap'])}.

Те же величины для остальных методов и для пары с Ablation приведены в отчёте MTA-0025 и в `pairwise.csv`. Их нельзя складывать в одну оценку качества. Высокое согласие означает, что смена периода мало переставила порядок. Низкое согласие означает, что порядок зависел от семейства периода. Ни то ни другое не называет рукав более верным.

Отдельно посчитаны ранги на {nfmt(experiment['protocol']['period_values_changed'])} строках с изменившимся периодом и на {nfmt(experiment['protocol']['period_values_unchanged'])} строках без такой замены. Сдвиг на неизменных строках возможен, потому что модель обучается на всей матрице. Он не является ошибкой соединения: соединение проверено по OCID и дубликатов не содержит.

В этом прогоне MAD исключил `bid_window_days` как константу и в Legacy, и в Stage-consistent. Совпадение его флагов между рукавами поэтому не означает, что срок был учтён и признан неважным. Оно означает, что правило MAD эту длину отбросило: больше половины строк несут одно и то же число, 30 в старом снимке и медиану наблюдаемых окон после заполнения пропусков в матрице детектора. Isolation Forest, LOF и SVM этот столбец видят. Списки всех исключений сохранены в `experiment_summary.json`.

## Стоимость и воспроизводимость

Полный прогон трёх рукавов занял {sfmt(experiment['seconds_total'])} с настенного времени. Посекундная разбивка по методам лежит в отчёте MTA-0025. Обучающая выборка соседних методов ограничена {nfmt(experiment['protocol']['neighbourhood_fit_cap'])} строками, как в действующем протоколе. Оценки всех строк сохранены отдельно по рукавам: `scores_legacy.csv.gz`, `scores_stage_consistent.csv.gz`, `scores_ablation.csv.gz`.

Повторное чтение пакетов и снимка достаточно для повторения чисел. Сеть, MongoDB и переобучение production-модели не требуются. Новый результат не заменяет `features.csv` и не записывается в коллекцию scores.

## Ограничение вывода

Исправление делает срок сопоставимым внутри одной стадии текущего пакета. Оно не создаёт признак, доступный на момент первой публикации, и не увеличивает число сертифицированных тестовых процедур. MTA-0022 оставил для publication-постановки 0 положительных и 0 отрицательных сертифицированных наблюдений из восьми проверенных дел. Этот статус не изменён. Сравнение детекторов измеряет чувствительность порядка к формуле периода. Оно не выбирает модель для решения и не оценивает её против административного исхода.
"""


def main() -> int:
    quality = _load(QUALITY)
    export_summary = _load(SUMMARY_PATH)
    experiment = _load(EXPERIMENT)
    REPORTS.mkdir(parents=True, exist_ok=True)
    documents = {
        "MTA-0024_FEATURE_CORRECTION.md": write_feature_report(quality, export_summary),
        "MTA-0025_FINAL_EXPERIMENT.md": write_experiment_report(
            quality, experiment, EXPERIMENT.parent
        ),
        "THESIS_CHAPTER3_EXPERIMENTAL_RESULTS.md": write_chapter(quality, experiment),
    }
    for name, text in documents.items():
        path = REPORTS / name
        path.write_text(text, encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
