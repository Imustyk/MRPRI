# Аудит перед модернизацией

10.11.2026. Ветка feature/risk-specific-detection, HEAD 81533b6. Посторонние правки: удалённый frontend/public/_lang-bootstrap.html, изменённый styles.css, docs/network-view/, notebooks/, корневой package-lock.json. Эти правки сохраняются вне коммита задачи.

Изучены App, api, ui, styles/interface, девять страниц, локализации EN/RO/RU, FastAPI main/research/workspace, adapter, store, explain, analytics, model_kpis, features.py и код detection script 06.

## До изменений

- Оболочка уже имеет светлые карточки и ленивую маршрутизацию. Нет тёмной темы. Мобильное меню разворачивает всю навигацию в потоке, вместо отдельной панели. Sticky topbar перекрывает заголовки при прокрутке к элементам.
- TenderDetail раскрывает одновременно факты, четыре оценки, правила, пять слоёв объяснения и ограничения. Нет графика распределения score и компактной матрицы согласия. Методология и результаты смешаны.
- Нет самостоятельных разделов моделей и индикаторов. KPI и RACI существуют и должны сохраняться.
- Длинные таблицы и подписи нуждаются в ограничении высоты и ширины. Recharts уже покрывает основные виды аналитики; новая библиотека не требуется.
- Локализации типизированы относительно EN. Добавляемые действия и объяснения должны присутствовать на трёх языках.
- Количества, сырые score и percentiles имеют разный смысл. Их нельзя помещать на одну шкалу или считать вероятностью коррупции.

## Данные и границы достоверности

- Tender: model_flags (true/false/null), rule_score, iso_score, lof_score, svm_score, risk_score, risk_level, n_models_flagging, consensus_flag, flags и семь основных значений индикаторов; has_bid_data и has_award_data.
- Explanation: facts, indicators, detectors, references, limitations. Это детерминированные объяснения, а не доказательство причинности.
- Analytics: распределения/ECDF, scatter, корреляции, category comparison/crosstab/time series. Их база — текущая проекция корпуса, не обучающие данные модели.
- Mongo anomaly_scores хранит run_id. CSV fallback не содержит run_id: его нельзя автоматически приписывать текущему detection_summary.
- В локальном Mongo два запуска; последний detect-20261009T064837Z-8e1170 совпадает с detection_summary. Для графиков моделей сравниваются только записи с тем же непустым run_id.
- MAD: сохранены score, флаг и параметры scored_features/z_threshold для совпадающего summary. Медианы/MAD по обучающим признакам не сохранены: не восстанавливать по клиентской выборке.
- IF/LOF: сохранённые score и решения доступны. Contamination — параметр обучения, не числовая граница score. Не придумывать деревья и соседей.
- SVM: код score = -decision_function. Нулевая граница может описываться только при совпадении записи с подтверждённым summary; отсутствие сведений остаётся явным.
- estimate_to_award_ratio фактически estimated_value / award_total с fallback award_value, fillna(1), clip(0,20). Существующая английская generic подпись API вводит в заблуждение — в новой странице использовать логику кода.
- bid_window_days заполняется 30 при пропуске, clip(0,3650); short_deadline <7. Поэтому наличие производного значения не доказывает полноту исходных сроков. Известное смешение PN/EV и отсутствие t0 сертификации должны оставаться видимыми.
- Два buyer–supplier share в текущем коде совпадают: это не два независимых сигнала.

## Реализация после аудита

Приоритет: повторно используемая карточка модели и анализ выбранной закупки; отдельные маршруты models/indicators; provenance по реальному run_id; progressive disclosure; темы light/dark; выдвижная мобильная навигация; контроль ширин 375/768/1024/1440/1920; сохранение существующих функций.

Вдохновение, без копирования кода/ассетов: Apple HIG Charts (https://developer.apple.com/design/human-interface-guidelines/charts), Tabler (https://github.com/tabler/tabler), Berry (https://github.com/codedthemes/berry-free-react-admin-template), указанные пользователем демонстрационные Apple-clone/portfolio и awesome-frontend-charts. Технологический стек остаётся React/TypeScript/Recharts.
