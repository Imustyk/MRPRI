# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are dated tags of the form
`MTA-YYYYMMDD`.

## [MTA-0012-2026-10-18] — ANSC label reconnaissance inside the raw OCDS (feasibility, no training, no new cycle)

Local-only inventory plus a policed 50-document sample — a feasibility report,
not a label in the model (production stays v0, budget stays 6 of 10).
`scripts/29_ansc_docs_inventory.py` scans all 152,378 raw OCDS packages
(read-only) at the four document levels: **430,959 documents** (tender
342,220 / award 68,377 / contract 20,362 / planning 0), all on
`storage.mtender.gov.md`; `documentType = complaints` exists for **6,970
documents of 1,665 procedures** — the only structural complaint trace (the
`complaints` array is absent everywhere; `enquiries` 19,810, `amendments`
26,462+2,676). Keyword search (ro/ru, diacritic-insensitive): `03D-` 524
procedures, `ANSC` 67, `contestați` 37, full agency names ~0, weak `decizi`
6,502 (award-decision noise) — union of STRONG candidates = **2,183
procedures = 1.43% of the corpus** (per-year: 2018 0.65% … 2021–22 ~3.2% …
2024 0.27%); the author's known pair (03D-159-26, 2026) is outside the
2018–2024 corpus. `scripts/30_ansc_sample_parse.py` refuses to run without
`--allow-network`, downloads ≤ 50 docs stratified by year from
storage.mtender.gov.md only (≥ 2 s pauses, academic User-Agent, host checked
after redirects; on 403/429/anti-bot it stops — never happened here: **50/50
downloaded, no block**), each file in its own fresh sandbox folder outside
the repo, `python -I`, pypdf only, full texts never enter the repo. Text
extracted from **35/50 = 70%**; 15/50 scans marked «требует OCR» (not run).
Real decision numbers parsed from live documents: 03D-555-18, 03D-1003-20,
03D-801-21; outcomes admis 3 / respins 3 / admis_partial 1 (heuristic).
Verdict in `reports/ansc_labels_feasibility.md`: **partial** — a weak
"contested / upheld" label covers ~1–1.4% of the corpus and is too small for
training or external validation; the full ANSC register (manual site check or
the OCP BI tool) is needed from the author. +15 tests (`tests/test_ansc_parser.py`,
synthetic strings only + the no-`--allow-network` regression), 181 total.
Annotation unchanged (250 words).

## [MTA-0011-2026-10-18] — Text-only: AAP = Agenția Achiziții Publice, unified v5/v6 ΔAUC procedure CI, section-10а wording

No calculations. (1) The AAP interdiction list is published by **Agenția Achiziții Publice** —
the previous attribution to the Competition Council was wrong: fixed in `docs/thesis_text.md`
(§3 line 19 and §10а) and `reports/legal_and_sources.md:42`; a repo-wide grep for the old
attribution now returns nothing
(other "Consiliul …" hits are buyer names — rayon councils — and stay
untouched).
(2) The v5/v6 tuning ΔAUC procedure CI is unified to the single value of
`scripts/27_delta_cluster_boot.py` (1 000 replicates, seed 42; exact artefact bounds
−0.002085 / 0.048152, `results/methodology/delta_v5_vs_v0_boot.json`) — **[−0.002; +0.048]**:
replaced in the thesis §10а table (was `scripts/20`'s [−0.0043; +0.0487]) and in
`reports/cycle_6.md` (4-decimal rendering unified to 3-decimal, `scripts/27` named in the row
header); `reports/cycle_5.md`, `docs/model_card.md`, `cycle_log.md` and this CHANGELOG already
carried the scripts/27 value and needed no change. `reports/cycle_dynamics.md` remains
generated from `scripts/20`'s framework JSON and keeps the scripts/20 CI there (outside the
author's file list). (3) Section 10а wording per the author: the point-2 header is now
«Провал внешней валидности — свойство данных и задачи, а не артефактов выгрузки», and the
temporal-skew sentence reads «обратный временно́й перекос: интердикции датированы 2023–2026
годами, процедуры — 2018–2024, то есть часть интердикций относится к более позднему периоду,
чем сами процедуры» — interdictions, not "decisions", matching the AAP renaming. Annotation
unchanged (250 words); 166 tests.

## [MTA-0010-2026-10-18] — Thesis section «Label limits and cycles v0–v6» (no new calculations)

Documentation-only task (no new computations, no new cycle: budget stays 6 of 10, production
stays v0). `docs/thesis_text.md` gains section 10а «Ограничения метки и итоги циклов v0–v6»:
what the AAP label measures (22 entries, 18 exact matches, 17 suppliers, 633 procedures, base
rate 0.415%, 259 of 633 from one supplier, decisions postdating procedures, selection bias →
the label is weak and narrow, AUC against it cannot be the sole acceptance criterion); one
consolidated v0–v6 table (change, κ, consensus, paired ΔAUC tuning with the supplier-cluster
CI where measured, holdout AUC, decision — every number taken verbatim from the existing
artefacts); three findings (no ΔAUC improvement beyond the CI by any change; the failure is a
data/task property, not an export artifact — v0 bands already carry the size bias; the
MTA-0009 random-5%-control: C3/B4 reproduced by the normalisation alone, κ / signal retention /
residual ≥ 50 m share not). The audit-E-on-control note states the mandated wording — the
control audit ran on **5 repeats out of 200** (200 bootstrap replicates each) and v6's total
of 41 verdicts is **above the random-flag baseline** of 5–12, the excess not attributed to
detector quality. Also propagated the same wording correction (from «detector verdicts») into
`reports/cycle_6.md` F, `reports/random_flags_control.md` (`scripts/28` template),
`cycle_log.md`, `docs/model_card.md`. No numbers changed anywhere; annotation unchanged
(≤ 250 words, 166 tests).

## [MTA-0009-2026-10-18] — Random-5%-within-group control for v6 (cycle-6 correction, no new cycle)

Author-requested correction to cycle 6, **not a new cycle** (budget stays 6 of 10, no v7 is
created, production stays v0, the cycle-6 verdict "not adopted — compromise", the contract
matrix 9/16/2 and the closing status 1 of 4 are unchanged). Question: are v6's improvements
(C3 passing, B4 within band, size dominance down) achieved by the within-group flag
normalisation itself rather than by detector quality? The control keeps the normalisation and
throws the detector signal away (no detector score is used anywhere).

### Added

- `scripts/28_random_flags_control.py`: two controls, 200 repeats each with fixed seeds —
  (a) 4 independent random 5%-within-group flags (exact per-group flag count of v6's
  `group_flag_frame`), consensus ≥ 3; (b) rank-consensus-matched: v6's band sizes (consensus
  2,965, high+ 6,969) drawn at random inside the groups proportional to group size, critical
  nested in high+ (the low/medium split of (b) is undefined and unused by every compared
  metric). Per repeat: C3 (`scripts/20` formula), direct-award share/disparity of high+,
  ≥ 50 m rate/disparity (`scripts/18` formula), signal retention (share of v0-critical kept),
  mean pairwise κ; the full section-E audit re-run on control votes with the production code
  path (`scripts/18.audit_group_table`, 5 repeats per control, 200 bootstrap replicates) —
  **production audit artefacts v0/v6 are never overwritten**. Outputs:
  `results/methodology/random_flags_control.json`, `results/tables/random_flags_control.csv`,
  `reports/random_flags_control.md`. The v0 self-check inside the script reproduces every
  artefact value (C3 0.1586, B4 0.2099, ≥ 50 m rate 0.5085, disparity 10.4829, 3,031/7,662).
- `scripts/18_bias_audit.py` refactored into module functions `build_audit_frame()` and
  `audit_group_table(df, n_boot=BOOT)` (behaviour byte-identical: both audits regenerated and
  diffed against the pre-refactor artefacts — only two self-description fields
  `votes_source`/`variant` appear in the production JSON, by MTA-0008 design);
  `bootstrap_disparity` gains an optional `n_boot` (production default unchanged).
- `reports/cycle_6.md`: new section F (the control table and the honest reading) and the
  explicit power caveat for the cheapest-band stratified AUC ("19 positives — insufficient
  power; enrichment not claimed").

### Measured result

Control (a)/(b) medians [p2.5; p97.5] vs v0 / v6: C3 0.318 [0; 0.597] / 0.869 [0.748; 0.943]
(vs 0.159 / 0.537 — random flags with the same bands pass C3 *better* than v6);
B4 direct disparity 0.998 [0.936; 1.074] / 1.000 [0.997; 1.002] (vs 0.21 / 1.13 — the return to
the OK band is reproduced by random flags; v6's 1.13 sits outside control (a), +13% over its
median — a small detector-driven under-flagging of direct awards); ≥ 50 m rate in high+
0.0136 [0.005; 0.024] / 0.044 [0.029; 0.063] (vs 0.509 / 0.146 — v6 far outside both, 3.3×
control (b): the size signal survives normalisation); v0-critical retention 0.0003 / 0.0195
(vs 1.00 / 0.492 — outside both); κ ≈ 0.0002 (vs 0.2497 / 0.2991). Audit verdicts on random
votes: 5–12 unexplained (medians 8 and 5) vs 41 (v6) and 32 (v0) — random flags show only the
multiple-comparison false-positive baseline (audit on 5 repeats per control out of 200): v6's
total of 41 is **above the random-flag baseline**, but the excess is not attributed to
detector quality without a further breakdown. Honest reading fixed in `reports/cycle_6.md` F and
`reports/random_flags_control.md`: **the C3/B4 equalisation is a property of the
normalisation; what distinguishes v6 from a random flag with the same share is κ, signal
retention and the residual size concentration** — and none of it passes the thresholds
(v6 still not adopted). 8 new tests (flag-count mirror of `group_flag_frame`, proportional
allocation and nesting of control (b), C3/disparity formulas against the production
definitions, determinism, production bootstrap default) — **166 passed**; annotation test
count updated.

## [MTA-0008-2026-10-18] — Iteration cycle 6 (v6_group_flags): flags normalised within group, bias audit re-run on its own votes, cycle-5 corrections

Author-requested cycle 6 (budget 6 of 10). **Production behaviour unchanged** (v0 remains
the shipped configuration). Author's decision recorded 2026-10-18 (`docs/METHODOLOGY_CYCLE.md`):
v6 may lower AUC against AAP if the bias audit (C6/B4) improves — **AUC against AAP stays a
"no worse" control, not an acceptance criterion**. Cycle-5 corrections: the "C2 passes for the
first time" claim was wrong (v2 passed C2-topN with Jaccard 0.671) and has been fixed in
`reports/cycle_5.md`, `cycle_log.md`, `CHANGELOG.md`, `docs/model_card.md`, `scripts/22`;
holdout v5 is now stated directly (CI [0.396, 0.452] excludes 0.5 — v5 significantly ranks
AAP labels as LESS risky); a stably negative association no longer counts toward completion
condition (2) in `scripts/22` (test `test_completion_status_stably_negative_not_credited`);
`reports/cycle_5.md` gained the ΔAUC sign-change paragraph (tuning +0.023, holdout −0.093 —
the AAP label reflects size/competition; a label limitation).

### Added

- `scripts/20_cycle_framework.py`: variant `v6_group_flags` — a detector's flag is the top
  5% (`OUTLIER_RATE`) **inside its «cost band × procedure type» group** (`group_flag_frame`,
  groups/edges from the saved `v5_group_bands.json` rule), consensus = ≥ 3 votes, ranking =
  v5's within-group percentile max (so external AUC equals v5's by construction).
  `build_group_labels` accepts saved `edges` (`edges_source` recorded); `fit_ensemble` takes
  `group_flags`; `evaluate_c6_bias_audit(artefact=...)` reads a per-variant audit.
  New blocks for v6: `group_vote_stats` (consensus load per group vs corpus), `b4_directaward`,
  `auc_by_cost_band`; post-loop `signal_loss_vs_v0` + `results/methodology/v6_signal_loss.json`.
- `scripts/18_bias_audit.py --variant v6_group_flags`: the section-E audit re-run on v6's own
  votes — separate artefacts `bias_audit_v6.json` / `_v6` tables / figure / `reports/bias_audit_v6.md`
  (self-describing header, votes source); **the production v0 audit is never overwritten**.
- `scripts/27_delta_cluster_boot.py`: passes `group_flags` for v6.

### Measured result

κ 0.2497 → **0.2991** (threshold 0.40 still unmet); consensus 3,031 → 2,965 (−2.2%), high+
7,662 → 6,969; **C3 passes for the first time among all versions** (yearly consensus-share
ratio 0.159 → **0.537** ≥ 0.25); top-200 seed Jaccard 0.656 (= v5), cv 3.54%, PSI 0.148.
Bias audit on v6's own votes (79 groups): violations 24 → 29, warnings 8 → 12 — **41
unexplained deviations vs v0's 32** (10 groups fixed, 19 broken: industry ×6, supplier size
×4, supplier region ×3 … — size/procedure-type bias is moved, not removed). The author's
size metrics improve markedly: ≥ 50 m contracts' share of high+ **50.9% → 14.6%**, disparity
10.48× → **3.23×** (target [0.8, 1.25] not reached), all other cost bands now допустимо;
**B4 fixed**: direct-award disparity 0.21 → **1.13** (in band; 18.3% → 54.5% of high+ vs 51.5%
of corpus), all five procedure types допустимо. Cost of the fix: **50.8% of v0-critical
procedures leave the band** (707 of 1,539 lost with 2 votes), ≥ 50 m criticals 74 → 22, and
7 of the 10 largest lost contracts (178–996 m, all in band b3) get **zero** v6 votes — the
within-group rule is blind to a whole-group anomaly, as the author predicted; C5 fails in
both splits for the first time among versions (holdout +1.1% over "flag nothing"). Control
AUC (ranking = v5's): Δ tuning +0.023, procedure CI [−0.002, +0.048], supplier-cluster CI
[−0.123, +0.090] — crosses zero; holdout 0.4248 [0.396, 0.452] — CI excludes 0.5. Stratified
AUC by cost band: 0.69/0.70 in the cheapest band only (19 positives — power caveat), 0.36–0.46
elsewhere. Stop criteria **4/8** (C2-topN, C2-cv, **C3**, C7). Verdict: **compromised, not
adopted** — first size-audit improvement in three cycles, thresholds unmet (C6 41, C1 κ 0.299,
≥ 50 m 3.23×) plus a C5 regression; **cycle 7 not started without the author's decision**.
Contract matrix (`scripts/23 --soft`): 9 met / 16 unmet / 2 not verifiable — unchanged.
Closing status **1 of 4** — condition (2) fails for every version (tuning CI entirely below
0.5 in v0–v6, holdout additionally in v5/v6). All headline numbers reproduce
(`scripts/19`), pytest **158 tests**, annotation ≤ 250 words (protocol v0–v6).

## [MTA-0007-2026-10-18] — Iteration cycle 5 (v5_group_percentile): within-group percentile ranking, measured

Author-requested cycle 5 (main cycle; budget 5 of 10). **Production behaviour unchanged**
(v0 remains the shipped configuration; replacing it is the author's explicit decision).
Thresholds are now **author-approved** (κ ≥ 0.40; Spearman LIME/SHAP ≥ 0.70 / 0.40;
C7 recall@3 ≥ 0.60 ∧ hallucinations = 0) — the "proposed by the agent, approval pending"
wording in scripts 20/22/24/26 and the current-state docs was updated accordingly.

### Added

- `scripts/20_cycle_framework.py`: variant `v5_group_percentile` — each detector's score is
  ranked **inside its group «cost band × procedure type»** and the ranking is the max over
  those within-group percentiles; votes/consensus stay exactly v0's rules (one change per
  cycle). New helpers `build_group_labels` (band edges = corpus quantiles of
  `log_award_value` — 4 final bands after an edge collision at zero values; groups under
  100 rows merge into the nearest band of the same type, with a recorded fallback path;
  24 final groups, 14 fallback merges, min group 168) and `group_percentile_max`; group
  metadata written to `results/methodology/v5_group_bands.json`.
- Every variant now carries a `size_composition` block (money-band shares of the top-200
  list and of the audit's high+ band) — the explicit check that a within-band normalisation
  MOVES size rather than removing it.
- `scripts/27_delta_cluster_boot.py` generalised to any variant pair
  (`--variant/--baseline/--out`); defaults reproduce the cycle-4 v4b measurement.
- `tests/test_cycle_protocol.py`: +4 tests (deterministic band boundaries, exact 1/n..n/n
  within-group percentiles, the small-group merge counters, the v5 artefact block) —
  **154 tests total**.

### Measured result

v5 vs v0: consensus **identical** (3,031; κ 0.2497 — votes untouched, by construction).
Stability improves: top-200 seed Jaccard 0.479 → **0.656** (C2 ≥ 0.60 passes — as it did
for v2, whose top-200 Jaccard was 0.671), consensus-count cv 4.76% → **2.98%**, PSI 0.293 → **0.148** (KS 0.207 → 0.107).
Size dominance of the tuning top-200 falls: ≥ 50 m contracts 10.9× → **2.9×** the corpus
share, ≥ 5 m 3.3× → **0.6×** (an overshoot into under-representation) — size is MOVED, not
removed, and the votes-based audit bands do not move at all (C6 stays 24/8, C3 stays
0.159). AUC (control, not an acceptance criterion): tuning 0.407 → 0.431, Δ +0.023 —
procedure bootstrap [−0.002, +0.048], supplier-cluster bootstrap [−0.123, +0.090]
(`scripts/27`, 1,000 replicates, 2,717 clusters) — crosses zero, no significance claim;
holdout **0.518 → 0.425**, holdout CI [0.396, 0.452] excludes 0.5 — v5 significantly
ranks AAP labels as LESS risky (corrected per MTA-0008: a stably negative association
does NOT count toward completion condition 2; and C2-topN/C2-cv passing is not "for the
first time" — v2 passed them too, with top-200 Jaccard 0.671). Stop criteria **4/8**. Contract
matrix (`scripts/23 --soft`): 9 met / 16 unmet / 2 not verifiable — unchanged. Closing
status stays **1 of 4** (computed from the artefacts by `scripts/22`; the holdout-CI chain
is now also broken at v4b–v5). Verdict: **compromised, not adopted** — the expected
size-vs-cohesion trade-off is confirmed, external validation did not improve. All headline
numbers reproduce (`scripts/19`: v0–v3 anchors byte-identical; v5 is an extra row).

### Changed

- Threshold wording: "proposed by the agent, author approval pending" → "approved by the
  author (MTA-0007)" in `scripts/20`, `scripts/22`, `scripts/24`, `scripts/26`,
  `docs/contract_matrix.md` (M10, M16), `docs/thesis_text.md`, `docs/METHODOLOGY_CYCLE.md`.
- `scripts/22_cycle_dynamics.py`: v5 verdict; protocol line now reads "cycle 4 — additional
  author measurement (v4/v4b); cycle 5 — main cycle per the author's task (MTA-0007);
  5 of 10 spent".
- `docs/model_card.md`, `docs/thesis_text.md`, `docs/METHODOLOGY_CYCLE.md`,
  `docs/annotation.md` (protocol v0–v5, 154 tests), `cycle_log.md` (cycle-5 entry),
  `reports/cycle_5.md` (new cycle report).

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
  byte-identical duplicate column dropped as in v1 — measured through two
  variants: `v4_datafix` (fixes + duplicate drop) and
  `v4b_datafix_keep_duplicate` (the same fixes with the duplicate kept), so the
  data-fix effect and the duplicate-drop effect are separable.
- `reports/cycle_4.md`, cycle-4 entry in `cycle_log.md`; `tests/test_cycle_protocol.py`
  extended (variant set now v0–v4, functional `apply_datafix` test) — **150 tests total**.
- `scripts/27_delta_cluster_boot.py`: paired ΔAUC bootstrap of v4b vs v0 on tuning in
  BOTH resampling flavours — procedure-level and supplier-cluster (the AAP label is
  supplier-level, so the cluster interval is the honest one): 1,000 replicates, 2,717
  supplier clusters; procedure [−0.0046, −0.0006], cluster [−0.0097, +0.0015] — the
  cluster CI crosses zero, which is why the data-fix effect is reported without a
  significance claim.

### Measured result

v4 vs v0: tuning ΔAUC **+0.0022 [−0.0058, +0.0105]** — within the CI; consensus
3,031 → **2,381** (≈ v1); mean pairwise κ 0.250 → **0.217**; PSI 0.29 → 0.38;
stop criteria **3/8** (unchanged). Variant `v4b_datafix_keep_duplicate` (the same
fixes with the duplicate KEPT) separates the effects: consensus 3,034 ≈ v0 and
κ 0.248 ≈ v0 — the v4 consensus/κ changes are the duplicate drop's, not the id
normalisation's; and the fixes alone shift tuning AUC by ≈ **−0.002**
(`scripts/27_delta_cluster_boot.py`, 1,000 replicates: procedure bootstrap
[−0.0046, −0.0006]; supplier-cluster bootstrap [−0.0097, +0.0015] — crosses
zero, so no significance claim) (v4b vs v0). Conclusion: data defects are
fixed and were **not** the cause of the contract-matrix failure — external metrics
did not change beyond the interval in v4, while the isolated v4b measurement
shows a slight non-significant (cluster-level) degradation from the cleanup
itself. Contract matrix after the
run (`scripts/23`): 9 met / 16 unmet / 2 not verifiable — unchanged. All headline
numbers reproduce (`scripts/19`: v0–v3 anchors byte-identical; v4/v4b are extra
rows). Cycle-4 completion criterion after this cycle: 1 of 4 (conservative reading —
holdout CIs of the last two versions v3 and v4 no longer overlap; for the
data-hygiene variants v4/v4b the literal reading is inappropriate, both overlap
v0).

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
- `scripts/22_cycle_dynamics.py`: the polishing-close status is now COMPUTED from
  `cycle_framework.json` (max κ vs the agent-proposed 0.40 threshold, sign flips of the
  external AUC between splits, holdout-CI overlap chain of consecutive versions) instead
  of hardcoded prose — renders «1 из 4» with the data behind it; the PSI attribution in
  cycle 4 corrected (growth follows the duplicate drop, v1: 0.32 — the caps are present
  in v4b too, where PSI is 0.29; exact decomposition not performed).
- `docs/annotation.md` trimmed to **250 words** with the author's wording fixes
  («измеряют прежде всего размер», the extractive-design clause after the
  zero-hallucination figure, and «the fixes alone leave κ and consensus unchanged»
  in item 5); the «band × type percentiles» future item cut for space.

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
