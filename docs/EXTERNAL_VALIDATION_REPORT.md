# External Validation Report (Phase 5)

Date: 2026-10-20 · Measurement only (no retraining) · v0 production untouched

This report evaluates the production anomaly score and the Phase 4
risk-specific indicators against **external labels**: a supplier-level
regulatory sanction record and a buyer-side complaint record. It also defines
the framework (registry, baselines, bootstrap, temporal guard, robustness
checks) that makes any future external label testable. Code:
`scripts/35_external_validation.py`; tests: `tests/test_external_framework.py`
(9 tests).

---

## 1. The external-label registry — problem and importance

**Problem.** The author's brief lists six external data sources
(interdictions, complaints, Metodologia AAP, MoF cross-check, court decisions,
expert reviews), but nothing binds them into one auditable artefact with a
uniform schema: what each source *is*, when it happened, how it was matched,
its confidence and its limitations. Without this, external validation is
cherry-pickable and unfalsifiable.

**Change.** `scripts/35` writes `results/methodology/external_label_registry.json`
covering all six sources with a fixed schema (`source`, `entity_type`,
`event_date`, `publication_date`, `matching_method`, `confidence`,
`limitations`, `status`, `blocker`/`blockers`, `n_records`, `provenance`, plus
`related_deliverables`). Statuses on the real data:

| Source | Status | Records / blocker |
|---|---|---|
| AAP interdictions (tender.gov.md blacklist) | available | 33/47 suppliers parsed; 633 positive procedures; snapshot 2026-09-25 |
| ANSC complaints | available | 1665 procedures with a `complaints` document |
| ANSC decision documents | **blocked** | decision-type counts empty in the inventory → the label stays «complaint filed», never «guilt» |
| Metodologia AAP | **blocked** | file not provided |
| Court decisions (HG 957/2017, HG 1420/2016 and the 2026 judgments) | **blocked** | judgments not provided |
| MoF OpenData cross-check | empty | 2026-10-09 pipeline compared 0 records (needs the live API) |
| Expert-reviewed cases | **pending** | export ready (Phase 6), reviewers not yet engaged |

Blocked sources are reported as blockers with `n_records = 0`; no value is
ever invented for them.

**Test.** `test_registry_schema_and_blocked_sources` asserts the schema on
every source and that blocked/pending/empty sources carry their blocker text.
The Phase 5 end-to-end test asserts `cross_check_frame_positives_match`
consistency with MTA-0013.

---

## 2. Leakage prevention and cross-checks — importance and change

- **Dates.** AAP event dates are per-entry decision dates (earliest 2024-01-05,
  latest 2025-09-17); ANSC event dates are complaint publication dates. Both
  are recorded in the registry; the eligibility rule requires every score
  input to be computable at or before the event date of its own record.
- **PN-alias fidelity.** The first framework run rebuilt the ANSC label from
  `ansc_candidates.csv` and reproduced **1195** positives where MTA-0013
  reported **1222**. Cause: 36 planning-notice packages carry a `-PN-`-suffixed
  compiled ocid while the corpus indexes the same procedure under the base
  ocid; MTA-0012/0013 register that alias, the naive rebuild did not. The
  framework now applies the identical rule (`pn_ocid_aliases_applied: 36`)
  and the cross-check passes exactly: `positives = 1222`,
  `cross_check_frame_positives_match: true`.
- **Frames.** AAP frame: 117 535 rows / 633 positives (winner present, all
  ranking columns complete). ANSC frame: 33 612 rows / 1222 positives
  (competitive `n_bidders >= 2` = MTA-0013's main population). Note the AAP
  frame's v0 AUC (0.5302) differs from the historical 0.493453 in MTA-0012:
  same score, different eligible population (winner-named procedures only) —
  documented, not reconciled away.

---

## 3. Pre-registered baselines

Eight rules with directions fixed *before* evaluation (the direction of the
v0 score is **never flipped**; the competition rule is pre-registered as
*fewer bidders = higher risk*; `amount` is exposure, not a model):

`v0_max_score` (production), `amount`, `n_bidders_fewer`, `value_within_cpv`,
`single_bidder`, `votes`, `random`, and the experimental `module_hits`
(Phase 4). Adoption criterion: the experimental ranking is adopted **only if
its paired ΔCI vs v0 excludes 0 in its favour** on an external label.

Cluster bootstrap (B=1000, seed 42): resampling the *label's natural unit* —
AAP suppliers, ANSC buyers — via `sample_weight`; percentile CIs on ROC-AUC
and PR-AUC plus paired per-replicate differences. Constant-score rules (ANSC
`single_bidder`) are flagged, not silently reported.

---

## 4. AAP interdiction label (supplier sanctions)

ROC-AUC (point [cluster CI]):

| Rule | ROC-AUC | Paired Δ vs v0 | Verdict |
|---|---|---|---|
| v0_max_score | 0.5302 [0.4829, 0.5901] | — | reference |
| **amount** | **0.7342 [0.6783, 0.8217]** | **−0.2040 [−0.2753, −0.1546]** | **ci_excludes_0 (amount wins)** |
| value_within_cpv | 0.6277 [0.5712, 0.6673] | −0.0976 [−0.1696, 0.0012] | ci_includes_0 |
| single_bidder | 0.5341 [0.4943, 0.5921] | −0.0039 [−0.0546, 0.0631] | ci_includes_0 |
| votes | 0.4909 [0.4567, 0.5468] | +0.0393 [0.0088, 0.0574] | ci_excludes_0 (v0 wins) |
| random | 0.5063 [0.4891, 0.5420] | +0.0238 [−0.0440, 0.0843] | ci_includes_0 |
| **module_hits** | **0.4839 [0.4527, 0.5418]** | **+0.0463 [0.0032, 0.0998]** | **ci_excludes_0 (v0 wins)** |
| n_bidders_fewer | 0.2423 [0.1991, 0.3348] | +0.2879 [0.1858, 0.3560] | ci_excludes_0 (v0 wins) |

Findings, stated as-is:

- **Contract amount alone significantly beats the production score** on this
  label (Δ −0.2040, CI excludes 0). The sanction label is dominated by large
  procurement volume — exposure, not anomaly. This is a label property, not
  a reason to replace the anomaly direction (guard rail: direction never
  flipped for metrics).
- **The pre-registered competition direction inverts on the AAP label**: AUC
  0.2423 (< 0.5) means sanctioned suppliers are associated with *more*
  bidders, not fewer. The complement (0.7577) exists arithmetically but is
  not reported as a finding — the direction was fixed a priori.
- **v0 is indistinguishable from random on AAP** (+0.0238, CI includes 0).
  Honest negative result.
- The experimental module ranking is **significantly worse than v0** on AAP
  (Δ +0.0463, CI excludes 0) — no adoption (see §7).
- At the 100-procedure review budget: v0 P@100 = 0, amount P@100 = 0,
  module_hits P@100 = 0.02 (lift 3.71) — a single point observation over a
  very small budget, reported for completeness, not as a claim.

**Robustness (leave-one-supplier-out).** 17 distinct matched suppliers drive
all 633 positives; dropping each one moves AUC within a range of 0.0308 with
max |Δ| = 0.0213 (largest: «rodital lux», 259 procedures). No single supplier
controls the result.

**Temporal stability.** 2018–2021 → 2022–2024: v0 0.428 (194 positives) →
0.553 (439); module_hits 0.456 → 0.494; amount 0.466 → 0.806. Both label
halves clear the 30-positive guard; per-period numbers are point estimates
only (no CI). The 2018–2021 period precedes the first sanction date (2024-01-05),
which is why that period's AAP discrimination is weak and why the overall
frame stays a *weak* label (registry, `known_limitation`).

---

## 5. ANSC complaint label (buyer-side)

ROC-AUC (point [cluster CI], clustering by buyer):

| Rule | ROC-AUC | Paired Δ vs v0 | Verdict |
|---|---|---|---|
| v0_max_score | 0.5112 [0.4895, 0.5593] | — | reference |
| amount | 0.5112 [0.4497, 0.6215] | +0.0000 [−0.0884, 0.0454] | ci_includes_0 |
| n_bidders_fewer | 0.5135 [0.4317, 0.5568] | −0.0023 [−0.0644, 0.1164] | ci_includes_0 |
| value_within_cpv | 0.5129 [0.4803, 0.5316] | −0.0017 [−0.0301, 0.0657] | ci_includes_0 |
| single_bidder | 0.5000 [0.5000, 0.5000] | +0.0112 [−0.0105, 0.0593] | ci_includes_0 (rule constant under `n_bidders>=2` → not applicable, flagged) |
| votes | 0.4997 [0.4804, 0.5451] | +0.0115 [−0.0013, 0.0264] | ci_includes_0 |
| random | 0.4892 [0.4685, 0.4999] | +0.0220 [−0.0043, 0.0824] | ci_includes_0 |
| **module_hits** | **0.4838 [0.4663, 0.5277]** | **+0.0274 [0.0046, 0.0551]** | **ci_excludes_0 (v0 wins)** |

- **Cross-validation passes exactly**: framework v0 AUC 0.5112 reproduces
  MTA-0013's 0.511196 within the same cluster-bootstrap CI, and positives
  (1222) match MTA-0013 exactly after the PN-alias fix.
- The framework's headline reproduces the production evaluation's finding:
  v0 ≈ chance on buyer-side complaints (CI includes 0.5). This is a
  cross-source convergence, not a new claim.
- **The label is «complaint filed», not «confirmed violation»** — the ANSC
  decision documents are a documented blocker (§1); without them this label
  cannot measure enforcement outcomes.

**Temporal stability.** v0: 0.540 (593 positives) → 0.485 (629); module_hits:
0.502 → 0.468. All periods clear the positive guard; per-period values are
point estimates.

---

## 6. What this changes for the project

1. **A falsifiable external-validation framework** now exists: uniform
   registry, pre-registered baselines, cluster bootstrap, temporal guard,
   supplier-robustness check — reusable for any future label.
2. The **honest negative results are now first-class deliverables**: v0 is at
   chance on both external labels; the AAP label is largely an exposure label
   (amount wins); the competition direction inverts on AAP.
3. The **ANSC label's semantic ceiling** is documented: complaints ≠ outcomes
   until the decision documents arrive.

## 7. Adoption decision for the experimental ranking

Criterion (pre-registered): adopt `module_hits` as a ranking only if its
paired ΔCI vs v0 **excludes 0 in its favour** on an external label. Result:
the CI excludes 0 **against** it on both labels (AAP +0.0463 [0.0032, 0.0998];
ANSC +0.0274 [0.0046, 0.0551]). **Decision: do not adopt.** The Phase 4 module
track stays what it is by construction — an explanatory/review lens with
interpretability, never a replacement scoring function. No threshold, band,
vote or model weight changes with this report.

## 8. Unresolved / blockers

- ANSC decision documents → label semantic ceiling (see §5); HG 957/2017,
  HG 1420/2016, the 2026 judgments and the Metodologia AAP file were not
  provided; MoF cross-check needs the live API; expert reviews are pending
  (Phase 6). All recorded in the registry with `status: blocked/empty/pending`.
- The AAP label's supplier-level attribution and name-based matching
  (no company codes) remain a `known_limitation` in the registry.

## 9. Reproduction

```bash
.venv/bin/python scripts/35_external_validation.py            # registry + both labels, B=1000, seed 42
.venv/bin/python -m pytest tests/test_external_framework.py -q # 9 tests (synthetic; real-data smoke skips without results/)
```

Inputs (read-only): `results/tables/tender_anomaly_scores.csv`,
`aap_procedure_matches.csv`, `ansc_candidates.csv`, `risk_module_indicators.csv`,
`data/features/features.csv`. Outputs: `results/methodology/external_label_registry.json`,
`external_validation_framework.json`, `results/tables/external_baselines.csv`,
`aap_leave_one_supplier_out.csv`, `temporal_stability_external.csv`.

---

*Measurement only: no retraining, no threshold/band/vote changes, no fabricated
values for unavailable sources. Anomaly ≠ guilt; a complaint is not a decision;
an interdiction is not a court finding; the external labels stay weak labels
with documented limitations.*
