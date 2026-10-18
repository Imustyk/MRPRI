# Model card — MTender anomaly screening (consensus detector)

| | |
|---|---|
| **Version** | `MTA-methodology-cycle-2026-10-17` (see `CHANGELOG.md`) |
| **Model type** | Unsupervised ensemble of four outlier detectors + majority vote; **ranking/screening**, not a classifier of wrongdoing |
| **Purpose** | Prioritise which tender procedures a human auditor looks at first |
| **Status** | Production thresholds **unchanged** by this cycle; all changes are recommendations (§9) |
| **Standing disclaimer** | Every output carries: *indicator of potential risk, not evidence of corruption* |

## 1. Intended use and misuse

**Use.** Ordering a queue of manual reviews over 152,378 Moldovan public-procurement procedures (MTender OCDS feed, publications 2018-10 … 2024-04).

**Misuse (explicitly out of scope).** Any automated or semi-automated consequence for a party: sanctions, debarment, blocking, naming-and-shaming, procurement bans. A "critical" band means "unlike the typical procedure in this corpus", nothing more. Legal framing: `reports/legal_and_sources.md`.

## 2. Data

- **Corpus:** 152,378 procedures from archived OCDS packages (`data/raw/ocds_packages/`, read-only), normalised into `data/features/features.csv`.
- **External label (weak):** AAP interdiction list snapshot `aap_lista_interdictie_2026-09-25.json` — 22 entries; 18 exact name-normalised matches (17 distinct suppliers), 4 ambiguous candidates **never counted as positives**; 633 labelled procedures, base rate 0.415% (`src/mtender/external_labels.py`, tests in `tests/test_external_labels.py`).
- **Known label limits:** catches only suppliers who were caught (selection bias); decisions dated 2023-12 … 2026-09 while procedures are 2018–2024 (part of the decisions postdate the procedures); supplier-level attribution (all procedures of a supplier inherit the label).

## 3. Features (22)

Four groups: financial (`log_award_value`, `log_award_total`, `value_vs_cpv_median`, `value_zscore_cpv`, `estimate_to_award_ratio`, `multi_award_tender`), competition (`n_bidders_log`, `single_bidder`, `no_bid_data`, `multi_supplier_award`), procedural (`bid_window_days`, `short_deadline`, `long_deadline`, `n_amendments`, `amended`, `accelerated_like`, `cancelled`, `no_award_after_tender`), behavioural (`buyer_supplier_repeat_share`, `winner_share_of_buyer_awards`, `supplier_win_concentration`, `supplier_award_count_log`).

**Known defect — duplicate column.** `winner_share_of_buyer_awards` ≡ `buyer_supplier_repeat_share` (identical in 100% of rows, Pearson 1.0): the same ratio enters the detectors twice. Ablation proof: dropping *either* column gives an identical model (consensus 2,379, Jaccard 0.702). Recommendation: merge (keep one copy). **Not applied** — author's decision (§9).

## 4. Detectors and threshold

| Component | Parameters |
|---|---|
| MAD z-score | z > 5, deterministic |
| IsolationForest | 300 trees, contamination 0.05, random_state 42, n_jobs from env |
| LOF | k = 20, contamination 0.05, novelty=True, fit on seeded 20,000-row sample |
| One-Class SVM | RBF, nu = 0.05, gamma scale, fit on seeded 20,000-row sample |

**Decision boundary:** `consensus = (votes ≥ 3)` → band **critical**; 2 votes → high; 1 → medium; 0 → low. `max_score` = max of per-detector percentile ranks (used for ordering within bands).

**Why ≥3 and why it stays.** External evidence does not support changing it: at the tested error prices the production rule is the cheapest defensible one — but only if a missed case costs ≥ ~200 review-equivalents (§7). The "optimal" rule found by search (weighted rank ≥ 0.98) fits the 2018–2021 tuning period and then *loses* to the production rule on 2022–2024.

## 5. Metrics (all numbers reproduced by `scripts/19_final_verification.py`)

**Against the external AAP label** (`results/tables/external_metrics.csv`, 1,000 bootstrap replicates):

| Rule | ROC-AUC (proc. 95% CI) | supplier-cluster CI | precision | lift |
|---|---|---|---|---|
| production `max_score` | 0.493 [0.472, 0.515] | [0.424, 0.576] | — | — |
| `precision@200` (max_score) | — | — | **0.000** | 0 |
| `precision@1000` (max_score) | — | — | 0.007 | 1.69 |
| votes ≥ 3 (3,031 flagged) | — | — | 0.0082 [0.0056, 0.0121]* | 1.99 |
| votes ≥ 4 (664 flagged) | — | — | 0.0105 | 2.54 |

\* Wilson interval. The top of the production ranking is statistically indistinguishable from random on this label; enrichment exists only in the consensus tail.

**Strong univariate signals discarded by the ranking** (`scripts/16`, verified in `scripts/19`): `n_bidders_log` AUC 0.801 (cluster CI [0.700, 0.861]; leave-one-supplier-out [0.781, 0.812]), `log_award_total` 0.795, `log_award_value` 0.760, `multi_award_tender` 0.745 — versus 0.493 for the ensemble. The max-of-percentiles combination destroys signal that single features carry.

**Agreement between detectors** (`results/methodology/agreement_matrix.json`): mean pairwise Cohen's kappa 0.250 (min 0.089 MAD–LOF); mean pairwise Jaccard of flags 0.185; 97.6% of "any-detector" flagged procedures are flagged by a strict minority — disagreement is the normal case.

**Seed stability** (20 runs, `results/methodology/robustness_seeds.json`): consensus **count** reproducible (mean 3,013 ± 143, cv 4.8%), consensus **membership** is not (Jaccard vs seed 42: mean 0.711, min 0.655; top-200 Jaccard mean 0.470). Adding a pure-noise placebo column shifts the set the same way (Jaccard 0.702). Lists must record the run's seed/parameters and be regenerated on any change.

**Drift** (`results/methodology/threshold_calibration.json`): PSI 0.29–0.41, KS 0.21–0.26 between 2018–2021 and 2022–2024; consensus share falls 4.3% (2018) → 0.69% (2024). A fixed vote threshold yields a *shrinking* audit load; periodic recalibration is required.

## 6. Circularity controls (why "important feature" ≠ "valid feature")

- ANOVA against the consensus flag: 95.5% of fed features are significant at 0.01 — and so are **100% of columns the detectors never saw** (`n_lots` F=129, `n_items` F=69.7, `n_contracts` F=36.6). The test measures correlation with the construction, not validity. A Gaussian placebo column fed to the detectors is *not* significant (p=0.72), so the test is not vacuous — it "legitimises" anything correlated with procurement structure.
- Permutation importance against the model's own predictions (as in `scripts/07`) versus against the external label: Spearman **0.065** between the two rankings — self-agreement, not evidence.
- Correlation of ANOVA-importance ranks with external-discrimination ranks: Spearman 0.18.
- **Randomised control — shuffled buyer–supplier links** (`scripts/21`, `reports/circularity_check.md`): winners were permuted across procedures (winner and buyer marginals preserved exactly) and the four behavioural features recomputed. Their external association *survives* the shuffle (single-feature AUC repeat_share 0.560→0.622, concentration 0.673→0.603), so it is carried by the marginals (buyer portfolio size, supplier win count), not by the pair identity; and behavioural features still dominate ANOVA-vs-bands after the links are destroyed (repeat_share F 37,046→71,355). By the protocol's own rule this makes their dominance a **calculation artefact**, not evidence of real buyer–supplier relationships. The shuffled ensemble even matches the AAP label *better* than the real one (AUC 0.493→0.576).
- **Feature halves** (`scripts/21`): bands built from one half of the features agree with bands from the other half only at Jaccard ≈ 0.18–0.26 (group split 0.01) — the same order as detector-to-detector agreement; bands are not reproducible from half a feature set.
- **Per-feature verdicts** (`reports/circularity_check.md`, `results/tables/circularity_verdicts.csv`): 18/22 features show a *confirmed external association* with the AAP label (including inverse ones — `no_bid_data` AUC 0.21, `cancelled` 0.49), 1 is confirmed internally only (`single_bidder`: external association present but direction inconsistent across periods), 3 are unconfirmed (`long_deadline`, `no_award_after_tender`, the constant `accelerated_like`). "Confirmed" means a confirmed association with this single label source — not validity as a risk indicator; internally-confirmed features may be used as model description only, never as evidence.

## 6a. Iterative validation (versions v0–v4; protocol in `cycle_log.md`)

The model was put through an iterative polishing loop: one change per cycle, the same metric suite each time (`scripts/20`), decisions made on the 2018–2021 tuning split only (194 AAP positives), holdout 2022–2024 (439) touched once per cycle for final assessment, improvement counted only if the paired-bootstrap ΔROC-AUC CI excludes zero.

| version | one change | ΔAUC tuning (paired) | side effects | decision |
|---|---|---|---|---|
| v0 | production baseline (refit = shipped, Jaccard 1.0) | — | — | — |
| v1 | drop duplicate share column | +0.003 [−0.003, +0.010] | consensus −21.5%, κ 0.250→0.217 | not adopted (within CI) |
| v2 | rank combination max→mean percentile | **−0.033 [−0.056, −0.009]** | top-200 seed Jaccard 0.479→0.671 | rejected (significant tuning regression) |
| v3 | drop behavioural group | −0.025 [−0.056, +0.004] | consensus −50.8%, κ→0.186, PSI 0.29→0.60 | not adopted |
| v4 | data-artifact fixes (`apply_datafix`): full supplier-id normalisation (536 phantom ids merged, 14,477→13,941; behavioural features recomputed), explicit P99.9 caps on the two value features that had none in production (`log_award_value` ≤ 17.50, `log_award_total` ≤ 18.76), 7,712 placeholder localities cleaned, duplicate column dropped as in v1 | +0.002 [−0.006, +0.010] | consensus −21.4% (3,031→2,381), κ 0.250→0.217 — both from the duplicate drop (as in v1), PSI 0.29→0.38 | not adopted (within CI; defects fixed, external metrics unchanged) |
| v4b | the same data-artifact fixes with the duplicate KEPT (separates the two effects: v4b vs v0 = the fixes alone; v4 vs v4b = the duplicate drop) | −0.002: procedure boot [−0.005, −0.001]; supplier-cluster boot [−0.010, +0.002] — crosses zero (`scripts/27_delta_cluster_boot.py`) | consensus 3,034 ≈ v0, κ 0.248 ≈ v0 — the v4 consensus/κ changes are the duplicate's, not the id normalisation; PSI 0.29 | not adopted (no improvement; the fixes alone leave κ and consensus unchanged) |
| v5 | the ranking percentile computed inside the group «cost band × procedure type» (bands = corpus quantiles of log_award_value; groups < 100 merged, 24 final groups); votes/consensus exactly v0's | tuning Δ +0.023: procedure boot [−0.002, +0.048]; supplier-cluster boot [−0.123, +0.090] — crosses zero; **holdout 0.518 → 0.425**, holdout CI [0.396, 0.452] excludes 0.5 — v5 significantly ranks AAP labels as LESS risky (MTA-0008: a stably negative association does not satisfy completion condition 2) | consensus 3,031 = v0, κ 0.2497 = v0; top-200 seed Jaccard 0.479 → **0.656** (C2 passes, as it did for v2 with 0.671), cv 4.76% → 2.98%, PSI 0.293 → 0.148; top-200 size dominance ≥ 50 m 10.9× → 2.9× (≥ 5 m overshoots to 0.6×); C6 24/8, C3 0.159 unchanged | not adopted (compromise with a negative external outcome: stability and size-debiasing improve, holdout AUC degrades significantly; no improvement beyond the CI by either bootstrap) |
| v6 | each detector's flag = the top 5% **inside its group** «cost band × procedure type» (groups/edges as v5), consensus = ≥ 3 votes, ranking = v5's `group_pct_max` — external AUC identical to v5's by construction; the section-E audit is re-run on v6's own votes (`bias_audit_v6.json`, `scripts/18 --variant v6_group_flags`; production v0 audit untouched) | tuning Δ +0.023: procedure boot [−0.002, +0.048]; supplier-cluster boot [−0.123, +0.090] — crosses zero; **holdout 0.425**, CI [0.396, 0.452] excludes 0.5 — significantly ranks AAP labels as LESS risky | consensus 3,031 → 2,965 (−2.2%), κ 0.2497 → **0.2991** (threshold 0.40 unmet); **C3 passes for the first time among all versions** (yearly consensus-share ratio 0.159 → 0.537); Jaccard 0.656, cv 3.54%, PSI 0.148; ≥ 50 m share of high+ 50.9% → **14.6%** (disparity 10.5× → 3.23×, still a violation), direct awards 0.21 → **1.13** (B4 within band, first time), all procedure types within band; audit on its own votes 29 violations / 12 warnings vs v0's 24/8 (10 fixed, 19 broken — size/type bias moved, not removed); **50.8% of v0-critical leave the band** (≥ 50 m criticals 74 → 22, 7 of the 10 largest lost get zero v6 votes), C5 fails on both splits for the first time among versions | not adopted (compromise: the first size-audit improvement in three cycles and the first C3 pass, but C6 41 verdicts vs limit 0, κ 0.299, ≥ 50 m 3.23× outside [0.8, 1.25], C5 regression, holdout anti-association; cycle 7 not started without the author's decision) |

**Protocol stop after 3 cycles with no improvement beyond the CI** (3 of 10 budget spent); an additional author-requested cycle 4 (variants v4/v4b — measured data fixes), the author-requested main cycle 5 (variant v5 — within-group percentile ranking, MTA-0007) and the author-requested cycle 6 (variant v6 — flags normalised within the group, MTA-0008) brought the total to 6 of 10. Proposed convergence criteria — mean pairwise κ ≥ 0.40, top-200 seed Jaccard ≥ 0.60, consensus-count cv ≤ 10%, yearly consensus-share range ≥ 0.25, threshold beats flag-nothing at c_miss = 200 on both splits, section-E bias audit with no "violation" and no "warning" verdicts (C6, added at the author's request and applied retroactively to every version), RAG explanation layer with zero hallucinated references and recall@3 ≥ 0.60 (C7, added at the author's request), circularity checks passed — are met by **no version** (best: v5 and v6 at 4/8; v6 is the first version to pass C3 — the yearly consensus-share ratio 0.537 — while also passing C2-topN, C2-cv and C7; thresholds approved by the author in MTA-0007; cycle 7 not started without the author's decision).

**Completion criterion for the polishing loop** (proposed to the author): the closing statement *"the model converges and agrees with independent sources"* is permissible only when **all four** conditions hold — (1) ensemble convergence (mean pairwise κ ≥ 0.40); (2) stability across seeds, bootstrap and periods (no sign change of the external association between the tuning and holdout splits, and no split whose AUC CI lies entirely below 0.5 — the latter added at the author's request, MTA-0008: a stably negative association is NOT credited); (3) circularity checks fully executed (section B); (4) holdout metrics stable between the last two versions (overlapping bootstrap CIs of holdout-AUC). Status at the end of cycle 3: **2 of 4** — (3) and (4) hold (v2 holdout-AUC 0.544 [0.516, 0.570] vs v3 0.580 [0.558, 0.601], CIs overlap); (1) and (2) do not (κ 0.19–0.25; the AUC sign flips between periods in every version). After cycle 4, condition (4) read as "the last two versions" stops holding: v3 [0.558, 0.601] and v4 [0.504, 0.554] do not overlap; status after cycle 4: **1 of 4**. Cycle 5 adds a second broken link (v4b [0.488, 0.541] vs v5 [0.396, 0.452]); v5 additionally removes the period sign-flip — but by being significantly negative in BOTH splits (holdout AUC 0.425, CI [0.396, 0.452] excludes 0.5: v5 significantly ranks AAP labels as LESS risky), which is stability of a wrong-direction association, not convergence — under the MTA-0008 reading it fails condition (2) exactly as a flip would. Cycle 6 (v6, same ranking as v5 — external AUC identical by construction, holdout 0.425 [0.396, 0.452]) leaves the status at **1 of 4**; condition (2) now fails for every version explicitly: the tuning CI lies entirely below 0.5 in v0–v6, and the holdout CI additionally in v5 and v6. The literal reading is inappropriate for the data-hygiene variants (v4, v4b): their holdout CIs overlap v0 [0.490, 0.544] (v4b [0.488, 0.541]) — 1 of 4 is the conservative reading. The honest current statement is therefore *not* "the ensemble converges and agrees with independent sources": it is that the ensemble is reproducible and documented, but its bands have not passed independent external validation and do not meet the convergence criteria. In all cases the output remains an indicator of potential risk, not evidence of corruption. Dynamics: `reports/cycle_dynamics.md`, `results/figures/cycle_dynamics.png`, `results/tables/cycle_metrics.csv`.

## 7. Decision-boundary economics

Cost = `c_miss × FN + FP` (one review per false positive; a true positive costs nothing extra; a missed case is priced at `c_miss` reviews). Baselines "flag nothing" / "flag everything" included (`results/tables/threshold_sweep.csv`):

| Rule | flagged | precision | cost@10 | cost@50 | cost@200 |
|---|---|---|---|---|---|
| flag nothing | 0 | — | **6,330** | **31,650** | 126,600 |
| votes ≥ 3 (production) | 3,031 | 0.82% | 9,086 | 33,406 | **124,606** |

No rule beats "flag nothing" at `c_miss` ≤ 50. The screening pays only under `c_miss ≳ 200`. Temporal split: votes≥3 precision 0.42% (lift 0.81) on 2018–2021 vs 1.18% (lift 3.09) on 2022–2024 — the rule is not stable across periods.

## 8. Fairness and bias (`reports/bias_audit.md`)

79 groups across 13 dimensions: buyer size, buyer type (central/local from official `typeOfBuyer` with a documented name-heuristic fallback), buyer spend (budget proxy — OCDS carries no buyer budget), buyer region, supplier region (OCDS address, grouped by the CUATM code so Cyrillic/Latin spellings merge), industry (CPV-2), procedure type, contract-value band, supplier seniority, supplier size (awards won), publication year, audit period (tuning/holdout), publication completeness (bids+values / values only / neither). Disparity band [0.8, 1.25] (four-fifths rule, adapted); conditional gap after standardising over the *other* legitimate factors, tolerance max(0.5 pp, 25% of expected) — this tolerance doubles as the **proposed per-group calibration rule** (observed high+ share must sit within it relative to the standardised expectation). Band shares and ranking percentiles are reported per group; TPR/FPR versus the AAP label are computed only where a group has ≥ 10 labelled procedures, always with the gap to the corpus TPR.

- **24 groups violate, 36 differences are explained by legitimate factors, 11 pass, 8 warn**; calibration within tolerance — 50 groups, outside — 29 (all listed with reasons in `reports/bias_audit.md`).
- Contracts ≥ 50 MDL: 50.9% land in high+ (disparity 10.5; +37 pp unexplained) — **the bands substantially measure contract size**. A critical flag on a very large contract is low-information beyond "it is large".
- Direct awards (51.5% of the corpus): 1.8% flagged (disparity 0.21, unexplained) — screening is largely blind there.
- Publication completeness: procedures with bids and values published (31% of the corpus) are flagged at 5.18×; procedures with neither bids nor values (23%) at 0.45× — **the bands partly measure how completely a buyer publishes**, not only its behaviour.
- Supplier regions (31% coverage, address published only with the award): Străşeni 4.28×, Orhei 3.82×, Ialoveni 3.19×, Bălţi 3.06× — flags concentrate among Chişinău-area suppliers (Chişinău itself 3.28×, explained after standardisation).
- Smallest-buyer quintile: 10.7% flagged (disparity 2.95, +5.3 pp unexplained) — likely a data-completeness artifact (`no_bid_data`/`single_bidder`), not buyer behaviour.
- Buyer type: central buyers flagged at 0.33×, local at 1.78× — the whole difference is explained by legitimate factors (contract size × procedure type) after standardisation.
- 7,712 rows carry a placeholder locality ("unknown" region): flagged at 2.39× — data artifact.
- TPR against AAP varies by group (0.24 in the smallest-buyer quintile vs 0.02–0.04 elsewhere) — partly selection bias of the label source itself.
- Feature proxies: only `supplier_award_count_log` crosses |r| ≥ 0.3 with a structural attribute (first-contract supplier, r = −0.77) — and that is definitional. No protected attributes (gender, ethnicity) exist in the open data to audit directly.
- **What to do on a violation** (recommendations, never applied automatically): percentile normalisation in a reference group; removal/merging of proxy features (author's decision, with ablation); group-specific thresholds only with a written justification in this model card; data fixes (publication completeness, placeholder locality) on the publisher/ETL side; a precision/recall trade-off only with both effects recorded here.
- **Cycle-6 re-audit on v6's own votes** (`reports/bias_audit_v6.md`, `results/methodology/bias_audit_v6.json` — the production v0 artefacts above are never overwritten): the size and procedure-type deviations shrink sharply (≥ 50 m share of high+ 50.9% → 14.6%, disparity 10.5× → 3.23×; direct awards 0.21 → **1.13, within band for the first time**; all five procedure types within band), but the total rises to **29 violations + 12 warnings** (10 groups fixed, 19 broken — industry ×6, supplier size ×4, supplier region ×3): normalising the flags inside the group **moves the bias rather than removing it**, and by making risk relative inside a group it loses 50.8% of v0-critical procedures, including 7 of the 10 largest (178–996 m, all in the top cost band) which get zero v6 votes — a whole-group anomaly is invisible to a within-group rule.

## 9. Recommendations (NOT applied; author's decision required)

1. **Merge the duplicate share column** — measured in cycle 4 (`v4_datafix`): consensus 3,031 → 2,381 (−21.4%), external AUC 0.4935 → 0.5031, tuning Δ +0.002 [−0.006, +0.010] — within CI. The isolated variant `v4b_datafix_keep_duplicate` confirms the attribution: with the duplicate kept, consensus stays 3,034 and κ 0.248 — the v4 consensus/κ changes come from the duplicate, not from the data fixes.
2. **Add a recalibration trigger** for the vote threshold (drift PSI 0.29–0.41; consensus share 4.3% → 0.69%).
3. **Normalise percentiles within (value band × procedure type)** or state explicitly that ≥ 50 MDL contracts carry a low-information critical band — **measured in cycles 5–6 and not adopted**: v5 (ranking only) and v6 (flags normalised within the group) reduce the ≥ 50 m dominance (10.9× → 2.9× → 14.6% of high+) and fix the direct-award bias, but v6 costs 50.8% of v0-critical procedures, fails C5 on holdout for the first time, and both leave the ≥ 50 m disparity outside [0.8, 1.25] (3.23× at best).
4. **Fix the placeholder locality** (7,712 rows) — cleaned in `v4_datafix` (display/audit groups only; locality is not a model feature).
5. **Record seed/parameters as part of the list version** (membership Jaccard 0.71 across seeds).
6. Decide whether direct awards (51.5% of the corpus) are in scope at all.

## 9a. Explanation consistency (section H: LIME vs SHAP)

Both methods explain **the same function**: the production IsolationForest
output `f(z) = expected_value + Σ shap_values(z)` — the exact function
TreeExplainer decomposes (additivity error 0.0; rank-equivalent to the
production `iso.score_samples`, Spearman 1.0). LOF and One-Class SVM have no
per-feature local explanation by construction (stated in scripts/17, not
invented).

- Sample: 60 procedures (10 per band + 10 AAP-positive + consensus-boundary),
  5 LIME restarts × 5 000 perturbations each, bootstrap CIs over procedures.
- Spearman(LIME, SHAP) median **−0.68**, sign agreement **0.11**, top-3 overlap
  0.00, top-5 overlap 0.20; LIME restart stability **0.98** (self-consistent);
  local surrogate R² ≈ 0.58.
- **Verdict: «не согласованы»** under agent-proposed thresholds (median ≥ 0.70
  and sign ≥ 0.80 → «согласованы»; median ≥ 0.40 → «частично»; author approves
  the thresholds). The verdict is **robust to the contribution convention**:
  all four standard readings of LIME output as a contribution (bin effect,
  bin × deviation, raw coefficient, coefficient × deviation) stay below the
  «partially» bar (medians −0.68 / −0.20 / +0.06 / −0.79).
- Diagnosis: restart instability is **rejected** (0.98); correlated features
  contribute (10/22 features with VIF ≥ 10 — SHAP spreads credit, LIME does
  not); nonlinearity is confirmed (agreement changes materially with
  discretization on/off). Full report: `reports/xai_report.md`; artefacts
  `results/methodology/xai_consistency.json`, `results/tables/xai_consistency.csv`.
- Contract row M10 is **unmet**: local explanations from different methods do
  not agree, so a single explanation should not be presented as the only
  authoritative reading — this is a limitation of the explanation layer, not
  of the risk scores themselves.

## 9b. Explanation layer with normative sources (RAG)

Every high/critical procedure (7 662 of 7 662 = 100%, contract row B10) gets an
explanation with normative sources: plain-language top-3 SHAP features plus
extractive citations from the official corpus (Legea nr. 131/2015 consolidated
to LP82/2022, the AAP methodological seminar, the official interdiction
register snapshot; editions, URLs and sha256 in `docs/rag_sources.md` and
`results/rag/manifest.json`). Known gaps (HG 957/2017, HG 1420/2016, ANSC
decisions, the risk-indicator methodology) are documented, not hidden.

- Evaluation (`results/methodology/rag_eval.json`): recall@1/3/5 =
  **0.925/1.0/1.0**, MRR 0.9625 on a self-supervised retrieval test; refusal
  without relevant fragments **5/5**; hallucinated references **0 of 1 105**
  citations re-verified verbatim (stopping criterion C7); prompt-injection
  defence (corpus-side and query-side) confirmed on marked synthetic text.
- Protections: extractive-only answers (quotes cannot be paraphrased),
  explicit refusal below the relevance floor (score ≥ 5.0 **and** ≥ 2 matched
  terms), neutralisation of injected instructions, no guilt/intent wording,
  no personal data beyond fields published in MTender, mandatory disclaimer
  (potential-risk indicator, not evidence of corruption; competent-authority
  review required).
- Thresholds (recall@3 ≥ 0.60, zero hallucinations, coverage = 100%) were
  proposed by the agent; **the author approves them**. Limitations: answers
  are bounded by corpus completeness and edition validity (see §12).

## 10. Reproduce

```bash
.venv/bin/python scripts/12_external_metrics.py --boot 1000   # external metrics
.venv/bin/python scripts/13_agreement_matrix.py               # agreement + ensembles
.venv/bin/python scripts/14_threshold_calibration.py          # thresholds, split, drift
.venv/bin/python scripts/15_robustness_seeds.py --runs 20     # seed stability
.venv/bin/python scripts/16_feature_ablation.py               # contribution + ablation
.venv/bin/python scripts/17_explain_ocid.py --ocid <OCID>     # right to an explanation
.venv/bin/python scripts/18_bias_audit.py                     # fairness audit
.venv/bin/python scripts/19_final_verification.py             # re-derives every number above
.venv/bin/python scripts/20_cycle_framework.py --variants v0 v1 v2 v3 v4  # iterative cycle (v0–v4)
.venv/bin/python scripts/21_circularity_check.py              # circularity check, section B
.venv/bin/python scripts/22_cycle_dynamics.py                 # cycle → metrics dynamics
.venv/bin/python scripts/23_check_contract.py                 # contract matrix: accept / not accept
.venv/bin/python scripts/24_xai_consistency.py                # section H: LIME vs SHAP
.venv/bin/python scripts/25_rag_pipeline.py                   # RAG: index + explanations with sources
.venv/bin/python scripts/26_rag_eval.py                       # RAG: recall@k, refusals, hallucinations
```

## 11. Limitations

Small external sample (633 procedures / 17 suppliers; 259 from one supplier); weak, supplier-attributed, temporally-shifted label; no ground truth for corruption (classical precision/recall are **not computable** — `backend/app/model_kpis.py`); circularity of in-model importance tests (controls in §6); set-level non-reproducibility across seeds (§5); bands partly track contract size and are blind to direct awards (§8); no protected attributes available for a direct bias audit (structural groups are a substitute, not an equivalent); **possible incomplete publication by part of the buyers** (bids and values published for 31% of procedures, values only for 46%, neither for 23% — their features are truncated; the audit keeps them as an explicit group, but completeness is fixed by publisher requirements, not by the model); official `typeOfBuyer` covers 57.8% of procedures (the rest is a documented name heuristic plus an explicit unknown group) and supplier-region coverage is 31% (the address is published only with the award); OCDS carries no buyer budget (total awarded value is used as the proxy); **local explanations do not agree across methods** (§9a: LIME vs SHAP median Spearman −0.68, robust to the contribution convention — an individual explanation is one of several readings, not the authoritative one); **normative answers are bounded by the RAG corpus** (§9b: complete only for Legea 131/2015 + AAP seminar + interdiction register; HG 957/2017, HG 1420/2016, ANSC decisions and the risk-indicator methodology are documented gaps, so recall on questions touching them is provably low, and edition validity on legis.just.gov.md could not be re-checked from this machine — Cloudflare 403); external-source inventory only partially verified from this machine (tender.gov.md and faolex.fao.org reachable since 2026-10-17, legis.md and decisions.ansc.md still blocked).

*Indicator of potential risk, not evidence of corruption.*
