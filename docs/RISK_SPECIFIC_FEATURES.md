# Risk-specific detection — experimental modules A–D and the direct-award track

Phase 4 of `docs/IMPROVEMENT_PLAN.md`, 2026-10-20. Production v0 is untouched:
this phase *adds* hypothesis-specific indicator lenses over the real corpus; it
does not retrain, rethreshold or replace the ensemble, and it changes no votes,
bands or scores. An anomaly is an indicator of potential risk, never evidence
of wrongdoing.

## 1. Problem — what was found and why it matters

* **v0 measures general statistical unusualness.** The ensemble (MAD-z,
  Isolation Forest, LOF, OCSVM) answers "is this row unusual relative to
  peers", not "does this row match a known procurement-risk hypothesis".
  Splitting, buyer–supplier persistence and comparable-value questions were
  simply not measurable.
* **Direct procurement is poorly represented among high-risk alerts.**
  `directaward` is 78 550 of 152 378 procedures (51.5 %), yet v0 critical
  flags (`n_models_flagging >= 3`) concentrate elsewhere and the *reasons*
  were unmeasured — so an independent track for this population was needed.
* **Risk signals were not population-scoped.** A single bidder in a direct
  award is the legal form; a single bidder in an open tender is a review
  signal. Without explicit populations any "risk score" would mix the two and
  penalise the wrong legal form.

## 2. What was changed (design)

### 2.1 Modules (`src/mtender/risk_modules.py`)

| Module | Population | Indicators | Hit rule | Point-in-time status |
|---|---|---|---|---|
| **A. Competition** | `opentender`, `licitație_deschisă`, `restrictedtender`, `testminicompetition`; `NaN` = not applicable elsewhere | `comp_single_bidder` (n = 1), `comp_no_bid_data` (n = 0), `comp_short_window` (window < 7 d), `buyer_prior_single_share` (share of the buyer's *strictly prior* 365-day procedures with at most one known bidder) | short window, or single-bidder / no-bid-data inside a competition-expecting procedure type | prior-only part valid at bid close; no future procedure is ever read |
| **B. Splitting** | rows with buyer + CPV2 + event date | `split_cluster_member/n`, `split_cluster_value_mdl`, `split_same_supplier_share`, `split_min_gap_days`, `split_small_value_share` over same buyer + same CPV2 ± 90 days | cluster member **and** same-supplier share ≥ 0.5 | **retrospective (as-of-now)**: the ±90-day cluster needs the repeat contracts to exist — monitoring, not publication-time scoring; declared, not hidden |
| **C. Network** | rows with buyer + winner + date | `pair/buyer/supplier_prior_awards`, `supplier_prior_buyers`, `pair_buyer_share`, `supplier_dep_share`, `pair_prior_365d` | `pair_prior_awards ≥ 1` **and** `pair_buyer_share ≥ 0.5` | **strictly prior-only**: only awards dated *before* the evaluated event; same-day events are committed as one batch and never see each other; frame order is irrelevant |
| **D. Value distribution** | rows with price + CPV2 + procedure type, ≥ 20 priced rows in the group | `val_robust_z` (median/MAD on log-value), `val_pctile`, `val_group_n` | `|z| ≥ 3` | cross-sectional at award time; **value-distribution anomaly, not overpricing** — quantities, specifications and unit prices are absent |

Windows and rules are statistical constants with stated rationale (90 days for
splitting, 365 days for repeat patterns, `|z| ≥ 3` tail, minimum group size 20
for MAD stability) — **not legal ones**.

**Threshold-based legal interpretation is disabled**
(`threshold_interpretation.enabled = false` in every output): no authoritative,
date-versioned procurement-threshold history for Moldova exists in the corpus
(same blocker class as the MoF cross-check, `compared: 0`). Module B is
therefore threshold-independent by construction and carries no legal verdict.

**Hit semantics**: `NaN` = inputs unknown (not a hit *and* not a clearance),
`0` = known and not triggered, `1` = triggered. `n_module_hits` sums *known*
hits only; `n_module_known` records how many modules were determinable, so
"0 of 3 known" is distinguishable from "0 of 3 triggered". Direct-award rows
carry `module_a_hit = NaN` by design (module A does not apply to them).

**Forward outcomes** (`future_repeat_same_winner_365d`,
`future_same_buyer_cpv2_90d`) are computed but labelled *evaluation-only*
(`OUTCOME_NOTE` travels inside the JSON): they deliberately look FORWARD to
test whether module-selected cases show reviewable follow-up patterns — they
are never features, never model inputs, and same-day events never confirm each
other.

### 2.2 Pipeline (`scripts/34_risk_modules.py`)

* reads `data/features/features.csv` (read-only) and joins
  `results/tables/tender_anomaly_scores.csv` read-only as a *v0 reference
  baseline* (existing rule `n_models_flagging ≥ 3`, unchanged);
* reports per-population rates **as measured** — no group normalisation and no
  equal-rate target: measured selection shares differ (24.0 %–61.9 %) and are
  published exactly as they fall out; equal representation is not evidence of
  model quality;
* **direct-award track**: selected = ≥ 1 determined hit among modules B/C/D
  (module A is undefined there); matched **1:1 controls**, strata = event year
  × contract-value quartile (quartiles computed inside the direct population,
  rank-based, seed 42, without replacement, controls disjoint from selected);
  outcome rates compared with a **buyer-cluster bootstrap** (1 000 replicates;
  point estimate and CI are computed over the same cluster-eligible rows);
* artefacts (gitignored, reproducible): `results/methodology/risk_modules.json`
  (rulebook metadata + limitations travel with the numbers),
  `results/tables/risk_module_indicators.csv` (152 378 × 43),
  `results/tables/risk_module_cases.csv` (top 200 for the Phase-5 export).

### 2.3 Integration with the temporal audit (Phase 3)

`event_date` reuses the audit's fallback chain (award → tender start →
publication): corpus provenance `award_date` 128 130 / fallback-only 24 248 /
missing 0 (the fallback is a documented approximation, recorded in the JSON).
Module C's prior-only construction directly satisfies
`docs/TEMPORAL_LEAKAGE_AUDIT.md`'s rule *"historical aggregates are calculated
using only information available before the evaluated event"*; module B's
retrospection is declared explicitly instead of being presented as
point-in-time.

## 3. How it was tested

`tests/test_risk_modules.py` — **24 tests**, synthetic frames only (no real
data, no training, no network):

* *network prior-only*: same-day backfill impossible; frame-order independence;
  adding a later award never moves earlier rows; 365-day window edges;
  missing winner → all `NaN` including the hit; non-positional index rejected;
* *splitting*: ±90-day membership edges (104 days excluded, 73 days included);
  cluster sizes / value sums / minimum gaps; buyer-own-quartile small-value
  share; known "no cluster" = `0` while unknown inputs stay `NaN`; cluster
  with unknown supplier → hit undetermined (`NaN`), not `0`;
* *competition*: prior share counts strictly earlier procedures with *known*
  bidder counts (unknown bidder count never counts as zero bidders);
  population masking (a direct row with no bids and a short window yields
  module A = `NaN`, not a hit);
* *value distribution*: minimum group size honoured on **priced** rows only;
  constant group (MAD = 0) → undefined; missing price → `NaN`;
* *forward outcomes*: strictly-later windowing, same-day twin excluded,
  missing winner → `NaN` while the CPV follow-up stays determined;
* *composition/metadata*: `n_module_hits` vs `n_module_known`; foreign-index
  restoration; threshold interpretation disabled; disclaimer, collusion and
  overpricing notes present in the machine-readable rulebook;
* ***scripts/34 end-to-end smoke***: 16-row synthetic corpus → exit 0,
  direct track 3 selected ↔ 3 matched controls, 0 dropped; absent v0 scores →
  verdict `insufficient_data` with `null` rates (never fabricated);
  guardrails present in the JSON; a second run with the same seed produces
  **byte-identical** indicator and case tables.

Executed (all green):

```bash
.venv/bin/python -m pytest tests/test_risk_modules.py -q   # 24 passed
.venv/bin/python -m pytest -q                              # 277 passed
.venv/bin/python scripts/34_risk_modules.py                # artefacts written, exit 0
```

## 4. Results on the real corpus (as measured; seed 42, 1 000 bootstrap reps)

### 4.1 Indicator hit rates per population (rate among known inputs)

| population | n rows | years | A | B | C | D | selected share |
|---|---|---|---|---|---|---|---|
| direct | 78 550 | 2022–2024 | n/a (by design) | 0.3079 | 0.0104 | 0.0072 | 0.3042 (21 500 / 70 676 eligible) |
| microvalue | 24 214 | 2017–2024 | n/a | 0.2786 | 0.0044 | 0.0100 | 0.2397 |
| smallvalue | 28 414 | 2018–2024 | n/a | 0.3151 | 0.0227 | 0.0278 | 0.2773 |
| open tender | 21 090 | 2016–2024 | 0.5162 | 0.2414 | 0.0151 | 0.0263 | 0.6185 |
| other | 110 | 2019–2024 | n/a | 0.0000 | 0.0000 | n/a | 0.0000 |

Rates are deliberately **not** equalised. Populations differ in era and form —
notably the `directaward` label exists only from 2022 (99.997 % of direct rows
are 2023–2024); this corpus property is recorded in the JSON `limitations`
rather than smoothed away.

### 4.2 Direct-award track: module-selected vs matched controls

Matching: 21 500 selected ↔ 21 500 controls, 8 strata (2023–2024 × 4 value
quartiles; 2022 holds only 2 direct rows), pool 48 696, 0 selected dropped
(missing stratum or exhausted pool), controls disjoint from selected.
Outcomes are rates over rows with a known outcome *and* a known buyer
(1 142 cluster buyers, 1 000/1 000 valid bootstrap replicates):

| outcome | selected | control | difference | 95 % CI (buyer-cluster bootstrap) | verdict |
|---|---|---|---|---|---|
| `future_repeat_same_winner_365d` | 0.6516 | 0.4117 | **+0.2400** | [0.2190, 0.2612] | CI excludes 0 |
| `future_same_buyer_cpv2_90d` | 0.7221 | 0.7636 | **−0.0415** | [−0.0585, −0.0243] | CI excludes 0 |
| `v0_critical` (read-only baseline) | 0.0136 | 0.0014 | +0.0122 | [0.0073, 0.0181] | CI excludes 0 |

Frequency context (medians): prior-365-day procedures per buyer 53 (selected)
vs 70 (control); share of the buyer's prior procedures with at most one known
bidder 0.982 vs 0.967 (direct population mean 0.917). In a direct-dominated
history "at most one known bidder" is nearly always true, so this feature
carries little discrimination there and is reported as context only.

Honest reading — **none of these outcomes is evidence of wrongdoing**:

* **Repeat-same-winner +0.24 (≈1.58× relative)**: module-selected direct
  procedures are markedly more likely to be followed by another award to the
  same buyer–winner pair within a year. This is a *persistence* pattern and is
  partly mechanical — module C selects on past repetition, and past repetition
  predicts future repetition. It confirms the indicators surface exactly the
  stable buyer–supplier patterns they were built to find (meaningful and
  reviewable), but it is **not** independent validation and says nothing about
  collusion.
* **CPV2-90-day follow-up −0.0415 (CI excludes 0)**: selected cases are
  slightly *less* likely to receive another same-CPV2 award within 90 days
  than matched controls. Plausible reading: selection fires on buyers whose
  burst of same-category purchases already sits inside the ±90-day window,
  after which activity pauses, while controls include buyers on a steadier
  cadence. The direction was not anticipated; it is reported as measured and
  remains unexplained (§6).
* **v0-critical +0.0122 (≈9.4× relative, 1.36 % absolute)**: module-selected
  cases are far more likely to also be v0-critical than matched controls, yet
  the absolute rate stays ≈1.4 % — v0's under-alerting on direct procurement
  persists even for cases flagged by independent hypotheses. The experimental
  track covers a blind spot that the ensemble does not.

### 4.3 Case export (input for the Phase-5 blinded review)

Top-200 by hit count: 115 direct / 83 open tender / 2 smallvalue; module hits
A = 82, B = 196, C = 163, D = 68 (each case carries 2–3 module hits); 35 are
also v0-critical — i.e. the experimental ranking overlaps the ensemble only
partially, as intended. Together with v0-selected cases and the matched
controls this file forms the three blinded evaluation groups of
`docs/EXPERT_REVIEW_PROTOCOL.md` (Phase 5).

## 5. What improved

* Three previously unmeasurable hypotheses — splitting, buyer–supplier network
  persistence, value-distribution tails — are now computed over all 152 378
  real procedures, population-scoped, with a machine-readable rulebook
  (metadata) travelling inside every artefact.
* Direct procurement has an independent evaluation track with matched random
  controls and buyer-cluster bootstrap CIs; its relationship with v0 is now
  quantified (≈9.4× relative overlap, 1.36 % absolute).
* Unknown-vs-zero semantics are enforced in code *and* tests: missing data can
  neither trigger nor clear an indicator, and "0 of 3 known" is distinguishable
  from "0 of 3 triggered".
* The pipeline is seeded and reproducible (byte-identical tables across runs),
  and the smoke test proves the missing-scores branch reports insufficiency
  instead of inventing numbers.

## 6. Unresolved / blockers

* **Legal thresholds**: no authoritative date-versioned threshold history in
  the corpus → threshold-based legal interpretation stays disabled (blocker
  class shared with HG 957/2017, HG 1420/2016, ANSC decisions, Metodologia AAP
  — all awaiting files from the author).
* **Negative CPV2-90-day difference** (§4.2): direction unexpected, causes
  hypothesised but not established.
* **Precision of the high selection shares** (24–30 % in direct/micro/small,
  62 % in open tender) is unknown: hits are candidate indicators, not an
  alerting threshold. Reviewable-case precision requires the blinded expert
  review of Phase 5; no qualified reviewers are available yet, so the interface
  and export exist while the scientific results stay pending.
* **Cross-population rate comparisons span different eras** (direct 2022–2024
  vs open tender 2016–2024); only within-population and year-matched figures
  are quoted. Recorded in JSON `limitations`.
* `buyer_prior_single_share` is defined as "at most one known bidder" and
  therefore lumps 0-bidder and 1-bidder procedures; the module A hit rule keeps
  them separate, the descriptive feature does not.
* MoF cross-check remains `compared: 0`; steps requiring the live MTender API
  are unchanged from `docs/IMPROVEMENT_PLAN.md`.

## 7. Reproduction

```bash
.venv/bin/python scripts/34_risk_modules.py            # seed 42, 1000 reps, top 200
.venv/bin/python -m pytest tests/test_risk_modules.py -q  # 24 passed
# artefacts (results/ is gitignored, regenerated by the command above):
#   results/methodology/risk_modules.json
#   results/tables/risk_module_indicators.csv
#   results/tables/risk_module_cases.csv
```

**Disclaimer.** Everything above is an indicator of *potential* risk requiring
independent review by a competent authority. An anomaly is not corruption;
repeated relationships do not prove collusion; a value-distribution tail is not
a verified overpricing finding. Synthetic frames appear only in tests and are
never presented as real data.
