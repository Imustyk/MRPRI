# План иллюстраций и таблиц

Проверены семь существующих графиков. Новые экспериментальные значения не генерировались. В текущем DOCX включены проверенные числовые таблицы; графические вставки остаются по этому плану, чтобы не переносить ошибочные подписи.

|Элемент|Раздел|Источник|Действие и ограничение|
|---|---|---|---|
|Рисунок 2.1 Архитектура|2.6|CODE-INGEST/NORM/F/DET/API/UI/WORKSPACE|Показать реализованные блоки. Kafka/SQL/LLM не включать в действующий контур|
|Рисунок 2.2 Поток данных|2.2|Скрипты 01a/b→02→03→04→06/07, CODE-RISK|Различить исходные bytes, Mongo-проекцию, признаки, scores и reviewer ledger. Не изображать архив t0 как существующий|
|Таблица 2.1 Слои данных|2.2|CODE-INGEST, CODE-NORM, M22|Уже в тексте; raw_tenders не назван полным response body|
|Таблица 2.2 Выходы ranking|2.4|CODE-DET, CODE-ADAPTER|Уже в тексте; percentile не вероятность|
|Рисунок 2.3 Группы признаков|2.3|CODE-F FEATURE_COLUMNS|22 колонки, четыре группы; показать дубли и три преобразования одного window|
|Таблица 3.1 Корпус по годам|3.1|DATA published_date|Уже в тексте; metadata year не certified t0|
|Таблица 3.2 Детекторы|3.3|DET/models|Уже в тексте; MAD threshold не contamination|
|Таблица 3.3 Голоса и полосы|3.3|SCORES, CODE-ADAPTER|Уже в тексте; 3031 critical/4631 high|
|Рисунок 3.1 Распределения scores|3.3|results/figures/anomaly_overview.png, SCORES|Общая линейная шкала сжата LOF tail. Подготовить читабельные отдельные масштабы/ECDF по существующим scores, без fit|
|Рисунок 3.2 Baseline comparison|3.5|docs/figures/external_validation_baselines.png, EXT-TABLE|AUC/CI подтверждены. В новой копии исправить label «votes>=3» на число голосов 0–4 по CODE-EXT. Сохранить weak-label caveat|
|Рисунок 3.3 Парные разности|3.5|docs/figures/external_validation_paired_vs_v0.png, EXT|Ось ошибочно подписана rule−v0 при фактическом v0−rule. Не включать до исправления новой копии; исходник не менять|
|Таблица 3.4 Внешние AUC|3.5|EXT-TABLE, EXT labels/config|Уже в тексте; указаны target, population, cluster и CI|
|Рисунок 3.4 Seed stability|3.4|results/figures/seed_robustness.png, SEED|Действительный график; 20 запусков включают baseline 42. Jaccard не является validity|
|Рисунок 3.5 Noise sensitivity|3.4|results/figures/noise_sensitivity_stability.png, NOISE|На графике средние, в критериях есть минимумы; не смешивать эти величины|
|Рисунок 3.6 Групповые различия|3.4|results/figures/bias_audit.png, BIAS|Статусы допусков не правовые нарушения. Перекрывающиеся группы не складывать как число процедур|
|Рисунок 3.7 XAI|3.4|results/figures/xai_global.png, CODE-XAI2, XAI|Global mean SHAP по всем xs_all подтверждён; local panel — 60 случаев. Ранний SHAP 2000 относится к другому расчёту|
|Таблица 3.5 ANSC TEST coverage|3.5|M21-LABELS|Уже в тексте; 2+/6− до certification, 0/0 после|
|Рисунок 3.8 ANSC funnel|3.5|M19-METRICS, M21|50 URL→44 PDF→13 decisions; новые шесть процедур/восемь жалоб отдельной веткой|
|Таблица 3.6 Историческая пригодность|3.6|M22-SUM, M23-SUM|Уже в тексте; 0/8 и 0/2 certified не доказывают отсутствие истории у издателя|
|Рисунок 3.9 Publication timeline|3.6|M23-CERT, mta0023_release_versions.csv|Показать известные references и отсутствующие payload. Не придумывать версии|
|Схема полей DUAE|3.7/приложение|A01/A02|Одна обезличенная схема, без персональных контактов и новых labels|

Для каждой будущей иллюстрации зафиксировать source path/hash, run/date, population, единицу, метрику/преобразование и политику пропусков. Стабильность, ANOVA и SHAP не подписывать как доказательство коррупции. Скриншоты интерфейса показывают функции, а не эффективность работы аналитиков.
