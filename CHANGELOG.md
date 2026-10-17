# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are dated tags of the form
`MTA-YYYYMMDD`.

## [MTA-datafix-2026-10-18] — Iteration cycle 4 (v4_datafix): author's data-artifact fixes, measured

Author-requested data-quality fixes, measured in the cycle protocol rather than applied on
trust. **Production behaviour unchanged** (v0 remains the shipped configuration; replacing
it is the author's explicit decision).

### Added

- `scripts/20_cycle_framework.py`: variant `v4_datafix` and `apply_datafix` — full
  supplier-id normalisation (strip + internal-whitespace collapse + case folding:
  **536 phantom supplier ids merged**, 14,477 → 13,941; behavioural features recomputed,
  1,953 rows change `buyer_supplier_repeat_share`), explicit P99.9 winsorisation caps on
  the two value features that had none in production (`log_award_value` ≤ 17.50,
  `log_award_total` ≤ 18.76; the other three capped features already had caps in
  `features.py`), cleanup of **7,712 literal 'locality' placeholder** rows in
  `buyer_locality` (region is not a model feature — display/audit groups only), plus the
  byte-identical duplicate column dropped as in v1.
- `reports/cycle_4.md`, cycle-4 entry in `cycle_log.md`; `tests/test_cycle_protocol.py`
  extended (variant set now v0–v4, functional `apply_datafix` test) — **150 tests total**.

### Measured result

v4 vs v0: tuning ΔAUC **+0.0022 [−0.0058, +0.0105]** — within the CI; consensus
3,031 → **2,381** (≈ v1: the shrink comes from the duplicate, not the id normalisation);
mean pairwise κ 0.250 → **0.217**; PSI 0.29 → 0.38; stop criteria **3/8** (unchanged).
Conclusion: data defects are fixed and were **not** the cause of the contract-matrix
failure — external metrics did not change beyond the interval. Contract matrix after the
run (`scripts/23`): 9 met / 16 unmet / 2 not verifiable — unchanged. All headline numbers
reproduce (`scripts/19`: v0–v3 anchors byte-identical; v4 is an extra row). Cycle-4
completion criterion after this cycle: 1 of 4 (holdout CIs of the last two versions v3
and v4 no longer overlap).

### Changed

- `docs/annotation.md` rewritten to the verified figures at the author's request: label
  source stated as the AAP interdiction list (Lista de interdicție), 13,986 suppliers in
  production (13,941 under full normalisation), 25 verifiable + 2 documented-not-verifiable
  matrix rows, 150 tests, period-dependent AUC (0.41 tuning / 0.53 holdout), pay-off
  statement matched to the artefacts (no rule beats flag-nothing at c_miss 10 and 50),
  bias-audit headline findings, keywords.
- `docs/model_card.md`, `docs/thesis_text.md`, `docs/METHODOLOGY_CYCLE.md`,
  `docs/PROJECT_OVERVIEW.md`, `docs/RACI_MATRIX.md`: v4 cycle recorded; phantom-id counts
  reconciled as 491 (strip-only) / 536 (full normalisation); completion criterion status
  updated after cycle 4.

## [MTA-explanation-layer-2026-10-17] — Section H (LIME vs SHAP), RAG explanation layer, stop criterion C7

Author-requested additions on top of the completed methodology cycle. **No production
behaviour changed:** features, bands, detectors and the consensus threshold are untouched;
the additions are analysis, documentation and a new stop criterion applied retroactively.

### Added — XAI consistency (section H)

- `scripts/24_xai_consistency.py` — LIME vs SHAP on **the same explained function**
  (the production IsolationForest output decomposed exactly by TreeExplainer, additivity
  error 0.0, rank-equivalent to the shipped score): 60-procedure stratified sample
  (10 per band + AAP positives + consensus boundary), 5 LIME restarts × 5 000
  perturbations, bootstrap CIs, VIF linkage, low-agreement diagnosis, PDP/ALE top-5,
  and a **contribution-semantics sensitivity block** (4 standard readings of LIME
  output as a "contribution").
- Outputs: `results/methodology/xai_consistency.json`, `results/tables/xai_consistency.csv`,
  `results/figures/xai_global.png`, `results/figures/xai_pdp_ale.png`, `reports/xai_report.md`.
- Result: median Spearman −0.68, sign agreement 0.11 — verdict **«не согласованы»** under
  agent-proposed thresholds (author approval pending), robust across all four contribution
  conventions (medians −0.68 / −0.20 / +0.06 / −0.79, none reaching the «partially» bar);
  restart instability rejected (LIME stability 0.98), correlated features
  (10/22 with VIF ≥ 10) and tree nonlinearity identified as the drivers.

### Added — RAG layer with normative sources

- `src/mtender/rag.py` — official-corpus registry (act / issuer / URL / edition /
  download date / sha256), documented corpus gaps, structural chunkers (article /
  slide / register entry), BM25 index, **extractive** answers with verbatim citations
  re-checked against the stored chunks, refusal below the relevance floor
  (score ≥ 5.0 **and** ≥ 2 matched terms), prompt-injection neutralisation on both the
  corpus and query side, forbidden-formulation guard, mandatory disclaimer.
- `scripts/25_rag_pipeline.py` — indexes `data/legal/raw/` (Legea 131/2015 consolidated
  to LP82/2022 via the FAOLEX mirror, the AAP methodological seminar, the official
  interdiction-register snapshot of 2026-10-17) and produces an explanation with
  sources for **every high/critical procedure: 7 662 / 7 662 = 100 %**.
- `scripts/26_rag_eval.py` — self-supervised retrieval test (recall@1/3/5 =
  0.925/1.0/1.0, MRR 0.9625), refusal tests (5/5), hallucination verification
  (**0 of 1 105 citations**), injection-defence smoke test, coverage check.
- Outputs: `results/rag/corpus_chunks.jsonl` (184 fragments), `results/rag/manifest.json`,
  `results/rag/procedure_explanations.jsonl`, `results/rag/pipeline_summary.json`,
  `results/methodology/rag_eval.json`, `reports/rag_eval.md`, `docs/rag_sources.md`.

### Added — stop criterion C7 and contract-matrix updates

- `scripts/20_cycle_framework.py` — C7: zero hallucinated references and recall@3 ≥ 0.60
  (thresholds proposed by the agent, author approval pending), evaluated from
  `rag_eval.json`; applied retroactively to every version — all pass (criterion counters
  3/8, 3/8, 4/8, 3/8).
- `scripts/23_check_contract.py` — four new checks: `xai_spearman_median`,
  `rag_coverage_high_critical`, `rag_recall_at_3`, `rag_hallucination_rate`.
- `docs/contract_matrix.yaml` / `docs/contract_matrix.md` — B10 (100 % high/critical with
  normative sources, met), M16 (recall@3, met), M17 (zero hallucinations, met); M10
  (LIME/SHAP consistency) moves from «не проверяемо» to verifiable and is **unmet**
  (median Spearman −0.68); B9 note updated (partial network unblock). Totals:
  **9 met / 16 unmet / 2 documented not-verifiable** — the contract still does not converge.
- `scripts/19_final_verification.py` — stop-criteria anchors updated to the /8 scale.

### Documentation

- `docs/rag_sources.md` — corpus inventory: editions, URLs, sha256, licences status
  («требует проверки»), documented gaps (HG 957/2017, HG 1420/2016, ANSC decisions,
  risk-indicator methodology).
- `docs/data_provenance.md` — new section «Нормативный корпус» + honest update of the
  network-access limitation (tender.gov.md / faolex.fao.org reachable since 2026-10-17).
- `docs/model_card.md` — §9a (explanation consistency), §9b (RAG layer), limitations
  extended (method disagreement; corpus completeness and edition validity).
- `docs/thesis_text.md` — §8а, §8б, rewritten «not confirmed» item 7 (LIME now
  implemented — negative result), conclusions and traceability updated.
- `docs/METHODOLOGY_CYCLE.md`, `cycle_log.md`, `reports/cycle_1..3.md` — C7 and the
  /8 criterion scale.

### Tests

- `tests/test_rag.py` — 12 tests on synthetic marked corpora: chunking, diacritics,
  refusal paths, verbatim citations, single-token leak floor, injection neutralisation
  (corpus and query side), formulation guard, disclaimer, HTML stripping.
- `tests/test_cycle_protocol.py` — C7 threshold, missing-artefact and failure-path tests.

## [MTA-methodology-cycle-2026-10-17] — Methodology cycle (audit → version)

Full methodology cycle over the existing pipeline: audit, external validation, feature
contribution with circularity controls, agreement matrix, threshold calibration, seed
robustness, bias audit, legal review, model card. **No production behaviour was changed:**
detector parameters, the consensus threshold (votes ≥ 3) and the feature set are untouched;
every proposed change is a documented recommendation with ablation evidence.

### Added — analysis code (English docstrings, reproducible, `results/` outputs only)

- `scripts/12_external_metrics.py` — external validation against the AAP interdiction list:
  precision@k / recall@k / ROC-AUC / PR-AUC with procedure- and supplier-cluster bootstrap CIs.
- `scripts/13_agreement_matrix.py` — pairwise Cohen's kappa / Jaccard / rank correlations,
  vote distribution, alternative ensemble rankings.
- `scripts/14_threshold_calibration.py` — threshold sweep with `flag-nothing` / `flag-all`
  baselines, error-price curves (cost = c_miss·FN + FP), temporal split 2018–21 / 2022–24,
  drift (KS, PSI), consensus-share timeline.
- `scripts/15_robustness_seeds.py` — 20 seeded detector runs; count vs membership stability.
- `scripts/16_feature_ablation.py` — feature contribution table, **circularity controls**
  (columns the detectors never saw + a Gaussian placebo column fed to them), group and
  single-feature ablation with full detector re-fits, verdict table.
- `scripts/17_explain_ocid.py` — right to an explanation: plain-language SHAP breakdown for
  one procedure (RU/EN); states honestly that LOF/OCSVM have no per-feature local explanation.
- `scripts/18_bias_audit.py` — fairness/bias audit (section E): 13 dimensions incl. buyer
  type (official `typeOfBuyer` + documented name heuristic), buyer spend (budget proxy),
  supplier region (grouped by CUATM code so Cyrillic/Latin spellings merge), supplier
  size, publication year, audit period, publication completeness; disparity ratios with
  bootstrap CIs, band shares and ranking percentiles per group, direct standardisation
  over legitimate factors, per-group calibration rule with the proposed tolerance,
  TPR/FPR vs AAP where n ≥ 10 (plus gap to the corpus TPR), feature-proxy scan,
  label-coverage table, E.5 remediation recommendations; OCDS party attributes are
  read-only over `data/raw` and cached in `results/tables/party_attributes.csv`.
- `scripts/19_final_verification.py` — re-derives every headline number from artefacts and
  exits non-zero on any mismatch; adds supplier-cluster and leave-one-supplier-out
  uncertainty for the univariate AUCs.
- `scripts/20_cycle_framework.py` — the measuring instrument shared by every polishing cycle:
  one variant → the full metric suite (external metrics with bootstrap CIs on the
  tuning/holdout split, paired-bootstrap ΔAUC vs v0 on tuning only, band calibration,
  pairwise agreement, top-N stability across seeds, hyperparameter sensitivity, period
  drift) plus mechanical stop-criteria evaluation. Variant registry `v0`–`v3`; refuses an
  unknown variant instead of silently writing an empty result.
- `scripts/21_circularity_check.py` — section B of the addendum: pure ANOVA against the
  independent AAP label vs against the bands; feature halves (5 random + 1 group split,
  cross-half explanation); concentration ablation with re-computed bands/ANOVA/SHAP;
  permutation importance vs own predictions vs external label; **randomised control**
  (shuffled buyer–supplier links, marginals preserved, behavioural features recomputed);
  ANOVA vs SHAP divergence; mechanical per-feature verdicts (confirmed by independent
  labels / internally only / not confirmed).
- `scripts/22_cycle_dynamics.py` — cross-cycle summary: cycle → metrics table with CIs and
  the dynamics figure.
- `scripts/23_check_contract.py` — contract-matrix check: recomputes every verifiable KPI
  status from the last cycle's artefacts and fails (exit 1) on any unmet row, missing data
  source, stale recorded status, model KPI without a business KPI, or undocumented
  "not_verifiable" row; the model is accepted only when the matrix converges.

### Added — iterative-cycle journal and reports

- `cycle_log.md` (repo root) — the polishing journal: protocol, version registry v0–v3
  (one change each), per-cycle effects, the stop decision and the honest list of what
  blocks further polishing.
- `reports/cycle_1.md`, `reports/cycle_2.md`, `reports/cycle_3.md` — per-cycle reports
  (change, rationale, full metric table, comparison with the previous cycle, decision).
- `reports/cycle_dynamics.md` (generated) + `results/figures/cycle_dynamics.png` — the
  cross-cycle dynamics with bootstrap CIs.
- `reports/circularity_check.md` (generated) — section B results with per-feature verdicts.

### Added — library code and tests

- `src/mtender/eval_metrics.py` — precision/recall/lift@k, ROC/PR-AUC, bootstrap CIs
  (procedure and supplier-cluster resampling), Cohen's kappa, Jaccard, Wilson intervals.
- `src/mtender/external_labels.py` — AAP label construction; `load_scored_corpus()` is the
  single sanctioned features+scores+labels join **by ocid** (guards against a positional-join
  bug class: scores are sorted by votes, features by ocid).
- `tests/test_external_labels.py` — 6 regression tests: empty-name matching bug, known entry
  counts, ambiguous-candidate exclusion, and ocid-alignment of the scored corpus.
- `tests/test_contract_matrix.py` — 5 tests for the contract matrix: model-KPI → business-KPI
  links, status enum, documented "not_verifiable" rows, check-registry completeness,
  comparator semantics.

### Added — reports and documentation

- `docs/METHODOLOGY_CYCLE.md` — the cycle report (Russian): per-step status, findings,
  traceable numbers, prioritised problem list, open questions for the author.
- `docs/model_card.md` — model card: data, features, threshold, metrics, circularity
  controls, economics, fairness, recommendations, limitations, reproduction commands.
- `docs/thesis_text.md` — thesis-ready text (Russian) on methodology findings and the
  fairness/bias section.
- `reports/bias_audit.md` (generated), `reports/legal_and_sources.md` — legal framing and
  the inventory of external label sources with access status.
- `docs/contract_matrix.md` + `docs/contract_matrix.yaml` — the contract matrix (RU report /
  machine-readable source of truth): business and model KPIs with data source, metric and
  formula, acceptance threshold, legal/ethical conditions and a recorded status; the model
  is accepted only when every row is "met" or a documented "not_verifiable" (current state:
  6 met / 15 unmet / 3 not verifiable — the contract does not converge).
- `docs/data_provenance.md` — data provenance (RU): for every source — origin, download
  date, version, SHA-256, licence status and known gaps; the synthetic-data policy
  (tests / randomised controls only, always marked).
- `notebooks/09_methodology_cycle.ipynb` — walkthrough reproducing the key tables from
  saved artefacts.

### Artefacts (all regenerable by the scripts above)

- `results/methodology/*.json` — external validation, agreement, threshold calibration,
  seed robustness, feature verdicts, bias audit, final verification.
- `results/tables/*.csv` — external metrics, ensemble comparison, threshold sweep, drift,
  seed stability, feature contribution / ablation / circularity controls, bias audit tables.
- `results/figures/*.png` — agreement matrix, threshold/drift, seed robustness, feature
  verdicts, bias audit.

### Key findings (details and numbers in the cycle report)

- Production ranking is statistically indistinguishable from random on the external label at
  the top (ROC-AUC 0.493, CI includes 0.5; precision@200 = 0); enrichment exists only in the
  consensus tail (votes≥3 lift 1.99, votes≥4 lift 2.54).
- Single features (e.g. `n_bidders_log`, AUC 0.80, robust to supplier-cluster bootstrap and
  leave-one-supplier-out) carry signal the max-of-percentiles ensemble destroys.
- `winner_share_of_buyer_awards` is a byte-identical duplicate of
  `buyer_supplier_repeat_share`; merging them shifts the consensus by −21.5% (recommendation,
  not applied).
- In-model importance tests (ANOVA/permutation vs the model's own outputs) are circular —
  proven with never-fed control columns and a placebo column; they are construction checks,
  not validity evidence.
- Consensus *count* is seed-stable (cv 4.8%) but *membership* is not (Jaccard ≈ 0.71);
  adding a noise column perturbs the set the same amount.
- Threshold economics: no rule beats "flag nothing" unless a missed case costs ≥ ~200 review
  equivalents; strong drift (consensus share 4.3% → 0.69% by year) requires recalibration.
- Bias audit (79 groups, 13 dimensions): the bands substantially measure contract size
  (≥ 50 MDL: 50.9% in high+, disparity 10.5), are near-blind to direct awards (51.5% of
  the corpus), over-flag the smallest buyers and placeholder-locality rows, and partly
  track **publication completeness** (bids+values published → 5.18×, nothing published →
  0.45×) and **supplier region** (Chişinău-area suppliers 3–4.3×). Buyer type
  (central 0.33× / local 1.78×) and the tuning/holdout period split are fully explained
  by legitimate factors. Verdicts: 24 violations, 36 explained, 11 pass, 8 warnings;
  C6 (the "bias audit passes" stop criterion, added at the author's request and applied
  retroactively to all versions) fails for every version.
- Iterative polishing (v0–v3, one change per cycle, decisions on the 2018–21 tuning split):
  no candidate improves the external AUC beyond the CI (v2 mean-percentile ranking
  significantly *regresses* on tuning: −0.033 [−0.056, −0.009]); stopped after 3 of 10
  cycles. No version meets the proposed convergence criteria (best: 3/7 — C1–C3, C5, C6;
  C6 added after the loop stopped, applied retroactively to all versions); the ensemble is
  reproducible and documented but has **not** passed independent external validation.
- Completion criterion for the polishing loop (proposed to the author, recorded in
  `cycle_log.md`, `docs/METHODOLOGY_CYCLE.md`, `docs/model_card.md`, `docs/thesis_text.md`):
  the closing statement "the model converges and agrees with independent sources" is
  permissible only when all four conditions hold — ensemble convergence (κ ≥ 0.40),
  stability across seeds/bootstrap/periods, circularity checks executed, holdout metrics
  stable between the last two versions. Status at the end of the cycle: **2 of 4** (the
  last two conditions hold; κ 0.19–0.25 and the period sign flip block convergence).
- Randomised control: shuffling buyer–supplier links (marginals preserved) leaves the
  behavioural features' external association intact (it lives in the marginals, not the
  pairs) and their ANOVA-vs-bands dominance *grows* — a calculation artefact by the
  protocol's own rule; the shuffled ensemble matches the AAP label better than the real one
  (0.576 vs 0.493).
- Feature halves: bands built from one half of the features agree with the other half's
  bands only at Jaccard 0.18–0.26 (group split 0.01) — bands are not reproducible from half
  a feature set, and no hidden "correct" subset exists (half-rankings' external AUC stays
  in the same 0.44–0.58 band as the full model).

### Changed

- Nothing in production paths. `backend/`, `frontend/`, `scripts/00..11` untouched by this
  cycle except `data/features`/`results` recomputations that reproduce the shipped baseline
  exactly (verified: bands 125 242 / 19 474 / 4 631 / 3 031).

## [MTA-0002] — 2026-10-09

Project audit, bug fixing, dead-code removal, environment rebuild, ETL re-run, service
restart (see `docs/AUDIT_REPORT.md` for the full record).
