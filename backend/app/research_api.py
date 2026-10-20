"""Research endpoints: dataset provenance, evaluation, explainability.

Added 2026-10-20 on branch ``feature/risk-specific-detection`` to satisfy the
real-data integration brief: the dashboard must be able to show *where the
data came from*, *how the model performs on external proxy labels* (with the
negative results visible), and *why an individual procedure scored high* -
all served from artefacts that actually exist on disk. Missing artefacts
degrade to ``available: false`` payloads instead of fabricated numbers.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import store
from .explain import build_explanation

router = APIRouter(prefix="/api", tags=["research"])


@router.get("/dataset")
def dataset(
    verify_hash: bool = Query(
        False,
        description="Recompute SHA-256 of manifest-covered files and compare "
        "against results/mongo/export_manifest.json (cached separately).",
    ),
) -> dict:
    """Dataset metadata: counts, origin (real vs synthetic), provenance, model."""
    return store.load_dataset_report(verify_hash=verify_hash)


@router.get("/evaluation")
def evaluation() -> dict:
    """Research evaluation metrics: external labels with cluster CIs, seed and
    noise stability, drift, bias - negative results included as measured."""
    return store.load_evaluation()


@router.get("/explainability")
def explainability() -> dict:
    """Global explainability artefacts, including the measured SHAP/LIME
    disagreement (reported, not hidden)."""
    return store.load_explainability()


@router.get("/tenders/{tender_id}/explanation")
def tender_explanation(tender_id: str) -> dict:
    """Deterministic layered explanation for one procedure.

    404 (not a fallback) for unknown ids, same as the detail endpoint.
    """
    row = next(
        (r for r in store.load_tenders() if r.get("tender_id") == tender_id), None
    )
    if row is None:
        raise HTTPException(status_code=404, detail="unknown tender id")
    xai = store.load_explainability().get("xai_consistency") or {}
    run = store.detection_run()
    return build_explanation(
        row,
        store.load_population_stats(),
        xai_verdict=xai.get("verdict"),
        scoring_run_id=run.get("run_id"),
        scoring_generated_at=run.get("generated_at"),
    )
