# Comprehensive technical & scientific audit — MTender anomaly detection

**Date:** 2026-10-19 (initial report, written before any code changes; §7–§9
completed after the experiment and fixes)
**Auditor role:** independent ML/research-engineering review
**Repository state at audit start:** `c947083` (HEAD = origin/main, MTA-0015)
**Standing rule of the project:** an anomaly is a statistical outlier and a
potential risk indicator — **not** evidence of corruption or a violation;
verification by a competent authority is required.

---

## 1. Scope and method

The audit covers the full repository: data acquisition (MTender/OCDS API),
normalisation, feature engineering, four-detector anomaly scoring, consensus
bands, external validation (AAP interdiction list, ANSC complaint documents),
explainability (SHAP/LIME, RAG), bias audit, threshold calibration, robustness
experiments, the iterative v0–v6 protocol, tests, and documentation.

Method: full structural inspection (all scripts 00–31, `src/mtender/*`, tests,
reports, docs, artefacts on disk), re-execution of the verification suite
(`scripts/19`, full `pytest`), targeted reproducibility probes (feature
re-derivation, model artefact inventory), then one new pre-registered
experiment (noise sensitivity, §6). No historical artefact was overwritten;
`data/raw/**` was treated read-only; `backend/`, `frontend/` and
`scripts/00..11` were not modified.

## 2. Architecture (as built)

```
MTender API ──01a/01b──► data/raw/ocds_packages/*.json.gz (152 378 pkgs, ~814 MiB, 2026-09-26)
   │  (MongoDB raw_tenders/raw_parties/raw_releases; offline rebuild via seed_mongo.py)
   ├──02 normalize──► norm_tenders / norm_parties
   ├──03 features ──► features_tenders  (src/mtender/features.py — single shared implementation)
   ├──04 export ────► data/features/features.csv (152 378 × 62) + manifest with SHA-256
   ├──05 aggregations ► results/tables/*.csv (descriptive, MongoDB-computed, cross-checked)
   ├──06 detect ────► 4 detectors on identical preprocessing → tender_anomaly_scores.csv
   │                    MAD robust z-score | IsolationForest(300) | LOF(k=20, novelty) | OCSVM(rbf)
   │                    votes = n_models_flagging (0..4) → bands low/medium/high/critical;
   │                    max_score = max over per-detector percentile ranks (production ranking)
   ├──07 explain ───► permutation importance + SHAP (IF only; refuses fake SHAP for LOF/SVM)
   ├──09 external ──► AAP interdiction label (22 records → 633 procedures)
   └──10/11 ────────► MoF open data + blacklist into Mongo (independent sources)

Methodology cycle 12–31 (measurement layer, production stays v0):
   12 external metrics · 13 agreement κ · 14 threshold calibration (+temporal split, PSI/KS)
   15 seed robustness (≥20 seeds, refit) · 16 feature ablation + circularity controls
   17 per-OCID explanation · 18 bias audit (13 dimensions, 79 groups)
   19 final verification (recomputes every headline number; exits non-zero on mismatch)
   20 cycle framework (variants v0–v6, one metric suite) · 21 circularity checks
   22 cycle dynamics · 23 contract matrix · 24 LIME↔SHAP consistency
   25/26 normative RAG + self-supervised eval (hallucination = 0 requirement)
   27 paired ΔAUC cluster bootstrap · 28 random-5%-flags control for v6
   29/30/31 ANSC label reconnaissance + second external check (verdict: signal
   indistinguishable from random on the "procedure contested" label)

Serving: FastAPI (`backend/app/main.py`) over tenders.json + Mongo; React 18/Vite UI.
Tests: 9 files, 196 collected, all passing at audit start.
```

## 3. Capabilities already implemented (vs. the audit checklist)

| Checklist item | Status in repo | Evidence |
|---|---|---|
| Baseline preserved | **Yes** — production v0 never replaced; v1–v6 are measured variants only | `cycle_log.md`, `scripts/20`, contract matrix 23 |
| Threshold calibration | **Yes** — votes/top-N/round cuts, Wilson CIs, cost function, thresholds chosen on 2018–2021 and applied to 2022–2024, PSI/KS drift | `scripts/14`, `results/methodology/threshold_calibration.json` |
| Seed robustness | **Yes** — ≥20 seeds, refit of the 3 stochastic detectors, Jaccard vs seed-42, per-procedure band-change frequency | `scripts/15`, `robustness_seeds.json` |
| Feature ablation / circularity | **Yes** — non-fed control columns, noise placebo, group/behavioural ablations with refit, permutation importance re-scored vs external label | `scripts/16`, `scripts/21` |
| Bias audit | **Yes** — 13 structural dimensions, disparity ratios with bootstrap CIs, conditional deviations, TPR/FPR vs AAP with selection-bias caveats | `scripts/18` (2874 lines incl. v6 variant), `reports/bias_audit*.md` |
| External validation | **Yes, two independent labels** — AAP supplier interdiction (633 procedures) and ANSC "procedure contested" (1 665 procedures); both honestly reported as non-confirming | `scripts/12`, `scripts/31`, `reports/ansc_external_check.md` |
| Statistical validity | **Mostly** — supplier-cluster bootstrap for supplier-level labels, temporal splits, pre-registered verdict rules, hypothesis-vs-conclusion separation, holdout never used for version selection | `scripts/27`, `cycle_log.md` |
| Normalisation dependence study | **Yes** — v6 within-group normalisation measured against a random-5%-within-group control | `scripts/28`, MTA-0009 |
| Explainability | **Yes with refusals documented** — SHAP for IF only, LIME↔SHAP consistency with CIs, RAG with verbatim citations and 0-hallucination gate | `scripts/24`, `25`, `26` |
| SMOTE / supervised learning | **Correctly absent** — no reliable corruption labels exist; AAP/ANSC are weak, supplier- or procedure-attribution labels, not ground truth (see §7) | model card, MTA-0013 leakage finding |
| Reproducibility | **Strong** — pinned requirements, seeded RNG everywhere checked, SHA-256 manifests, `scripts/19` end-to-end number verification, offline rebuild path | `docs/data_provenance.md`, `scripts/19` |

## 4. Overlap assessment: existing scripts vs. the requested new work

The brief explicitly asks not to duplicate existing functionality.

* **`scripts/14_threshold_calibration.py`** already performs the threshold
  sweep, review-load economics, temporal transfer and drift analysis. The only
  *additional* question not answered there is threshold stability under input
  noise — that is covered as one metric of the new noise experiment
  (band-transition / high+-set stability), not by a second sweep.
* **`scripts/15_robustness_seeds.py`** measures *training* robustness (refit
  with different seeds). The new experiment measures *inference* robustness
  (frozen models, perturbed inputs) — a different axis; both are needed and
  neither subsumes the other. Script 15's reconstruction pattern
  (`importlib` load of `scripts/06`, deterministic `fit_sample`) is reused.
* **`scripts/16_feature_ablation.py`** covers feature *removal* (refit) and
  circularity controls — not input perturbation. No duplication.
* **`scripts/18_bias_audit.py`** covers group *disparity* of bands — the new
  experiment adds group-wise *sensitivity to noise* (a stability, not fairness,
  question). No duplication.

**Conclusion:** no equivalent of a noise/input-perturbation sensitivity audit
exists anywhere in the repository. It is the genuine gap and is implemented as
`scripts/32_noise_sensitivity.py` (§6).

## 5. Gaps and defects found during the inspection

Defects are classified: **B** = bug/defect to fix now, **D** = documentation
defect, **L** = limitation to document (no code change in this audit).

1. **B/L — production LOF, OCSVM and the MAD parameters are not persisted.**
   `scripts/06` saves only `{scaler, isolation_forest, pca, ...}` into
   `results/models/anomaly_models.joblib`. The two neighbourhood models are
   deterministic to reconstruct (seed 42 + `fit_sample(20000)`), and the audit
   reconstructs them and *verifies* fidelity against the published score table
   (§6 fidelity gates). Still, an auditor cannot reload the exact production
   scoring objects from disk. `scripts/00..11` are read-only by project rule,
   so this is documented as a limitation with a recommendation, not patched.
2. **D — stale synthetic artefacts beside the real corpus.**
   `data/processed/{meta.json, stats.json, graph.json, tenders_scored.csv}`
   still describe the legacy 1 200-row synthetic demo (`"source":"synthetic"`)
   while `tenders.json` in the same directory is the real 152 378-procedure
   corpus. The API masks it (store overrides), but the files are misleading.
   Recommendation: regenerate or quarantine under a `legacy/` name; not done
   here because `backend/ml/*` (the writer) is out of scope by project rule.
3. **D — resolved: data integrity verified against the manifest.** The
   5-byte discrepancy was between the *old* `docs/AUDIT_REPORT.md` §7.2 and
   the manifest. This audit re-hashed the files: `features.csv`
   (85 211 079 B, sha256 `9e267823…`) and `tenders.json`
   (248 705 260 B, sha256 `a7629eae…`) match
   `results/mongo/export_manifest.json` byte-for-byte. The manifest is
   authoritative; the stale figures live only in the 2026-10-09 report text.
4. **D — root `package-lock.json` is an orphan** (`{"packages":{}}`, no root
   `package.json`, untracked). Removed in a past audit per `docs/AUDIT_REPORT.md`
   §3.4 and present again; it is not in the commit set of this audit (project
   rule: never commit it).
5. **D — `.ruff_cache/` is not gitignored** (shows as untracked). One-line
   `.gitignore` addition applied in this audit (§7).
6. **D — dangling doc reference.** `scripts/seed_mongo.py` cites
   "section 18 of `NEED_TO_DO.md`" — the file does not exist. Docstring-only;
   `scripts/seed_mongo.py` is outside the 00–11 guard but also outside the
   change scope of this audit — documented only.
7. **D — run summaries are last-run snapshots, not cumulative totals.**
   `scan_summary.json` says 48 599 OCIDs (last resumed scan) while
   `fetch_summary.json` processed 152 378; quoting either alone misleads.
   The authoritative corpus size is the export manifest (152 378).
8. **D — README drift.** `README.md` §15 project tree stops at step 08 and
   §16 points Chapter 3 at `tenders_scored.csv` — the only such file on disk
   is the *synthetic* one; the real scored export is
   `results/tables/tender_anomaly_scores.csv`. Documented in §7 of this report
   (README is user-facing docs, patched minimally in §7).
9. **L — MoF cross-check compares nothing yet** (36 067 rows,
   `"compared": 0`): the available extracts (2025-12, 2026-07) do not overlap
   the 2018–2024 archived corpus. The "second source" claim is inventory-only.
10. **L — step 08 (data dictionary) requires the live API** and was skipped in
    the offline rebuild; the on-disk dictionary is dated 2026-09-26.
11. **L — known dead frontend wrappers** (`getTimeSeries`, `resetWorkspace`,
    `updateWatchlistItem`; routes `/api/indicators`, `/api/pipeline/run`)
    remain from the 2026-10-09 audit. Frontend is out of scope by project rule.
12. **No functional bugs were found in the numeric core** (features.py
    re-derivation reproduces the stored table to ≤5e-7 — CSV rounding; the
    deterministic-ness of the seeded paths was re-verified by tests).

## 6. The new experiment: noise/input-perturbation sensitivity (pre-registered)

*Research question.* Is the **fixed production v0 ranking** stable when the
input data are perturbed by small, realistic errors (misreported amounts,
counts, dates, missing publications, rounding)?

*Hypotheses (written before the run).*
* H1 — with ±1 % monetary jitter the Spearman rank correlation of `max_score`
  stays ≥ 0.99 (rank-based scoring is dominated by tail positions).
* H2 — the moderate regime (±5 %, count jitter p=0.15) keeps ρ ≥ 0.97 and
  top-200 overlap ≥ 0.8; if not, the finding is reported as instability.
* H3 — the missing-value regimes degrade more than the noise regimes for the
  affected blocks (award-derived features zero/fill-1 by ETL convention).
*H4 — per-detector comparison locates which detector drives any instability.

*Design.* Inference-only: models are **frozen** (IF from the joblib; LOF/OCSVM
reconstructed deterministically as in production and verified against the
published scores; the MAD robust statistics are recomputed by the production
code path on the scored population — documented deviation, O(n⁻¹ᐟ²) effect at
n = 152 378). Perturbations act on **source columns** of
`data/features/features.csv`; all 22 features are then re-derived by the
production `engineer_features()` so derived features stay consistent with
their sources. Identifiers (ocid, buyer/supplier ids), CPV codes, statuses,
procedure types and behavioural relationship shares are never perturbed
(numerical noise there would be meaningless). Regimes: `round` (deterministic),
`noise_small`, `noise_moderate` (10 seeds each), `missing_1pct`,
`missing_5pct` (5 seeds each). Metrics: Spearman ρ of `max_score` with
bootstrap CIs, Jaccard of high+ (votes ≥ 2), critical (votes ≥ 3) and top-200
sets, Top-K overlap (K = 50/100/200/500), 4×4 band transition matrix and
% band changes, score-distribution shifts (quantiles, two-sample KS),
per-detector ρ, and sensitivity by contract-value band and procedure type.
Outputs go to `results/methodology|tables|figures/` (gitignored,
regenerable) and the reports in this directory. Production artefacts, bands,
votes, thresholds and the v0 status are **not** modified.

## 7. Changes made in this audit (after the initial inspection)

| # | File | Why |
|---|---|---|
| 1 | `scripts/32_noise_sensitivity.py` (new) | The one genuine capability gap (§4): inference robustness of the frozen v0 ranking under realistic input perturbations. Pre-registered design (§6), resumable per-pass progress, fidelity gates before any perturbed score is trusted. |
| 2 | `tests/test_noise_sensitivity.py` (new) | 24 synthetic-data tests: perturbation determinism/invariants, dependency-consistent re-derivation, metric formulas and bounds, ETL fill conventions, no-network + `python -I` standalone execution, pre-registered constants. |
| 3 | `.gitignore` | Added `.ruff_cache/` — the cache directory was untracked-but-not-ignored and polluted `git status` (defect 5). |
| 4 | `README.md` (3 lines) | Fixed documentation drift (defect 8): the pipeline table said `scripts/01a–08` (real range is 01a–11 plus the measurement layer 12–32), and §16 pointed Chapter 3 at the *synthetic* `tenders_scored.csv` instead of `results/tables/tender_anomaly_scores.csv`. |
| 5 | `CHANGELOG.md`, `cycle_log.md` | Entries for this audit run (measurement, not a cycle: budget stays 6 of 10, production stays v0). |

Bug found and fixed during implementation: `run_metrics()` initially read
`award_value` from the scored frame that does not carry it (caught by the new
tests before any run), and `procedure_type_labels()` had a `Series.to_numpy()`
glue error on `np.where` output (caught on the first live launch, fixed and
covered by a new test).

Not changed on purpose: `scripts/00..11`, `backend/`, `frontend/`,
`data/raw/**` (project guard rails); `docs/AUDIT_REPORT.md` (historical
record); `data/processed/{meta,stats,graph}.json` + `tenders_scored.csv`
(legacy synthetic files written by `backend/ml/` — quarantining them would
touch the guarded legacy generator; recommendation only, §5.2).

## 8. Experiment results

Full write-up: `NOISE_SENSITIVITY_REPORT.md`; machine table:
`EXPERIMENT_RESULTS.csv` (31 scoring passes: 10 + 10 seeds for the noise
regimes, 5 + 5 for the missing regimes, 1 deterministic `round`; 200-rep
bootstrap CIs; ~16 s per pass).

* **Fidelity gates passed before anything else:** re-derived features match
  the stored table to 5e-7; the frozen reconstruction reproduces the
  published production scores at per-detector Spearman ≥ 0.9999997 and
  100 % band agreement — the experiment measures noise, not reconstruction
  error.
* **H1 rejected:** ±1 % monetary noise gives ρ = 0.962 [0.960; 0.963] < 0.99.
  Even so, Top-200 retains ≥ 94.5 % and ≤ 2.1 % of procedures change band —
  triage-level stability is intact, exact positions are not.
* **H2 rejected:** the moderate stress regime gives ρ = 0.646 [0.642; 0.650]
  and 28.4 % band changes (min Top-200 = 0.785 < 0.80). Reported as
  instability, exactly as the acceptance criteria require.
* **H3 (descriptive):** missing publication blocks — MTender's dominant real
  defect — are the *best-tolerated* perturbation (1 % missing: ρ 0.979,
  1.1 % band changes; 5 %: ρ 0.903, 5.2 %), better than moderate noise,
  worse than small noise.
* **Worst case is coarse rounding, not continuous noise:** the 10k-MDL grid
  collapses 63 738 distinct amounts to 1 426 (99.4 % of rows tied; below
  1 MDL mln: 101 unique values for 57 433 rows) → ρ = 0.574, LOF 0.445.
  Recommendation: never pre-round monetary inputs before scoring.
* **H4 — driver located:** stability depends on regime — OCSVM 0.966 and
  IF 0.946 are the most noise-stable detectors, LOF 0.828 (and 0.445 under
  quantization), MAD 0.803 overall but perfectly stable under ±1 % monetary
  noise (binary-flag dominated) and collapsing only under count jitter.
* **Marginal vs assignment:** KS ≤ 0.152 in every regime — the score
  *distribution* barely moves; what reshuffles is *which* procedure holds
  which rank. Group detail: `opentender`/`smallvalue`/`microvalue` are the
  most noise-sensitive types (37–47 % band changes under stress), direct
  awards the least (14.6 %).
* **No production change** follows from any of this: production stays v0,
  votes/bands/thresholds untouched, cycle budget stays 6 of 10.

## 9. Test execution, verification and recommendation

**Executed (this session, actual output):**

| Check | Command | Result |
|---|---|---|
| Final verification | `scripts/19_final_verification.py` | **EXIT=0** — "all headline numbers reproduce" |
| Full test suite | `pytest tests/ -q` | **220 passed** in 6.83 s (196 pre-existing + 24 new for scripts/32) |
| New experiment | `scripts/32_noise_sensitivity.py` | EXIT=0, 31 passes, 484 s, resumable progress written; `--report-only` verified |
| Data integrity | SHA-256 vs `results/mongo/export_manifest.json` | both files match byte-for-byte |
| Application startup | documented procedure: `uvicorn backend.app.main:app` | `/api/health` 200 (rs0 writable primary, artefacts present), `/api/meta` 200 (152 378 real procedures), `/api/model-kpis` 200 (21 checks, 0 failed, 3 skipped); shut down cleanly |
| Hygiene | `git status` audit | only intended files staged; author's uncommitted `frontend/` changes untouched; `notebooks/`, `docs/network-view/`, `package-lock.json` excluded per protocol |

**Remaining scientific limitations** (beyond those in the experiment report):
no ground-truth corruption labels exist (AAP/ANSC are weak, non-confirming
proxies); the corpus snapshot is single-date; MOF cross-check compares zero
rows until a date-overlapping extract appears; step 08 dictionary requires the
live API; the noise magnitudes are bracketed assumptions, not measured error
rates.

**Recommendation (final):**

1. **Adopt no model change.** Production stays **v0**; no detector
   reordering, no threshold/band change, no new version — no axis of
   evidence (external labels, ΔAUC cluster CIs, chance controls, seed
   robustness, input-noise stability) supports a change, and two of them
   actively argue against one. See `MODEL_COMPARISON.md`.
2. **Adopt the operational guidance** from the noise axis: consume review
   lists at top-K ≥ ~200 granularity, treat exact ranks as indicative, never
   pre-round monetary inputs before scoring.
3. **Adopt the documentation fixes** (§7 items 4–5: `.gitignore`, README
   drift) and treat the §5 limitations as a backlog for author decisions
   (persist LOF/OCSVM in step 06 — guard-railed range; quarantine legacy
   synthetic files — writer is `backend/ml/`, out of scope).
4. The instability findings are **reported as found, not hidden** (H1/H2
   rejected), exactly as the acceptance criteria require.

---
*Anomaly ≠ corruption. Every flagged procedure is a potential risk indicator
requiring review by a competent authority.*
