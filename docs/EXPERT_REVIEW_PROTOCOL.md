# Expert Review Protocol (Phase 5/6)

Date: 2026-10-20 · Status: **workflow ready; assessments pending — no reviews
have been requested or fabricated**

This protocol defines how qualified external reviewers evaluate the Phase 4
risk-specific indicators *without* ever being exposed to model output, and how
their assessments feed back as a **weak human label** with reviewer-agreement
statistics. Code: `scripts/36_export_expert_review.py`; tests:
`tests/test_external_framework.py`.

---

## 1. Purpose and what this cannot do

**Purpose.** Ask procurement/legal/audit experts whether the *facts* of a
case look irregular, then compare three groups selected by different criteria
(Phase 4 module indicators, production v0 critical flag, matched controls).
The experts' answers become reviewable-precision and lift measurements with
inter-reviewer agreement.

**What this cannot establish.** An expert impression is not a finding of
violation, not guilt, not a court or ANSC decision. An anomaly ≠ corruption;
a reviewed case is not a «problem case». The protocol deliberately measures
*perceived irregularity on facts*, never case outcomes.

## 2. The three groups (seed 42, 100 cases each)

| Group | Selection rule |
|---|---|
| `module_selected` | top-100 by (`n_module_hits`, `pair_prior_awards`, `ocid`) among cases with ≥1 known module and a complete stratum |
| `v0_selected` | top-100 by (`max_score`, `ocid`) among production-critical cases (`n_models_flagging >= 3`), **excluding** every `module_selected` case (25 overlaps excluded on the real data) |
| `matched_control` | 1:1 per `module_selected` case from the remaining pool, matched on (procedure group, event year, value quartile within group); the pool excludes both selected groups, so a case is in **exactly one** group |

Documented drops: 7747 module-known cases lack a year or value quartile
(no-stratum) and are ineligible for selection; stratum-exhausted trimming was
0 at N=100. Group sizes and drops are written to
`results/methodology/expert_review_export.json`.

## 3. Blinding

- Reviewers receive `results/tables/expert_review_cases.csv` with **opaque
  sequential ids** (`ER-0001`…), rows shuffled by a seeded RNG, and only
  *fact* columns: tender title/status/method, buyer, winner, CPV, dates,
  values, n_bidders, bid window, and the public MTender URL for source
  verification.
- **17 exported columns are screened against a deny-list** (`score`, `flag`,
  `vote`, `band`, `consensus`, `hit`, `module`, `group`, `rank`, `percentile`,
  `anomaly`, `model`) — the script aborts on any offender, and the test suite
  asserts the same independently.
- The group key (`expert_review_key.csv`) and the withheld-model facts stay in
  `results/`, never enter the reviewer file. Reviewers must not see the key
  until their assessments are submitted.

## 4. The answer form

`results/tables/expert_review_template.csv` is **header-only** — zero rows,
zero manufactured assessments. The columns implement the five questions the
review must answer (brief §8), one column per question, plus process fields:

| Brief question | Column | Coding |
|---|---|---|
| Does the case deserve further investigation? | `reviewable` | 0 = no, 1 = yes |
| Which observable indicator triggered concern? | `indicators_observed` | free text naming observable facts only |
| Are supporting documents sufficient? | `documents_sufficient` | 0 = no, 1 = yes, 2 = unknown from the given facts |
| Is the alert explainable? | `explainable` | 0 = no, 1 = yes |
| Does the case appear to be a false alarm? | `false_alarm` | 0 = no, 1 = yes |

Process/metadata columns: `confidence` (1–5), `review_time_minutes`,
`reviewer_id`, `comments`.

## 5. Reviewers and independence

- **Eligibility:** procurement-law, public-procurement audit or anti-corruption
  specialists with real case experience. **None have been engaged yet** —
  hence every metric below stays `pending`; the export is generated so the
  review can start the moment reviewers are available.
- **Independence:** each case reviewed by ≥2 reviewers; `reviewer_id` recorded;
  conflicts of interest declared per reviewer (any relation to a buyer or
  supplier in a case excludes that reviewer from that case).
- Reviewers work blinded to groups, model output and each other's answers.

## 6. Planned measurements (all pending until reviews exist)

Mirrors `METRIC_DEFINITIONS` in `scripts/36` (written to
`results/methodology/expert_review_export.json`):

- **Reviewable-case precision**: share of `reviewable = 1` per group, reported
  with buyer-cluster bootstrap 95% CIs (procedures of one buyer are not
  independent reviews).
- **Lift over matched controls**: precision(group) /
  precision(`matched_control`); undefined while the control precision is 0 —
  reported as undefined, never imputed.
- **Inter-reviewer agreement**: pairwise Cohen's κ on the reviewable
  judgement (`src/mtender.eval_metrics.cohen_kappa`), only when ≥ 2 reviewers
  see overlapping cases.
- **Confidence intervals**: percentile bootstrap clustered by buyer.
- **Average review time**: mean of `review_time_minutes` per group.
- **Secondary descriptors**: `false_alarm` / `explainable` /
  `documents_sufficient` shares per group; per-indicator breakdown grouped by
  the observable indicator the reviewer names (free-text coding, descriptive).

## 7. Workflow

1. Distribute `expert_review_cases.csv` (blinded) + this protocol + the answer
   form to ≥2 independent reviewers.
2. Collect completed templates; validate schema (every `case_id` known, no
   duplicates per reviewer, allowed codes only).
3. Compute §6 metrics; only then unlock `expert_review_key.csv` for the
   group comparison.
4. Publish results in `results/methodology/` and cite them in
   `IMPLEMENTATION_SUMMARY.md`, keeping reviewer quotes attributed with
   consent or anonymised by default.

## 8. Anti-fabrication rules

- The template ships empty; **assessment rows are only ever written by human
  reviewers**. No test, script or document in this repo may create
  `expert_review_*` assessment values.
- Every metric in §6 stays `pending` in reports until real submissions exist;
  a missing review is reported as missing, never imputed.
- The export is deterministic (seed 42) and byte-identical across reruns
  (tested), so any later review batch is comparable to this one.

## 9. Reproduction

```bash
.venv/bin/python scripts/36_export_expert_review.py --n 100 --seed 42
.venv/bin/python -m pytest tests/test_external_framework.py -q
```

Outputs: `results/tables/expert_review_cases.csv` (blinded, 300 rows),
`expert_review_key.csv` (group key), `expert_review_template.csv` (0 rows),
`results/methodology/expert_review_export.json` (selection audit: sizes,
drops, overlap exclusions, blinding check, metric definitions).

---

*An expert review is a weak, perception-based label: it cannot confirm guilt,
cannot substitute for ANSC decisions or court findings, and does not change
any production threshold, band, vote or model. Reviews requested, received and
analysed will be reported here with their date and provenance; until then this
section of the pipeline is honestly marked pending.*
