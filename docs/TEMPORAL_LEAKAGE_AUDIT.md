# Temporal Leakage Audit — feature availability by scoring stage

**Repository:** `feature/risk-specific-detection` (branched from `f114452`)
**Date:** 2026-10-20
**Scope:** the 22 production features of model **v0** (`src/mtender/features.py`),
their inputs, the procurement event after which each becomes observable, and
whether the computation as implemented contains information from *after* the
event being scored.

> Anomaly scores are indicators of potential risk, not evidence of corruption
> or violation. Verification by a competent authority is required.

This audit **changes no model**: production v0 stays untouched, no v7 is
created, bands/weights/thresholds are not modified, the v0–v6 budget stays
6 of 10. It is a measurement with automated guards
(`tests/test_temporal_leakage.py`, `scripts/33_temporal_leakage_audit.py`).

---

## 1. Scoring moments analysed

| Stage | Event | What the stage means here |
|---|---|---|
| `publication` | tender notice published | earliest moment an early-warning system could score |
| `bid_submission` | bids become visible at close | competition features become observable |
| `award_decision` | award published (winner, values, lots) | financial/relationship features become observable |
| `post_award` | terminal state (cancellation, final amendments, no-award outcome) | **retrospective as-of-now scoring of the finished corpus — what production v0 does** |

**Never inputs (labels only):** AAP sanctions, ANSC complaints/decisions, court
outcomes, and synthetic `planted_pattern` / `is_planted_anomaly`. They may only
be used for evaluation after the fact; the test
`test_labels_are_never_features` fails the build if any of these names ever
appears among model inputs.

## 2. Availability matrix (all 22 features)

Grouped as in `docs/model_card.md`. "Future info" = the value requires events
after tender publication. "Point-in-time safe" = the computation as implemented
does not use corpus events after the evaluated row (row-local inputs and, where
a reference distribution is needed, a reference computed over the full corpus
window breaks this).

### Financial

| Feature | Inputs | Calculation (source: `features.py`) | Earliest availability | Future info | Point-in-time safe |
|---|---|---|---|---|---|
| `log_award_value` | `award_value` | `log1p(award_value)` | award decision | yes | yes |
| `value_vs_cpv_median` | award, CPV + **all corpus awards** | award / median(award \| CPV), clip [0,20], missing → 1.0 | award decision | yes | **no** — CPV median spans the whole corpus window |
| `value_zscore_cpv` | award, CPV + **award distribution** | (award − median)/std per CPV, clip [−10,10], missing → 0.0 | award decision | yes | **no** — same corpus-window reference |
| `estimate_to_award_ratio` | `estimated_value`, `award_total` | est / award_total, clip [0,20], missing → 1.0 | award decision (numerator known at publication) | yes | yes |
| `log_award_total` | `award_total` (`award_value` fallback) | `log1p(sum over lots)` | award decision | yes | yes |
| `multi_award_tender` | `n_awards_with_value` | `int(n_awards > 1)` | award decision | yes | yes |

### Competition

| Feature | Inputs | Calculation | Earliest availability | Future info | Point-in-time safe |
|---|---|---|---|---|---|
| `n_bidders_log` | `n_bidders` (bids.details) | `log1p(n_bidders)` | bid close | yes | yes |
| `single_bidder` | `n_bidders` | `int(n_bidders == 1)` | bid close | yes | yes |
| `no_bid_data` | `n_bidders` | `int(n_bidders == 0)` — marks *unpublished* bid data, not proven absence of bids | bid close | yes | yes |
| `multi_supplier_award` | `n_suppliers` (award parties) | `int(n_suppliers > 1)` | award decision | yes | yes |

### Procedural

| Feature | Inputs | Calculation | Earliest availability | Future info | Point-in-time safe |
|---|---|---|---|---|---|
| `bid_window_days` | `tender_start`, `tender_end` | days between, clip [0,3650]; **missing → 30** (documented fill, not a measurement) | publication | no | yes |
| `short_deadline` | same | `int(0 ≤ window < 7)` | publication | no | yes |
| `long_deadline` | same | `int(window > 90)` | publication | no | yes |
| `accelerated_like` | `procurement_method_details` | regex `accelerated\|urgent\|exception` (name-based proxy, not a legal classification) | publication | no | yes |
| `n_amendments` | `n_amendments` | count of published amendments | first amendment; final value only at terminal state (amendments can continue past the award, and OCDS amendment lists may touch award/contract entries) | yes | yes |
| `amended` | `n_amendments` | `int(n_amendments > 0)` — flips 0→1 after publication | same | yes | yes |
| `cancelled` | `status` | `int(status ∈ {cancelled, unsuccessful})` | terminal status only | yes | yes |
| `no_award_after_tender` | `status`, `award_value` | `int(status == complete ∧ award missing)` | terminal status only | yes | yes |

### Behavioural (cross-tender statistics)

| Feature | Inputs | Calculation | Earliest availability | Future info | Point-in-time safe |
|---|---|---|---|---|---|
| `buyer_supplier_repeat_share` | buyer, winner, **all awards** | pair awards / buyer awards | award decision | yes | **no** — full-window counts |
| `winner_share_of_buyer_awards` | idem | same pair/buyer share (mirrors the previous column by construction) | award decision | yes | **no** |
| `supplier_win_concentration` | winner, **all awards** | supplier count / corpus total, clip [0,1] | award decision | yes | **no** — corpus-wide denominator |
| `supplier_award_count_log` | winner, **all awards** | `log1p(supplier award count)` over the window | award decision | yes | **no** — includes later wins |

## 3. Stage feature sets (machine-readable: `src/mtender/stage_features.py`)

| Stage | Features whose inputs exist | Strict point-in-time subset |
|---|---|---|
| `publication` | **4** — `bid_window_days`, `short_deadline`, `long_deadline`, `accelerated_like` | 4 |
| `bid_submission` | **7** — + `n_bidders_log`, `single_bidder`, `no_bid_data` | 7 |
| `award_decision` | **18** — + 6 financial, `multi_supplier_award`, 4 behavioural | **12** (drops the 6 corpus-reference features) |
| `post_award` | **22** (all — production v0) | 22 |

API: `stage_columns(stage, strict=False)` / `strict_stage_columns(stage)`.
Unknown stage names raise `ValueError` (typos cannot silently return `[]`).
The sets are monotone (4 ⊂ 7 ⊂ 18 ⊂ 22 and 4 ⊂ 7 ⊂ 12 ⊂ 22) — pinned by test.

**Strict equals plain at `post_award` by design:** retrospective as-of-now
scoring observes the corpus by definition. That is the regime production v0
operates in, and it is legitimate *for retrospective monitoring* — it is not a
publication-stage early-warning model.

## 4. Findings

1. **Only 4 of 22 features exist at publication; 7 at bid close.** Any claim of
   "risk scoring at publication" with the current v0 feature set would be
   impossible: 18 of 22 inputs do not exist yet.
2. **Six features are not point-in-time safe as implemented**
   (`value_vs_cpv_median`, `value_zscore_cpv`, and the four behavioural). They
   reference corpus-wide statistics computed over the *whole* 2016–2025 window,
   so for a historical event the value can absorb later awards/relationships.
   For as-of-now scoring (v0's actual mode) this is valid; for point-in-time
   scoring they must be recomputed against a trailing window only.
3. **The ten post-decision features of MTA-0013** (`multi_award_tender`,
   `amended`, `n_amendments`, `cancelled`, `no_award_after_tender`,
   `log_award_value`, `log_award_total`, `estimate_to_award_ratio`,
   `value_vs_cpv_median`, `value_zscore_cpv`) are classified in this matrix at
   `award_decision`/`post_award` — none is available before the award. MTA-0013
   quantified their effect on the ANSC proxy label: v0 AUC **0.5112**
   [0.489; 0.557] (cluster by buyer) → refit without the ten: **0.4646**
   [0.417; 0.561], with `determined_by_leakage: false` — i.e. removing them did
   not help (both intervals include 0.5). Recorded as a diagnostic, not a cycle;
   the refit changed no production artefacts.
4. **Production v0 is a retrospective monitor, not an early-warning model.**
   Its 22 features assume the procedure is finished. A stage-aware system
   (4-feature publication scoring, 7-feature bid-close scoring) would be a
   *different model* and requires the author's explicit approval — it is not
   implemented here, no v7 exists, and no retraining was performed.
5. **Labels never enter features** — enforced programmatically
   (`LABEL_ONLY_FIELDS` ∩ `FEATURE_COLUMNS` = ∅), cross-checked by
   `scripts/33` (check `labels_never_features: match`). External labels
   postdate the procedures by construction and are used only for evaluation,
   which is the correct side of the temporal line.
6. **Observed quirk (not changed):** `winner_share_of_buyer_awards` and
   `buyer_supplier_repeat_share` are computed as the same pair/buyer share in
   `add_behavioural_features`, i.e. the two columns are numerically identical
   in the pandas path (`scripts/05_aggregations.py` cross-checks the same
   quantities via MongoDB). Recorded for a future task; changing features is
   outside this audit's mandate.
7. **Documented fills are not measurements:** missing windows default to 30
   days, missing ratios to 1.0/0.0 — visible in the matrix notes so downstream
   interpretation does not mistake fills for observed values.

## 5. Stage-aware feature generation (implemented as an API, not wired to production)

```python
from src.mtender.stage_features import stage_columns, strict_stage_columns

pub  = stage_columns("publication")          # 4 features, inputs-only rule
bid  = stage_columns("bid_submission")       # 7
aw   = strict_stage_columns("award_decision")  # 12 point-in-time-safe
full = stage_columns("post_award")           # 22 = production set
```

Intended future use (requires author approval): a publication-stage baseline
fit on `stage_columns("publication")` evaluated on the same fixed protocol.
**Not executed here** — that would be a new model version (v7 territory) and
consuming budget requires a decision.

## 6. Automated leakage guards (executed)

`tests/test_temporal_leakage.py` — 13 tests, all green in the full suite run:

| Test | Guarantee |
|---|---|
| `test_matrix_covers_exactly_the_production_features` | matrix = exactly the 22 columns v0 runs |
| `test_every_availability_record_is_complete` | every record complete; `future_event_info` ⇔ stage ≠ publication |
| `test_stage_sets_are_monotone_and_complete` | 4 ⊂ 7 ⊂ 18 ⊂ 22 (plain and strict); final stage = full set |
| `test_unknown_stage_raises` | stage typos fail loudly |
| `test_publication_stage_is_exactly_the_four_pre_award_inputs` | publication/bid sets pinned |
| `test_mta0013_leak_suspects_unavailable_before_award` | the 10 suspects are unavailable at publication/bid close |
| `test_corpus_reference_features_excluded_from_point_in_time_sets` | the 6 corpus-reference features never appear in strict pre-production sets |
| `test_labels_are_never_features` | AAP/ANSC/synthetic labels never model inputs |
| `test_feature_matrix_is_json_serialisable_and_documented` | export contract + disclaimer present |
| `test_stage_sets_match_detection_summary_when_artefact_present` | matrix equals what production actually ran (skip if artefact absent) |
| `test_publication_features_invariant_to_all_later_events` | **functional:** perturbing award/bids/status/amendments does not move publication-stage features (with a non-vacuous counter-check) |
| `test_bid_stage_features_invariant_to_award_and_terminal_state` | **functional:** bid-close features unaffected by later award/terminal events |
| `test_award_stage_features_invariant_to_terminal_state_only` | **functional:** award-stage features unaffected by terminal state/amendments |

Reproducible export:

```bash
.venv/bin/python scripts/33_temporal_leakage_audit.py
# -> results/methodology/temporal_feature_matrix.json
# cross-checks: detection_summary=match, features_csv=match, labels_never_features=match
```

## 7. What this audit does *not* establish

* It does not say any procedure is suspicious. Feature timing ≠ guilt.
* It does not quantify how much score quality would change under stage-aware
  scoring — no such model was trained (needs approval, budget, protocol).
* Contract-signing timestamps and per-amendment dates are not used as inputs
  today; if a future stage model needs them, their availability must be
  re-audited against `docs/DATA_DICTIONARY.md`.
* The `post_award` stage inherits every limitation of retrospective scoring
  (drift between 2018–2021 tune and 2022–2024 test: PSI up to 0.41 — see
  `/api/evaluation` and `results/methodology/threshold_calibration.json`).

## 8. Unresolved / blockers

* Full point-in-time reimplementation of the 6 corpus-reference features
  (trailing-window CPV medians, prior-only behavioural counts) — **planned in
  Phase 4** of the improvement plan as threshold-independent network/price
  indicators with prior-only aggregates; the v0 features themselves stay as is.
* ANSC decisions (confirmed vs rejected complaints) remain inaccessible; the
  complaint label cannot be temporally ordered against complaints' own
  resolution — documented in `CORPUS_GAPS`.
