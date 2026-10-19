# Model comparison — v0 detectors across every evaluation axis (audit 2026-10)

**Purpose:** decide, on evidence, whether any model/detector change should be
adopted. Companion of `NOISE_SENSITIVITY_REPORT.md`; all numbers below are
read from the repository's own artefacts (paths cited), not re-derived here.

> Anomaly scores are potential risk indicators, **not** evidence of
> corruption. Nothing in this comparison changes the production system.

## 1. Baseline under comparison

Production **v0**: four detectors — MAD robust z-score, IsolationForest(300),
LOF(k=20, novelty), OCSVM(rbf) — on identical preprocessing, one vote each,
bands = vote count, ranking = `max_score` (max of per-detector percentile
ranks). Artefacts: `results/tables/tender_anomaly_scores.csv`,
`results/models/anomaly_models.joblib`.

## 2. Evidence axes already measured (before this audit)

| Axis | Script / artefact | Result |
|---|---|---|
| Detector agreement | `13` → `agreement_matrix.json` | mean pairwise κ = **0.250**, min κ = 0.089 — detectors see genuinely different structure (this is why the vote exists) |
| Training/seed robustness | `15` → `robustness_seeds.json` | 20 seeds: consensus-set Jaccard vs seed-42 mean **0.711** (min 0.655); top-200 Jaccard mean **0.470** (min 0.299); band identical for a procedure in **86.2 %** of runs, band spans ≥ 2 levels in 1.6 % |
| Ablation + circularity | `16`, `21` → `feature_verdicts.json`, `circularity_check.json` | MAD-only ≈ full ensemble (weighted ≈ MAD, non-fed controls weaker); noisy-name placebo has no effect; permutation importances against the external label ≈ 0 (circularity documented) |
| External label — AAP (633 procedures) | `09`, `12` → thesis §4 | ensemble ROC-AUC **0.493** (≈ random) while single size/competition features reach 0.760–0.801 with supplier-cluster CI [0.700; 0.861] → the label validates *size/competition*, not the ensemble |
| External label — ANSC "contested" (1 665 procedures) | `31` → `ansc_external_check.json` | ROC-AUC **0.5112**, customer-cluster CI **[0.489; 0.557]**, random-rank mean 0.5006 → verdict **(б): indistinguishable from random**; leakage-free refit 0.4646 [0.417; 0.561] |
| Version deltas vs v0 | `27` → `delta_v*_vs_v0_boot.json` | v4b: ΔAUC −0.0023, supplier-cluster CI [−0.0097; +0.0015]; v5/v6: ΔAUC +0.0234, supplier-cluster CI **[−0.123; +0.090]** (procedure CI [−0.002; +0.048]) — **every CI includes 0** |
| v6 normalization vs chance | `28` → `random_flags_control.json` | v6's ΔAUC lies inside the distribution of random-5 %-within-group flags → no supported signal beyond the control |
| Threshold behaviour | `14` → `threshold_calibration.json` | no rule pays off at miss price 10–50; temporal PSI 0.29–0.41; consensus share falls 4.3 %→0.69 % (2018→2024) |

## 3. New axis added by this audit: input-noise stability (scripts/32)

Per-detector Spearman ρ under perturbation of the inputs (frozen models;
`noise_sensitivity_runs.csv`, means over seeds):

| Regime | MAD | IF | LOF | OCSVM | `max_score` (ensemble) |
|---|---|---|---|---|---|
| `round` (10k grid) | 0.871 | 0.887 | **0.445** | 0.691 | 0.574 |
| `noise_small` (±1 %) | **1.000** | 0.984 | 0.955 | 0.991 | 0.962 |
| `noise_moderate` (±5 %) | **0.607** | 0.907 | 0.701 | 0.941 | 0.646 |
| `missing_1pct` | 0.993 | 0.998 | 0.981 | 0.982 | 0.979 |
| `missing_5pct` | 0.964 | 0.990 | **0.912** | 0.912 | 0.903 |

Reading (stability only, no label involved):

* **OCSVM is the most noise-stable detector** (mean 0.966 over the two noise
  regimes), **IF second** (0.946), **LOF third** (0.828), **MAD most fragile
  under stress** (0.803) — yet MAD is *perfectly* stable under ±1 % monetary
  noise (its max-z rides on binary flags) and only collapses when counts
  jitter (moderate regime).
* **LOF is the quantization-fragile one** (0.445 under the 10k grid) — the
  regime that creates massive ties (99.4 % of rows) destroys neighbour
  structure specifically.
* The ensemble `max_score` inherits the *worst* behaviour of its members in
  each regime (max-over-ranks aggregation amplifies whichever detector moves
  most) — consistent with the known drawback already documented for the
  external label ("max chooses the worst indicator of a procedure", thesis §4).

## 4. Before-and-after summary

| Question | Answer before audit 2026-10 | Answer after scripts/32 |
|---|---|---|
| Are detectors consistent with each other? | κ 0.25 — measured (13) | unchanged |
| Is v0 stable across refits/seeds? | partially: bands 86 % stable, top-200 Jaccard 0.47 (15) | unchanged |
| Is v0 stable under **input errors**? | **never measured** | ρ 0.962 at ±1 %; ρ 0.646 at ±5 % stress; missing data best-tolerated (ρ 0.979/0.903); grid-rounding worst (0.574) |
| Does any version/variant beat v0? | no — all ΔAUC CIs include 0 (27), v6 ≈ chance control (28) | unchanged (no new version tested — none was justified) |
| Does any external label validate the ensemble? | no — AAP 0.493 ≈ random, ANSC 0.5112 CI includes 0.5 | unchanged |
| Which detector is most/least trustworthy *positionally*? | not answered | OCSVM/IF most stable; LOF/MAD regime-dependent (§3) |

## 5. Recommendation

1. **Do not change the model.** No axis of evidence — external labels,
   version deltas, chance controls, seed robustness, or the new noise axis —
   supports replacing v0, reordering the vote, or re-tuning bands. The new
   experiment demonstrates *stability characteristics*, not performance gain;
   adopting anything on its basis would violate the acceptance criteria
   (fair comparison with v0, statistical uncertainty, no metric gaming).
2. **Operational guidance derived from stability:** review lists should be
   consumed at **top-K ≥ ~200 granularity** (Top-200 survives realistic noise
   at ≥ 0.945); exact rank positions are not reliable; never pre-round
   monetary inputs before scoring (worst regime, ρ 0.574).
3. **If a future refresh ever forces simplification**, the stability evidence
   (OCSVM/IF ≫ LOF under noise) would be one *input* to that decision — but
   it must be combined with the external-label and ablation axes, none of
   which currently favors any subset. This is a hypothesis for future work,
   not a recommendation to act now.
4. Follow-ups requiring an author decision (not executed): persist LOF/OCSVM
   in step 06 (guard-railed range), re-run scripts/32 after a corpus refresh.

---
*Anomaly ≠ corruption: every flagged procedure is a potential risk indicator
requiring review by a competent authority.*
