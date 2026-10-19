# Reproducibility — audit 2026-10 (noise sensitivity + repository audit)

## Environment

* macOS (darwin), 12 cores / 24 GB; no GPU used.
* Python 3.11.6 in `.venv`, all dependencies pinned in `requirements.txt`
  (numpy 2.2.1, pandas 2.2.3, scikit-learn 1.6.1, matplotlib 3.11.2, joblib 1.4.2 …).
* MongoDB 6.0 replica set `rs0` (docker or Homebrew) is required only by the
  ETL/backend, **not** by this audit: `scripts/32` reads the exported snapshot
  `data/features/features.csv` and the published score table
  `results/tables/tender_anomaly_scores.csv`.

## Inputs (immutable for this audit)

| File | Role | Integrity |
|---|---|---|
| `data/features/features.csv` (152 378 × 62) | feature + source snapshot | SHA-256 `9e267823…` = `results/mongo/export_manifest.json` (re-verified in this audit) |
| `data/processed/tenders.json` (152 378 records) | corpus snapshot | SHA-256 `a7629eae…` = manifest |
| `results/models/anomaly_models.joblib` | frozen `StandardScaler` + `IsolationForest` | loaded as-is; `feature_columns` verified == `FEATURE_COLUMNS` |
| `results/tables/tender_anomaly_scores.csv` | published production scores | fidelity reference for the reconstruction |

## Exact commands

```bash
# full experiment (defaults: 10 noise seeds, 5 missing seeds, 200 bootstrap reps)
.venv/bin/python scripts/32_noise_sensitivity.py            # 31 passes, 484 s (~8 min) on this machine

# verification after the run
.venv/bin/python scripts/19_final_verification.py           # must exit 0
.venv/bin/python -m pytest tests/ -q                        # 220 passed
```

Resumability: after every perturbed pass the script writes
`results/methodology/noise_sensitivity_progress.json`; deleting that file forces
a full re-run, keeping it skips completed `(regime, seed)` passes.

## Seeds and determinism

* Production baseline seed **42** (unchanged from `scripts/06`).
* Noise regimes: seeds `0..9`; missing regimes: seeds `0..4`; `round` is
  deterministic (seed 42, ignored). Bootstrap seed per pass = `42 + seed`.
* All randomness goes through `numpy.random.default_rng(seed)`; no wall-clock
  or environment-dependent randomness exists in the scoring path.
* The frozen components are deterministic: `IsolationForest` and `StandardScaler`
  come from the production joblib; LOF/OCSVM are rebuilt exactly as production
  built them (`fit_sample(n, 20000, 42)` = sorted seeded choice without
  replacement). This reconstruction is *verified*, not assumed: the fidelity
  gates require per-detector Spearman ≥ 0.99999 vs the published scores and
  100% band agreement; the measured values were ≥ 0.9999997 (see
  `results/methodology/noise_sensitivity.json → fidelity`).

## Artefact map (what writes where)

| Artefact | Produced by | Tracked in git? |
|---|---|---|
| `results/methodology/noise_sensitivity.json` | scripts/32 | no (gitignored, regenerable) |
| `results/methodology/noise_sensitivity_progress.json` | scripts/32 (resume state) | no |
| `results/tables/noise_sensitivity_runs.csv` | scripts/32 | no |
| `results/tables/noise_sensitivity_transitions.csv` | scripts/32 | no |
| `results/figures/noise_sensitivity_*.png` (6) | scripts/32 | no |
| `results/logs/step32_noise_sensitivity.log` | run log | no |
| `reports/audit_2026-10/*.md`, `EXPERIMENT_RESULTS.csv` | written from the artefacts above | **yes** |

## What this experiment does *not* do

It does not retrain, re-tune or replace anything: production stays **v0**, the
vote rule, bands, thresholds and every historical artefact are untouched, and
no iteration cycle is opened (this is a measurement; cycle budget stays 6 of
10). Anomaly scores remain statistical outlier indicators — potential risk
indicators, not evidence of corruption.
