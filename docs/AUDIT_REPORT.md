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

See §7 results below — recorded after the run completed.

---

## 8. Service restart

See §8 results below — recorded after the run completed.

---

## 9. Verification matrix

Final state after all stages.
