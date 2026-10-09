"""CRUD routes for the analyst workspace, plus the analytics aggregates.

Validation lives in Pydantic models so a bad payload is a 422 with a field-level
message rather than a 500 from deep inside SQLite. Enum-ish vocabularies are
checked explicitly: the store would happily accept ``status="banana"``, and a
typo'd status would silently vanish from every filter built on top of it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from backend.app import analytics as an
from backend.app import store
from src.mtender import workspace as ws

router = APIRouter(prefix="/api", tags=["workspace"])


# --------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------
def _check(value: str, allowed: list[str], label: str) -> str:
    if value not in allowed:
        raise HTTPException(422, f"{label} must be one of {allowed}, got {value!r}")
    return value


class CaseIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    status: str = "open"
    priority: str = "medium"
    owner: str = Field("", max_length=200)
    summary: str = Field("", max_length=8000)
    ocids: list[str] | str = Field(default_factory=list)


class CasePatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=300)
    status: str | None = None
    priority: str | None = None
    owner: str | None = Field(None, max_length=200)
    summary: str | None = Field(None, max_length=8000)
    ocids: list[str] | str | None = None

    def fields(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump(exclude_unset=True).items() if v is not None}


class AnnotationIn(BaseModel):
    ocid: str = Field(min_length=3, max_length=300)
    note: str = Field(min_length=1, max_length=8000)
    category: str = "observation"
    case_id: int | None = None
    author: str = Field("", max_length=200)


class AnnotationPatch(BaseModel):
    ocid: str | None = Field(None, min_length=3, max_length=300)
    note: str | None = Field(None, min_length=1, max_length=8000)
    category: str | None = None
    case_id: int | None = None
    author: str | None = Field(None, max_length=200)

    def fields(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump(exclude_unset=True).items() if v is not None}


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=4000)
    color: str = "navy"

    @field_validator("color")
    @classmethod
    def _color(cls, v: str) -> str:
        if v not in ws.WATCHLIST_COLORS:
            raise ValueError(f"color must be one of {sorted(ws.WATCHLIST_COLORS)}")
        return v


class WatchlistPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    color: str | None = None

    def fields(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump(exclude_unset=True).items() if v is not None}


class ItemsIn(BaseModel):
    ocids: list[str] | str
    note: str = Field("", max_length=2000)


class ItemPatch(BaseModel):
    note: str = Field("", max_length=2000)


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ViewPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    payload: dict[str, Any] | None = None

    def fields(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump(exclude_unset=True).items() if v is not None}


def _uniqueness(exc: Exception) -> HTTPException:
    return HTTPException(409, f"That name is already taken ({exc})")


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------
@router.get("/workspace/summary")
def workspace_summary():
    """Counts, vocabularies and the store revision. Cheap; safe to poll."""
    return ws.summary()


@router.get("/workspace/cases")
def cases(status: str | None = None, q: str = ""):
    return {"items": ws.list_cases(status=status, text=q), "vocab": {
        "status": ws.CASE_STATUS, "priority": ws.CASE_PRIORITY
    }}


@router.post("/workspace/cases", status_code=201)
def create_case(body: CaseIn):
    _check(body.status, ws.CASE_STATUS, "status")
    _check(body.priority, ws.CASE_PRIORITY, "priority")
    try:
        return ws.create_case(
            title=body.title,
            status=body.status,
            priority=body.priority,
            owner=body.owner,
            summary=body.summary,
            ocids=body.ocids,
        )
    except Exception as exc:  # noqa: BLE001
        raise _uniqueness(exc) from exc


@router.get("/workspace/cases/{case_id}")
def case_detail(case_id: int):
    case = ws.get_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return {
        "case": case,
        "ocids": ws.case_ocids(case),
        "annotations": ws.list_annotations(case_id=case_id),
    }


@router.patch("/workspace/cases/{case_id}")
def patch_case(case_id: int, body: CasePatch):
    if not ws.get_case(case_id):
        raise HTTPException(404, "Case not found")
    fields = body.fields()
    if "status" in fields:
        _check(fields["status"], ws.CASE_STATUS, "status")
    if "priority" in fields:
        _check(fields["priority"], ws.CASE_PRIORITY, "priority")
    try:
        return ws.update_case(case_id, fields)
    except Exception as exc:  # noqa: BLE001
        raise _uniqueness(exc) from exc


@router.delete("/workspace/cases/{case_id}")
def remove_case(case_id: int):
    if not ws.delete_case(case_id):
        raise HTTPException(404, "Case not found")
    return {"deleted": case_id}


# --------------------------------------------------------------------------
# annotations
# --------------------------------------------------------------------------
@router.get("/workspace/annotations")
def annotations(ocid: str | None = None, case_id: int | None = None, category: str | None = None, q: str = ""):
    return {
        "items": ws.list_annotations(ocid=ocid, case_id=case_id, category=category, text=q),
        "vocab": {"category": ws.ANNOTATION_CATEGORY},
    }


@router.post("/workspace/annotations", status_code=201)
def create_annotation(body: AnnotationIn):
    _check(body.category, ws.ANNOTATION_CATEGORY, "category")
    if body.case_id is not None and not ws.get_case(body.case_id):
        raise HTTPException(422, f"case_id {body.case_id} does not exist")
    return ws.create_annotation(
        ocid=body.ocid, note=body.note, category=body.category, case_id=body.case_id, author=body.author
    )


@router.patch("/workspace/annotations/{annotation_id}")
def patch_annotation(annotation_id: int, body: AnnotationPatch):
    if not ws.get_annotation(annotation_id):
        raise HTTPException(404, "Annotation not found")
    fields = body.fields()
    if "category" in fields:
        _check(fields["category"], ws.ANNOTATION_CATEGORY, "category")
    return ws.update_annotation(annotation_id, fields)


@router.delete("/workspace/annotations/{annotation_id}")
def remove_annotation(annotation_id: int):
    if not ws.delete_annotation(annotation_id):
        raise HTTPException(404, "Annotation not found")
    return {"deleted": annotation_id}


# --------------------------------------------------------------------------
# watchlists
# --------------------------------------------------------------------------
@router.get("/workspace/watchlists")
def watchlists():
    return {"items": ws.list_watchlists(), "colors": ws.WATCHLIST_COLORS}


@router.post("/workspace/watchlists", status_code=201)
def create_watchlist(body: WatchlistIn):
    try:
        return ws.create_watchlist(name=body.name, description=body.description, color=body.color)
    except Exception as exc:  # noqa: BLE001
        raise _uniqueness(exc) from exc


@router.get("/workspace/watchlists/{watchlist_id}")
def watchlist_detail(watchlist_id: int):
    wl = ws.get_watchlist(watchlist_id)
    if not wl:
        raise HTTPException(404, "Watchlist not found")
    return {"watchlist": wl, "items": ws.list_watchlist_items(watchlist_id)}


@router.patch("/workspace/watchlists/{watchlist_id}")
def patch_watchlist(watchlist_id: int, body: WatchlistPatch):
    if not ws.get_watchlist(watchlist_id):
        raise HTTPException(404, "Watchlist not found")
    try:
        return ws.update_watchlist(watchlist_id, body.fields())
    except Exception as exc:  # noqa: BLE001
        raise _uniqueness(exc) from exc


@router.delete("/workspace/watchlists/{watchlist_id}")
def remove_watchlist(watchlist_id: int):
    if not ws.delete_watchlist(watchlist_id):
        raise HTTPException(404, "Watchlist not found")
    return {"deleted": watchlist_id}


@router.post("/workspace/watchlists/{watchlist_id}/items")
def add_items(watchlist_id: int, body: ItemsIn):
    added = ws.add_watchlist_items(watchlist_id, body.ocids, body.note)
    if added == -1:
        raise HTTPException(404, "Watchlist not found")
    return {"added": added, "items": ws.list_watchlist_items(watchlist_id)}


@router.patch("/workspace/watchlists/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch):
    if not ws.update_watchlist_item(item_id, body.note):
        raise HTTPException(404, "Item not found")
    return {"updated": item_id}


@router.delete("/workspace/watchlists/items/{item_id}")
def remove_item(item_id: int):
    if not ws.delete_watchlist_item(item_id):
        raise HTTPException(404, "Item not found")
    return {"deleted": item_id}


# --------------------------------------------------------------------------
# saved views
# --------------------------------------------------------------------------
@router.get("/workspace/views")
def views():
    return {"items": ws.list_saved_views()}


@router.post("/workspace/views", status_code=201)
def create_view(body: ViewIn):
    try:
        return ws.create_saved_view(name=body.name, payload=body.payload, description=body.description)
    except Exception as exc:  # noqa: BLE001
        raise _uniqueness(exc) from exc


@router.patch("/workspace/views/{view_id}")
def patch_view(view_id: int, body: ViewPatch):
    if not ws.get_saved_view(view_id):
        raise HTTPException(404, "View not found")
    try:
        return ws.update_saved_view(view_id, body.fields())
    except Exception as exc:  # noqa: BLE001
        raise _uniqueness(exc) from exc


@router.delete("/workspace/views/{view_id}")
def remove_view(view_id: int):
    if not ws.delete_saved_view(view_id):
        raise HTTPException(404, "View not found")
    return {"deleted": view_id}


@router.get("/workspace/activity")
def activity(limit: int = Query(40, ge=1, le=200)):
    return {"items": ws.recent_activity(limit)}


@router.post("/workspace/reset")
def reset_workspace(confirm: bool = False):
    """Wipes every workspace row. Requires ``confirm=true`` as a guard."""
    if not confirm:
        raise HTTPException(409, "Pass confirm=true to delete all workspace rows")
    ws.reset()
    return ws.summary()


# --------------------------------------------------------------------------
# analytics
# --------------------------------------------------------------------------
def _rows() -> list[dict]:
    if not store.artefacts_ready():
        raise HTTPException(404, "Run the pipeline first")
    return store.load_tenders()


@router.get("/analytics/features")
def analytics_features():
    return an.feature_catalog(_rows())


@router.get("/analytics/correlations")
def analytics_correlations(
    features: str | None = None,
    method: str = "pearson",
    min_abs: float = Query(0.0, ge=0.0, le=1.0),
    top: int = Query(20, ge=1, le=200),
):
    """Pearson/Spearman matrix. ``features`` is a comma-separated column list."""
    if method not in {"pearson", "spearman", "kendall"}:
        raise HTTPException(422, "method must be pearson, spearman or kendall")
    cols = [c.strip() for c in features.split(",") if c.strip()] if features else list(an.FEATURES)
    return an.correlations(_rows(), cols, method=method, min_abs=min_abs, top=top)


@router.get("/analytics/distribution")
def analytics_distribution(
    column: str,
    bins: int = Query(40, ge=5, le=200),
    group: str | None = None,
    log_x: bool = False,
    scale: str = "auto",
):
    if column not in an.FEATURES:
        raise HTTPException(422, f"unknown column {column!r}; see /api/analytics/features")
    if group and group not in an.CATEGORIES:
        raise HTTPException(422, f"unknown group {group!r}")
    if scale not in {"auto", "linear", "log", "quantile"}:
        raise HTTPException(422, "scale must be auto, linear, log or quantile")
    return an.distribution(_rows(), column, bins=bins, group=group, log_x=log_x, scale=scale)


@router.get("/analytics/scatter")
def analytics_scatter(
    x: str,
    y: str,
    group: str | None = None,
    limit: int = Query(4000, ge=100, le=20000),
    log_x: bool = False,
    log_y: bool = False,
):
    for col in (x, y):
        if col not in an.FEATURES:
            raise HTTPException(422, f"unknown column {col!r}; see /api/analytics/features")
    if group and group not in an.CATEGORIES:
        raise HTTPException(422, f"unknown group {group!r}")
    return an.scatter(_rows(), x, y, group=group, limit=limit, log_x=log_x, log_y=log_y)


@router.get("/analytics/group-compare")
def analytics_group_compare(
    value: str,
    group: str,
    limit: int = Query(14, ge=2, le=40),
):
    if value not in an.FEATURES:
        raise HTTPException(422, f"unknown value column {value!r}")
    if group not in an.CATEGORIES:
        raise HTTPException(422, f"unknown group {group!r}")
    return an.group_compare(_rows(), value, group, limit=limit)


@router.get("/analytics/crosstab")
def analytics_crosstab(
    a: str,
    b: str,
    value: str | None = None,
    limit: int = Query(18, ge=2, le=40),
):
    for col in (a, b):
        if col not in an.CATEGORIES:
            raise HTTPException(422, f"unknown category {col!r}")
    if value and value not in an.FEATURES:
        raise HTTPException(422, f"unknown value column {value!r}")
    return an.crosstab(_rows(), a, b, limit=limit, value=value)


@router.get("/analytics/timeseries")
def analytics_timeseries(
    date_field: str = "list_date",
    grain: str = "month",
    group: str | None = None,
    value: str = "award_total_mdl",
):
    if date_field not in an.DATES:
        raise HTTPException(422, f"unknown date field {date_field!r}")
    if grain not in {"day", "week", "month", "quarter", "year"}:
        raise HTTPException(422, "grain must be day, week, month, quarter or year")
    if group and group not in an.CATEGORIES:
        raise HTTPException(422, f"unknown group {group!r}")
    return an.timeseries(_rows(), date_field=date_field, grain=grain, group=group, value=value)
