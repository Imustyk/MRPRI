# Improvement plan — `feature/risk-specific-detection` (2026-10-20)

Branch: `feature/risk-specific-detection` (from `f114452`, the 2026-10-19 audit
commit). No push to `main`. Uncommitted author changes in `frontend/`
(`styles.css`, deleted `_lang-bootstrap.html`) and untracked `notebooks/`,
`docs/network-view/`, `package-lock.json` are preserved untouched.

**Guard rails carried over (unchanged):** production **v0 stays**; no `v7`;
the v0–v6 budget (6 of 10 cycles) is not consumed; no retraining of the
production model; holdout 2022–2024 never used for selection; anomaly ≠
corruption wording everywhere; no fabricated labels or metrics; `data/raw/**`
read-only; `scripts/00..11` untouched; `results/` stays gitignored
(artefacts regenerable); every claim backed by an executed check.

## What inspection found (facts that shape the plan)

1. **The frontend already displays exclusively real API data** — no synthetic
   or mock data exists in `frontend/src` (verified by search). The real-data
   layer (`store.py` + `adapter.py`) reads the 152 378-record ETL snapshot
   and production v0 scores (Mongo → CSV fallback) and has **no silent
   synthetic fallback** (the only synthetic path is an explicit
   `POST /api/pipeline/run?source=synthetic&confirm=true`, which 409s
   otherwise).
2. **Real gaps in "real-data integration"** are metadata and honesty gaps:
   * `/api/meta.model` serves the **stale synthetic** model name
     ("IsolationForest + LOF + rule layer", from legacy `meta.json`) against
     real data, `etl_run_id` is null — model version and scoring date are not
     shown anywhere;
   * no dataset/provenance endpoint (counts, SHA-256 manifest, origin
     detection real-vs-synthetic);
   * no research-evaluation endpoint (external AUCs, CIs, seed/noise
     stability, drift, bias are all on disk in `results/methodology/*.json`
     but unreachable from the UI);
   * no explanation endpoint or panel; no links to original MTender
     procedures;
   * bugs: `store.invalidate()` does not clear `_csv_scores` (stale scores
     after a rebuild), `/api/tenders?level=` typo silently returns `[]`
     (should be 422), `POST /api/pipeline/run?source=ocds` without
     `ocds_path` → unhandled 500, `/api/tenders` re-lowercases 4 fields over
     152 k rows per request;
   * **zero HTTP-route tests** (no `TestClient` anywhere).
3. Temporal leakage is already *measured* for one label (MTA-0013: 10 of 22
   features are post-decision) but there is **no feature-availability
   matrix, no stage-aware feature sets, no automated leakage tests**.
4. Risk-specific lenses (competition / splitting / network / price),
   a direct-award evaluation track, a structured label registry, an expert
   review workflow and per-procedure explanations **do not exist**.

## Phases and concrete work items

| Phase | Work | Files (planned) | Verification |
|---|---|---|---|
| **1. Inspection** | branch, preserve changes, this plan | `docs/IMPROVEMENT_PLAN.md` | git state clean except author changes |
| **2. Real data integration** | fix `load_meta` (real model/run/origin), origin probe (real vs synthetic schema), invalidate-bug fix, level validation → 422, `sort` param, search-key cache, pipeline 500 → 422; new endpoints `/api/dataset`, `/api/evaluation`, `/api/explainability`, `/api/tenders/{id}/explanation`; frontend: dataset provenance card, evaluation/reliability section, per-procedure explanation panel, MTender external links, typed api helpers, en/ro/ru strings | `backend/app/{store,main,explain,research_api}.py`, `frontend/src/{api.ts,pages/*}`, i18n locales, `tests/test_api_real_data.py` | TestClient suite + `npm run build` + uvicorn smoke |
| **3. Temporal leakage** | feature availability matrix (source, calculation, earliest availability, future-info flag, stage validity), stage-aware column sets (publication/bid/award/post-award), automated leakage tests | `src/mtender/stage_features.py`, `tests/test_temporal_leakage.py`, `docs/TEMPORAL_LEAKAGE_AUDIT.md` | pytest |
| **4. Risk-specific detection** | modules A competition, B splitting (threshold-independent by default — no invented legal thresholds), C temporal buyer–supplier network (prior-awards-only features), D value-distribution anomalies (labelled *not* overpricing); direct-award track with matched random controls (no forced equal rates) | `src/mtender/risk_modules.py`, `scripts/34_risk_modules.py`, `tests/test_risk_modules.py`, `docs/RISK_SPECIFIC_FEATURES.md` | pytest + live run |
| **5. External validation + expert review** | label registry (source/entity/dates/matching/confidence/limits, provenance-preserving, leakage guard test), AAP leave-one-supplier-out + paired baselines re-measured, ANSC complaints-vs-decisions distinction (decisions unavailable → documented blocker), blinded 3-group expert-review export (v0 / experimental / matched random) with interface = existing workspace, results pending no reviewers | `scripts/35_external_validation.py`, `scripts/36_export_expert_review.py`, tests, `docs/EXTERNAL_VALIDATION_REPORT.md`, `docs/EXPERT_REVIEW_PROTOCOL.md` | pytest + live runs |
| **6. Explainability** | deterministic layered per-procedure explanation (facts → indicators → detector percentiles → references → limitations), global importance + **SHAP/LIME disagreement stated, not hidden**; no causal wording | in Phase 2 endpoints/panel + `docs/` sections | tests |
| **7. Controlled experimental evaluation** | evaluate risk-module indicators vs baselines (amount, bidders, random, v0) on AAP/ANSC with supplier/buyer cluster CIs; **no adoption without CI excluding 0**; explicitly not a new version | `scripts/35` outputs, `docs/EXPERIMENTAL_MODEL_COMPARISON.md` | live run |
| **8. Testing & docs** | full pytest, `scripts/19`, `npm run build`, uvicorn+vite smoke, API docs in README, `REAL_DATA_INTEGRATION_REPORT.md`, `IMPLEMENTATION_SUMMARY.md`, CHANGELOG, cycle_log note (measurement, budget 6/10) | docs + CHANGELOG | all suites green |

**Acceptance mapping:** reproducibility (scripts/19 + full suite), v0
untouched, leakage tests, real data displayed with explicit provenance,
specialized indicators tested, direct award evaluated separately, honest
external validation, tests for everything added, synthetic never presented as
real, no experimental model promoted.

## Explicit non-goals

No v7 / no new production model, no SMOTE, no neural networks, no threshold
or band changes, no equal-quota fairness normalization, no holdout reuse, no
deletion of historical scripts/reports, no broad rewrites.
