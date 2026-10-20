# Real Data Integration Report — Phase 2 (retro-document) + Phase 6 (explainability)

Date: 2026-10-20 · Branch `feature/risk-specific-detection` · commits `ddb2f8b`
(backend) and `f395361` (frontend)

The frontend already rendered exclusively real API data before this branch
(verified by search — no synthetic/mock values exist in `frontend/src`), but
the *integration* had honesty and metadata gaps: the dashboard could not show
where its data came from, could not show the measured external validation
results (including negatives), could not explain an individual procedure, and
carried several correctness bugs. This report is the promised per-fix record
(проблема / важность / изменение / тест / улучшение / нерешённое).

---

## 1. Backend correctness fixes

| # | Problem | Importance | Change | Test |
|---|---|---|---|---|
| 1 | `store.invalidate()` did not clear the CSV score cache → stale scores served after a pipeline rebuild | silent wrong data | `_csv_scores` cleared in `invalidate()` | `test_invalidate_clears_csv_score_cache` |
| 2 | `level=` typo returned `[]` (looked like an empty result) | silent wrong data | unknown risk level → **422** with the allowed values | `test_unknown_risk_level_is_422_not_empty_page` |
| 3 | `POST /api/pipeline/run?source=ocds` without `ocds_path` → unhandled **500** | robustness | argument validation → **422**; synthetic source keeps its explicit `confirm=true` guard (409 otherwise) | `test_pipeline_argument_error_is_422`, `test_pipeline_synthetic_guard_keeps_409` |
| 4 | `/api/meta` served the **stale synthetic** model name against real data; `etl_run_id` was null | honesty — wrong model identity is the worst failure mode | `load_meta` reports the production run (real model/run/scoring date from detection artefacts) and marks synthetic datasets loudly | `test_meta_serves_production_model_not_synthetic_meta`, `test_meta_marks_synthetic_dataset_loudly` |
| 5 | 4 fields were re-lowercased per request over 152 k rows; no `sort` param | performance + usability | normalisation at load time; a search-key cache; deterministic `sort=` (file order by default, `risk`/`value`/`date`) | `test_default_sort_keeps_file_order`, `test_sort_risk_value_date`, `test_search_case_insensitive_and_field_bounded`, `test_level_filter_and_pagination` |

## 2. New provenance and evaluation surface

| Endpoint | What it serves | Degrades honestly? |
|---|---|---|
| `GET /api/dataset?verify_hash=` | record counts (152 378), origin probe (**real vs synthetic** by schema), provenance, model identity; `verify_hash=true` recomputes the SHA-256 manifest and reports `verify_hash: true/false` against `results/mongo/export_manifest.json` | missing artefacts → `available: false` payloads, never invented numbers |
| `GET /api/evaluation` | the research evaluation actually on disk: external-label metrics **with their negative results visible** (v0 ≈ chance on AAP/ANSC proxy labels), CIs, seed/noise stability, drift, bias | artefacts absent → `available: false` |
| `GET /api/explainability` | global explainability artefacts including the **measured SHAP/LIME disagreement, reported not hidden** | same |

Tests: `test_dataset_report_shape_and_counts`,
`test_dataset_verify_hash_detects_mismatch` (tampered fixture file must be
detected), `test_evaluation_keeps_negative_external_results`,
`test_evaluation_degrades_to_unavailable_without_artifacts`,
`test_explainability_states_shap_lime_disagreement`.

Smoke on real data (uvicorn): `/api/dataset` → 152 378 records, origin real,
`verify_hash: true`; `/api/evaluation` → AUC 0.493453 (AAP) and 0.511196
(ANSC) exactly as recorded in `results/methodology/`.

## 3. Per-procedure explanation (Phases 2 + 6)

`GET /api/tenders/{id}/explanation` (`backend/app/explain.py`) builds a
**deterministic, five-layer** explanation, keeping five things apart:

1. **facts** — observed fields of the procedure (absent fields omitted, never
   defaulted);
2. **indicators** — which risk indicators the procedure triggered;
3. **statistical contributions** — detector-level percentiles/contributions
   relative to the population;
4. **references** — links to the original MTender procedure
   (`public.mtender.gov.md/tenders/{ocid}`) and to the methodology artefacts;
5. **limitations** — what the explanation does *not* prove. Anomaly ≠
   corruption is stated here; an unscored record is **not** a clearance.

No causal wording anywhere; explanations are identical for identical inputs
(tested byte-for-byte). Tests: `test_explanation_layers_and_determinism`,
`test_explanation_unscored_record_is_not_a_clearance`,
`test_explanation_unknown_id_404`, `test_explanation_facts_omit_absent_fields`.
Global importance plus the SHAP/LIME disagreement are surfaced through
`/api/explainability` — the disagreement is a reported measurement, not a
hidden inconsistency.

## 4. Frontend (commit `f395361`)

- `frontend/src/api.ts`: typed helpers for the new endpoints (dataset,
  evaluation, explainability, per-procedure explanation).
- **Overview**: dataset provenance card — counts, origin (real/synthetic badge),
  model identity, scoring date, SHA-256 verification state.
- **Kpis**: evaluation/reliability section rendering external metrics with CIs
  **including the negative results** (no cherry-picking).
- **TenderDetail**: layered explanation panel + external MTender link per
  procedure.
- **Tenders**: MTender links per row.
- i18n: 126 strings × 3 locales (en/ro/ru); `frontend/src/styles.css` append.

Verification: `tsc --noEmit` → 0 errors; `npm run build` → success; backend
route coverage via the 20-test `TestClient` suite
(`tests/test_api_real_data.py`).

## 5. Unresolved / limitations

- A **browser-level smoke was not possible** in this environment (no desktop
  browser attached to the agent session); the UI layer was verified by
  type-check, production build and API-level smoke through the vite proxy.
  A manual visual pass in a browser remains recommended.
- `/api/dataset` SHA-256 verification depends on
  `results/mongo/export_manifest.json` existing locally (gitignored); on a
  fresh clone it reports `available: false` rather than a fabricated hash.
- Evaluation numbers served by `/api/evaluation` reflect the artefacts from
  the 2026-10-19 audit run (MTA-0012/0013); the Phase 5 framework produces a
  *separate*, population-specific re-measurement documented in
  `EXTERNAL_VALIDATION_REPORT.md`.

## 6. Reproduction

```bash
.venv/bin/python -m pytest tests/test_api_real_data.py -q   # 20 TestClient tests
.venv/bin/python -m uvicorn backend.app.main:app --port 8000
curl 'localhost:8000/api/dataset?verify_hash=true'
npm run build --prefix frontend
```

---

*All served numbers come from artefacts on disk; missing artefacts degrade to
`available: false`, never to invented values. Synthetic data is only ever
produced by the explicit, confirmed pipeline route and is labelled as such.*
