> Дополнение после отдельного согласования: CSV-парсер исправлен, API перезапущен. Live mean_risk=76.59; обзор и список работают без alerts. Подробности: [CSV_PARSER_FIX.md](CSV_PARSER_FIX.md). Ниже сохранён отчёт предыдущего frontend-этапа; его CSV-блокер и проверка неизменности backend относятся к состоянию до этого согласованного исправления.

# Завершение frontend: пользовательские сценарии и достоверность

Дата: 10 ноября 2026. Проект `/Users/imustyk/Diplom`, ветка `feature/risk-specific-detection`, начальный и конечный HEAD `9b8167d4320d3c305d8fd3de0933e7781a53f58d` (предыдущий baseline `a37838d`). Коммит и push не выполнялись.

## Результат и границы

Реализованы безопасное отображение API, независимые запросы карточки/моделей/объяснения, завершённые действия Workspace, применение сохранённых представлений, возврат к точному списку и поддержка темы canvas. Существующий визуальный стиль и архитектура React Router/Recharts сохранены. Неизвестная закупка и неизвестный маршрут имеют разные состояния.

Frontend готов к работе с корректным контрактом API. Достоверность текущих live scores **не подтверждена**: CSV-fallback backend повреждает поля, MongoDB не подключена, у строк отсутствует подтверждённый scoring run. Тестовые гистограммы не доказывают наличие настоящей reference-выборки. Формальный MTA-0020 не запускался.

## Исходное состояние и сохранность

До изменений: удалён `frontend/public/_lang-bootstrap.html`, изменён `frontend/src/styles.css`, untracked `docs/network-view/`, `notebooks/`, корневой `package-lock.json`. Они сохранены. Применимых AGENTS.md в репозитории и проверенных родительских каталогах не обнаружено. Изучены diff HEAD, отчёт stage-2, страницы, API client, FastAPI schemas и read-only endpoints.

Сняты исходные status/diff и SHA-256 деревьев `backend`, `data`, `results`, `src`, `scripts`. Финальная сверка подтвердила неизменность этих деревьев, HEAD, пользовательского `styles.css` и корневого lock-файла. 152 443 файла дерева data проверены по содержимому. Старые свидетельства `docs/frontend-verification/` не перезаписаны. Все новые свидетельства находятся в `docs/frontend-completion/`.

## Матрица функций: до → после

Повторяющиеся элементы одной формы/таблицы объединены в строку. «Проверено по коду» не означает проверку настоящих расчётных результатов. GET — read-only; мутации Workspace выполнялись исключительно через браузерный API-перехват в памяти.

| Маршрут / действия | API / метод | Исходное состояние | Итоговые loading / error / empty / success | Проверка и фактическая граница |
|---|---|---|---|---|
| `/`: показатели, даты/cohorts, tooltip/легенды, ссылки к списку/методологии, источник/покрытие | GET stats, meta, health, dataset?verify_hash=true | Часть ошибок скрывалась; повтор загружал всё; некорректный ранг попадал в UI | Независимые запросы и повторы; недостоверный stats скрыт с причиной; advisory ошибки локальны; null не заменён нулём | Live terminal-state + шесть ширин; live графики заблокированы CSV; корректные values/графики проверены изолированно |
| `/tenders`: поиск с задержкой, band/procedure/min, сброс, страницы, кликабельная строка/ссылка, MTender | GET tenders, stats (options) | Не передавался signal; ошибка справочника скрывалась; карточка теряла список | Контрактная ошибка вместо ложной таблицы; отдельный retry options; abort+late guard; URL восстанавливает q/level/procedure/min/offset | Исходные тесты URL и новые E2E visible-back; controlled API; live повреждённые значения отклоняются |
| `/tenders/:id`: факты, section links, disclosures, модели, индикаторы, первичный источник, возврат | GET tender, model-analysis, explanation | Explanation error проглатывалась; общий retry; любая ошибка называлась not found | Три независимых запроса; 404 explanation = unavailable, 500/network = retry; tender 404 отличается от отказа; безопасный returnTo; rank legacy только при совпадении row/run | E2E: отказ/повтор explanation не перезапрашивает tender/model; unsafe return; прямой вход; live 404 и ошибочный контракт |
| `/models`: поиск/выбор процедуры, Inspect, четыре вкладки/клавиши, score distribution/raw table/params/agreement | GET tenders, tender, model-analysis, explanation | Stage-2 уже исправил bins/markers и неполный список; не было независимых retry | Сохранён корректный model card; run/tender association проверяется; ручной выбор создаёт history entry, автоподбор replace; отсутствие reference не заполняется | 4 модели на controlled API, same-bin/edge/zero/missing tests, rapid A→B/Back; реальный same-run reference отсутствует |
| `/indicators`: группы, раскрытие формул/значений/ограничений, выбранная закупка | GET tenders, tender (+ независимые вспомогательные ресурсы) | Контекст выбора мог теряться | Общий защищённый picker; переход models ↔ indicators ↔ detail сохраняет ID и returnTo | E2E переключений и матрица EN/RU/RO; вычисления индикаторов не менялись |
| `/distributions`: четыре вкладки, feature/method/group/scale/log controls, quartiles, raw tables/tooltips | GET analytics/features, correlations, distribution, scatter, group-compare, crosstab | Signal игнорировался; семантических проверок не было; геометрия quartiles исправлена stage-2 | Все сигналы до fetch; перезапрос блока независим; invalid percentile в aliases/summary скрывает зависимое представление; padded bin edges не объявляются наблюдениями | 45 исходных unit включают stage-2; изолированные browser quartile/raw-table/request-state tests; live catalog отклоняется из-за scores |
| `/network`: фильтры, reset, top N, sort, mouse/keyboard/touch, CSV, drill, DOM list | GET graph (две ограниченные выборки) | Цвета canvas фиксированы; malformed percent encoding мог уронить страницу | Отмена чтения, локальный retry; безопасный hash с сообщением; canvas использует вычисленные CSS colors и перерисовывается при теме; DOM-альтернатива сохранена | Изолированные keyboard/touch/theme/CSV, live error-state; числовые правила bands/голосования не изменялись |
| `/workspace`: summary, tabs, Activity | GET summary/activity | Ошибки summary скрывались, Activity не обновлялась | Отдельные loading/error/retry/empty; revision обновляет summary/активный список/детали/Activity после мутаций | In-memory browser store; существующие пользовательские записи не менялись |
| Workspace Cases: create/read/edit title/owner/summary/OCIDs/status/delete + case note | GET/POST cases; GET/PATCH/DELETE cases/:id; POST annotations | Не было ожидания, rollback, prop sync; детали могли перепутаться | Async lock+disabled+status; draft сохраняется при отказе; статус только после ответа, синхронизация prop; delete с ожидающим подтверждением; отмена устаревшего чтения; OCID link | Полный E2E CRUD, отказ создания/статуса, double submit/delete, note и Activity; компонентные тесты отказа ConfirmButton |
| Workspace Annotations: create/filter/search/edit/delete | GET/POST annotations; PATCH/DELETE annotations/:id | Мутации без защиты; гонки поиска | Изолированное состояние чтения, сохранение черновика, Awaited form/button/delete | Полный E2E CRUD на mock store |
| Workspace Watchlists/items: create/select/edit/color/delete/add/edit-note/remove | GET/POST watchlists; GET/PATCH/DELETE watchlists/:id; POST .../:id/items; PATCH/DELETE .../items/:itemId | Выбор мышью; ошибки действий терялись; детали могли опоздать | Кнопка выбора с aria-pressed, вложенные controls независимы; rollback color; request key для деталей; редактирование списков и item note | Полный E2E CRUD, выбор Enter, мобильный сценарий; null/empty/error различаются |
| Workspace Saved views: create/read/edit name/description/payload/delete/Apply | GET/POST views; PATCH/DELETE views/:id; navigation `/tenders?...` | Apply отсутствовал; произвольный JSON без object validation | Понятные поддерживаемые поля + legacy JSON; object-only; неподдерживаемые поля сохранены и явно блокируют Apply; min_value не проигнорирован | E2E invalid []; min_value; edit → Apply → reload → delete; unit безопасной сериализации |
| `/method`: ссылки, определения, bands/недоступные признаки | GET meta | Ошибка meta скрывалась | Статическая методология доступна; live metadata имеет loading/error/retry | Live маршрут/шесть ширин, проверка связей и метаданных; никаких запусков pipeline |
| `/kpis`: KPI/checks, evaluation, explainability, disclosure/ссылки | GET model-kpis, evaluation, explainability | Retry advisory сбрасывал все блоки | Три независимых запроса, локальные ошибки, null/нет источника не становятся оценкой качества | Live terminal state + adaptive sweep; код расчётов/источники не изменены |
| `/raci`: role focus, поиск, phase, A/R-only, reset, ссылка методологии | Нет API, статическая матрица | Работало; удалять функциональность не требовалось | Сохранено; локальные controls не меняют научные результаты | Browser route/layout + дополнительная проверка controls |
| Неизвестный маршрут; shell search/theme/language/menu | Router, localStorage; GET только после перехода | Stage-2 содержит focus trap | Сохранены Escape, Tab trap, возврат focus и мобильный drawer; отдельная 404-страница | Chromium menu E2E, язык/темы, unknown-route live |

## Исправления достоверности

Общая проверка применяется к readJson/send перед передачей данных всем страницам. Percentiles/risk_score должны быть конечными 0–100, votes целыми 0–4, решения boolean/null, количества конечными неотрицательными. ISO/SVM raw score не ограничен 0–1; LOF/MAD проверяются в своей шкале. Параметр estimator `n_jobs=-1` не принят за количество наблюдений. Проверяются также переименованные аналитические summary/координаты risk_score. Нарушение отклоняет payload с локализованной причиной; отсутствуют clamp, imputation, пересчёт percentile или сохранение исправленных значений.

Значения 0, false, null и unavailable различаются. Нет client reference, invented thresholds, trees, neighbors, attribution. Неподтверждённый run запрещает bins/threshold/percentile/reference count/agreement; связь analysis с конкретной строкой и run проверяется отдельно. Legacy fact percentile не отображается без совпадающей provenance строки.

## Внешний дефект CSV: воспроизведение и влияние

Источник `results/tables/tender_anomaly_scores.csv`, SHA-256 `d698f71872db5bbcd56838b590e9604547ba8348a1e68af83e5f97fcce7d941d`.

| Разбор | Строк | Лишние поля | Числовой max_score вне 0–1 | Нечисловой max_score |
|---|---:|---:|---:|---:|
| csv.QUOTE_NONE | 152378 | 37200 | 30786 | 700 |
| стандартный csv.QUOTE_MINIMAL | 152378 | 0 | 0 | 0 |

Минимальное read-only воспроизведение:

```python
import csv
from pathlib import Path
source = Path('results/tables/tender_anomaly_scores.csv')
for mode in (csv.QUOTE_NONE, csv.QUOTE_MINIMAL):
    rows = extra = invalid = non_numeric = 0
    with source.open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle, quoting=mode):
            rows += 1
            extra += None in row
            try:
                value = float(row['max_score'])
                invalid += not (0 <= value <= 1)
            except (ValueError, TypeError):
                non_numeric += 1
    print(mode, rows, extra, invalid, non_numeric)
```

Причина: `_csv_scores` в `backend/app/store.py` игнорирует CSV quoting; запятые в заключённых в кавычки полях смещают столбцы. Влияние: scores, flags, агрегаты и связанные визуализации могут быть ошибочны. Live `/api/stats` вернул `mean_risk=9974840695.45`, поэтому показ графика недопустим. `/api/health` сообщил `mongodb.connected=false`, что делает fallback актуальным.

**Предлагаемое отдельное исправление:** проверить стандартный CSV parser на этом файле, число полей и типы/домены на границе backend, запретить тихое смещение, сопоставить все строки с авторитетным export, добавить регрессию quoted fields и сверку выборочных процедур. В этой задаче backend не исправлялся. Простое прохождение frontend ranges не доказывает правильность: ошибочно сдвинутое значение может случайно оказаться внутри диапазона.

Отдельный blocker: 0 строк имеют доказанную привязку к run_id в этом CSV. detection_summary рядом не устанавливает такую связь. Нужен подтверждённый экспорт provenance/идентичности запуска; восстановление через догадки во frontend запрещено. MongoDB connection также требует отдельной диагностики. После backend/data исправлений необходим новый live прогон.

Санитизированные примеры:

```json
{"endpoint":"/api/stats","n_tenders":152378,"mean_risk":9974840695.45,"ui":"contract error; chart hidden"}
{"endpoint":"/api/health","mongodb":{"connected":false},"ui":"source unavailable"}
{"endpoint":"model-analysis","run_id":null,"n_reference":0,"detectors":[{"score_percentile":null,"bins":[],"threshold":null}],"ui":"reference unavailable"}
{"endpoint":"controlled test only","risk_score":0,"n_models_flagging":0,"model_flags":{"mad":false,"svm":null}}
```

Последний пример — тестовый, не результат научного расчёта. Пути SQLite, parties и строки жалоб из live API здесь не публикуются.

## Проверки и свидетельства

| Команда (в frontend) | Фактический результат |
|---|---|
| `npx tsc --noEmit` | PASS |
| `npm test` | 9 файлов, **85/85**, в том числе все исходные 45 тестов без изменения их файлов |
| `npm run build` | PASS; Vite 752 modules; test/dev route и fixture-run не найдены в dist |
| `npx playwright test --reporter=line` | **45 сценариев проверены**: 43 в основном прогоне; два повторно успешно после конфликта временных trace-файлов |
| `npx playwright test --config=playwright.completion-mobile.config.ts --reporter=line` | **8/8**: четыре CRUD сценария в desktop + те же четыре на 375×812 |
| `git diff --check` | PASS |
| Content SHA-256 baseline comparison | PASS: backend/data/results/src/scripts, styles.css, root lock, HEAD |

Из 45 браузерных проверок: 17 новых controlled-API сценариев, 7 адаптированных изолированных сценариев distributions/network/tenders, 2 dev model fixture; 19 live/read-only shell/layout/source-state проверок. Основной прогон завершился 43 passed / 2 failed исключительно из-за `browserContext.close: ENOENT ... recording.trace`: параллельные desktop/mobile запуски использовали один outputDir. Две затронутые проверки повторены отдельно: **2/2 passed**. Для mobile задан отдельный outputDir; ошибка инфраструктуры и повтор сохранены в логах. Полный единичный зелёный 45/45 прогон после разделения каталогов не заявляется. Ни один mock-прогон не объявлен доказательством live reference. Сначала исходные live-dependent проверки дали 10 отказов на заблокированных источниках; лог сохранён как `full-suite-external-blockers.log`. Затем UI interaction tests явно изолированы и названы MOCKED, ошибочный selector таблицы квартилей исправлен, а отдельный live набор проверяет действительную ошибку контракта. Это разделение отражено в именах и коде тестов, без подмены production API.

Дополнительно исправлен реальный UX-дефект raw-quartile disclosure: исчезновение tooltip при уходе с фокусированной строки сдвигало summary между pointer down/up и поглощало клик. Теперь последняя изученная строка остаётся в информационном блоке, а mouse/keyboard раскрытие таблицы работает. CSV export проверен фактическим download и содержимым; RACI filters/role/reset и header search — отдельным сценарием.

EN/RU/RO × light/dark: 5 маршрутов с заполненными тестовыми карточками/моделями/индикаторами/графом/формами × 6 ширин (375/768/1024/1280/1440/1920) = 180 сочетаний. В каждом сочетании проверено отсутствие document overflow; для моделей наличие четырёх вкладок и реального chart container ненулевого размера, End/выбор модели. Дополнительно legacy language tests проверяют пять live маршрутов × 6 language/theme combinations, где ошибка контракта остаётся честным terminal state.

Live read-only inventory: 14 маршрутов, включая известную карточку, неизвестную закупку и неизвестный route, на всех шести ширинах; проверяются отсутствие pageerror/вечных skeleton и прокрутка таблиц внутри. Это проверка UI/доступа, **не подтверждение правильности scores**. Мутации live API не выполнялись.

200%: штатный `chrome.tabs.setZoom(tabId,2)` в одноразовом локальном тестовом профиле/расширении Chromium; не CSS zoom и не pinch. Проверены 11 live terminal routes и 4 populated mock routes. Измерены outerWidth=1440, innerWidth=720, devicePixelRatio=2, visualViewport.scale=1; overflow отсутствует. Постоянный профиль пользователя не изменялся.

Reduced motion включён в матрице; keyboard model tabs, menu focus trap/Escape, watchlist Enter, network rows Enter/Space и touch tap проверены. Реальные touch-устройства и screen reader в этой среде не проверялись. Firefox и WebKit не установлены: попытки запуска сообщили отсутствующие executable; ничего не скачивалось.

Визуально просмотрены: открытый case editor, отказ explanation, unsupported saved view, models/indicators, canvas и DOM-list, результаты мутаций. При проверке обнаружен и исправлен белый фон canvas в dark theme. Формы и действия проверены после прокрутки, а не только верх страниц.

## Следующий минимальный шаг

Отдельно исправить CSV-fallback на backend и подтвердить происхождение scores/run. После этого повторить live API и графические сценарии без перехвата. До восстановления источника сайт честно показывает недоступность зависимой аналитики. Модели, ETL, ANSC labels и научные результаты не менялись; MTA-0020 остаётся вне этой работы.

## Изменённые файлы

- `docs/frontend-completion/browser-availability.json`
- `docs/frontend-completion/chromium-final.log`
- `docs/frontend-completion/chromium-recheck.log`
- `docs/frontend-completion/csv-audit.json`
- `docs/frontend-completion/full-suite-external-blockers.log`
- `docs/frontend-completion/invariants.json`
- `docs/frontend-completion/production-build.log`
- `docs/frontend-completion/verification.json`
- `docs/frontend-completion/workspace-mobile.log`
- `docs/frontend-completion/zoom.json`
- `frontend/e2e/completion-fixtures.ts`
- `frontend/e2e/completion-live.spec.ts`
- `frontend/e2e/completion.spec.ts`
- `frontend/e2e/distributions.spec.ts`
- `frontend/e2e/helpers.ts`
- `frontend/e2e/network.spec.ts`
- `frontend/e2e/routes.spec.ts`
- `frontend/e2e/tender-detail.spec.ts`
- `frontend/e2e/tenders.spec.ts`
- `frontend/playwright.completion-mobile.config.ts`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/components/AsyncAction.test.tsx`
- `frontend/src/components/AsyncAction.tsx`
- `frontend/src/components/ProcedurePicker.tsx`
- `frontend/src/components/QuartileRangeChart.tsx`
- `frontend/src/components/useProcedureData.ts`
- `frontend/src/contracts.test.ts`
- `frontend/src/contracts.ts`
- `frontend/src/hooks.ts`
- `frontend/src/i18n/locales/en/completion.ts`
- `frontend/src/i18n/locales/en/index.ts`
- `frontend/src/i18n/locales/ro/completion.ts`
- `frontend/src/i18n/locales/ro/index.ts`
- `frontend/src/i18n/locales/ru/completion.ts`
- `frontend/src/i18n/locales/ru/index.ts`
- `frontend/src/navigation.ts`
- `frontend/src/pages/Distributions.tsx`
- `frontend/src/pages/Kpis.tsx`
- `frontend/src/pages/Method.tsx`
- `frontend/src/pages/Network.tsx`
- `frontend/src/pages/Overview.tsx`
- `frontend/src/pages/ResearchAnalysis.tsx`
- `frontend/src/pages/TenderDetail.tsx`
- `frontend/src/pages/Tenders.tsx`
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/pages/network/band.ts`
- `frontend/src/pages/network/presentation.ts`
- `frontend/src/product.css`
- `frontend/src/ui.tsx`

- `docs/frontend-completion/REPORT.md` и новые PNG/JSON/log свидетельства в этом каталоге.

Исходные 7 файлов unit/component-тестов не менялись. Изменения вне frontend и новой frontend-документации относительно сохранённого старта отсутствуют. В отчёте перечислены именно изменения этой задачи; начальные пользовательские файлы исключены из списка.
