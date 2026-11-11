# Frontend verification report — stage 2 (analytical visualisations, request states, URL context, theming/i18n, tests)

**Date:** 2026-11-10 · **Branch:** `feature/risk-specific-detection` · **Baseline HEAD:** `a37838d`
**Stack:** React 18 + TypeScript + Vite 6 + Recharts + i18next (Apple-inspired design preserved, no redesign).

> **Risk disclaimer (EN):** An anomaly warrants further analysis. It is not proof of corruption, collusion or a legal violation. Percentiles are midranks within this dataset, not probabilities.
>
> **Дисклеймер риска (RU):** Аномалия является основанием для дополнительного анализа, но не доказательством коррупции, сговора или нарушения закона. Процентили — это средние ранги внутри этого датасета, а не вероятности.

---

## 1. Problems → changes

### P0 — quartile chart (`/distributions` → Relationships → Spread)
| Problem | Change |
|---|---|
| p25/median/p75 were not rendered as a real interval (risk of stacked/summed bars) | New pure module `src/pages/quartileRange.ts` (`buildQuartileLayout`, `classifyQuartileRow`, `quartileMarks`, `nonPositiveQuartileRows`) + hand-rolled SVG `src/components/QuartileRangeChart.tsx`: one span from **real p25 → real p75** and a **separate diamond median marker**; values are never summed (unit-tested numerically: 10/20/30 → x=0/200/100 on a 200 px plot) |
| Null quartiles silently became 0 | `p25/p75 = null` → row classified `missing`, rendered as a labelled placeholder ("no quartiles · n=…"), never a bar from zero; `p25 > p75` → `invalid` placeholder |
| Zero/negative values on a log axis | Log is used only when **every** endpoint is > 0 (auto also requires ≥100× span); rows a log axis refuses are **listed by name** in the note; explicit log with nothing positive falls back to linear with an explanation |
| Tooltip/units/n missing | Focusable rows (`tabIndex=0`, `role="img"`, aria-label with raw quartiles + measure + n) drive a **reserved tooltip box below the chart** (raw p25/median/p75/n, units via `value_label`); full raw-quartile table in a disclosure |
| Empty/invalid groups | Explicit `Empty` state from `RequestPanel` when no group qualifies; undrawable rows counted in the note |

### P1 — request states (all four Distributions tabs + Tenders)
| Problem | Change |
|---|---|
| No unambiguous loading/success/empty/error | New `useRequest` hook (`src/hooks.ts`): abort + `live` guard, per-request error, `stale` flag, `reload()`; new `RequestPanel` (`src/ui.tsx`) centralises: persistent `role="status"` announcer (loading/updating/ready), error → `ErrorNote` + retry (old data hidden), loading-no-data → pending, stale → `.stale-note` banner naming **both** parameter sets, `isEmpty` → `Empty`, else children |
| Stale data shown as the answer to new filters | `stale` only renders behind the explicit "updating" marker with `describe(key)` labels (`params_*` i18n keys per tab) |
| Late responses on fast switching | Fetch aborted on key change + `live` flag (unit test proves a late resolve cannot overwrite a newer result) |
| Scatter vs group-compare conflated | Separate `useRequest` instances/keys for scatter and spread; by-group table only renders when fresh (`dataKey === key`) |
| Infinite skeletons after error/empty | Terminal states asserted per tab in e2e (`distributions.spec.ts`) |
| Retry without reload | `state.reload()` re-runs only the failed request (unit-tested) |

### P1 — Tenders URL as source of state
| Problem | Change |
|---|---|
| Filters/page lost on navigation | `Tenders.tsx` rewritten: `q`, `level`, `procedure`, `min`, `offset` read from and written to the query string. Scenario verified e2e: search+band+percentile+page 2 → open tender → **Back → identical filters, page and input values**; reload/shared link restores too |
| Bad URL params reach the API | `readTenderFilters` validates: band whitelist, `min` snapped to 0–95 step 5, `offset` floored to a whole 40-row page; an effect normalises foreign params via `replace` (no history stop) — e2e |
| History spam / lost context | Filter edits `replace`, paging `push` (Back steps pages; Forward restores — e2e); filter change clears `offset` (e2e) |
| Debounced search | 300 ms debounce writes `q` to the URL; e2e proves no per-keystroke request and that the list request follows the URL |
| Full reset | "Clear filters" button (toolbar and empty state) |
| Procedure overwritten by background search | `ProcedurePicker` keeps a `manual` ref: auto-select only when nothing is selected, not manual, not busy/error and query empty; `ResearchAnalysis.select` uses functional `setParams` preserving other params with `replace: true` |

### P1 — model results & workbench
| Problem | Change |
|---|---|
| Histogram markers ambiguous | `histogramFlags()` pure helper + custom Recharts `shape`: threshold interval is **hatched (texture)** (`url(#hist-hatch-…)` pattern + red stroke), score interval solid green; threshold `ReferenceLine` (5 px dashed) drawn **before** the score line (2 px solid) so both stay legible in the same bin; legend explains the coincidence |
| Exact numbers vs bin markers | Exact score/threshold sit in `.model-metrics`/`.model-boundary` next to the chart; `bin_note` states markers identify intervals, not exact coordinates; exact counts in tooltip (raw `n`) and in the disclosure table |
| `log10(1+n)` confusion | Toggle labelled `log10(1 + count)`; note says ticks show counts with raw n in tooltip/table; y-axis tick formatter inverts to raw counts |
| Empty bins / all-zero / missing score | Zero-height bars render nothing; all-zero → domain `[0,1]`, ticks `[0]`, explicit `hist_all_zero` note; missing score → no selected marker derived from a stale flag (unit + fixture e2e) |
| Pooling raw scores across models | Unchanged: each card shows only its own run's reference (`scales_note`); no cross-model pooling introduced |
| `% 4` keyboard nav | `ModelWorkbench` wraps by `analysis.detectors.length`, guards missing targets, hides tablist at 0 detectors, `MODEL_SHORT[key] ?? label` fallback, agreement rows skip indices past the list (unit-tested for 0/1/4/partial) |

### P1 — layout/a11y, P2 — themes/i18n
- **Semantic tokens** in `product.css` (`--chart-gold/teal/muted/neutral/heat/range`, `--band-*`, light+dark); Distributions/Overview charts use tokens only; dark-theme hacks on Recharts internals removed; `corrColor` uses `color-mix` tokens; crosstab cells = `--chart-heat` mixed into `--card`, **capped at 55 %** so numbers keep WCAG AA in both themes (unit test computes the real mixed colours from the shipped CSS: ≥ 4.5:1 in light and dark).
- Crosstab/heatmap intensity note translated; Network canvas `NAVY/GOLD` constants left unchanged (canvas needs resolved colours — scoped limitation, see §5).
- **i18n:** all new states/units/tooltips/captions/announcements added in **EN/RU/RO** (distributions, common, analysis, tenders, fixture); locale-completeness unit test asserts RU/RO carry every EN key, no empty strings, and the new keys are actually translated.
- **Mobile menu:** focus trap (Tab/Shift+Tab wrap), Escape closes and returns focus to the toggle, backdrop, `inert` on background — e2e at 375 px; after navigation focus moves to `#main`.
- **Network:** keyboard/touch/mouse equivalence via the accessible path — sortable table rows (`tabIndex=0`, Enter/Space select), focusable matrix axis labels (Enter/Space drill), drill-down `<details>` list; tab-stop count bounded (≤ 100 rows asserted).

## 2. Verification commands and results

| Command | Result |
|---|---|
| `npx tsc --noEmit` | **0 errors** (tests included; `noUnusedLocals/Parameters` respected) |
| `npm run build` (vite) | **✓ built in 1.10 s**; `dist/assets` contains **0 fixture chunks** (dev-only route tree-shaken) |
| `npx vitest run` | **7 files, 45/45 tests passed** (quartile geometry, useRequest race/stale/error, RequestPanel states, Tenders URL validation+behaviour, histogramFlags, workbench 0/1/4/partial detectors, heatmap AA contrast, locale completeness) |
| `npx playwright install chromium` | chromium 1.65 headless shell installed |
| `uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` | live API (serves `data/processed/tenders.json`, 152 378 procedures; read-only) |
| `npx playwright test` | **27/27 e2e tests passed (2.2 min)** against dev server + live API |

Environment notes: Node v20.20.0, npm 10.8.2; Playwright browsers were not present and were installed as part of this task; no pipeline/data-generation scripts were run.

## 3. Checked matrix

- **Routes:** `/`, `/tenders`, `/tenders/:id`, `/models`, `/indicators`, `/distributions`, `/network`, `/workspace`, `/method`, `/kpis`, `/raci` (+ dev-only `/__fixture/model-card`).
- **Widths:** 375 / 768 / 1024 / 1280 / 1440 / 1920 — asserted: no document-level horizontal overflow; wide tables scroll inside their containers; charts (`recharts`, quartile SVG, network canvas) keep non-zero size after load and resize.
- **Languages:** EN / RU / RO (`<html lang>` asserted; visible translations asserted on 5 key routes).
- **Themes:** light / dark (`data-theme` asserted; screenshots).
- **Text zoom:** 200 % re-checked for overflow on the 5 key routes in all 6 language/theme combinations.
- **Interactive scenarios:** Tenders filters→detail→Back, reload, Back/Forward, invalid params, page reset, debounce; mobile menu focus trap/Escape/focus return; Network mouse≡keyboard≡tap selection + drill list; Distributions tab terminal states + live regions; quartile rows keyboard focus + raw tooltip + raw table; model histogram states via fixture.

## 4. Evidence (screenshots, `docs/frontend-verification/`)

- `distributions-spread-quartiles.png` — P0 interval chart with median markers, legend, raw table.
- `tenders-filters-restored.png` — filters/page restored after open → Back → reload.
- `mobile-menu-open-375.png` — drawer open at 375 px (focus inside).
- `network-keyboard-selection.png` — accessible table selection path.
- `histogram-same-interval.png` — score + hatched threshold marker sharing one interval, exact values adjacent.
- `histogram-zero-and-missing.png` — all-zero and missing-score cards.
- `tender-detail-model-card.png` — real procedure, honest "reference unavailable" state.
- `i18n-{en,ru,ro}-dark.png` — RU/RO/EN in dark theme.
- `route-*-375.png` / `route-*-1440.png` — all 10 routes at both extremes.

## 5. Limitations and remaining defects

1. **No run provenance in the served dataset.** 0 of 152 378 rows carry `score_provenance.run_id`, so on live procedures the same-run reference (bins/threshold/percentile) is genuinely absent and the card shows the honest "A comparable reference is unavailable" state (asserted e2e). The histogram marker states were therefore verified against an **isolated dev-only fixture** (`/__fixture/model-card`, synthetic data, excluded from production builds — 0 fixture chunks in `dist`). This is a data/API limitation, documented, not worked around.
2. **Network canvas colours** (`NAVY`/`GOLD` constants) are not tokens: canvas `fillStyle` needs resolved colours. DOM legend swatches use the same constants; theming of the canvas itself is a scoped, documented limitation.
3. **Browsers:** Playwright ran on Chromium only (Firefox/WebKit not installed). Touch equivalence uses emulated `tap` (`hasTouch`), not a physical device.
4. **Sticky-vs-focusables:** covered indirectly (menu focus assertions, drawer focus trap); no automated global check for every sticky header on every route.
5. **Visual regression:** screenshots are evidence, not golden-diff baselines (no diff tool introduced).
6. **Vote denominator "/ 4"** in the consensus block left as-is — it encodes the documented voting rule, which this task must not change.
7. Pre-existing, untouched: MTA gates `45`/`47`/`46 validate` exit 5 by design; `reports/MTA-0019_FINAL.md` still awaits human labeling (out of scope here).

## 6. Final diff vs baseline (integrity)

```
git diff HEAD -- backend data results models scripts src/mtender   →  (empty: 0 lines)
```

- **Backend/API/models/training/features/ETL: unchanged.** No pipeline or data-generation command was run; `data/`, `results/`, thresholds, voting rules and risk bands untouched.
- **Frontend changes (this task):** `App.tsx`, `ui.tsx`, `hooks.ts`, `pages/{Distributions,Tenders,Overview,ResearchAnalysis}.ts(x)`, `components/{ModelExplanationCard,ProcedurePicker,QuartileRangeChart}.tsx`, `product.css`, i18n `en/ru/ro × {distributions,common,analysis,tenders}`, new `pages/{quartileRange.ts,ModelCardFixture.tsx}`, test infra (`vitest.config.ts`, `playwright.config.ts`, `src/test/`, `src/**/*.test.ts(x)`, `e2e/`), `package.json` (+`test`, `test:watch`, `test:e2e` scripts; devDeps: vitest, jsdom, @testing-library/*, @playwright/test, @types/node).
- **Foreign baseline changes preserved:** `frontend/src/styles.css` (user edit), deleted `frontend/public/_lang-bootstrap.html`, untracked `docs/network-view/`, `notebooks/`, root `package-lock.json`.
- New artefacts: `docs/frontend-verification/` (this report + 31 screenshots); `frontend/test-results/` gitignored.
- **Not pushed** — all commits (if any) stay local per instructions.
