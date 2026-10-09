# Project Audit Report

**Date:** 2026-10-09 · **Scope:** full project audit, bug fixing, dead-code removal, environment
rebuild, ETL re-run, service restart.

**Decisions taken (agreed up front):**
- Keep `backend/` + `frontend/` as the product surface; remove the Streamlit front-end.
- Conservative deletion: only code proven unreferenced anywhere (code, docs, tests, scripts) is
  removed; everything else is listed below for a decision.
- Offline ETL rebuild from the archived response bodies — not a full API crawl.

---

## 0. Safety net

The folder was **not** a git repository, so a `git init` + `pre-audit snapshot` commit was made
first (103 source files, 2.4 MB; `data/`, `results/`, `.venv/`, `node_modules/` excluded). Every
change below is recoverable from that commit.

A full `mongodump` of the live database was also taken before the rebuild:

```
results/backup/pre_audit/mtender/   1.9 GB   (all collections, pre-rebuild state)
```

---

## 1. Baseline

| Check | Before |
|---|---|
| `pytest` | **66 passed, 2 failed** |
| `ruff check --select F,E9` | **25 errors** (15 unused imports, 6 repeated dict keys, 2 undefined names, 2 unused locals) |
| `tsc --noEmit` | clean |
| `vite build` | clean (650 kB chunk warning) |
| Backend imports | all 5 modules import cleanly |
| Live MTender API | **HTTP 200, 0 bytes — the API serves nothing** |

---

## 2. Defects found and fixed

### 2.1 Two failing tests encoded a superseded behaviour — **fixed**

`tests/test_backend_adapter.py` asserted `risk_level(None) == "low"` in two places
(`test_risk_level_bands_on_model_agreement[None]` and
`test_project_tender_without_scores_is_still_valid`).

The *code* is correct and deliberately documented otherwise: `backend/app/adapter.py::risk_level`
returns `"unscored"`, with a docstring explaining that folding the unscored majority into `low`
"would assert that tens of thousands of procedures were examined and cleared". The same band is
wired through `backend/app/store.py`, `frontend/src/api.ts` (`RiskLevel` union), `Overview.tsx`
(coverage banner), `Network.tsx` and `ui.tsx`.

So the **tests were stale** — they still encoded the pre-fix behaviour that defect #4 in
`docs/PROJECT_OVERVIEW.md` records as a bug that was already fixed. Tests updated to expect
`"unscored"`, with comments recording why. No production code changed.

### 2.2 `scripts/00_check_api.py` — dead local in `check_history_depth` — **removed**

`url = f"{MTENDER_BASE}/tenders/?limit=1&offset={cursor}"` was built on every loop iteration and
never used; the real request goes through `client.fetch_page(1, cursor)`. (ruff F841)

### 2.3 `src/mtender/features.py` — dead leftover from an earlier bug fix — **removed**

`idx = pd.MultiIndex.from_arrays([work["_buyer"], work["_winner"]])` was unused. The comment
directly below it explains that index-alignment "silently produces the wrong length" and that the
code now maps through dicts instead — so `idx` was the dead residue of that fix. (ruff F841)

### 2.4 15 unused imports — **removed**

| File | Imports removed |
|---|---|
| `backend/app/store.py` | `Path`, `risk_level`, `MONGO_DB_NAME` |
| `scripts/01a_scan_ocids.py` | `MONGO_DB_NAME` |
| `scripts/01b_fetch_records.py` | `MAX_LIMIT` |
| `scripts/06_detect_anomalies.py` | `RobustScaler` |
| `tests/test_pipeline.py` | `datetime`, `find_party` |

(ruff F401, auto-fixed)

### 2.5 `/api/tenders/{id}` could 500 on malformed rows — **fixed**

`backend/app/main.py::tender_detail` called `json.loads()` on `flags` and `bids_json` with no
guard, while the list endpoint `/api/tenders` wrapped the identical parse in
`try/except json.JSONDecodeError`. One malformed row would have turned the detail view into a 500.
Both fields now use the same guard as the list endpoint.

### 2.6 Repeated dict keys in `dashboard/components/charts.py` (ruff F601) — *moot*

`{0: …, 1: …, False: …, True: …}` duplicates keys (`False` hashes to `0`). Found and reported, but
the file was removed with the Streamlit front-end before any fix was needed.

---

## 3. Dead code removed

### 3.1 The entire Streamlit front-end (agreed)

| Removed | Size |
|---|---|
| `app.py` | 131 lines |
| `dashboard/` (13 pages, 5 components, 4 utils) | ~3,500 lines / 19 files |
| `.streamlit/config.toml` | — |
| `requirements.txt`: `streamlit`, `plotly` | 2 pins |
| README §7b, §8a Streamlit column, project-tree entry | ~47 lines |
| `docs/PROJECT_OVERVIEW.md`: architecture diagram, §10, §13, §14 | ~44 lines |

`openpyxl` was **kept**: `scripts/10_load_mof_opendata.py` calls `pd.ExcelFile()` on the Ministry
of Finance `.xlsx` extracts. It was only moved out of the Streamlit comment block.

No Python module outside `app.py`/`dashboard/` imported anything from the removed surface —
verified before deletion. The remaining `"dashboard"` strings in `backend/`, `src/` and `scripts/`
are prose meaning "the UI", not imports.

### 3.2 Symbols proven unreferenced (code + docs + tests + scripts)

| Location | Symbol | Evidence |
|---|---|---|
| `src/mtender/aggregations.py` | `count_where_pipeline` | definition only |
| `src/mtender/aggregations.py` | `count_where_to_csv_pipeline` | definition only |
| `src/mtender/normalize.py` | `VALID_AWARD_STATUS` | definition only (sibling `VALID_TENDER_STATUS` *is* used) |
| `src/mtender/workspace.py` | `saved_view_payload` | definition only |
| `scripts/08_data_dictionary.py` | `_norm` | definition only |
| `frontend/src/api.ts` | `RISK_ORDER` | exported, never imported |
| `frontend/src/api.ts` | `Indicators` type | exported, never imported |

### 3.3 Caches

Removed `__pycache__/` (root, contained a stale `app.cpython-311.pyc` for the deleted Streamlit
entry point), `.pytest_cache/`, `.ruff_cache/`.

### 3.4 Orphaned file

`package-lock.json` at the repository root — an empty stub
(`{"name": "Diplom", "packages": {}}`) with **no root `package.json`** and no reference anywhere in
the docs, scripts or frontend. Removed.

---

## 4. Flagged, **not** removed — needs your decision

Conservative policy: these are unreferenced by the UI but back endpoints that are live and
documented in the README, so deleting them would silently reduce documented capability.

**Three dead client wrappers in `frontend/src/api.ts`** (0 call sites anywhere):

| Wrapper | Backend route | Documented |
|---|---|---|
| `getTimeSeries` | `GET /api/analytics/timeseries` | README §8b |
| `resetWorkspace` | `POST /api/workspace/reset?confirm=true` | README §8a, `docs/PROJECT_OVERVIEW.md` §11 |
| `updateWatchlistItem` | `PATCH /api/workspace/watchlists/items/{id}` | — |

Consequences if left: the UI has **no** time-series chart, **no** "clear workspace" button and **no**
watchlist-item note editor. All three are reachable only by `curl`. Removing the wrappers (keeping
the routes) is a one-line-each change; removing both sides is larger.

**Other observations, deliberately left alone:**

- `/api/indicators` and `/api/pipeline/run` have no UI path. Both are documented in the README
  (`/api/pipeline/run` is the documented `curl` escape hatch, guarded by `confirm=true` for
  synthetic data).
- `/api/pipeline/run` is unauthenticated. Acceptable for a localhost research tool; it would need a
  guard before any non-local deployment.
- `backend/ml/` is legacy synthetic-generator code — **kept on purpose** per README (Chapter 3
  precision/recall evaluation) and reachable from `backend/app/main.py`.
- Heuristic scan flagged ~13 CSS selectors as possibly unreferenced. Manual check showed most are
  reached through template-literal class construction (`badge ${key}`, `dot ${key}`,
  `tone-${tone}`, `node-${kind}`), so **no CSS was removed**.

---

## 5. Dependency findings

**Python** — no advisories surfaced; all 57 packages are pinned to exact versions.

**Node** — `npm audit`: 3 advisories before the fix.

| Package | Severity | Status |
|---|---|---|
| `source-map-js` | **high** (event-loop DoS) | **fixed** via non-breaking `npm audit fix` |
| `react-router` / `react-router-dom` | moderate ×2 (open redirect, constructor injection) | **not fixed** — only fix is `react-router-dom@7.18.4`, a **breaking** major upgrade |

`react-router-dom` is genuinely used (`App.tsx`, `main.tsx`, `Tenders.tsx`, `TenderDetail.tsx`), so
it is not dead weight. Upgrading to v7 changes `<Routes>`/`useNavigate` semantics and should be its
own deliberate task, not an audit side effect.

---

## 6. Environment rebuild

| | |
|---|---|
| `.venv` | deleted and recreated from scratch (`python3 -m venv`), `pip install -r requirements.txt` → **57 packages, exit 0** |
| `frontend/node_modules` | deleted, `npm ci` from the lockfile → **exit 0** |
| Post-rebuild `pytest` | **68 passed** |
| Post-rebuild `tsc --noEmit` + `vite build` | **clean** |

---

## 7. ETL rebuild (offline)

Chosen depth: **rebuild from the archived response bodies, no API crawl.** This became the only
option anyway — see §1, the live API was serving empty responses.

### 7.1 Backup first

`mongodump` of the pre-rebuild database → `results/backup/pre_audit/mtender/` (**1.9 GB**, all
collections). The older `results/backup/pre_rebuild/` was left untouched.

### 7.2 Stages run

| Stage | Result |
|---|---|
| `seed_mongo.py --target mtender --drop` | **152,378** archived packages → `raw_tenders` 152,378, `raw_parties` 552,089; then ran `02_normalize` + `03_features` |
| `10_load_mof_opendata.py` | 2 workbooks → 36,067 rows (2026-07: 20,723 · 2025-12: 15,345), 1,462 authorities |
| `11_load_blacklist.py` | 22 entries, 21 operators |
| `04_export_snapshot.py` | `features.csv` 152,378 × 62 (85,211,084 B), `tenders.json` 248,705,265 B — both SHA-256 recorded |
| `05_aggregations.py` | 10 tables |
| `06_detect_anomalies.py` | 152,378 rows × 22 features; consensus ≥3 models: **3,069 (2.01%)** |
| `07_explainability.py` | 3,069 flagged vs 149,309 normal; SHAP over 12 features |
| `08_data_dictionary.py` | **skipped** — requires the live API, which was down |
| `09_external_validation.py` | 18 exact name matches out of 22 blacklist entries, 17,841 suppliers scored |

`PIPELINE_FAIL_FLAG=0` — every stage that ran succeeded.

### 7.3 Two consequences of `--drop`, both handled

1. **`raw_releases` (526,499) and `ingest_runs` (5) were destroyed** and have *no offline source* —
   `raw_releases` is the resumable-fetch checkpoint written only by the network stages `01a`/`01b`.
   Restored exactly from the pre-audit backup with `mongorestore`, so a future `01b` run still
   skips the 526k OCIDs it already holds.
2. **`raw_mof_procedures` and `raw_blacklist` went to 0** — these *were* rebuildable offline, and
   were correctly regenerated from `data/raw/opendata/*.xlsx` and
   `data/raw/blacklist/aap_lista_interdictie_2026-09-25.json`.

### 7.4 Pre-existing issue surfaced by stage 10 (not a regression)

The MoF cross-check reported `"compared": 0` and `"mof_rows_without_api_record": 36067` — **not one
MoF OCID matched the fetched records.** The two MoF extracts cover 2025-12 and 2026-07, while the
archived OCDS packages are older, so the overlap is genuinely empty. The cross-check therefore
compares nothing and reports success. This is a data-coverage gap worth a thesis footnote; it is
independent of this audit (the archive is byte-identical to before).

### 7.5 Final database state

```
anomaly_scores        152,378     features_tenders   152,378     norm_tenders     152,378
norm_parties          552,089     raw_parties        552,089     raw_tenders      152,378
raw_releases          526,499     raw_mof_procedures  36,067     raw_blacklist         22
ingest_runs                  5   validation_reports      1
```

20 CSV tables and 2 PNG figures regenerated (timestamps 2026-10-09 09:13–09:14).

### 7.6 Model output

| `n_models_flagging` | count | derived band |
|---|---|---|
| 0 | 125,261 | low |
| 1 | 19,409 | medium |
| 2 | 4,639 | high |
| 3 | 2,397 | critical |
| 4 | 672 | critical |
| `None` | **0** | unscored |

Every record now carries detector output, so the `unscored` band is empty for this run. The band
itself is kept — it is the honest answer whenever the corpus *is* scored sparsely, and
`frontend/src/api.ts` still renders it as its own colour rather than folding it into `low`.

---

## 8. Service restart

Nothing was running at audit start except `mongod` (system service). State:

| Service | State |
|---|---|
| MongoDB | `mongod` 6.0.18, replica set **`rs0` → PRIMARY**, `supports_transactions: True` (needed for `src/mtender/workspace.py`) |
| FastAPI | started fresh: `.venv/bin/uvicorn backend.app.main:app --port 8000` |
| Vite dev | started fresh: `npm run dev` → `http://localhost:5173`, proxying `/api` → `:8000` |

Restarting the API was **required**, not cosmetic: `backend/app/store.py` caches artefacts under
`@lru_cache(maxsize=1)`, so a process started before `04_export_snapshot.py` would keep serving the
previous 251 MB `tenders.json`.

> One operator error worth recording: `uvicorn --loglevel` is invalid (it is `--log-level`); the
> first launch died with exit 2 and was relaunched correctly.

---

## 9. Verification matrix (final state)

| Check | Result |
|---|---|
| `pytest` | **68 passed** |
| `ruff check --select F,E9` | **All checks passed** (was 25 errors) |
| `tsc --noEmit` | clean |
| `vite build` | clean |
| `npm audit` | 2 moderate left (react-router, breaking fix only) |
| `pip install -r requirements.txt` | 57 packages, exit 0, no streamlit/plotly |
| `npm ci` | exit 0 |
| `GET /api/health` | `ok:true`, `artefacts:true`, rs0 PRIMARY, all collections populated |
| `GET /api/stats` | `n_tenders=152,378`, bands `{unscored:0, low:125261, medium:19409, high:4639, critical:3069}` |
| `GET /api/tenders?limit=2` | `total=152,378` |
| `/api/analytics/*` (7 routes) | all 200 |
| `/api/workspace/*` (6 routes) | all 200 |
| `POST /api/pipeline/run` (no confirm) | **409 guard works** |
| Vite proxy `/api/health` | 200 — full chain browser → Vite → FastAPI → Mongo |
| Vite module transforms (`main.tsx`, `App.tsx`, `api.ts`, `styles.css`) | all 200 |

**26/26 smoke-tested routes pass.** (Four initial 422s were incorrect query parameters in the test
harness itself — `group-compare` takes `value`, `crosstab` takes `a`/`b` — not server defects.)

The desktop browser was not connected to this session, so UI verification was done over HTTP rather
than visually.

---

## 10. Open items

1. **`react-router-dom` 2 moderate advisories** — only fixed by the breaking v7 upgrade. Needs its
   own task.
2. **3 dead client wrappers** in `frontend/src/api.ts` (§4) — remove, or wire up the UI.
3. **MoF cross-check compares nothing** (§7.4) — coverage gap, footnote-worthy.
4. **`/api/pipeline/run` is unauthenticated** — fine on localhost, must be guarded before deployment.
5. **Live MTender API down** — stages `00` and `08` cannot run until it recovers.
