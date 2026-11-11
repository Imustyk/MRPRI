# Отчёт об извлечении исходов решений ANSC (MTA-0018, шаг 3)

Сгенерировано: 2026-11-08T08:36:45Z. Только измерение; production v0 не меняется; `data/raw/**` не трогается.

## Метод (двухэтапный)

- **этап 1 — локация резолютивной части**: сначала сильные структурные якоря (`HOTĂRĂȘTE`, `DECIDE`, OCR-вариант `d e c i d e`), затем только слабые (`temeiul`, `inadmisibil`, `retragere`, `anulează`) как вспомогательные; кандидаты проверяются с конца документа по типу и контексту — последний якорь не принимается вслепую; слабый якорь открывает часть только если за ним следует полная формулировка;
- **этап 2 — классификация по полной юридической формулировке** внутри найденной части (`se admite parțial contestația`, `se respinge contestația`, `declară contestația inadmisibilă`, `retragerea contestației`, …); цитаты чужих решений и требования заявителя в мотивировочной части игнорируются;
- без достоверной резолютивной части — `unknown`; разные исходы по разным жалобам/требованиям без явного `parțial` — `unknown`; противоречие (`admite` + `respinge contestația` без `parțial`) — `unknown`; решение никогда не классифицируется по одному слову;
- OCR — только при отсутствии/непригодности текстового слоя, со последних страниц, с ограничением числа страниц;
- цитата-доказательство берётся из ОРИГИНАЛЬНОГО текста (нормализованная копия не используется как улика), для каждой записи: исход, точная цитата, страница, метод, уверенность, ссылка на первоисточник.

## Фактические числа

| Показатель | Значение |
|---|---:|
| Строк инвентаризации | 7750 |
| Документ присутствует в песочнице | 7295 |
| Документ отсутствует / не PDF | 455 |
| С текстовым слоем | 6208 |
| Сканов (OCR) | 1087 |

| Исход | Всего | Доля | С текстовым слоем | Сканы |
|---|---:|---:|---:|---:|
| `admitted` | 100 | 1.3% | 79 | 21 |
| `partially_admitted` | 21 | 0.3% | 18 | 3 |
| `rejected` | 10 | 0.1% | 10 | 0 |
| `inadmissible` | 0 | 0.0% | 0 | 0 |
| `withdrawn` | 7 | 0.1% | 5 | 2 |
| `terminated` | 0 | 0.0% | 0 | 0 |
| `unknown` | 7612 | 98.2% | 6096 | 1061 |

Методы извлечения: `no_resolutory_part` — 6082, `ocr_no_resolutory_part` — 1041, `none` — 470, `resolutory_strong_anchor` — 123, `ocr_resolutory_strong_anchor` — 27, `resolutory_weak_anchor` — 5, `ocr_resolutory_weak_anchor` — 2.

Уверенность: `none` — 7612, `high` — 107, `medium` — 29, `low` — 2.

## Причины `unknown`

| Причина | Записей |
|---|---:|
| no structural anchor in the document (not a decision text or unreadable) | 3195 |
| 1 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 1216 |
| 2 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 920 |
| 3 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 772 |
| document not fetched or not a PDF | 455 |
| 4 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 386 |
| 6 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 219 |
| 9 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 158 |
| 5 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 144 |
| 7 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 51 |
| 15 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 43 |
| no extractable text (missing or unusable document) | 15 |
| multiple different outcomes for different claims/complaints: admitted, partially_admitted | 14 |
| 10 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 12 |
| 8 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 5 |
| different complaints in the resolutory part: partial admission nr. 02/413/19 vs rejection nr. 02/411/19 | 3 |
| 11 anchor candidate(s) found but no full resolutory formulation follows them (cited/motivational text only, or unreadable resolutory part) | 2 |
| different complaints in the resolutory part: partial admission nr. 02/880/21 vs rejection nr. 02/883/21 | 1 |
| different complaints in the resolutory part: partial admission nr. 02/118/21 vs rejection nr. 02/111/21 | 1 |

## Ограничения

- `unknown` означает «исход не установлен надёжно» и НИКОГДА не является отрицательной меткой (жалоба не «отклонена»); это правило закреплено тестом;
- OCR использует модель `eng` (румынские диакритики могут искажаться) — записи с методом `ocr_*` имеют пониженную уверенность;
- извлечение — техническая операция над документом; корректность классификации подтверждается только ручной проверкой (шаг 4), метрики качества (шаг 5) до неё не считаются;
- возможные ошибки сопоставления документа с процедурой и апелляционное смещение выборки не устраняются извлечением;
- исход решения по жалобе — результат административного спора, а не доказательство нарушения; решение может быть изменено судом.

> An upheld ANSC complaint indicates an administrative procurement dispute outcome and does not constitute proof of corruption.

> Индикатор потенциального риска, а не доказательство коррупции/нарушения. Требуется проверка компетентным органом.
