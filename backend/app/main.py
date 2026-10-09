from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app import store
from backend.app.workspace_api import router as workspace_router

app = FastAPI(
    title="Moldova Procurement Risk Intelligence",
    description="Anomaly detection and corruption-risk indicators for public procurement (MTender / OCDS).",
    version="1.1.0",
)

app.include_router(workspace_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    """Liveness plus the MongoDB topology the API is actually connected to."""
    return {
        "ok": True,
        "artefacts": store.artefacts_ready(),
        "source": "mtender-ocds",
        "model_present": store.model_present(),
        "mongodb": store.mongo_status(),
    }


@app.post("/api/pipeline/run")
def pipeline_run(
    source: str = "synthetic",
    n_tenders: int = 1200,
    ocds_path: str | None = None,
    confirm: bool = False,
):
    """Regenerate artefacts.

    The synthetic generator writes the same files as the real ETL
    (``data/processed/tenders.json``), so calling it without ``confirm=true``
    would silently replace real procurement data with invented records.
    Synthetic runs are therefore blocked unless explicitly confirmed, and the
    response says which dataset is now being served.
    """
    if source not in {"synthetic", "ocds"}:
        raise HTTPException(400, "source must be 'synthetic' or 'ocds'")
    if source == "synthetic" and not confirm:
        raise HTTPException(
            409,
            "Refusing to overwrite the real ETL output in data/processed/ with "
            "synthetic records. Re-run scripts/01a-08 for real data, or pass "
            "confirm=true if you really want a synthetic demo dataset.",
        )
    from backend.ml.pipeline import run_pipeline

    result = run_pipeline(source=source, ocds_path=ocds_path, n_tenders=n_tenders)
    store.invalidate()
    return result


@app.get("/api/meta")
def meta():
    if not store.artefacts_ready():
        raise HTTPException(404, "Run the pipeline first")
    return store.load_meta()


@app.get("/api/stats")
def stats():
    if not store.artefacts_ready():
        raise HTTPException(404, "Run the pipeline first")
    return store.load_stats()


@app.get("/api/graph")
def graph():
    if not store.artefacts_ready():
        raise HTTPException(404, "Run the pipeline first")
    return store.load_graph()


@app.get("/api/tenders")
def tenders(
    q: str | None = None,
    level: str | None = None,
    procedure: str | None = None,
    buyer: str | None = None,
    min_risk: float = Query(0, ge=0, le=100),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if not store.artefacts_ready():
        raise HTTPException(404, "Run the pipeline first")
    rows = store.load_tenders()
    if q:
        needle = q.lower()
        rows = [
            r
            for r in rows
            if needle in (r.get("title") or "").lower()
            or needle in (r.get("buyer_name") or "").lower()
            or needle in (r.get("winner_name") or "").lower()
            or needle in (r.get("tender_id") or "").lower()
        ]
    if level:
        rows = [r for r in rows if r.get("risk_level") == level]
    if procedure:
        rows = [r for r in rows if r.get("procedure") == procedure]
    if buyer:
        rows = [r for r in rows if r.get("buyer_id") == buyer]
    rows = [r for r in rows if (r.get("risk_score") or 0) >= min_risk]
    total = len(rows)
    slice_ = []
    for raw in rows[offset : offset + limit]:
        r = dict(raw)
        flags = r.get("flags")
        if isinstance(flags, str):
            try:
                r["flags"] = json.loads(flags)
            except json.JSONDecodeError:
                r["flags"] = []
        bids = r.get("bids_json")
        if isinstance(bids, str):
            try:
                r["bids"] = json.loads(bids)
            except json.JSONDecodeError:
                r["bids"] = []
        slice_.append(r)
    return {"total": total, "items": slice_}


@app.get("/api/tenders/{tender_id}")
def tender_detail(tender_id: str):
    if not store.artefacts_ready():
        raise HTTPException(404, "Run the pipeline first")
    for r in store.load_tenders():
        if r.get("tender_id") == tender_id:
            item = dict(r)
            # Same guards as the list endpoint: one malformed row must not turn
            # the whole detail view into a 500.
            if isinstance(item.get("flags"), str):
                try:
                    item["flags"] = json.loads(item["flags"])
                except json.JSONDecodeError:
                    item["flags"] = []
            if isinstance(item.get("bids_json"), str):
                try:
                    item["bids"] = json.loads(item["bids_json"])
                except json.JSONDecodeError:
                    item["bids"] = []
            return item
    raise HTTPException(404, "Tender not found")


@app.get("/api/indicators")
def indicators():
    """Mean of each real indicator per risk band - used in Chapter 3 charts.

    Keys are the features the ETL actually computes. Indicators MTender does
    not publish are listed in /api/meta under "unavailable" and are absent here
    rather than reported as 0.
    """
    if not store.artefacts_ready():
        raise HTTPException(404, "Run the pipeline first")
    return store.load_indicators()
