# MTA-0024 / MTA-0025

Рабочая копия эксперимента. Diplom остаётся источником для чтения. Этот каталог не заменяет `features.csv` и не записывает scores в MongoDB.

## Что считать

Период подачи берётся только из одной полной неотрицательной пары evaluation. Пропуск не заменяется на 30 суток. `historically_certified` равен 0: это текущий снимок, не сертификат публикации.

Сравнение детекторов идёт на одном списке OCID в трёх рукавах: Legacy, Stage-consistent, Ablation. Протокол совпадает с `scripts/06_detect_anomalies.py`: зерно 42, contamination 0.05, 300 деревьев, LOF и SVM обучаются на 20 000 случайных строках. Внешние метки не используются. Преимущество модели не утверждается.

## Повтор в этой копии

Из корня `mta_0024_0025`, интерпретатором `/Users/imustyk/Diplom/.venv/bin/python`:

```bash
export PYTHONPYCACHEPREFIX="$(pwd)/.pyc"
python -m pytest -p no:cacheprovider -q
python scripts/55_stage_period_export.py \
  --packages /Users/imustyk/Diplom/data/raw/ocds_packages \
  --out results/mta0024_stage_periods
python scripts/56_build_stage_features.py
python scripts/57_closed_experiment.py
python scripts/58_write_reports.py
```

`55` читает 152 378 локальных пакетов и ничего не скачивает. `56` читает `data/features/features.csv` и не переписывает его. Запись внутрь `/Users/imustyk/Diplom` скрипты 56 и 57 отклоняют.

Зависимости перечислены в `requirements-mta0024-0025.txt`. Они уже стоят в виртуальном окружении Diplom: pandas 2.2.3, numpy 2.2.1, scikit-learn 1.6.1, pytest 9.1.1.

## Где лежат измерения

- `results/mta0024_stage_periods/stage_periods.csv` — окно по каждому пакету
- `results/mta0024_stage_periods/stage_feature_table.csv.gz` — новая матрица признаков
- `results/mta0024_stage_periods/quality.json` — качество данных
- `results/mta0025_closed_experiment/scores_*.csv.gz` — оценки трёх рукавов
- `results/mta0025_closed_experiment/experiment_summary.json` — согласие, top-K и время
- `reports/MTA-0024_FEATURE_CORRECTION.md`
- `reports/MTA-0025_FINAL_EXPERIMENT.md`
- `reports/THESIS_CHAPTER3_EXPERIMENTAL_RESULTS.md`

Перенос в Diplom описан в `IMPORT_INSTRUCTIONS.md` в корне этой копии. Коммит и push этой работой не выполнялись.
