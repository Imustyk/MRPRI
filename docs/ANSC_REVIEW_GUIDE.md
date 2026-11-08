# ANSC_REVIEW_GUIDE — инструкция по ручной проверке документов (MTA-0019)

**Этот гид — для ЧЕЛОВЕКА-проверяющего.** Автоматика (алгоритмы, OCR, LLM,
классификаторы) поля `reviewer_*` **никогда** не заполняет: машинная
«проверка» не является независимой человеческой экспертизой и за неё не
выдаётся. Разметка выполняется только вручную.

> An upheld ANSC complaint indicates an administrative procurement dispute
> outcome and does not constitute proof of corruption.
>
> Индикатор потенциального риска, а не доказательство коррупции/нарушения.
> Требуется проверка компетентным органом.

## 1. Файлы

| Файл | Что это |
|---|---|
| `data/external/ansc_manual_review_pilot10.csv` | **пилот: первые 10 документов** (§3 ниже) |
| `data/external/ansc_manual_review_50.csv` | все 50 документов выборки |
| `docs/ANSC_MANUAL_REVIEW_PROTOCOL.md` | полные правила определения исходов (7 категорий, several complaints, маркеры) |
| `data/external/ansc_review_sample_50.csv` | машинная сторона (предсказания) — **НЕ открывать до завершения разметки** |

**Слепота (правило §3 протокола):** в файлах `ansc_manual_review_*`
отсутствуют колонки `extracted_outcome` / `extraction_method` /
`confidence` — предсказание скрыто до окончания разметки. Сначала
самостоятельно определите исход, запишите его, и только потом (по
желанию) сравните с автоматическим в машинной выборке.

## 2. Что заполнять (колонки `reviewer_*` — всегда сначала пустые)

| Колонка | Допустимые значения |
|---|---|
| `reviewer_outcome` | `admitted`, `partially_admitted`, `rejected`, `inadmissible`, `withdrawn`, `terminated`, `unknown` |
| `reviewer_document_type` | `ansc_decision`, `other_document`, `uncertain` |
| `reviewer_link_verified` | `confirmed` (документ относится к указанной процедуре), `rejected` (относится к другой/не относится), `uncertain` |
| `reviewer_evidence_page` | номер страницы с резолютивной частью (только цифры; можно оставить пустым) |
| `reviewer_evidence_quote` | фактически найденная цитата (можно пусто) |
| `reviewer_notes` | свободный текст; маркеры — §4 |

Всё, что начинается с `reviewer_`, заполняется **только вручную**. Если
исход достоверно не устанавливается — ставьте `unknown` (не «наугад» и не
подгонку под предсказание).

## 3. Пилот из 10 документов (`ansc_manual_review_pilot10.csv`)

Группа отобрана детерминированно и покрывает разные исходы, типы PDF
(текстовый слой и скан) и уровни уверенности извлечения. Прежде чем
переходить к остальным 40, заполните эти 10 строк вручную.

| # | OCID | № решения | Страница резолютивной | Локальный PDF |
|---:|---|---|---:|---|
| 1 | `ocds-b3wdp1-MD-1563452870963` | — | 8 | `…/mtender_ansc_decisions/e827b0425e6850b2.pdf` |
| 2 | `ocds-b3wdp1-MD-1586765700891-PN-1586765700928` | 03D-355-20 | 15 | `…/mtender_ansc_decisions/f852a9cbadcb1955.pdf` |
| 3 | `ocds-b3wdp1-MD-1601638627306` | 03D-884-20 | 7 | `…/mtender_ansc_decisions/bd91c7b1df610a41.pdf` |
| 4 | `ocds-b3wdp1-MD-1586171621901-PN-1586171621936` | 03D-541-20 | 9 | `…/mtender_ansc_decisions/0d959caa563a7d1f.pdf` |
| 5 | `ocds-b3wdp1-MD-1617707120055` | — | 1 | `…/mtender_ansc_decisions/290f4d3b2b2748f0.pdf` |
| 6 | `ocds-b3wdp1-MD-1544104748471` | — | нет | `…/mtender_ansc_decisions/38cbd8f562426c9b.pdf` |
| 7 | `ocds-b3wdp1-MD-1566565055568` | — | нет | `…/mtender_ansc_decisions/8d3eb3f5135d52ef.pdf` |
| 8 | `ocds-b3wdp1-MD-1566362389793-PN-1566362389828` | 03D-704-19 | 27 | `…/mtender_ansc_decisions/a1694f98ed185c87.pdf` |
| 9 | `ocds-b3wdp1-MD-1638446510157` | — | нет | `…/mtender_ansc_decisions/fa4bdd1a59c101fc.pdf` |
| 10 | `ocds-b3wdp1-MD-1664265846211` | — | нет | `…/mtender_ansc_decisions/70662a35a2f85733.pdf` |

Полный путь песочницы: `/var/folders/j8/sq_85g7x7_d3rwd0crjrg5nh0000gn/T/mtender_ansc_decisions`
(он же в `results/methodology/ansc_decision_inventory.json → sandbox_dir`;
имя файла = `sha1(document_url)[:16] + ".pdf"`).

**Ссылки на первоисточник** (в каждой строке CSV — колонка
`document_url`), напрямую:

1. <http://storage.mtender.gov.md/get/e9791e92-cee7-4d8e-a436-4fd9cfae3e6f-1568025514094>
2. <http://storage.mtender.gov.md/get/95d648f1-c2be-4165-ad49-a2e8f32ea725-1592222887931>
3. <http://storage.mtender.gov.md/get/17b5512d-8752-4273-a3fe-b725a7f13ef5-1606812367374>
4. <http://storage.mtender.gov.md/get/15c7a06c-6774-48c6-a020-295a6da3ae0d-1597235222575>
5. <http://storage.mtender.gov.md/get/ddd85a70-993a-4ff5-858e-a834d532e35d-1618396648832>
6. <http://storage.mtender.gov.md/get/093485e9-5640-4238-afe3-c77718c59c92-1551857636671>
7. <http://storage.mtender.gov.md/get/1b0f792a-7fc9-4b76-a6cc-aa7ced44b923-1573217218424>
8. <http://storage.mtender.gov.md/get/f81e614f-bea3-41e6-84a9-1e0dc8f52b6a-1574863078619>
9. <http://storage.mtender.gov.md/get/3ad68f5b-6ca8-480c-bb43-401165cfdab3-1640162322617>
10. <http://storage.mtender.gov.md/get/afc9c415-0aa4-40a7-bce5-298f49a0d5a8-1667546156250>

Строки 6, 7, 9, 10 (и 1–5) без извлечённой цитаты/страницы — для них
просто откройте документ и найдите резолютивную часть самостоятельно
(конец документа: `HOTĂRĂȘTE:` / `DECIDE:`). Строка 8 — случай с
**несколькими жалобами**: перечислите исходы по каждой в `reviewer_notes`
через `multiple:` и поставьте `unknown`, если исходы различны (§5
протокола).

## 4. Маркеры в `reviewer_notes`

| Маркер | Значение |
|---|---|
| `mislink: …` | документ не является решением по жалобе на эту процедуру |
| `quote page N` | цитата фактически на странице N |
| `quote not found` | цитата не найдена в документе |
| `multiple: nr-A outcome; nr-B outcome` | разные исходы по разным жалобам |
| `contradiction: …` | противоречивые формулировки в резолютивной части |
| `garbled OCR` | текст восстановлен трудно |

## 5. Порядок работы

1. Откройте PDF (локальная копия из песочницы **или** `document_url`).
2. **Сначала определите исход самостоятельно** — не подсматривая в
   машинную выборку (`ansc_review_sample_50.csv`).
3. Заполните `reviewer_document_type`, `reviewer_link_verified`,
   `reviewer_outcome` (+ по желанию страницу/цитату/заметки).
4. После пилота из 10 — те же действия для остальных 40 строк
   `ansc_manual_review_50.csv`.
5. Проверка себя (можно после разметки):
   ```bash
   .venv/bin/python scripts/46_ansc_review_package.py validate                 # 0 = готово, 5 = прогресс, 6 = невалидно
   .venv/bin/python scripts/46_ansc_review_package.py validate --file data/external/ansc_manual_review_pilot10.csv
   .venv/bin/python scripts/45_ansc_review_metrics.py                           # до конца разметки: exit 5, metrics: null
   ```
6. Только после ВСЕХ 50 строк `scripts/45` посчитает метрики; внешняя
   метка `ansc_upheld` создаётся отдельным скриптом `scripts/47` и тоже
   отказывается работать до полной разметки.

## 6. Запреты

* не заполнять `reviewer_*` автоматикой, OCR, LLM или классификатором;
* не копировать в `reviewer_*` машинное предсказание;
* не подсматривать `extracted_outcome` до собственного решения;
* не изменять `data/raw/**`, `backend/**`, `frontend/**`, production v0,
  признаки и веса моделей;
* не считать метрики и не делать выводов о качестве/превосходстве моделей
  до полной ручной разметки (это MTA-0020).
