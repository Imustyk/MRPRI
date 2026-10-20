# Experimental Model Comparison — Phase 7 (controlled evaluation)

Date: 2026-10-20 · **Decision: the experimental module ranking is NOT adopted**
· production v0 unchanged · no thresholds/bands/votes changed

This is the controlled experimental evaluation pre-registered in
`docs/IMPROVEMENT_PLAN.md` Phase 7: are the Phase 4 risk-specific indicators
useful as a **ranking**, measured against pre-registered baselines on the two
external labels from Phase 5, with supplier/buyer cluster bootstrap CIs? The
adoption rule was fixed *before* looking at results: **no adoption without a
paired ΔCI vs v0 excluding 0 in the module ranking's favour**. The measurement
code is `scripts/35_external_validation.py`; all numbers below are machine
outputs from `results/methodology/external_validation_framework.json`
(boot=1000, seed=42), not hand-copied claims.

---

## 1. Hypothesis and metric

- **H1 (adoption):** `module_hits` (count of triggered Phase 4 risk-specific
  indicators) discriminates external-label positives at least as well as the
  production score, and significantly better than it.
- **Metric:** ROC-AUC as the primary metric (pre-registered); PR-AUC,
  precision/lift@100 and recall@500 as secondary point estimates at the real
  review budget.
- **Uncertainty:** percentile CIs from a cluster bootstrap that resamples the
  label's natural unit — **supplier** for AAP, **buyer** for ANSC — B=1000,
  seed 42; paired differences share the same replicate draws.
- **What is explicitly not tested:** no retraining, no threshold tuning, no
  holdout reuse for selection, no direction flips (guard rails).

## 2. Pre-registered baselines

Production `v0_max_score` (reference), `amount` (exposure), `n_bidders_fewer`
(pre-registered direction: fewer bidders = higher risk), `value_within_cpv`,
`single_bidder`, `votes`, `random`, plus the experimental `module_hits`.
Directions were locked in code (`BASELINE_SPECS`) before evaluation;
`tests/test_external_framework.py::test_directions_are_pre_registered`
guards them against post-hoc edits.

## 3. Results

### 3.1 AAP interdiction label (117 535 procedures, 633 positives, base rate 0.0054)

| Rule | ROC-AUC [supplier-cluster CI] | Paired Δ vs v0 | Verdict |
|---|---|---|---|
| amount | 0.7342 [0.6783, 0.8217] | −0.2040 [−0.2753, −0.1546] | ci_excludes_0 — amount wins |
| value_within_cpv | 0.6277 [0.5712, 0.6673] | −0.0976 [−0.1696, 0.0012] | ci_includes_0 |
| single_bidder | 0.5341 [0.4943, 0.5921] | −0.0039 [−0.0546, 0.0631] | ci_includes_0 |
| **v0_max_score** | **0.5302 [0.4829, 0.5901]** | — | reference |
| random | 0.5063 [0.4891, 0.5420] | +0.0238 [−0.0440, 0.0843] | ci_includes_0 |
| votes | 0.4909 [0.4567, 0.5468] | +0.0393 [0.0088, 0.0574] | ci_excludes_0 — v0 wins |
| **module_hits** | **0.4839 [0.4527, 0.5418]** | **+0.0463 [0.0032, 0.0998]** | **ci_excludes_0 — v0 wins** |
| n_bidders_fewer | 0.2423 [0.1991, 0.3348] | +0.2879 [0.1858, 0.3560] | ci_excludes_0 — v0 wins |

Secondary point estimates: `module_hits` P@100 = 0.02 (lift 3.71), P@100 = 0
for both `v0_max_score` and `amount`; recall@500 = 0.0063 vs 0.0095 (v0) and
0.0032 (amount). Temporal halves (2018–2021 → 2022–2024): module_hits
0.456 → 0.494, v0 0.428 → 0.553.

### 3.2 ANSC complaint label (33 612 competitive procedures, 1 222 positives, base rate 0.0364)

| Rule | ROC-AUC [buyer-cluster CI] | Paired Δ vs v0 | Verdict |
|---|---|---|---|
| n_bidders_fewer | 0.5135 [0.4317, 0.5568] | −0.0023 [−0.0644, 0.1164] | ci_includes_0 |
| value_within_cpv | 0.5129 [0.4803, 0.5316] | −0.0017 [−0.0301, 0.0657] | ci_includes_0 |
| **v0_max_score** | **0.5112 [0.4895, 0.5593]** | — | reference |
| amount | 0.5112 [0.4497, 0.6215] | +0.0000 [−0.0884, 0.0454] | ci_includes_0 |
| votes | 0.4997 [0.4804, 0.5451] | +0.0115 [−0.0013, 0.0264] | ci_includes_0 |
| single_bidder | 0.5000 [0.5000, 0.5000] | +0.0112 [−0.0105, 0.0593] | ci_includes_0 (rule constant under n_bidders≥2 — not applicable, flagged) |
| random | 0.4892 [0.4685, 0.4999] | +0.0220 [−0.0043, 0.0824] | ci_includes_0 |
| **module_hits** | **0.4838 [0.4663, 0.5277]** | **+0.0274 [0.0046, 0.0551]** | **ci_excludes_0 — v0 wins** |

Cross-validation note: the v0 point (0.5112) reproduces MTA-0013's production
figure (0.511196 [0.488919, 0.557061]) and the positives count (1222) matches
exactly after the PN-ocid alias rebuild — the framework is measuring the same
population as the historical audit.

## 4. Decision and interpretation

- **H1 is rejected on both external labels.** The paired ΔCI excludes 0
  *against* `module_hits` on AAP (+0.0463) and ANSC (+0.0274). By the
  pre-registered rule, **no adoption** — the Phase 4 indicators are not a
  replacement ranking and are not promoted to production. This mirrors the
  author's brief: a failed experimental model is a documented result, not a
  reason to hunt for a favourable metric (no direction flips, no quota
  normalisation, no re-tuning were attempted).
- **Why the indicator count loses to v0 even at similar chance-level AUC:**
  `module_hits` is an unweighted trigger count built for *interpretability*
  (each hit explains a documented pattern); ranking quality was never its
  objective. The v0 score keeps its production role.
- **Where the module track stays valuable:** Phase 4's real contribution —
  deterministic per-procedure explanations of *which* patterns fired
  (splitting, repeat winners, price outliers, direct-award regularity) and
  the direct-award evaluation track — is unaffected by this decision. The
  indicators remain an explanation/review lens (also used by the blinded
  expert-review export, Phase 6), not a scoring function.
- **Label caveats carry over:** the AAP label is supplier-level and
  exposure-heavy (amount, an exposure rule, wins it); the ANSC label is
  «complaint filed», not a confirmed violation (decision documents are a
  documented blocker). Neither label is ground truth for guilt.

## 5. What this is not

Not a new model version (no v7; budget 6/10 untouched); no retraining; no
threshold/band/vote changes; no holdout-based selection; no SMOTE/neural
networks; no fabricated metrics. `results/` artefacts are regenerable and
gitignored; every number above is reproducible with
`.venv/bin/python scripts/35_external_validation.py`.

## 6. Reproduction

```bash
.venv/bin/python scripts/35_external_validation.py     # full framework, B=1000, seed 42
.venv/bin/python -m pytest tests/test_external_framework.py -q
```
