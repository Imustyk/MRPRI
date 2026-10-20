# Implementation Summary — iterative improvement protocol (8 phases)

Date: 2026-10-20 · Branch `feature/risk-specific-detection` (not pushed to
`main`) · Commits `5535ab9` → `ddb2f8b` → `f395361` → `9d363b5` → `fd693f7`
→ `10d35bd` → this doc

This is the umbrella deliverable of the author's iterative-improvement brief:
one record per phase (problem → importance → change → test → improvement →
unresolved), the full verification table, and the guard-rail compliance
statement. Every number below was produced by an executed check in this
repository; `results/` artefacts are regenerable and stay gitignored.

**Framing:** measurement, not a methodology cycle. Production stays **v0**;
no v7; the v0–v6 budget (6 of 10) is not consumed; the production model was
never retrained; no threshold, band, vote or quota changed anywhere in this
branch.

---

## Phase 1 — plan (`docs/IMPROVEMENT_PLAN.md`)

Problem: no binding plan for the author's 8-phase brief. Change: plan with
guard rails, inspection findings, per-phase files/verifications, acceptance
mapping. Improvement: work became falsifiable up front (e.g. «no adoption
without CI excluding 0» was fixed *before* any result existed). Unresolved:
none.

## Phase 2 — real-data integration (`docs/REAL_DATA_INTEGRATION_REPORT.md`)

Problem: the dashboard rendered real data but could not show provenance,
measured (negative) evaluation results or per-procedure explanations; four
correctness bugs; zero HTTP-route tests. Change: dataset/evaluation/
explainability/explanation endpoints, real model identity, 422-for-bad-input
fixes, search/sort optimisation, typed frontend helpers + provenance card +
research section + explanation panel + MTender links. Test: 20 `TestClient`
tests; `tsc --noEmit` clean; `npm run build` success; uvicorn smoke on real
data. Improvement: synthetic-as-real failure modes are now structurally
impossible (origin probe + loud synthetic marking + `available: false`
degradation). Unresolved: browser-level visual smoke not possible in this
environment (no attached browser); recommended as a manual step.

## Phase 3 — temporal leakage (`docs/TEMPORAL_LEAKAGE_AUDIT.md`)

Problem: post-decision information was measured for one label (10 of 22
features) but there was no availability matrix, no stage-aware feature sets,
no automated leakage tests. Change: `src/mtender/stage_features.py`
(availability matrix + stage-valid column sets), 13 tests asserting the
stage rules mechanically. Improvement: future work cannot silently reintroduce
post-decision features. Unresolved: the production v0 feature set itself is
unchanged by design (measurement only).

## Phase 4 — risk-specific detection (`docs/RISK_SPECIFIC_FEATURES.md`)

Problem: the project had one anomaly lens for four distinct risk types.
Change: modules A–D (competition, splitting *without* invented legal
thresholds, buyer–supplier recurrence from prior awards only, value
outliers labelled *not* overpricing) + a direct-award track with matched
random controls and no forced equal rates; NaN semantics for undetermined
indicators. Test: 24 synthetic-data tests; live run over 152 378 real
procedures (hit rates and the direct-award track's significant
repeat-winner enrichment +0.2400 [0.2190, 0.2612]). Improvement: an
explanation-level decomposition of *which* pattern fired. Unresolved: the
indicator count is not a ranking — evaluated in Phase 7.

## Phase 5 — external validation + expert review
(`docs/EXTERNAL_VALIDATION_REPORT.md`, `docs/EXPERT_REVIEW_PROTOCOL.md`)

Problem: six external label sources with no uniform registry, no uncertainty
estimation, no robustness checks; no expert-review workflow. Change:
`scripts/35` (registry with blocked/pending statuses, pre-registered
baselines, supplier/buyer cluster bootstrap B=1000, paired vs-v0 CIs,
leave-one-supplier-out, temporal guard) and `scripts/36` (blinded 3×100
export, fact-only columns behind a deny-list, separated key, header-only
template). Test: 9 tests; live runs; the ANSC rebuild reproduces MTA-0013
exactly after the PN-ocid alias fix (1 222 positives; v0 AUC 0.5112 vs
0.511196). Improvement: external validation is now falsifiable and
cherry-pick-proof. Unresolved (documented blockers): ANSC decision
documents, HG 957/2017, HG 1420/2016, the 2026 judgments, the Metodologia
AAP file were not provided; the MoF cross-check needs the live API; no
qualified reviewers engaged yet — all expert metrics stay `pending`, never
imputed.

## Phase 6 — explainability (`docs/REAL_DATA_INTEGRATION_REPORT.md`, §3)

Problem: no per-procedure explanation; global importance hidden. Change:
deterministic five-layer explanation (facts → indicators → detector
percentiles → references → limitations) with «anomaly ≠ corruption» and
«unscored ≠ clearance» stated in the limitations layer; global importance
plus the **measured SHAP/LIME disagreement, reported not hidden**
(`/api/explainability`). Test: layer/determinism/404/omitted-field tests.
Improvement: every claim about a procedure is now traceable to a layer with
its uncertainty attached. Unresolved: causal interpretation is deliberately
out of scope.

## Phase 7 — controlled experimental evaluation
(`docs/EXPERIMENTAL_MODEL_COMPARISON.md`)

Problem: pre-registered question — does the Phase 4 indicator count rank
external-label positives better than the production score? Change: nothing
in production; the evaluation was run per the pre-registered rule. Result:
**H1 rejected on both labels** — paired ΔCI vs v0 excludes 0 *against*
`module_hits` (AAP +0.0463 [0.0032, 0.0998]; ANSC +0.0274 [0.0046, 0.0551]).
Improvement: an honest negative result is now a first-class deliverable;
the module track keeps its explanatory role and is not promoted.
Unresolved: none — the pre-registered criterion was applied as written.

## Phase 8 — verification & summary (this document)

All verification executed on 2026-10-20:

| Check | Result |
|---|---|
| `scripts/19_final_verification.py` | ✅ all headline numbers reproduce |
| full `pytest` | ✅ **287 passed** |
| `tests/test_api_real_data.py` (TestClient) | ✅ 20 passed (in the 287) |
| `tsc --noEmit` (frontend) | ✅ 0 errors |
| `npm run build` | ✅ built in 1.17 s |
| uvicorn smoke, real data | ✅ 152 378 records, origin `real-ocds`, `hash_verified: true`, external AUCs 0.493453 / 0.511196 served, 5-layer explanation |
| `scripts/35` live (B=1000, seed 42) | ✅ registry + both labels + LOO + temporal written |
| `scripts/36` live (N=100, seed 42) | ✅ 3×100 blinded, deny-list check pass, template 0 rows |
| `scripts/37` live | ✅ `docs/figures/external_validation_baselines.png` + `external_validation_paired_vs_v0.png` rendered from artefacts only |

## Before and after (branch-level)

| Axis | Before (`f114452`, 2026-10-19) | After (`72ca368` + follow-up, 2026-10-20) |
|---|---|---|
| Provenance/evaluation/XAI routes | none; `/api/meta` served the stale synthetic model name | `/api/dataset` (origin probe + SHA-256 verification), `/api/evaluation` (negatives visible), `/api/explainability`, `/api/tenders/{id}/explanation` with `available: false` degradation |
| Per-procedure explanation | none | deterministic five-layer (facts → indicators → detector percentiles → references → limitations) |
| Temporal-leakage control | measured for one label only | availability matrix + stage-aware sets + 13 automated tests |
| Risk-specific indicators | none (single anomaly lens) | modules A–D + direct-award matched-control track, 24 tests, live run over 152 378 procedures |
| External-label registry | six scattered sources | uniform schema with honest blocked/pending statuses |
| External-validation statistics | point estimates | supplier/buyer cluster bootstrap (B=1000), paired vs-v0 CIs, LOO robustness, temporal guard |
| Expert review | no workflow | blinded 3×100 export, deny-list column check, header-only answer form implementing the five brief questions, metric definitions; results honestly `pending` |
| Experimental-model comparison | not pre-registered | pre-registered baselines + adoption rule; H1 rejected, no adoption |
| Charts | none for external validation | `docs/figures/*.png`, reproducible via `scripts/37` |
| API docs / change log | routes table without research endpoints | README updated; CHANGELOG + cycle_log entries |
| Tests | — | +67 new on this branch → **287 total** |

## Guard-rail compliance

| Guard rail | Status |
|---|---|
| production v0 unchanged; no v7; budget 6/10 untouched | ✅ `scripts/19` reproduces every v0 headline number |
| no retraining; holdout 2022–2024 not used for selection | ✅ all new code is measurement-only |
| anomaly ≠ corruption wording | ✅ in explanations, labels, docs, disclaimers |
| no fabricated metrics/labels/reviews | ✅ blocked sources carry blockers with `n_records = 0`; the expert template is header-only |
| no SMOTE, no neural networks, no direction flips, no equal quotas, no threshold/band/vote changes | ✅ pre-registered directions locked and unit-tested |
| synthetic never presented as real | ✅ origin probe + loud marking; synthetic tests are labelled as fixtures |
| `data/raw/**` read-only; `scripts/00..11` untouched | ✅ |
| author's uncommitted changes preserved | ✅ (`frontend/src/styles.css`, deleted `_lang-bootstrap.html`, `notebooks/`, `docs/network-view/`, `package-lock.json` untouched; no lock-file writes) |

## How to reproduce everything

```bash
.venv/bin/python scripts/19_final_verification.py
.venv/bin/python -m pytest -q                        # 287 tests
.venv/bin/python scripts/34_risk_modules.py          # Phase 4 indicators (live)
.venv/bin/python scripts/35_external_validation.py   # Phase 5/7 framework (B=1000)
.venv/bin/python scripts/36_export_expert_review.py --n 100 --seed 42
.venv/bin/python scripts/37_external_validation_chart.py           # docs/figures/*.png
npm run build --prefix frontend
.venv/bin/python -m uvicorn backend.app.main:app --port 8000
```

---

*Measurement only. No production decision was taken on the basis of these
results; the experimental ranking was not adopted; the external labels remain
weak proxy labels; an expert review remains pending with real reviewers; an
anomaly is not a finding of corruption.*
