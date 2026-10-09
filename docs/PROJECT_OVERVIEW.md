# MTender — How this project works, and why

A research pipeline and two dashboards for detecting anomalous patterns in Moldovan public
procurement, built on the official MTender OCDS feed.

**The central claim of this project is not "we found corruption".** It is that anomaly scores are
a *screening* signal: a way to rank 152,378 public contracts so a human analyst looks at the
7,708 that at least two independent detectors agreed on first, rather than all of them. Every design decision below follows from taking that seriously — most of them are
about being honest about what the data cannot support.

---

## 1. Current state

| | |
|---|---|
| Procedures | 152,378 (2018-10-18 → 2024-04-05) |
| Procurers | 2,564 |
| Suppliers | 13,986 distinct `winner_id` (see §8 — the raw snapshot appears to show 14,477) |
| Raw / normalised / feature documents | 152,378 each |
| Party records | 552,089 |
| Anomaly scores | 152,378 (100% of the corpus) |
| Detectors | 4 — MAD z-score, Isolation Forest, LOF, One-Class SVM |
| Risk bands | 82.2% low · 12.7% medium · 3.0% high · 2.0% critical |
| Ground truth | **None.** Precision/recall are not computable on real data. |

---

## 2. The shape of the system

```
MTender OCDS API ─┐
MoF open data ────┼─→ raw_* ─→ norm_* ─→ features_tenders ─→ results/tables/*
AAP blacklist ────┘         (Mongo)                        (CSV, no DB needed)
                                                          │
                              ┌───────────────────────────┴──────────┐
                              ↓                                      ↓
                     Streamlit (app.py)                    FastAPI (backend/) ─→ React (frontend/)
                     13 pages, in-browser                  read + CRUD + analytics
```

Two rules hold this together:

1. **Modelling never requires a running database.** Step 04 exports the feature table to CSV with a
   manifest recording the export query, row count and SHA-256. Steps 06 and 07 read only that file,
   so the ML half of the pipeline is reproducible from files alone.
2. **The two front-ends share one store, and it is not the research data.** Analyst work lives in
   SQLite at `data/workspace/workspace.db`. `data/features/` and `results/` stay read-only, so the
   ETL output can always be regenerated and can never be corrupted by someone clicking Delete.

---

## 3. The pipeline, stage by stage

Run everything with `./scripts/run_pipeline.sh` (or `SMOKE=1 ./scripts/run_pipeline.sh` for a
two-minute end-to-end proof against a throwaway database). Every stage is idempotent.

| Stage | Script | What it does | Why it exists |
|---|---|---|---|
| 0 | `00_check_api.py` | Requests every URL for real; reports non-200 and empty bodies as failures | The API intermittently returns HTTP 200 with an empty body. Silent failure here would look like "no data" much later |
| 0 | `pytest tests` | Regression tests for the verified API behaviours | Locks in the quirks before anything depends on them |
| 1a | `01a_scan_ocids.py` | Walks the date-cursor pagination, records every OCID | The list endpoint is the only way to enumerate history. Resumable via JSONL |
| 1b | `01b_fetch_records.py` | Downloads each OCDS package, flattens, stores | Uses `$setOnInsert` — never overwrites a stored raw body |
| 1c | `10_load_mof_opendata.py` | Ministry of Finance monthly extract | A *second, independent* source. Kept separate from `raw_tenders` so it can be cross-checked rather than silently merged |
| 1d | `11_load_blacklist.py` | AAP "Lista de interdicție" | The only official integrity list for Moldovan procurement |
| 2 | `02_normalize_mongo.py` | `norm_tenders`, `norm_parties`, validation report | Streams in chunks — a full ingest is hundreds of thousands of nested documents |
| 3 | `03_features_mongo.py` | Per-row + group-statistic features | MongoDB does the cross-tender joins; pandas does the per-row maths |
| 4 | `04_export_snapshot.py` | CSV + JSON + checksum manifest | Decouples modelling from the database |
| 5 | `05_aggregations.py` | Descriptive tables in Mongo | Deliberately recomputed in pandas by step 06 as a **cross-check of two independent toolchains** |
| 6 | `06_detect_anomalies.py` | Four detectors, scores to Mongo + CSV | The core model comparison |
| 7 | `07_explainability.py` | SHAP, permutation importance, ANOVA | Attribution layer |
| 8 | `08_data_dictionary.py` | Regenerates `docs/DATA_DICTIONARY.md` from live responses | The data dictionary must not contain assumed fields |
| 9 | `09_external_validation.py` | Matched suppliers against the blacklist | The only external check available |

### Why the source code lives in `src/mtender/`

The scripts are orchestration. The logic is in `src/mtender/` — `features.py`, `normalize.py`,
`ocds.py`, `aggregations.py`, `names.py` — so the stored documents, the CSV export and the unit
tests all call the *same* implementation and cannot drift apart.

---

## 4. Features: the 22 that are computable

Grouped by what they measure (`src/mtender/features.py`):

- **Financial** — `log_award_value`, `value_vs_cpv_median`, `value_zscore_cpv`,
  `estimate_to_award_ratio`, `log_award_total`, `multi_award_tender`
- **Competition** — `n_bidders_log`, `single_bidder`, `no_bid_data`, `multi_supplier_award`
- **Procedural** — `bid_window_days`, `short_deadline`, `long_deadline`, `n_amendments`, `amended`,
  `accelerated_like`, `cancelled`, `no_award_after_tender`
- **Behavioural** — `buyer_supplier_repeat_share`, `winner_share_of_buyer_awards`,
  `supplier_win_concentration`, `supplier_award_count_log`

`n_bidders`, not `n_bids`. MTender's `bids.details` is **per lot**, not per bidder — a 202-lot
tender was observed producing 503 bid records. Counting them as bids would invent competition that
does not exist. Both are exposed, but only `n_bidders` is treated as a competition measure.

### The 6 indicators deliberately *not* built

`UNAVAILABLE` in `features.py` records each with its reason. This is the most important table in
the project:

| Indicator | Why not |
|---|---|
| `winning_margin` | Awards expose no per-supplier split of the value |
| `bid_spread` | `bids.details` published for a small minority only |
| `direct_award_flag` | No field in the payload marks a single-source award |
| `supplier_age` | `party.details` carries no founding date |
| `change_in_award_value` | No amended award values observed |
| `collusion_contact_cluster` | `party.contactPoint` is the literal string `-` for most parties |

A missing indicator is reported as unavailable **with its reason**, never as `0`. A zero is a
measurement; an absent field is not. Averaging a missing value into a list yields `0.0`, which is
indistinguishable from a genuine zero — that is how a dashboard ends up confidently reporting
fiction.

---

## 5. Anomaly detection

Four detectors on identical preprocessing (`StandardScaler`, missing → 0), so the comparison is
about the models and nothing else:

| Model | Flagged | Role |
|---|---|---|
| Statistical MAD z-score | 10.2% | Interpretable baseline on non-binary features only |
| Isolation Forest | 5.0% | Captures interactions; the workhorse |
| Local Outlier Factor | 5.1% | Density-based; finds "alone in a sparse region" |
| One-Class SVM | 5.1% | Smooth global boundary |

`contamination=0.05` is an **assumption, stated in advance**, not a discovery. The real thresholds
are chosen by the detectors agreeing.

### The band is agreement, not a score threshold

```
unscored  no detector output at all
low       0 detectors flagged
medium    1 detector
high      2 detectors
critical  3 or more detectors
```

Banding on *how many independent models agreed* rather than on a score cut-off keeps the bands
reproducible and immune to the fact that score scales are incomparable — LOF scores run into the
hundreds while SVM decision scores go negative.

### Why neighbourhood models don't choke on 152k rows

LOF and One-Class SVM are O(n²). Both are fitted on a **seeded random sample of 20,000 rows** and
then used in `novelty=True` mode to score all 152,378. Isolation Forest and the MAD baseline see
everything.

The sample is random and never a prefix, and that matters: the snapshot is sorted by `ocid`, and an
MTender OCID embeds its publication timestamp, so the first rows are the *oldest* procurements. A
prefix would fit on 2018 and score 2024 — a temporal extrapolation, not an outlier search.

---

## 6. Explainability

`07_explainability.py` uses **permutation importance and univariate ANOVA** as the primary tools,
with a TreeExplainer on the Isolation Forest for attribution.

Exact SHAP values for LOF and One-Class SVM are undefined, so claiming a SHAP explanation for them
would be a category error. The ANOVA pass answers a different question — which features
*significantly separate* the consensus-flagged rows from the rest — and it is the more defensible
statement in a thesis.

Strongest separators in the current run: `winner_share_of_buyer_awards` and
`buyer_supplier_repeat_share` (F ≈ 36,730), then `no_bid_data`, `single_bidder`, `log_award_total`.
The recurring theme is *concentration*: one supplier dominating one buyer's awards.

---

## 7. Why there is no accuracy score

Real procurements have no ground truth. Nobody has published a court label saying "this contract
was corrupt", so precision, recall and F1 are **not computable** — and `build_stats` returns
`{"available": false, "reason": ...}` rather than omitting the field, so the absence is visible
rather than confusing.

The thesis therefore argues from **detector agreement**, **univariate significance**, and the
**external blacklist check** instead. That is a weaker claim than a precision score, and it is the
honest one available.

---

## 8. Known data problems

These are in the data, not the code. They constrain what the dashboards can show.

### One award total is inflated by ~10 orders of magnitude

| | Award total (MDL) | Estimate (MDL) | Bidders |
|---|---|---|---|
| Rank 1 | 50,160,310,175,476 | 2,724,979 | 7 |
| Rank 2 | 4,102,262,814 | 533,642 | 7 |
| Rank 3 | 2,196,127,608 | 427,505,000 | 9 |

Rank 1's award is **18 billion times its own estimate**, and 2.7 billion times the corpus median.
The second largest award in the entire corpus is 4.1 billion — the rank-1 value is 12,228× larger
than its nearest neighbour. That gap is the signature of a misplaced decimal separator, not of a
mega-contract.

**Consequence:** every *sum* and *mean* of award value in both UIs is wrong at the top of the
range. The median (≈18,662 MDL) and the p99 (28.5M) are trustworthy; the total is not. This is
precisely why the UI defaults to medians, quantiles and ECDFs, and why the histogram switches to
logarithmic bins automatically once max/median exceeds 1000.

### Coverage gaps

- **31.3%** of procedures publish any bid data. `single_bidder_share` is therefore computed over
  procedures that published a participant list, never over the full corpus — averaging in the
  missing ones would understate single-bidder awards.
- **77.3%** publish award data, so 22.7% have no `winner_id`. That is usually legitimate (no award
  was made), not missing data.
- **2,617** records have an inverted tender period (`endDate` before `startDate`).
- `award_total` is missing for 34,554 procedures, so every money correlation is computed on the
  117,824 rows where both sides exist — and the per-pair `n` is shown next to every coefficient.

### 491 supplier IDs are whitespace-padded

`winner_id` values arrive with trailing spaces or tabs:

```
'MD-IDNO-1006601004242 '
'MD-IDNO-  1010602002912      '
'MD-IDNO-2005040033904\t'
```

Counted raw, that yields **14,477** distinct suppliers. After stripping, **13,986** — 491 phantom
identities, a 3.4% overcount. Any exact-match join on `winner_id` will miss those rows.

The blacklist matching in step 09 is **not** affected: it matches on `winner_name` through
`names.normalise_name`, which collapses all whitespace runs to single spaces. The FastAPI adapter
also strips via `_s()`. Only ID-keyed aggregations need the normalisation.

---

## 9. Correlation: why the method is not a detail

Award values span roughly nine orders of magnitude between median and maximum (18,662 MDL →
5×10¹³ MDL, a factor of 2.7 billion). On a distribution like that, **Pearson's r is dominated by a
few points** and reports almost nothing:

| Pair | Pearson | Spearman |
|---|---|---|
| `award_total_mdl` ~ `estimated_value_mdl` | **+0.001** | **+0.989** |
| `award_total_mdl` ~ `n_bidders` | +0.006 | +0.814 |
| `n_bidders` ~ `value_vs_cpv_median` | +0.176 | +0.339 |

The first row is the whole argument. Two variables that are near-perfectly rank-correlated
register as *completely uncorrelated* under Pearson, because a handful of mega-contracts dominate
the covariance while the ranks are untouched.

Both UIs therefore default to **Spearman** and display the Pearson figure alongside it, so the gap
stays visible rather than being quietly resolved in favour of the flattering method. Correlations
use pairwise-complete observations, and the sample size `n` is reported per pair — a correlation
on 40 rows is not comparable with one on 117,824.

Correlations are also **co-variation, not causation**. A strong value between two money features
usually just means both were derived from contract size.

---

## 10. The two front-ends

| | Streamlit (`app.py`) | React (`frontend/`) + FastAPI (`backend/`) |
|---|---|---|
| Purpose | Research instrument: deep filtering, all 13 pages, export to CSV/Excel | Analyst-facing: browsing, workspace CRUD |
| Data | Reads CSV artefacts directly | Reads `tenders.json` + scores; **computes analytics server-side** |
| Shared | `src/mtender/workspace.py` (SQLite) | same |
| Style | Refined navy/gold/paper design system | Same token set, ported to CSS variables |

The React app cannot pull 152k rows through `/api/tenders` (capped at 500/page for table
rendering), and a correlation matrix over the full corpus should not be computed in a browser tab
anyway. So `/api/analytics/*` returns small aggregates computed in Python.

**No Vue.** `frontend/` is React 18 + TypeScript + Vite + Recharts.

---

## 11. The analyst workspace (CRUD)

Cases, per-procedure annotations, watchlists, saved views, and an audit log. In SQLite at
`data/workspace/`, separate from all research output. Full CRUD from both UIs against the same
store, so a case opened in one appears in the other.

Every mutation writes an `activity` row. `POST /api/workspace/reset` refuses to run without
`confirm=true`. Vocabulary is validated server-side (Pydantic), so a typo'd status returns 422
rather than silently vanishing from every filter built on it.

These are **working notes about published data**. A risk band is a statistical signal; a note is
not an allegation.

---

## 12. Defects found and fixed

Recorded because each one silently corrupted a headline number rather than crashing.

1. **`suppliers.py` IndentationError** — the Streamlit app could not start.
2. **Invalid CSV in `04_export_snapshot.py`** — the hand-rolled writer stripped `,` and `\n` but
   not `"`. Party names containing quotes (`фильм "Время инвестировать в Гагаузию"`) opened a quoted
   string that swallowed following records: *"Expected 62 fields, saw 67"*. This broke the snapshot
   for scripts 06 and 07, which is why detection silently ran against a stale 1,500-row file.
   Fixed by writing through `csv.writer` with `QUOTE_MINIMAL`.
3. **Empty Mongo `anomaly_scores`** — the API reported `scored: 0` and collapsed the whole corpus
   into one `"low"` bucket. Added a CSV fallback; the API now also prefers Mongo and only falls
   back.
4. **`risk_level(None)` returned `"low"`** — 150,878 unexamined procedures were presented as
   cleared. Now a distinct `unscored` band. This mattered because the procedures table filtered on
   `risk_level`, hiding the gap entirely.
5. **CSV string values reaching `_num()`** — the fallback path yielded strings, so bands populated
   while every `risk_score` stayed null.
6. **Stale `lru_cache`** — the API had been running since before `tenders.json` was regenerated.
7. **Duplicate column in a scatter frame** — a hover column that was also the axis made
   `frame[x]` a DataFrame; `to_numeric` rejected it.

---

## 13. Running it

```bash
# API + React
.venv/bin/uvicorn backend.app.main:app --port 8000
cd frontend && npm run dev            # proxies /api → :8000

# Streamlit (thesis instrument)
.venv/bin/python -m streamlit run app.py

# Full pipeline
./scripts/run_pipeline.sh             # or SMOKE=1 ./scripts/run_pipeline.sh
```

---

## 14. Where things live

```
src/mtender/        shared logic — features, normalize, ocds, aggregations, names, workspace
scripts/            00…11 pipeline stages + run_pipeline.sh
backend/app/        FastAPI: store.py, adapter.py, analytics.py, workspace_api.py
dashboard/          Streamlit: pages/ (13), components/ (theme, layout, charts, metrics, tables), utils/
frontend/src/       React: pages/, api.ts, ui.tsx, styles.css
data/               raw/ · processed/ · features/ · workspace/ (analyst SQLite)
results/            tables/ · figures/ · models/ · logs/ · mongo/
docs/               API_INVESTIGATION_REPORT.md · DATA_DICTIONARY.md
tests/              test_pipeline.py · test_backend_adapter.py
```

---

## 15. The principle underneath all of it

Three commitments run through every decision above:

1. **A missing value is not a zero.** Report it as unavailable, with the reason.
2. **A screening signal is not a finding.** Anomaly scores rank candidates for human review. They
   do not accuse a procurer, a supplier, or a procedure.
3. **Never let a reader infer more than the data supports.** Hence: `unscored` separate from
   `low`; per-pair `n` beside every correlation; method choice shown next to its result; and
   section 8 above, which lists what is wrong with the data rather than only what is right with
   the analysis.
