# RACI Matrix - Data and Anomaly Analysis (Mtender_anomaly)

Responsibility assignment for the analysis this project exists to produce: a trustworthy corpus of Moldovan public procurement records, 22 indicators, four anomaly detectors, an agreement-based risk band, and an interpretation a human analyst can act on.

Every task corresponds to real work in the repository - the artefact column names the actual script, module or document. Operations work that does not touch the analysis (repo hygiene, build gates, backups) is deliberately out of scope.

**Legend:** `R` Responsible (does the work) · `A` Accountable (owns the result, approves - exactly one per task) · `C` Consulted before (two-way) · `I` Informed after (one-way) · `A/R` same person both owns and performs.

## 1. Roles

| Code | Role | Basis |
|---|---|---|
| `SD` | Data Analyst / Author | Runs the pipeline, computes the indicators, reads the anomalies. Sole implementer. |
| `SS` | Scientific Supervisor | Approves the methodology and the claims drawn from the analysis. Assumed: named on the title page, not in the repo. |
| `DE` | Domain Expert (procurement / anti-corruption) | Decides whether a flagged pattern is meaningful in Moldovan procurement, and reviews the case studies. Assumed. |
| `TR` | Thesis Committee / Reviewer | Examines the analysis and its claims. Assumed. |
| `DP` | Data Provider (MTender / MoF / AAP) | **External - C/I only.** Publishes the data being analysed. EXTERNAL - may only be C or I. |
| `AI` | AI Coding Agent (Cursor) | Present in the repo as .cursor/settings.json. Assisted-by role; never accountable. |

## 2. Matrix

| ID | Task | Artefact (script / module) | `SD` | `SS` | `DE` | `TR` | `DP` | `AI` |
|---|---|---|---|---|---|---|---|---|
| **A. Corpus integrity** | | |  |  |  |  |  |  |
| A1 | Verify source endpoints: empty HTTP 200 bodies, date-cursor pagination | `scripts/00_check_api.py; docs/API_INVESTIGATION_REPORT.md` | A/R | I |  |  | C |  |
| A2 | Build the corpus: OCID inventory + immutable fetch of every package | `scripts/01a_scan_ocids.py; 01b_fetch_records.py` | A/R | I |  |  | C |  |
| A3 | Normalise to analysis-ready documents (merge compiled releases, parties, lots) | `scripts/02_normalize_mongo.py; src/mtender/normalize.py, ocds.py` | A/R | I | C |  |  |  |
| A4 | Resolve supplier identity: IDNO extraction, 491 whitespace-padded IDs (536 phantoms under the cycle's full v4 normalisation) | `src/mtender/ocds.py, normalize.py (_IDNO_IN_ID, _idno_from)` | A/R | I | C |  |  |  |
| A5 | Detect and quarantine corrupt values (award total inflated ~10 orders of magnitude) | `src/mtender/normalize.py (plausible_award_total, AWARD_AMOUNT_VS_ESTIMATE_MAX)` | A/R | I | C |  |  |  |
| A6 | Measure coverage and non-response: 31.3% bid data, 77.3% award data, 2,617 inverted periods | `scripts/02 (validation report); src/mtender/features.py` | A/R | C | I |  |  |  |
| A7 | Independent cross-checks: MoF monthly extract, AAP blacklist load | `scripts/10_load_mof_opendata.py; 11_load_blacklist.py` | A/R |  | I |  | C |  |
| **B. Indicators** | | |  |  |  |  |  |  |
| B1 | The 22 computable indicators, grouped by what they measure | `scripts/03_features_mongo.py; src/mtender/features.py` | A/R | I | C |  |  | C |
| B2 | The 6 indicators deliberately NOT built, each with its reason | `src/mtender/features.py (UNAVAILABLE register)` | A/R | C | I |  |  |  |
| B3 | Behavioural concentration indicators (repeat share, winner share of buyer awards) | `src/mtender/features.py` | A/R | I | C |  |  |  |
| B4 | Denominator discipline: single_bidder over published participant lists only | `src/mtender/features.py; tests/test_pipeline.py` | A/R | C | I |  |  |  |
| B5 | Correlation methodology on a 9-orders-of-magnitude distribution (Spearman default, Pearson shown, per-pair n) | `backend/app/analytics.py` | A/R | C | I |  |  |  |
| **C. Anomaly detection** | | |  |  |  |  |  |  |
| C1 | Four detectors on identical preprocessing (MAD z-score, Isolation Forest, LOF, One-Class SVM) | `scripts/06_detect_anomalies.py; backend/ml/detect.py` | A/R | C | I |  |  |  |
| C2 | Sampling design for O(n^2) models: seeded random 20,000 rows, novelty=True scoring | `scripts/06_detect_anomalies.py` | A/R | C | I |  |  |  |
| C3 | State contamination=0.05 in advance as an assumption, not a finding | `scripts/06_detect_anomalies.py; README.md section 11` | R | A | I |  |  |  |
| C4 | Consensus risk banding: agreement count, not a score threshold (incl. unscored) | `backend/app/adapter.py; src/mtender/` | R | A | C | I |  |  |
| C5 | Handle the absent ground truth: metrics.available=false rather than a fabricated accuracy | `backend/ml/pipeline.py; backend/app/adapter.py` | A/R | C | I |  |  |  |
| **D. Interpretation & validation** | | |  |  |  |  |  |  |
| D1 | Feature importance: permutation importance + univariate ANOVA as primary evidence | `scripts/07_explainability.py; results/figures/` | R | A | C | I |  |  |
| D2 | Attribution on Isolation Forest only; no SHAP claim for LOF / One-Class SVM | `scripts/07_explainability.py` | A/R | C | I |  |  |  |
| D3 | Blacklist matching: normalisation rules, exact vs ambiguous, never counting ambiguous as a hit | `scripts/09_external_validation.py; src/mtender/names.py` | A/R | I | C |  |  |  |
| D4 | Precision@K protocol as the substitute for precision/recall without labels | `thesis/ (Chapter 3); README.md section 12` | R | A | C | I |  |  |
| **E. Analyst-facing analysis** | | |  |  |  |  |  |  |
| E1 | Ranked procedures by percentile with risk bands and honest empty/unscored states | `frontend/src/pages/Tenders.tsx; TenderDetail.tsx` | A/R | I | C |  |  |  |
| E2 | Distribution and correlation views: medians, quantiles, ECDF, automatic log bins | `frontend/src/pages/Distributions.tsx` | A/R | C | I |  |  |  |
| E3 | Buyer-winner concentration network over the repeated-pair subgraph | `frontend/src/pages/Network.tsx; pages/network/` | A/R | I | C |  |  | C |
| E4 | 5-10 case studies: flagged procedures reviewed by a human, not by the score alone | `frontend/src/pages/Tenders.tsx; thesis/STATUS.md` | R | A | C | I |  |  |
| E5 | Analyst workspace for recording expert review, annotations and watchlists | `src/mtender/workspace.py; backend/app/workspace_api.py; Workspace.tsx` | A/R | I | C |  |  |  |
| E6 | Ethics framing in every view: a risk band is a screening signal, not an allegation | `frontend/src/pages/Method.tsx` | R | A | C | I |  |  |
| **F. Reproducibility & result** | | |  |  |  |  |  |  |
| F1 | Snapshot export with checksum manifest so the analysis runs from files alone | `scripts/04_export_snapshot.py; data/processed/tenders.json` | A/R | I |  |  |  |  |
| F2 | Recompute aggregations in two independent toolchains as a cross-check | `scripts/05_aggregations.py; results/tables/` | A/R | C | I |  |  |  |
| F3 | Regression suite locking in the verified data behaviours (77 tests) | `tests/test_pipeline.py; tests/test_backend_adapter.py` | A/R | C |  |  |  |  |
| F4 | Chapter 1: domain, Law 131/2015, red flags, limitations of the data | `thesis/` | R | A | C | I |  |  |
| F5 | Chapter 2: indicators, architecture, detectors, consensus methodology | `thesis/` | R | A | C | I |  |  |
| F6 | Chapter 3: results, Precision@K, case studies, honest limitations | `thesis/` | R | A | C | I |  |  |
| F7 | Supervisor review rounds and written notes on the analysis | `thesis/STATUS.md` | C | A/R |  | I |  |  |
| F8 | Final defence of the analysis and its claims | `-` | R | A | C | I |  |  |

## 3. Workload per role

| Role | R | A | C | I | Total |
|---|---|---|---|---|---|
| Data Analyst / Author | 34 | 24 | 1 | 0 | 59 |
| Scientific Supervisor | 1 | 11 | 11 | 12 | 35 |
| Domain Expert (procurement / anti-corruption) | 0 | 0 | 18 | 12 | 30 |
| Thesis Committee / Reviewer | 0 | 0 | 0 | 10 | 10 |
| Data Provider (MTender / MoF / AAP) | 0 | 0 | 3 | 0 | 3 |
| AI Coding Agent (Cursor) | 0 | 0 | 2 | 0 | 2 |
| **35 tasks** | **35** | **35** | **35** | **34** | |

35 accountable assignments for 35 tasks - exactly one `A` per task.

## 4. Bottlenecks, risks and gaps in the analysis

**1. The analysis has one author.** The Data Analyst holds `A` on 24 of 35 tasks (68%) and `R` on 34. Every number that reaches Chapter 3 passes through the same pair of hands, including the corrections to that same code. There is no second reader of the data path from `raw_tenders` to the risk band.

**2. The only validation available is a human one, and it is `C`, not `R`.** There are no court labels, so precision and recall are not computable (`metrics.available = false`). What replaces them is detector agreement plus expert judgement - and the Domain Expert is consulted on 18 tasks but performs none of them. The external blacklist check found 2 matches out of 22 suppliers, so it cannot carry the validity argument alone. Consequence: **if the expert review does not happen, the project has no validation of its anomalies at all.** That review should be a scheduled deliverable with a date, not an informal consultation.

**3. Unowned methodological choices.** Three decisions that determine what the anomalies mean are `A`-owned by the analyst alone, with no second signature:

| Decision | Where | Why it matters |
|---|---|---|
| `contamination = 0.05` | `scripts/06_detect_anomalies.py` | Fixes the flagged share in advance. C3 assigns `A` to the Supervisor; that approval should be recorded before the run, not after |
| 20,000-row seeded sample for LOF / SVM | `scripts/06_detect_anomalies.py` | A prefix would fit on 2018 and score 2024. The design is defensible but undocumented outside the code |
| Spearman as the default correlation | `backend/app/analytics.py` | Changes the headline relationship from +0.001 to +0.989. It is the right choice, and it needs to be argued in Chapter 2, not left in code |

**4. Data defects constrain what may be claimed, and they stay in the data.** The corrupt award value is now guarded at normalisation, but the raw document is immutable and still carries it; 491 supplier IDs remain whitespace-padded upstream (the cycle's `v4_datafix` variant measures the full normalisation at model level: 536 phantom identities merged, behavioural features recomputed); bid data exists for 31.3% of procedures and award data for 77.3%. Chapter 3 must state these as limits on the result. Ownership of the regenerated corpus (full re-ingest vs. the current guarded normalisation) is currently unclear - nobody is `A` for the decision.

**5. Synthetic and real results can be confused.** `backend/ml/pipeline.py` still writes `data/processed/graph.json`, which the API never reads. It exists for the Chapter 3 evaluation experiment. Risk: a synthetic-derived number quoted next to a real one. `A` for keeping the two separated is unassigned.

**6. The Thesis Committee has no `R` and no `A`** - `I` on 10 tasks, all of them late (C4, D1, D4, E4, E6, F4-F8). Its first contact with the analysis is the defence. There is no interim gate on the methodology before it is locked in.

**7. The Data Provider is external and uncontracted.** MTender's list endpoint returns HTTP 200 with an empty body in roughly one request in five. There is no SLA or escalation path; retry and resume in `01a`/`01b` are the only mitigation. An outage blocks Phase A and therefore every anomaly score downstream, including the figures quoted in Chapters 1 and 3.

**8. Role that would normally exist and does not: an independent reader of the results.** Someone who did not write the detectors and can be handed `results/tables/` and asked whether the top of the ranking looks like what it claims to be. Without it, the case studies in E4 are the analyst reviewing their own output.

## 5. Assumptions

Everything below is an assumption. None of it is stated in the repository.

| # | Assumption | Basis | Effect if wrong |
|---|---|---|---|
| 1 | One person performs the whole analysis - a **solo** master's thesis | `thesis/STATUS.md` is first-person throughout; a single author in git history | `SD` must be split and the matrix rebuilt |
| 2 | A **Scientific Supervisor** approves methodology and chapters | Standard for a master's thesis; no supervisor is named in the repo | The 11 `A` assignments on `SS` have no owner |
| 3 | A **Domain Expert** reviews flagged patterns and case studies | The project's own documents call for expert review in place of ground truth (`PROJECT_OVERVIEW.md` §7) | The 18 consultations do not happen and the anomalies go unvalidated - see risk 2 |
| 4 | A **Thesis Committee** receives the thesis and examines at defence | Standard for a master's thesis | Drop column `TR` |
| 5 | **MTender / MoF / AAP** are the data providers, external to the analysis | Real: `public.mtender.gov.md`, MoF monthly XLSX, the AAP blacklist | Documented, not assumed |
| 6 | An **AI coding agent (Cursor)** assists under the author's review | Real: `.cursor/settings.json` in the repo | Drop column `AI`; no `A` depends on it |
| 7 | Expert review happens at **phase boundaries**, not continuously | No review cadence is recorded anywhere | If continuous, `SS` and `DE` load rises without bound |
| 8 | The defence is the terminal task | `thesis/STATUS.md` ends at the full-history recompute | A publication or demo after defence adds tasks and an owner |

## 6. Files

`docs/RACI_MATRIX.xlsx` holds the same matrix as a spreadsheet: colour-coded cells, a `Workload` sheet and a `Legend & assumptions` sheet. The matrix is validated programmatically (one `A` per task, at least one `R`, external roles `C`/`I` only) - re-run that check after editing by hand.

