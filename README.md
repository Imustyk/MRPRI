# Mtender_anomaly

# Moldova Public Procurement Risk Intelligence

Full-stack master's application for the thesis:

**Detection of anomalies and identification of corruption-risk indicators in the public procurement system of the Republic of Moldova using artificial intelligence.**

The software scores procurement procedures, explains *why* they look unusual (red flags), and ranks them for an analyst. A high score is a **risk indicator**, not a legal finding of corruption.

---

## 0. What you get

| Piece | Role in the thesis |
|---|---|
| `scripts/01a`–`08`, `src/mtender/` | The real ETL: walks the live MTender OCDS API, normalises into MongoDB, engineers indicators, scores with four detectors, writes the tables and figures quoted in the thesis |
| `backend/app/adapter.py` | Maps the real ETL field names onto the dashboard contract and refuses to fabricate absent indicators |
| `backend/app/store.py` | Reads `data/processed/tenders.json` and the anomaly scores in MongoDB |
| `backend/app/main.py` | FastAPI for the dashboard |
| `backend/ml/` | **Legacy synthetic generator.** Kept only to reproduce the precision/recall evaluation against planted patterns; it is not what the UI serves |
| `frontend/` | Analyst UI: overview, ranked procedures, case file, buyer–bidder graph, distributions, workspace, methodology |

> **New:** [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) explains how the whole system
> works and *why* each design decision was made — the pipeline stage by stage, the features that
> are computable and the six that are not, how the risk bands are derived, the known data defects,
> and the defects found and fixed during development. Read that first if you are new to the codebase.

The dashboard is served from **real MTender data** held in a MongoDB replica set.
`backend/ml/` is retained for the Chapter 3 model-validation experiment and must
not be run over `data/processed/` without `confirm=true`, because it would replace
real records with invented ones.

---

## 1. What you need on the machine (do this first)

Check versions in a terminal:

```bash
python3 --version
node --version
npm --version
git --version
```

Required:

- **Python 3.11 or 3.12** (3.10 may work; 3.13 is untested with this pin set)
- **Node.js 20+** and npm (for the Vite React UI)
- **~500 MB** disk for venv + `node_modules`
- macOS, Linux, or Windows (steps below use macOS/zsh; Windows notes are in §12)

If `python3` is missing on macOS:

```bash
brew install python@3.12
```

If Node is missing:

```bash
brew install node
```

---

## 2. Open the project folder

```bash
cd /Users/imustyk/Diplom
```

If you cloned the repo elsewhere, `cd` into that copy instead. Every later command assumes you are in this root (the folder that contains `README.md`, `backend/`, `frontend/`, `data/`).

Confirm:

```bash
ls
```

You should see `backend`, `frontend`, `data`, `requirements.txt`, `README.md`.

---

## 3. Create a Python virtual environment

Never install thesis packages into the system Python.

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Your prompt should start with `(.venv)`.

Upgrade installer tools once:

```bash
python -m pip install --upgrade pip
```

---

## 4. Install Python dependencies

From the **project root**, with the venv active:

```bash
pip install -r requirements.txt
```

This installs FastAPI, Uvicorn, pandas, NumPy, scikit-learn, NetworkX, joblib, pydantic.

Check:

```bash
python -c "import sklearn, pandas, fastapi, networkx; print('ok')"
```

---

## 4b. MongoDB as a replica set (transactions)

The pipeline stores everything in MongoDB and reads it back for the API, so the
server is configured as a **single-node replica set** (`rs0`). A replica set is
required for multi-document transactions; a standalone `mongod` accepts the same
connection string but has no session support.

Homebrew install (what this machine uses):

```bash
# /opt/homebrew/etc/mongod.conf gains:
#   replication:
#     replSetName: rs0
brew services restart mongodb-community@6.0

.venv/bin/python -c "
from pymongo import MongoClient
c = MongoClient('mongodb://127.0.0.1:27017/?directConnection=true')
c.admin.command('replSetInitiate', {'_id': 'rs0', 'members': [{'_id': 0, 'host': '127.0.0.1:27017'}]})
"
```

Docker instead — `docker compose up -d` starts the set and runs `replSetInitiate`
once via the `mongo-init` service:

```bash
docker compose up -d
```

Verify:

```bash
curl -s localhost:8000/api/health | python3 -m json.tool | grep -A3 '"set_name"'
```

`MONGO_URI` should name the set (`mongodb://127.0.0.1:27017/?replicaSet=rs0`) so
the driver discovers the topology instead of treating the host as standalone.
`src.mtender.mongo_client.cluster_info()` and `supports_transactions()` expose the
same facts to Python callers.

---

## 5. Produce the data the dashboard reads

### Which dataset is real?

There are two generators in this repository, and they are **not** equivalent:

| | Real ETL (`scripts/01a`–`08`) | Legacy synthetic (`backend/ml/`) |
|---|---|---|
| Source | live MTender OCDS API | invented records |
| Storage | MongoDB `mtender` + `data/processed/` | `data/processed/` only |
| Field names | `value_vs_cpv_median`, `n_bidders`, … | `price_to_cpv_median`, `n_bids`, … |
| Ground truth | none published | planted patterns |

The dashboard serves the **real** ETL output. `backend/app/adapter.py` maps the
real field names onto the UI contract, and any field MTender does not publish is
returned as `null` with the reason listed in `/api/meta` under `unavailable`.
Fields that only ever existed in the synthetic dataset (`round_price`,
`near_threshold`, `bid_spread`, `negotiated_flag`, `collusion_phone_cluster`,
`planted_pattern`, …) are therefore never displayed as if they were measured.

`POST /api/pipeline/run?source=synthetic` returns **HTTP 409** unless you pass
`confirm=true`, because it would overwrite the real artefacts in
`data/processed/` with invented records.

### Run the real pipeline

```bash
cd /Users/imustyk/Diplom
source .venv/bin/activate
./scripts/run_pipeline.sh
```

Arguments are passed straight through to `01b`, so a partial run works:

```bash
./scripts/run_pipeline.sh --since 2024-01-01T00:00:00Z
```

To prove the whole chain end to end without a full-history crawl:

```bash
SMOKE=1 ./scripts/run_pipeline.sh    # 20 scan pages, 120 OCIDs, database mtender_smoke
```

The steps are individually restartable and each one prints a JSON summary:

| Step | What it does | Writes |
|---|---|---|
| `01a_scan_ocids.py` | Walks the whole public OCID history by date cursor | `data/raw/ocid_inventory.jsonl`, `raw_releases` |
| `01b_fetch_records.py` | Fetches one OCDS package per OCID | `raw_tenders`, `raw_parties`, `data/raw/ocds_packages/*.json.gz` |
| `02_normalize_mongo.py` | Normalises and validates | `norm_tenders`, `norm_parties` |
| `03_features_mongo.py` | Engineers indicators (SQL + pandas) | `features_tenders` |
| `04_export_snapshot.py` | Snapshot for the API and the thesis | `data/processed/tenders.json` |
| `05_aggregations.py` | Descriptive tables | `results/tables/*.csv` |
| `06_detect_anomalies.py` | Four detectors + consensus | `anomaly_scores` |
| `07_explainability.py` | SHAP, permutation importance | `results/figures/`, `results/mongo/` |
| `08_data_dictionary.py` | Live field-presence dictionary | `docs/DATA_DICTIONARY.md` |
| `09_external_validation.py` | Matches scored suppliers against the official AAP blacklist | `results/tables/blacklist_matches.csv`, `results/mongo/external_validation.json` |

`01a` resumes automatically: re-running it continues from the last cursor in the
inventory file and never duplicates or truncates existing rows. Use `--fresh` to
discard the inventory and rescan.

### Optional: the legacy synthetic dataset

Only needed to reproduce the Chapter 3 precision/recall evaluation against
planted patterns. It is **not** what the UI shows.

```bash
python -m backend.ml.pipeline
```

Expected output: JSON with `"ok": true`, `"n": 1200`, and `precision` / `recall` /
`f1` against the planted labels. Write it somewhere other than
`data/processed/` if you want to keep the real snapshot intact.

If the command fails with `ModuleNotFoundError: backend`, you are not in the
project root, or the venv is not active. `cd` back and activate again.

---

## 6. Start the API server

Keep the venv active. In **terminal 1**:

```bash
cd /Users/imustyk/Diplom
source .venv/bin/activate
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Leave this process running.

Checks:

- Open http://127.0.0.1:8000/docs — Swagger UI for every route
- Open http://127.0.0.1:8000/api/health — liveness plus the **MongoDB topology** the API is connected to (replica-set name, primary state, transaction support, collection counts)
- Open http://127.0.0.1:8000/api/stats — KPI JSON
- Open http://127.0.0.1:8000/api/meta — feature list and the fields MTender does not publish

Useful routes:

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/health` | Process alive + artefacts present |
| POST | `/api/pipeline/run?source=synthetic&n_tenders=1200` | Rebuild dataset from the UI or curl |
| POST | `/api/pipeline/run?source=ocds&ocds_path=/full/path/file.json` | Score a real OCDS dump |
| GET | `/api/stats` | Dashboard KPIs and evaluation metrics |
| GET | `/api/tenders?q=&level=high&min_risk=55&limit=40&offset=0` | Filtered ranked list |
| GET | `/api/tenders/{tender_id}` | One case file |
| GET | `/api/graph` | Buyer–winner network |
| GET | `/api/indicators` | Mean features by risk band |
| GET | `/api/meta` | Model weights and feature list |

Optional curl rebuild:

```bash
curl -X POST "http://127.0.0.1:8000/api/pipeline/run?source=synthetic&n_tenders=1200"
```

---

## 7. Install frontend dependencies

In **terminal 2** (venv is not required here):

```bash
cd /Users/imustyk/Diplom/frontend
npm install
```

This creates `frontend/node_modules/` (git-ignored).

---

## 8a. Analyst workspace (CRUD)

Cases, per-procedure annotations, watchlists and saved views. Stored in SQLite at
`data/workspace/workspace.db`, which is **separate from the pipeline output** — `data/features/`
and `results/` stay read-only, so the ETL artefacts remain reproducible.

via `src/mtender/workspace.py`:

| Operation | REST |
|---|---|
| Cases | `GET/POST /api/workspace/cases`, `PATCH/DELETE /api/workspace/cases/{id}` |
| Annotations | `GET/POST /api/workspace/annotations`, `PATCH/DELETE …/{id}` |
| Watchlists + items | `GET/POST /api/workspace/watchlists`, `…/{id}/items` |
| Saved views | `GET/POST /api/workspace/views`, `PATCH/DELETE …/{id}` |
| Audit log | `GET /api/workspace/activity` |

Every mutation writes an `activity` row. `POST /api/workspace/reset?confirm=true` wipes the
workspace and refuses to run without `confirm=true`.

---

## 8b. Distribution and correlation analytics

Aggregates are computed **server-side** over all ~152k rows — the browser cannot pull the corpus
through `/api/tenders`, which is capped at 500 per page for table rendering.

| Endpoint | Returns |
|---|---|
| `GET /api/analytics/features` | Numeric columns with coverage and five-number summaries |
| `GET /api/analytics/correlations` | Pearson/Spearman/Kendall matrix, ranked pairs, per-pair n |
| `GET /api/analytics/distribution` | Histogram bins, ECDF, quantiles, IQR outlier rate |
| `GET /api/analytics/scatter` | Stride-sampled pairs plus a least-squares fit |
| `GET /api/analytics/group-compare` | Per-group IQR, the source of the box plots |
| `GET /api/analytics/crosstab` | Two-way count or sum matrix |
| `GET /api/analytics/timeseries` | Bucketed totals, optionally split by category |

**Use Spearman, not Pearson, for money columns.** Award values here reach ~5e13 MDL against a
median under 2e4. On that distribution Pearson is dominated by a few mega-contracts: it puts
`award_total_mdl` against `estimated_value_mdl` at r = 0.18 where Spearman gives r = 0.99. The
histogram also switches to logarithmic bins automatically when the max/median ratio exceeds 1000,
because equal-width bins otherwise put 117,823 of 117,824 values in the first bar.

**Not scored is not low.** The UI keeps `unscored` as its own band, separate from `low`, because a
record with no detector output has not been examined and nothing clears it. After the full
detection run (step 06 over the whole snapshot) the band is empty — all 152,378 procedures carry a
score — but the distinction is kept so a partial or failed run cannot read as a clean bill of
health. Current split: 82.2% low, 12.7% medium, 3.0% high, 2.0% critical.

---

## 8. Start the web UI

Still in `frontend/`:

```bash
npm run dev
```

Vite prints a local URL, normally **http://127.0.0.1:5173**.

`frontend/vite.config.ts` proxies `/api` to port **8000**. Both servers must be running.

Open the URL in a browser.

Pages:

1. **Overview** — counts, monthly risk, bands, CPV table, and the scored-vs-unscored coverage note
2. **Procedures** — search, level, procedure type, min score, pagination
3. Click a row — case file: hybrid score, IF/LOF/rules, flag chips, bid table
4. **Distributions** — correlation matrix, ECDF, paired scatter, cross-tabulation
5. **Buyer–bidder graph** — navy = contracting authority, gold = supplier; red/gold edges = high risk
6. **Workspace** — cases, annotations, watchlists and saved views (CRUD, section 8a)
7. **Methodology** — mapping to thesis chapters

If Overview says the dataset is missing, click **Generate data and train models** (calls `POST /api/pipeline/run`) or repeat step 5.

---

## 9. Production-style frontend build (optional)

```bash
cd /Users/imustyk/Diplom/frontend
npm run build
npm run preview
```

`preview` serves `frontend/dist/`. The API must still run on port 8000, or you must put a reverse proxy in front of both.

If you serve the built app anywhere other than `localhost`, bind the preview
explicitly — `vite preview` listens on IPv6 only by default and a browser pointed
at `127.0.0.1` will be refused:

```bash
npm run preview -- --host 127.0.0.1 --port 4173
```

### How the dashboard behaves

| Situation | What you see |
|---|---|
| Request in flight | shimmer skeleton, announced via `role="status"` |
| No rows match the filters | an explicit empty state with a *Clear filters* action |
| API unreachable or failing | a red panel with the raw error and a *Retry* button |
| Unknown `tender_id` | "Procedure not found" with a link back, not a permanent spinner |
| A field MTender does not publish | an em dash and the reason in `/api/meta` |

Every control is labelled and keyboard reachable, wide tables scroll inside their
own card rather than stretching the page, and the network graph is mirrored as a
table so the relationships are readable without colour or hover.

### Supplier identifiers, and what the blacklist comparison can prove

MTender rarely publishes a supplier's `parties[].identifier` object. It puts the
fiscal code inside the party id instead, as `MD-IDNO-<code>`, so
`winner_identifier` is now derived from there and `winner_identifier_scheme` is
set to `MD-IDNO`. Without this the supplier identifier was `null` for **every**
one of the awarded records in the sample, which made supplier identity
unverifiable.

The AAP *Lista de interdicție* cannot be joined on that code. It is published as
a table of **company names only** — no IDNO, no fiscal code, no tender id — so
step `09` matches on a normalised legal name and says so in its own output:

| Match level | Meaning | Counted as |
|---|---|---|
| `exact_normalised` | identical after folding case, diacritics, punctuation, `S.R.L.`/`S.A.` and spelled-out legal forms | a match |
| `ambiguous` | one normalised name contains the other | a manual-review candidate, never a match |
| `none` | nothing comparable | no match |

Because the join is name-based it can both miss a supplier listed under an
abbreviation or a former name, and in principle match an unrelated company of the
same name. A match is a reason to read that award by hand, not evidence of
wrongdoing, and **a missing match does not clear a supplier**. The script writes
this limitation into `results/mongo/external_validation.json` so it cannot be
quoted without the caveat.

---

## 10. Point the pipeline at a local OCDS file instead of the API

The API is the primary source; this alternative exists for a bulk export you
already hold. Note that it bypasses `raw_tenders` immutability, so keep the
archived packages under `data/raw/ocds_packages/` as the audit trail.

1. Export releases from MTender / a national OCDS bulk file as JSON.
2. Acceptable shapes:
   - `[ { "ocid": "...", "tender": { ... }, "awards": [ ... ] }, ... ]`
   - `{ "releases": [ ... ] }`
3. Save e.g. `data/raw/mtender_ocds.json`.
4. With API running:

```bash
curl -X POST "http://127.0.0.1:8000/api/pipeline/run?source=ocds&ocds_path=/Users/imustyk/Diplom/data/raw/mtender_ocds.json"
```

Or from Python:

```bash
source .venv/bin/activate
python -c "from backend.ml.pipeline import run_pipeline; print(run_pipeline(source='ocds', ocds_path='data/raw/mtender_ocds.json'))"
```

On OCDS data, planted-label metrics are **not** available (`metrics.available = false`). Evaluate with expert review and Precision@K as described in the thesis.

A tiny fixture is included at `data/raw/sample_ocds.json` so you can test the loader without a full dump:

```bash
python -c "from backend.ml.pipeline import run_pipeline; print(run_pipeline(source='ocds', ocds_path='data/raw/sample_ocds.json'))"
```

Then restart or hit Overview — `n` will be small. Re-run the synthetic pipeline (step 5) to restore the 1,200-row demo.

---

## 11. How the model works (for the README and for Chapter 2)

**Indicators** (`src/mtender/features.py`, computed in `03_features_mongo.py`):

- competition: `n_bidders_log`, `single_bidder`, `no_bid_data`, `multi_supplier_award`
- value: `log_award_value`, `log_award_total`, `value_vs_cpv_median`, `value_zscore_cpv`,
  `estimate_to_award_ratio`, `multi_award_tender`
- timing: `bid_window_days`, `short_deadline`, `long_deadline`, `accelerated_like`
- procedure: `n_amendments`, `amended`, `cancelled`, `no_award_after_tender`
- relationship: `buyer_supplier_repeat_share`, `winner_share_of_buyer_awards`,
  `supplier_win_concentration`, `supplier_award_count_log`, guarded by
  `relationship_features_available` so a missing history is not read as a zero

`bids.details` holds one record **per lot**, not per bidder, so
`n_bid_records` counts bid records while `n_bidders` counts distinct tenderers.
Only the latter is a competition measure. Award amounts are summed across every
awarded lot (`award_total`) before being compared with `estimated_value`, which
covers the whole procedure.

**Detectors** (`scripts/06_detect_anomalies.py`), each at a 5% contamination
assumption:

- statistical MAD z-score, threshold 5.0. Binary indicators are reported as red
  flags rather than z-scores, and bounded spike-like ratios are left to the trees.
- Isolation Forest (300 trees)
- Local Outlier Factor (20 neighbours)
- One-Class SVM (RBF)

**Risk bands** are set by **model agreement**, not by a score threshold, because
the raw score scales differ by orders of magnitude (LOF scores run into the
hundreds, the SVM scores are negative):

| Band | Detectors that flagged the record |
|---|---|
| low | 0 |
| medium | 1 |
| high | 2 |
| critical | 3 or more (consensus) |

The percentile shown beside each band is `scores.rank(pct=True).max(axis=1)`: the
rank of the record's most extreme detector **within this dataset**. It is not a
probability and is not comparable between pipeline runs.

**What is deliberately not computed.** MTender publishes no per-bidder prices for
most procedures, no party registration dates, no direct-award or negotiated flag
and no per-procedure threshold, so bid spreads, winning margins, company age,
threshold proximity and round-price detection do not exist here. They are listed
with their reasons in `UNAVAILABLE` (`src/mtender/features.py`) and surfaced by
`/api/meta`. `scripts/08_data_dictionary.py` records, for every field, whether it
was actually present in the sampled live responses.

**Evaluation.** There is no public corrupt/not-corrupt label for Moldovan
procurements, so precision and recall are not computable on the real feed and the
API reports `metrics.available = false`. The legacy synthetic generator
(`backend/ml/`) exists solely to measure precision/recall against planted
patterns as a pipeline sanity check.

---

## 12. Windows notes

```bat
cd C:\path\to\Diplom
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m backend.ml.pipeline
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Second terminal:

```bat
cd C:\path\to\Diplom\frontend
npm install
npm run dev
```

---

## 13. Stop and clean

- API: `Ctrl+C` in the Uvicorn terminal
- UI: `Ctrl+C` in the Vite terminal
- Leave `data/processed/` if you want to reopen without retraining
- Delete artefacts and models:

```bash
rm -f data/processed/*.json data/processed/*.csv data/raw/tenders_synthetic.csv backend/models/detectors.joblib
```

- Remove environments (you will need steps 3–4 and 7 again):

```bash
rm -rf .venv frontend/node_modules
```

---

## 14. Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: python3` | Install Python 3.12; on macOS `brew install python@3.12` |
| `pip: command not found` | Activate `.venv` first |
| `ModuleNotFoundError: sklearn` | `pip install -r requirements.txt` inside `.venv` |
| `ModuleNotFoundError: backend` | Run commands from the repo root, not from `backend/` |
| `/api/stats` → 404 Run the pipeline first | Step 5 or Overview button |
| UI loads but data fails | API not on 8000; start Uvicorn |
| Port 8000 in use | `lsof -i :8000` then change `--port` **and** the proxy in `frontend/vite.config.ts` |
| Port 5173 in use | Vite will pick 5174; use the printed URL |
| `npm` errors on Apple Silicon | `node -p process.arch` should be `arm64`; reinstall Node via Homebrew |
| Isolation Forest too slow | Lower `n_tenders` in the POST query (e.g. 400) |

---

## 15. Project tree

```
Diplom/
  README.md
  requirements.txt / .env.example
  docker-compose.yml        ← MongoDB 6.0 as replica set rs0
  run_pipeline.sh (scripts/)← one-shot ETL driver
  src/mtender/              ← the ETL library
    api_client.py           ← MTender REST client, date-cursor pagination
    ocds.py                 ← package merging, CPV/locality, parties, awards
    normalize.py            ← norm_tenders / norm_parties
    features.py             ← indicators + UNAVAILABLE registry
    aggregations.py         ← MongoDB/pandas-aligned median pipelines
    mongo_client.py         ← connect, indexes, immutable upserts, cluster_info
    mongo_schema.py         ← collection names and indexes
  scripts/                  ← 00_check_api, 01a/01b, 02…08, seed_mongo
  backend/
    app/main.py             ← FastAPI
    app/adapter.py          ← real ETL fields -> UI contract, no fabrication
    app/store.py            ← tenders.json + anomaly_scores from MongoDB
    ml/                     ← legacy synthetic generator (evaluation only)
    models/                 ← detectors.joblib
  data/
    raw/ocid_inventory.jsonl    ← every OCID with its list date
    raw/ocds_packages/*.json.gz ← exact archived API responses
    processed/tenders.json      ← the snapshot the API serves
  results/                  ← tables, figures, mongo summaries
  docs/                     ← API investigation report, data dictionary
  thesis/                   ← STATUS.md working journal
  frontend/                 ← React + Vite + TypeScript prototype
  tests/                    ← pytest regression suite
```

---

## 16. Mapping to the three thesis chapters

1. **Chapter 1** — domain (Law 131/2015, MTender, red flags), goal, tasks, limitations (no court labels).
2. **Chapter 2** — this codebase: features, architecture, Isolation Forest / LOF / rules, hybrid score.
3. **Chapter 3** — run the demo, export `tenders_scored.csv`, discuss Precision@K and 5–10 case files from the Procedures page.

Screenshots: Overview, a critical case, the graph. Cite the disclaimer on every figure: scores are indicators for review, not proof of corruption.
