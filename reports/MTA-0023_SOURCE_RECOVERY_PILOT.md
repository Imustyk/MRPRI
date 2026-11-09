# MTA-0023 — ограниченный пилот восстановления первоначальных версий MTender

Дата: 2026-11-09. Ветка `feature/risk-specific-detection`, исходный коммит `71d8153`. Ровно две процедуры: `ocds-b3wdp1-MD-1659961877383` и `ocds-b3wdp1-MD-1665058207960`.

## 1. Вывод

**Получение первичных файлов принципиально возможно: официальное storage вернуло notice PDF для обеих процедур, включая две разные редакции августовского документа. Восстановление полного publication snapshot не доказано: CERTIFIED 0/2 процедур, 0/8 publication-признаков. MTA-0020: NO-GO.**

Идентичность и содержание найденных документов — PARTIALLY VERIFIED. Начальные структурированные tenderPeriod.startDate/endDate отсутствуют в полученных PDF; исходные procurementMethod/details и время первой публичной доступности не сертифицированы. Первая публичная contract notice publication (t0) не установлена достоверно. Полученные PDF — кандидаты первоначального notice, а не доказанные полностью исходные snapshots.

Остальные шесть TEST-процедур не запрашивались. Допуск TEST остаётся0/8, исходный состав по меткам2+/6− не меняется. Улучшено покрытие первичных документов, а не число сертифицированных наблюдений. Современные значения и дефолты не выданы за исторические.

## 2. Источники, доступ и лимит

Изучены отчёт MTA-0022, coverage CSV, feature certification CSV, source evidence JSON и два исходных raw packages. Из них извлечены exact actualReleases URI, четыре tender.documents notice URL и пять уникальных releaseID/amendsReleaseID. Ссылка на повторный notice внутри bid attachment от2022-10-28 исключена из загрузки: это более позднее размещение, не первоначальная tender-публикация.

Пилот завершён на **19/20 HTTP-запросах**: 8 ответов200, 6 перенаправлений301, 5 ответов404. Принято более строгое ограничение: каждый HTTP/HTTPS hop и неуспешная проверка считаются отдельным ресурсом. Автоматические перенаправления/повторы отключены; списки процедур, сторонние документы, страницы авторизации и extension/schema URL не запрашивались. Дополнительного расширения не требуется и не выполнено.

| Номера в HTTP ledger | Источник | Результат |
|---|---|---|
|1→2,3→8|actualReleases URI из raw, HTTP→HTTPS|2×200 JSON; по одному последнему EV release, awardUpdate, не история |
|4→9,5→10|Августовские notice documents из tender.documents|2×200 PDF, разные bytes/содержание |
|6→11,7→12|Два октябрьских tender.documents notice URL|2×200 PDF; один и тот же SHA-256, не две версии |
|13,14|Два HTTPS base record URI из raw|2×200; JSON содержимое полностью равно ранее сохранённым raw packages после декодирования |
|15–19|Проверка конкретных известных amendment releaseID в варианте `/tenders/{base}/{releaseID}`|5×404; это сконструированный вариант маршрута, **не supplied historical URI и не документированный API контракт** |

Сами releaseID/amendsReleaseID — идентификаторы, не готовые ссылки. Пять404 показывают только недоступность проверенного варианта адреса; они не доказывают отсутствие истории на сервере или невозможность иного официального API. Дальнейшие варианты маршрутов не перебирались. Реальные supplied actualReleases URI оказались доступными, но возвращают текущее состояние EV, а не набор первоначальных версий.

Все response body bytes, включая301/404, сохранены без перезаписи raw в `data/source_recovery/mta0023/01.body`…`19.body`. `http_provenance.json` содержит exact URL, retrieval UTC, HTTP status, полные response headers, request metadata, byte count и SHA-256 каждого тела. Transfer framing не является частью файла body; запрос Accept-Encoding: identity, тела не преобразовывались и не пересохранялись как PDF. Локальные текстовые извлечения и signature inspection — отдельные derived файлы. Дата HTTP Date —2026-11-09, не timestamp публикации2022. В ответах нет ETag/Last-Modified; даже их наличие само по себе не удостоверяло бы первую публикацию.

## 3. Полученные notice и timestamps

| Процедура / ресурс | Содержание и исходные страницы PDF | SHA-256 |
|---|---|---|
|MD-1659961877383 /09.body,8 страниц|Glodeni industrial platform; buyer IDNO1007600042792; p1 Licitație Publică; p7 deadline Conform SIA RSAP; p8 dispatch08.08.2022|`801ce21448b88d8c72e20e3f4fe84cc2043cd6179c3a4f41029290c5649405f1`|
|MD-1659961877383 /10.body,8 страниц|Тот же объект/buyer; p1 Licitație Publică; p7 deadline Conform SIA RSAP; p8 dispatch10.08.2022|`1491de5f2724eca72229325fc83ca072dc2cbe922af67f1e6d529bb64263ab34`|
|MD-1665058207960 /11.body и12.body,по4 страницы|Coșernița aqueduct; buyer IDNO1007601009705; p1 COP; p3 дата/время — informatia o gasiti pe SIA RSAP; p4 dispatch06.10.2022|`c7c8cf8f824f6bde74ddb6a07863d0f1f11642bfd4ade922741ff2e45f3e11fd`|

URL каждой строки и связь с record находятся в ledger и release_versions.csv. Buyer/title/estimate совпадают с соответствующей процедурой; URL официального документа прямо связан через tender.documents. Сам PDF не даёт независимо аутентифицированной связи immutable OCID/version→publication. Два разных октябрьских storage identifiers отдают побайтно один документ. Название файла содержит01_12_2021, но содержание и даты указывают на06.10.2022; имя не использовано как дата публикации.

Кандидаты t0: август2022-08-08T12:39:50Z и октябрь2022-10-06T12:20:01Z — значения современных EV package.publishedDate/document.datePublished. Они согласуются по календарной дате с dispatch в PDF, но не дают неизменяемого журнала первой публичной доступности. Base package creation2022-08-08T12:31:17Z /2022-10-06T12:10:07Z и PN.start2022-08-01 /2022-10-01 не приняты за t0.

PDF содержат signature fields `/ETSI.CAdES.detached`:09 —3,10 —5,11 —1. Прочитаны /M, metadata CreationDate/ModDate и структура полей. /M заявляет08.08,10.08,06.10.2022 соответственно; криптографическая проверка цепочек, revocation и доверенного TSA не выполнялась. Ни имя signed.pdf, ни /M, ни CreationDate не являются подтверждением публикации. Даже удостоверенное время подписи не означало бы публичную доступность файла в тот момент; дополнительно нужен publisher publication/audit log с привязкой к hash/version. Проверка подписей не инициировала сетевых OCSP/CRL-запросов.

Визуально просмотрены исходные p1,7,8 августовских редакций и p1,3,4 октябрьского документа: заголовки, buyer, сроки, процедура и dispatch читаемы. Текст сверён с изображениями. Значения60 дней валидности оферт и6/8 месяцев исполнения не перепутаны с bid window.

## 4. Цепочки изменений

Августовский EV-prefix: `ocds-b3wdp1-MD-1659961877383-EV-1659962391382-`.

| Release suffix | amends suffix | Дата, заявленная в современном amendment metadata | Получение исходного release payload |
|---|---|---|---|
|1659962391552|не установлено|не установлена независимо|проверенный маршрут404|
|1660158674116|1659962391552|2022-08-10T19:11:13Z|проверенный маршрут404|
|1660227337708|1660158674116|2022-08-11T14:15:37Z|проверенный маршрут404|

Реальные PDF09/10 подтверждают различающееся содержание двух notice-кандидатов, но не полноту цепочки. Например, p1 срок исполнения меняется6→8 месяцев, p7 гарантия работ2→5 лет. Это не поля tenderPeriod. В обеих редакциях точная дата/время подачи отсылает к SIA RSAP. К событию11.08 отдельный notice body не найден среди доступных notice references; нельзя считать, что содержание не изменилось. Документ metadata10.08 связан с amendment по времени и record references, однако immutable version/hash binding не доказан.

Октябрьский EV-prefix: `ocds-b3wdp1-MD-1665058207960-EV-1665058802048-`.

| Release suffix | amends suffix | Дата, заявленная в современном amendment metadata | Получение исходного release payload |
|---|---|---|---|
|1665080328131|не установлено|не установлена независимо|проверенный маршрут404|
|1665121866628|1665080328131|2022-10-07T05:51:06Z|проверенный маршрут404|

Предшественник1665080328131 не объявлен первоначальным notice: цепочка до первого события не получена. Одинаковые PDF11/12 не объясняют изменение07.10; поправка могла затрагивать структурированные поля/иные условия. Отсутствие тела версии оставляет field-specific changes UNKNOWN.

ActualReleases live responses содержат по одному release: август `…1669106739437`, date2022-11-22T08:45:38Z; октябрь `…1674552248461`, date2023-01-24T09:24:07Z. Tag awardUpdate; дата намного позже первоначального notice. Формальная оболочка releases[] не делает такой ответ архивом первоначальных версий. В исходных base records по-прежнему только compiledRelease, original release chain не появилась.

## 5. Сертификация полей и признаков

`mta0023_publication_evidence.csv`:20 строк (10 полей/проверок×2), certified_value пуст во всех строках. CERTIFIED требует одновременно исходную версию нужных значений, установленную идентичность и доказанный timestamp публичной доступности; PARTIALLY VERIFIED фиксирует полученное содержательное доказательство с оставшимися пробелами, а не научный допуск к prediction. NOT CERTIFIED означает отсутствие достаточного доказательства конкретного поля/признака.

| Поле/проверка | Август | Октябрь | Основание |
|---|---|---|---|
|initial_notice_identity|PARTIALLY VERIFIED|PARTIALLY VERIFIED|Получены publisher-linked notice-кандидаты, buyer/title совпадают; first-version/publication binding не доказан|
|t0|PARTIALLY VERIFIED|PARTIALLY VERIFIED|Есть metadata-кандидат и dispatch date; нет доверенного publication log|
|tenderPeriod.startDate|NOT CERTIFIED|NOT CERTIFIED|Исходный submission start не восстановлен|
|tenderPeriod.endDate|NOT CERTIFIED|NOT CERTIFIED|Точная дата/время только на SIA RSAP; в PDF нет значения|
|procurementMethod|PARTIALLY VERIFIED|PARTIALLY VERIFIED|Документные Licitație Publică/COP, но нет аутентичного initial OCDS enum|
|procurementMethodDetails|PARTIALLY VERIFIED|PARTIALLY VERIFIED|Текстовая процедура не доказывает исходные openTender/microValue или их хронологию|
|bid_window_days|NOT CERTIFIED|NOT CERTIFIED|Нет исходной пары дат; default30 не подставлен|
|short_deadline|NOT CERTIFIED|NOT CERTIFIED|Детерминирован uncertified window;0 не подставлен|
|long_deadline|NOT CERTIFIED|NOT CERTIFIED|Детерминирован uncertified window;0 не подставлен|
|accelerated_like|NOT CERTIFIED|NOT CERTIFIED|PDF narrative acceleration не заменяет exact input procurementMethodDetails;0 не присвоен|

Итого:8 PARTIALLY VERIFIED и12 NOT CERTIFIED field/check rows;8 из них — publication feature rows, все NOT CERTIFIED. В PDF раздел acceleration говорит Nu este cazul/Nu se aplica, но production proxy — regex accelerated|urgent|exception на исходном procurementMethodDetails; narrative не преобразован автоматически в бинарный признак. Нельзя удостоверить исходный0 лишь по позднему nonmatching методу. Три window-признака не независимы.

## 6. Сопоставление с ETL

| Процедура | Современный PN.start | Современный EV.start→end | features.csv window | EV-only diagnostic |
|---|---|---|---:|---:|
|MD-1659961877383|2022-08-01T00:00:00Z|2022-08-19T07:00:00Z→2022-08-29T08:00:00Z|28|10|
|MD-1665058207960|2022-10-01T00:00:00Z|2022-10-17T11:30:00Z→2022-10-26T11:30:00Z|25|9|

Смешение PN/EV подтверждается чистым чтением текущих пакетов и ранее исследованным merge. Историческая цепочка не восстановлена; PDF не позволяют определить, были ли EV-only10/9 именно исходными. Это диагностические числа современного snapshot, не новые certified features. Исправление merge и проверка schema semantics — отдельная задача; production ETL/features.csv сейчас не менялись.

## 7. Масштабирование и альтернативы

Успешный доступ к linked notice files показывает возможность адресно получать аналогичные материалы, но не гарантирует восстановление t0 остальных шести. Эти шесть не запрашивались. Расширение требует отдельного решения и бюджета; автоматически переносить статус или скачать корпус нельзя. Для текущих двух следующий полезный шаг — ответ владельца версии/журнала, а не увеличение количества поздних snapshots.

### Проект официального запроса владельцу MTender/SIA RSAP (не отправлен)

Просим оператора/держателя первичных данных MTender/SIA RSAP предоставить для `ocds-b3wdp1-MD-1659961877383` и `ocds-b3wdp1-MD-1665058207960`:

1. Исходный опубликованный contract notice и полный упорядоченный набор initial/amendment release payloads до завершения notice-stage, включая указанные выше5 releaseID и их предшественников до первого события; отличить planning от первого публичного contract notice.
2. Для каждой версии: OCID, releaseID, amendsReleaseID, тип события, исходные bytes/формат, полный payload либо документированный diff/replay, SHA-256, timezone и раздельные created/accepted/published timestamps.
3. Исходные и изменённые tenderPeriod.startDate/endDate, procurementMethod/details с field-level provenance; пояснение семантики PN planning period против EV submission period и mapping COP/прочих методов к OCDS enums в2022 году.
4. Неизменяемый журнал публикаций/версионный экспорт или заверенное подтверждение оператора, связывающее public publication event с exact release/document hashes; описание хранения, допустимости исправления задним числом и полноты экспорта. Если доступ ограничен, пояснить официальный порядок получения исследовательской копии.
5. Историю document replacements для storage identifiers09/10 и11/12, включая дату первого публичного размещения и подтверждение, что текущие bytes соответствуют версии того времени; материалы к поправке11.08.2022 и07.10.2022.
6. Документированный публичный маршрут получения конкретного releaseID либо ограниченный архивный экспорт только этих двух процедур; пояснить, почему supplied actualReleases URI возвращает лишь последнее awardUpdate.

Контактный адрес не выдуман; запрос не отправлялся. Подпись или server timestamp оцениваются с учётом того, что именно они удостоверяют: создание/подписание, приём сервером либо публичную доступность.

### Отдельный план ретроспективного анализа

Если version history получить нельзя: preregister исследование **аномалий завершённых процедур по состоянию на дату snapshot**, без утверждений о publication-time prediction. Зафиксировать hash/date выгрузки, единицу procedure/lot, endpoint и дедупликацию жалоб. После отдельной проверки исправить PN/EV-семантику в новом versioned export; не перезаписывать исходный. Оценивать согласованность данных и описательные аномалии относительно известных административных решений, явно учитывая post-outcome поля, selection bias targeted review и отсутствие causal/early-warning интерпретации. Если поздние поля могли стать следствием ANSC, их связи с endpoint считать описательными и отдельно анализировать чувствительность к исключению таких полей. Для модельного сравнения нужны отдельный протокол, достаточный независимый корпус и согласование; 2+/6− недостаточно для формального общего вывода. В этом пилоте анализ/обучение/метрики моделей не выполнялись.

## 8. Воспроизводимость, проверки и сохранность

Добавлен offline `scripts/54_source_recovery_pilot.py`: анализирует замороженные HTTP bodies, контролирует лимит/непрерывность request numbering, размеры/SHA-256, отказывается от усечённых/подменённых bodies и сравнивает свежие base JSON с исходными raw. Повторный запуск не обращается к сети: `.venv/bin/python scripts/54_source_recovery_pilot.py`. `mta0023_release_versions.csv` различает actual latest payload, compiled snapshot, PDF candidate и недокументированный failed route probe; в отсутствующие версии значения не перенесены.

Адресный прогон source recovery + temporal audit/leakage: **35 passed**. Полный `.venv/bin/python -m pytest -q`: **575 passed**, 1 прежнее deprecation warning Starlette/AnyIO, 19.68s. Проверены непревышение бюджета, непрерывная нумерация запросов, SHA/размеры тел, отказ при подмене/усечении, блокировка сертификации без каждого обязательного доказательства и покрытие ровно двух OCID. Контроль сохранности:302 ранее существовавших отслеживаемых файла совпали с baseline, все47 input fingerprints MTA-0022 также совпали (включая игнорируемые features/raw/dumps).

Сохранены прежние ANSC labels/reviewer-поля, модели, пороги/веса, features.csv, production ETL и все результаты MTA-0019/MTA-0021/MTA-0022. Посторонние frontend/notebooks/docs/network-view/package-lock изменения не затронуты. Коммит локальный, push нет. MTA-0020 не запускался. Работа остановлена после пилота, без объявления GO и без расширения на остальные процедуры.
