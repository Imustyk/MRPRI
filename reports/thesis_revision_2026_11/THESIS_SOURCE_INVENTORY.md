# Инвентаризация источников диссертации

Срез 09.11.2026, HEAD66f103d, feature/risk-specific-detection. Источники не перезаписывались.

Проанализированы 9 академических файлов (8 уникальных по SHA-256), 75 файлов проекта и 6 внешних первичных справочных источников: всего 90 файлов/ресурсов, 89 уникальных по содержанию/адресу. Число не означает столько независимых исследований: отчёты, код и таблицы одного прогона зависимы.

Из девяти точных имён задания найдены 8. **MISSING exact version:** `Отчет_MTender_ИИ(1).docx`. Найден `Отчет_MTender_ИИ.docx` (A06 по физической сортировке); использован как близкая версия, без заявления об идентичности отсутствующей. Имена с decomposed Unicode нормализованы только для поиска, сами файлы не переименованы.

## Академические файлы

|ID|Файл и местоположение|Размер bytes|SHA-256|
|---|---|---:|---|
|A01|/Users/imustyk/Desktop/Diplom/темы/30 duae.signed (1).pdf|1032987|7f9997dbf500a6eb48739368ce9bc45fc2c344d160062cef209085b8a12583d4|
|A02|/Users/imustyk/Desktop/Diplom/темы/30 duae.signed.pdf|1032987|7f9997dbf500a6eb48739368ce9bc45fc2c344d160062cef209085b8a12583d4|
|A03|/Users/imustyk/Desktop/Diplom/темы/glava1-full-draft.md|23892|12ab1df88ae3c8461e30017c986cab2e1946b1673c273052583ab2b07567d4e1|
|A04|/Users/imustyk/Desktop/Diplom/темы/glava2-2.2-2.3-glava3-3.5-draft.md.pdf|351047|9cc530aa8da078e1314292f04a884e08642d36f14098273d61f6e39aaf8f8bdd|
|A05|/Users/imustyk/Desktop/Diplom/темы/Диссертация_MTender_аномалии.docx|68992|404c0a5c7a542e2b3a682d653986ecbd93931a8a316621bbc39f675a30641864|
|A06|/Users/imustyk/Desktop/Diplom/темы/Отчет_MTender_ИИ.docx|77483|228efbaafc43e90b2a688647ff7557746f8fdc778c22488b21a2dcdb4b00b163|
|A07|/Users/imustyk/Desktop/Diplom/темы/Предложение_темы_магистерской_диссертации_MTender_для_научного_руководителя.docx|42839|b7fd18d7f821e87baae84377eb4d9f082193e0c7ed32a91fb2c0f02506595a25|
|A08|/Users/imustyk/Desktop/Diplom/темы/Тема_магистерской_диссертации_MTender.docx|21414|cba5cf25fdbb442cc0e96cd1c6705907878eaec08af57608602834227cfc9b69|
|A09|/Users/imustyk/Desktop/Diplom/темы/Темы_магистерской_диссертации.docx|11649|486ebe8f998374554521ade7cdfdbb81a09ff80b575514f40a0bbf93cefc703c|

A01/A02 — идентичные DUAE, не два независимых документа. A03 — глава 1; A04 —8-страничный PDF с §2.2–2.3/§3.5; A05 — диссертация; A06 — отчёт; A07 — предложение темы; A08 — тема MTender; A09 — альтернативные темы. Полный текст DOCX извлечён из OOXML, включая таблицы; PDF извлечены постранично. Персональные контакты/имена DUAE в новые материалы не перенесены.

## Код, данные, отчёты и иллюстрации

|ID|Первичный файл|Как использован|
|---|---|---|
|README|README.md|Сверка реализации, чисел, семантики или ограничений|
|CODE-F|src/mtender/features.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-O|src/mtender/ocds.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-N|src/mtender/normalize.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-STAGE|src/mtender/stage_features.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-RISK|src/mtender/risk_modules.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-RAG|src/mtender/rag.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-METRICS|src/mtender/eval_metrics.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-INGEST|scripts/01b_fetch_records.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-SCAN|scripts/01a_scan_ocids.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-NORM|scripts/02_normalize_mongo.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-FE|scripts/03_features_mongo.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-EXPORT|scripts/04_export_snapshot.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-DET|scripts/06_detect_anomalies.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-XAI|scripts/07_explainability.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-XAI2|scripts/24_xai_consistency.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-EXT|scripts/35_external_validation.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-RISK-RUN|scripts/34_risk_modules.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-RAG-RUN|scripts/26_rag_eval.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-API|backend/app/main.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-ADAPTER|backend/app/adapter.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-STORE|backend/app/store.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-EXPLAIN|backend/app/explain.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-RESEARCH|backend/app/research_api.py|Сверка реализации, чисел, семантики или ограничений|
|CODE-UI|frontend/src/App.tsx|Сверка реализации, чисел, семантики или ограничений|
|CODE-UI-META|frontend/package.json|Сверка реализации, чисел, семантики или ограничений|
|CODE-WORKSPACE|src/mtender/workspace.py|Сверка реализации, чисел, семантики или ограничений|
|DATA|data/features/features.csv|Сверка реализации, чисел, семантики или ограничений|
|SCORES|results/tables/tender_anomaly_scores.csv|Сверка реализации, чисел, семантики или ограничений|
|DET|results/mongo/detection_summary.json|Сверка реализации, чисел, семантики или ограничений|
|FE|results/mongo/features_summary.json|Сверка реализации, чисел, семантики или ограничений|
|EXPORT|results/mongo/export_manifest.json|Сверка реализации, чисел, семантики или ограничений|
|FETCH|results/mongo/fetch_summary.json|Сверка реализации, чисел, семантики или ограничений|
|EXT|results/methodology/external_validation_framework.json|Сверка реализации, чисел, семантики или ограничений|
|EXT-TABLE|results/tables/external_baselines.csv|Сверка реализации, чисел, семантики или ограничений|
|MODULES|results/methodology/risk_modules.json|Сверка реализации, чисел, семантики или ограничений|
|SEED|results/methodology/robustness_seeds.json|Сверка реализации, чисел, семантики или ограничений|
|NOISE|results/methodology/noise_sensitivity.json|Сверка реализации, чисел, семантики или ограничений|
|BIAS|results/methodology/bias_audit.json|Сверка реализации, чисел, семантики или ограничений|
|BIAS-V6|results/methodology/bias_audit_v6.json|Сверка реализации, чисел, семантики или ограничений|
|CIRC|results/methodology/circularity_check.json|Сверка реализации, чисел, семантики или ограничений|
|XAI|results/methodology/xai_consistency.json|Сверка реализации, чисел, семантики или ограничений|
|XAI-INITIAL|results/mongo/explainability_summary.json|Сверка реализации, чисел, семантики или ограничений|
|RAG|results/methodology/rag_eval.json|Сверка реализации, чисел, семантики или ограничений|
|RAG-MANIFEST|results/rag/manifest.json|Сверка реализации, чисел, семантики или ограничений|
|M19|reports/MTA-0019_FINAL_VALIDATION.md|Сверка реализации, чисел, семантики или ограничений|
|M19-METRICS|results/methodology/ansc_review_metrics.json|Сверка реализации, чисел, семантики или ограничений|
|M19-AUDIT|results/tables/ansc_final_audit.json|Сверка реализации, чисел, семантики или ограничений|
|M21|reports/MTA-0021_NEGATIVE_REVIEW_AUDIT.md|Сверка реализации, чисел, семантики или ограничений|
|M21-LABELS|results/tables/ansc_mta0021_combined_procedure_labels.csv|Сверка реализации, чисел, семантики или ограничений|
|M22|reports/MTA-0022_TEMPORAL_DATA_AUDIT.md|Сверка реализации, чисел, семантики или ограничений|
|M22-SUM|results/tables/mta0022_summary.json|Сверка реализации, чисел, семантики или ограничений|
|M22-CERT|results/tables/mta0022_feature_certification.csv|Сверка реализации, чисел, семантики или ограничений|
|M23|reports/MTA-0023_SOURCE_RECOVERY_PILOT.md|Сверка реализации, чисел, семантики или ограничений|
|M23-SUM|results/tables/mta0023_summary.json|Сверка реализации, чисел, семантики или ограничений|
|M23-CERT|results/tables/mta0023_publication_evidence.csv|Сверка реализации, чисел, семантики или ограничений|
|M20-PLAN|reports/MTA-0020_EVALUATION_PLAN.md|Сверка реализации, чисел, семантики или ограничений|
|TEST-TIME|tests/test_temporal_leakage.py|Сверка реализации, чисел, семантики или ограничений|
|TEST-M22|tests/test_temporal_data_audit.py|Сверка реализации, чисел, семантики или ограничений|
|TEST-M23|tests/test_source_recovery_pilot.py|Сверка реализации, чисел, семантики или ограничений|
|TEST-RISK|tests/test_risk_modules.py|Сверка реализации, чисел, семантики или ограничений|
|TEST-RAG|tests/test_rag.py|Сверка реализации, чисел, семантики или ограничений|
|TEST-API|tests/test_api_real_data.py|Сверка реализации, чисел, семантики или ограничений|
|TEST-REVIEW|tests/test_ansc_negative_review_register.py|Сверка реализации, чисел, семантики или ограничений|
|OLD-COMPARE|docs/EXPERIMENTAL_MODEL_COMPARISON.md|Сверка реализации, чисел, семантики или ограничений|
|OLD-EXT|docs/EXTERNAL_VALIDATION_REPORT.md|Сверка реализации, чисел, семантики или ограничений|
|OLD-TIME|docs/TEMPORAL_LEAKAGE_AUDIT.md|Сверка реализации, чисел, семантики или ограничений|
|OLD-STATUS|thesis/STATUS.md|Сверка реализации, чисел, семантики или ограничений|
|FIG-ANOM|results/figures/anomaly_overview.png|Существующий график, проверен визуально и по связанному артефакту|
|FIG-EXT|docs/figures/external_validation_baselines.png|Существующий график, проверен визуально и по связанному артефакту|
|FIG-PAIRED|docs/figures/external_validation_paired_vs_v0.png|Существующий график, проверен визуально и по связанному артефакту|
|FIG-SEED|results/figures/seed_robustness.png|Существующий график, проверен визуально и по связанному артефакту|
|FIG-NOISE|results/figures/noise_sensitivity_stability.png|Существующий график, проверен визуально и по связанному артефакту|
|FIG-XAI|results/figures/xai_global.png|Существующий график, проверен визуально и по связанному артефакту|
|FIG-BIAS|results/figures/bias_audit.png|Существующий график, проверен визуально и по связанному артефакту|

Все SHA-256 и размеры перечислены в `THESIS_SOURCE_HASHES.json`. Файлы моделей не загружались в исполнение. Проверены также список файлов приложения и отсутствие реализаций Autoencoder/Grad-CAM/Distillation/Kafka/MS SQL/Streamlit в src/backend/scripts/requirements; совпадение названия в академическом тексте не засчитывалось как реализация.

## Внешние первичные ссылки

- [UTM] [UTM](https://utm.md/wp-content/uploads/2020/05/Ghid-Elaborarea-si-sustinerea-tezelor-de-master-Master.pdf): Guide approved30.04.2020; currently linked by official UTM normative page; web text inspected, local download403; FCIM addendum unverified.
- [UTM-INDEX] [UTM-INDEX](https://utm.md/documente-institutionale/acte-normative/): Official current guide listing inspected09.11.2026.
- [IF] [IF](https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication.htm): Author publication page verifies Isolation Forest ICDM2008 reference; direct paper fetch timed out.
- [LOF] [LOF](https://www.dbs.ifi.lmu.de/Publikationen/Papers/LOF.pdf): Breunig et al.2000 primary paper/publication record.
- [SVM] [SVM](https://proceedings.neurips.cc/paper/1999/hash/8725fb777f25776ffa9076e44fcfd776-Abstract.html): Schölkopf et al. NIPS1999 proceedings abstract.
- [SHAP] [SHAP](https://arxiv.org/abs/1705.07874): Lundberg and Lee2017 v2 author preprint abstract inspected.

## Требования UTM

В локальных материалах официального guide не было. На действующей странице нормативных актов UTM найден guide, утверждённый 30.04.2020. Проверены §5–6: рекомендуемый объём 60–80 страниц без приложений, A4, TNR12 и 1,5 интервала; есть возможность дополнений программы. Это общие требования, не подтверждение актуального факультетского шаблона SD-251M. Локальная загрузка PDF вернула 403; содержание доступно через web-просмотр официального PDF. Не объявлено, что версия 2020 является единственным действующим документом программы 2026. Подтверждение у руководителя/департамента остаётся TODO. Число страниц черновика не увеличивалось искусственно.

Научные статьи подтверждают общую методическую основу, но не эмпирические результаты MTender. Статистика CPI/ВВП/AAP из старых глав не перенесена как актуальный факт: в доступном исследовательском архиве отсутствуют надёжно привязанные первичные извлечения соответствующих таблиц; требуется отдельная проверка.
