# Noise / input-perturbation sensitivity of the production v0 ranking

**Experiment:** pre-registered inference-robustness audit, 2026-10-19
**Code:** `scripts/32_noise_sensitivity.py` · **Tests:** `tests/test_noise_sensitivity.py` (24)
**Machine-readable results:** `EXPERIMENT_RESULTS.csv`,
`results/methodology/noise_sensitivity.json`,
`results/tables/noise_sensitivity_runs.csv`,
`results/tables/noise_sensitivity_transitions.csv`
**Status of production:** unchanged — v0, no retraining, no re-tuning, no new cycle
(budget stays 6 of 10; this is a measurement, like MTA-0009/0012/0013).

> An anomaly score is a statistical outlier indicator — a potential risk
> indicator, **not** evidence of corruption or a violation. Verification by a
> competent authority is required. This experiment measures *stability*, not
> correctness: no label is involved anywhere in it.

---

## 1. Research question

Is the fixed production ranking of MTender procedures (152 378 procedures,
`max_score` = max over four detectors' percentile ranks, vote bands
low/medium/high/critical) **stable when the input data carry small, realistic
errors** — misreported amounts, jittered counts and dates, missing publication
blocks, coarse rounding?

Complements `scripts/15_robustness_seeds.py`, which measures *training*
(refit/seed) robustness; this one is *inference* robustness with frozen models.

## 2. Hypotheses (pre-registered, before the run)

| | Statement | Threshold |
|---|---|---|
| H1 | ±1 % monetary jitter keeps rank correlation | min Spearman ρ ≥ 0.99 |
| H2 | moderate regime (±5 %, count jitter p = 0.15) keeps ranking usable | min ρ ≥ 0.97 **and** min Top-200 overlap ≥ 0.80 |
| H3 | missing-value regimes degrade more than noise regimes (band changes) | descriptive, no threshold |
| H4 | per-detector comparison locates the driver of any instability | report only |

## 3. Dataset and fidelity gates

* `data/features/features.csv` — 152 378 × 62 (sources + 22 features),
  SHA-256 verified against `results/mongo/export_manifest.json` in this audit.
* Fidelity gate 1 — features re-derived from the stored sources by the
  production `engineer_features()`: max |Δ| = **5e-7** (CSV rounding).
* Fidelity gate 2 — frozen reconstruction scored against the published
  production table: per-detector Spearman ≥ **0.9999997**, `max_score`
  ρ = 0.99999999994, band agreement **100 %**. The gates must pass before any
  perturbed score is trusted (the run aborts otherwise).

Frozen components: `StandardScaler` + `IsolationForest` from the production
joblib; LOF/OCSVM rebuilt exactly as `scripts/06` built them (seed 42,
`fit_sample(n, 20000, 42)`) because step 06 persists only scaler+IF — a
documentation finding of this audit (AUDIT_REPORT §5.1). The MAD robust
statistics are recomputed by the production function on the scored population
documented deviation; at n = 152 378 their sampling error is negligible next
to the injected noise).

## 4. Methodology

Perturbations act on **source columns**; all 22 features are then re-derived
by the production `engineer_features()`, so derived features (CPV medians,
ratios, deadline flags) stay consistent with their sources. Invariants by
design — never perturbed: `ocid`, buyer/supplier identifiers, `cpv_primary`,
`status`, `procurement_method_details`, `tender_start`, behavioural
relationship shares (aggregate statistics; per-procedure source noise moves
them by O(1/n)).

| Regime | Perturbation | Seeds |
|---|---|---|
| `round` | money → nearest 10 000 MDL (deterministic) | 1 |
| `noise_small` | monetary lognormal σ = ln 1.01 (±1 %); counts ±1 p = 0.02; end date ±1 day p = 0.05; amendments ±1 p = 0.02 | 10 |
| `noise_moderate` | σ = ln 1.05 (±5 %); counts ±1 p = 0.15; end date ±3 days p = 0.15; amendments ±1 p = 0.10 | 10 |
| `missing_1pct` / `missing_5pct` | publication blocks (award / bids / dates) masked with p = 0.01 / 0.05; re-derived via ETL fill conventions | 5 + 5 |

Per pass (31 scoring passes, ~16 s each): Spearman ρ of `max_score` with a
200-rep procedure-level bootstrap CI, per-detector ρ, Jaccard of high+
(votes ≥ 2), critical (votes ≥ 3) and top-200 sets, Top-K overlap for
K = 50/100/200/500, 4×4 band transition matrix and % band changes, score
quantiles and two-sample KS, sensitivity by contract-value quartile band and
by procedure type (top-8 + other). All RNG: `numpy.random.default_rng`
(seeds 0–9 / 0–4, bootstrap 42 + seed).

## 5. Results

Full table: `EXPERIMENT_RESULTS.csv`. Headline (mean over seeds; CI = 95 %
bootstrap CI of ρ):

| Regime | ρ (CI) | Top-200 | Top-500 | Jaccard high+ | Band change | KS |
|---|---|---|---|---|---|---|
| `round` (10k grid) | 0.574 [0.569; 0.578] | 0.605 | 0.648 | 0.391 | 32.0 % | 0.107 |
| `noise_small` (±1 %) | 0.962 [0.960; 0.963] | 0.958 | 0.971 | 0.894 | 2.05 % | 0.150 |
| `noise_moderate` (±5 %) | 0.646 [0.642; 0.650] | 0.827 | 0.597 | 0.473 | 28.4 % | 0.129 |
| `missing_1pct` | 0.979 [0.978; 0.980] | 0.968 | 0.986 | 0.911 | 1.10 % | 0.152 |
| `missing_5pct` | 0.903 [0.900; 0.905] | 0.801 | 0.915 | 0.677 | 5.24 % | 0.148 |

**Verdicts against the pre-registered hypotheses**

* **H1 — rejected.** Minimum ρ under ±1 % noise = 0.960 < 0.99 (CI upper
  bound 0.963 excludes 0.99).
* **H2 — rejected.** Minimum ρ = 0.643 < 0.97 and minimum Top-200 = 0.785 <
  0.80 under the moderate regime (CIs exclude both thresholds).
* **H3 — descriptive, and the picture is mixed.** Missing blocks are tolerated
  *better* than moderate noise (5.24 % vs 28.4 % band changes) but *worse*
  than small noise (5.24 % vs 2.05 %).
* **H4 — driver located, and it depends on the regime** (mean ρ over the two
  noise regimes): OCSVM 0.966, IF 0.946, LOF 0.828, MAD 0.803. Detail:
  MAD is *perfectly* stable under ±1 % monetary noise (ρ = 1.000 — its max-z
  rides on binary/spike flags) but collapses under moderate count jitter
  (0.607); LOF is the weakest under quantization (0.445) and under ±1 %
  (0.955); OCSVM is the most stable detector in every regime except
  `missing_5pct`-style structural loss.

**Mechanism of the worst case (`round`).** Rounding to a fixed 10 000 MDL
grid collapses 63 738 distinct positive amounts to **1 426** unique values —
99.4 % of rows land in a tie group, and for contracts below 1 MDL mln only
**101 unique values remain for 57 433 rows**. Tie-heavy feature vectors
destroy neighbour structure (LOF ρ = 0.445) and create massive ties in
percentile ranks, reshuffling the whole mid-table (ρ = 0.574). Coarse
absolute-grid quantization is *not* a benign precision change for this
corpus — its amounts live on a fine, small-value-dominated distribution.

**Marginal vs assignment stability.** KS ≤ 0.152 in *every* regime: the
overall shape of the `max_score` distribution barely moves. What moves is
*which procedure* holds which position. Aggregate dashboards (band shares,
score quantiles) are therefore far more robust than exact rankings.

**Group sensitivity** (worst regime, `noise_moderate`, % procedures changing
band): procedure type — `opentender` 47.4 %, `smallvalue` 42.9 %,
`microvalue` 41.7 %, `procedură de valoare mică` 41.1 %,
`licitație deschisă` 37.4 %, `directaward` 14.6 %. Value bands —
upper-mid 37.3 %, top 31.5 %, lower-mid 21.3 %, bottom 19.8 %.
Corresponding ρ: 0.52–0.74 by type, 0.60–0.68 by value band. Small-value and
open-procedure segments are the most noise-sensitive; direct awards the least.

**Figures** (`results/figures/`, regenerable):
`noise_sensitivity_stability.png` (noise level vs ranking stability),
`noise_sensitivity_topk.png` (noise level vs Top-K overlap),
`noise_sensitivity_transitions.png` (band-transition heatmap, log colour),
`noise_sensitivity_scatter.png` (original vs perturbed scores),
`noise_sensitivity_seeds.png` (seed distributions),
`noise_sensitivity_groups.png` (group-wise band sensitivity).

## 6. Interpretation

1. **Under realistic small errors (±1 %, 2 % count jitter) the production
   ranking is usable but measurably less stable than hypothesized:**
   ρ ≈ 0.96, Top-200 retains ≥ 94.5 %, ≤ 2.1 % of procedures change band.
   For review lists of ≥ 200 procedures this is defensible; for exact
   positions (procedure №17 vs №23) it is not.
2. **Under the moderate stress regime the fine ordering is not trustworthy**
   (ρ ≈ 0.65, 28 % band changes) — reported as instability, not hidden.
   This regime is a stress test (15 % of procedures get their bidder count
   flipped, a semantics-heavy field), not an estimate of MTender's actual
   error rate.
3. **Missing publications — the dominant real defect of MTender — are the
   best-tolerated perturbation** (ETL conventions turn absence into documented
   constants, and rank-based scoring absorbs it): 1 % missing changes 1.1 %
   of bands; 5 % missing changes 5.2 %.
4. **Do not coarsen monetary inputs** before scoring: grid-rounding destroys
   more ranking information than a ±5 % continuous error.
5. **Stability ≠ validity.** Nothing here changes the external-validation
   verdicts (AAP/ANSC labels do not confirm that the ensemble beats size or
   random flags) and nothing here justifies replacing v0.

## 7. Limitations

* Perturbation magnitudes are assumptions; no ground-truth measurement-error
  rates for MTender exist, so the regimes are bracketed (realistic → stress)
  rather than estimated.
* The MAD robust statistics are recomputed on the scored population
  (documented deviation from strict frozen inference).
* LOF/OCSVM are reconstructed (not loaded) because step 06 does not persist
  them; reconstruction is verified by the fidelity gates (≥ 0.9999997).
* Behavioural relationship shares are not perturbed (see §4).
* One snapshot (2026-09-26 corpus), one production configuration; training
  robustness is script 15's question, not this experiment's.
* KS on n = 152 378 makes even trivial shifts "significant"; effect sizes
  are reported, p-values are not.

## 8. Conclusions and recommendation

* **H1 and H2 are rejected; the instability is reported as found.**
* The production v0 ranking is **stable enough for band-level triage and
  ≥ 200-item review lists under realistic data errors**, and **unstable at
  exact rank positions and under coarse quantization or ≥ 5 % errors**.
* **Recommendation: keep production v0 unchanged.** This experiment adds a
  new axis of evidence (input-noise stability); it demonstrates no
  performance gain and proposes no version change, vote change or threshold
  change. Practical guidance follows instead: review at top-K granularity,
  treat rank positions as indicative, never pre-round monetary inputs.
* Follow-ups worth an author decision (not executed here): persist LOF/OCSVM
  in step 06 (guard-railed range), tie-robust score aggregation if data
  coarsening ever becomes unavoidable, and re-running this audit after any
  future corpus refresh.
