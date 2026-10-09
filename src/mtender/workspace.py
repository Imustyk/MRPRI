"""Analyst workspace: investigation cases, annotations, watchlists and saved views.

Deliberately dependency-free (standard library only) and free of any web
framework import, so the same store can back any front-end without a web
framework owning it.

The research pipeline output in ``data/`` and ``results/`` is treated as
**read-only**. Everything an analyst creates lives in a separate SQLite file, so
the ETL artefacts stay reproducible and can always be regenerated from source.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = ROOT / "data" / "workspace"
DB_PATH = WORKSPACE_DIR / "workspace.db"

CASE_STATUS = ["open", "in review", "escalated", "closed", "dismissed"]
CASE_PRIORITY = ["low", "medium", "high", "critical"]
ANNOTATION_CATEGORY = [
    "observation",
    "single bidder",
    "repeat relationship",
    "value anomaly",
    "documentation gap",
    "follow-up",
    "cleared",
]
WATCHLIST_COLORS = {
    "navy": "#1e3a5f",
    "gold": "#b8892a",
    "red": "#b4232c",
    "green": "#2a6b4a",
    "teal": "#2a7f8f",
    "plum": "#6b4a86",
}

#: Bumped by every mutation. Consumers poll it to know when their cached reads
#: are stale without having to guess.
REVISION = 0

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ref         TEXT    NOT NULL UNIQUE,
    title       TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open',
    priority    TEXT    NOT NULL DEFAULT 'medium',
    owner       TEXT    NOT NULL DEFAULT '',
    summary     TEXT    NOT NULL DEFAULT '',
    ocids       TEXT    NOT NULL DEFAULT '[]',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ocid        TEXT    NOT NULL,
    case_id     INTEGER REFERENCES cases(id) ON DELETE SET NULL,
    category    TEXT    NOT NULL DEFAULT 'observation',
    note        TEXT    NOT NULL,
    author      TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT '',
    color       TEXT    NOT NULL DEFAULT 'navy',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    ocid         TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    added_at     TEXT    NOT NULL,
    UNIQUE (watchlist_id, ocid)
);

CREATE TABLE IF NOT EXISTS saved_views (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT '',
    payload     TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    entity     TEXT NOT NULL,
    entity_id  INTEGER,
    action     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_annotations_ocid  ON annotations(ocid);
CREATE INDEX IF NOT EXISTS idx_annotations_case ON annotations(case_id);
CREATE INDEX IF NOT EXISTS idx_items_watchlist   ON watchlist_items(watchlist_id);
CREATE INDEX IF NOT EXISTS idx_activity_at      ON activity(at DESC);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Open a connection, apply the schema, and commit on clean exit."""
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _bump() -> int:
    global REVISION
    with _lock:
        REVISION += 1
        return REVISION


def revision() -> int:
    return REVISION


def _log(con: sqlite3.Connection, entity: str, entity_id: int | None, action: str, detail: str = "") -> None:
    con.execute(
        "INSERT INTO activity (at, entity, entity_id, action, detail) VALUES (?,?,?,?,?)",
        (now_iso(), entity, entity_id, action, detail[:400]),
    )


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with transaction() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def _one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with transaction() as con:
        row = con.execute(sql, params).fetchone()
        return dict(row) if row else None


def clean_ocids(values: Any) -> list[str]:
    """Accept a list, or a pasted blob of newlines/commas, and return unique ids."""
    out: list[str] = []
    if values is None:
        return out
    if isinstance(values, str):
        values = values.replace("\n", ",").replace("\t", ",").split(",")
    for value in values:
        for part in str(value).replace("\n", ",").split(","):
            token = part.strip()
            if token and token not in out:
                out.append(token)
    return out


# ==========================================================================
# cases
# ==========================================================================
def list_cases(status: str | None = None, text: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM cases"
    where: list[str] = []
    params: list[Any] = []
    if status and status != "all":
        where.append("status = ?")
        params.append(status)
    if text and text.strip():
        where.append("(LOWER(title) LIKE ? OR LOWER(ref) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(owner) LIKE ?)")
        q = f"%{text.strip().lower()}%"
        params += [q, q, q, q]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (
        " ORDER BY CASE status WHEN 'escalated' THEN 0 WHEN 'in review' THEN 1"
        " WHEN 'open' THEN 2 ELSE 3 END, updated_at DESC"
    )
    return _rows(sql, tuple(params))


def get_case(case_id: int) -> dict[str, Any] | None:
    return _one("SELECT * FROM cases WHERE id = ?", (case_id,))


def _next_case_ref(con: sqlite3.Connection) -> str:
    year = datetime.now(timezone.utc).year
    row = con.execute(
        "SELECT ref FROM cases WHERE ref LIKE ? ORDER BY id DESC LIMIT 1",
        (f"CASE-{year}-%",),
    ).fetchone()
    n = 0
    if row:
        try:
            n = int(str(row["ref"]).rsplit("-", 1)[1])
        except (ValueError, IndexError):
            n = 0
    return f"CASE-{year}-{n + 1:04d}"


def create_case(
    title: str,
    status: str = "open",
    priority: str = "medium",
    owner: str = "",
    summary: str = "",
    ocids: Any = None,
) -> dict[str, Any]:
    ocid_list = clean_ocids(ocids)
    with transaction() as con:
        ref = _next_case_ref(con)
        cur = con.execute(
            "INSERT INTO cases (ref,title,status,priority,owner,summary,ocids,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ref,
                title.strip(),
                status,
                priority,
                owner.strip(),
                summary.strip(),
                json.dumps(ocid_list),
                now_iso(),
                now_iso(),
            ),
        )
        cid = int(cur.lastrowid)
        _log(con, "case", cid, "create", f"{ref} — {title.strip()}")
    _bump()
    return get_case(cid) or {}


def update_case(case_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"title", "status", "priority", "owner", "summary", "ocids"}
    sets, params = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(json.dumps(clean_ocids(value)) if key == "ocids" else (value.strip() if isinstance(value, str) else value))
    if not sets:
        return get_case(case_id)
    sets.append("updated_at = ?")
    params += [now_iso(), case_id]
    with transaction() as con:
        cur = con.execute(f"UPDATE cases SET {', '.join(sets)} WHERE id = ?", tuple(params))
        if cur.rowcount == 0:
            return None
        _log(con, "case", case_id, "update", ", ".join(fields.keys()))
    _bump()
    return get_case(case_id)


def delete_case(case_id: int) -> bool:
    with transaction() as con:
        row = con.execute("SELECT ref, title FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            return False
        con.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        _log(con, "case", case_id, "delete", f"{row['ref']} — {row['title']}")
    _bump()
    return True


def case_ocids(case: dict[str, Any]) -> list[str]:
    try:
        return clean_ocids(json.loads(case.get("ocids") or "[]"))
    except json.JSONDecodeError:
        return []


def case_stats() -> dict[str, int]:
    rows = _rows("SELECT status, COUNT(*) AS n FROM cases GROUP BY status")
    stats = {r["status"]: int(r["n"]) for r in rows}
    stats["total"] = sum(v for k, v in stats.items() if k in CASE_STATUS)
    return stats


# ==========================================================================
# annotations
# ==========================================================================
def list_annotations(
    ocid: str | None = None,
    case_id: int | None = None,
    category: str | None = None,
    text: str = "",
) -> list[dict[str, Any]]:
    sql = (
        "SELECT a.*, c.ref AS case_ref, c.title AS case_title"
        " FROM annotations a LEFT JOIN cases c ON c.id = a.case_id"
    )
    where: list[str] = []
    params: list[Any] = []
    if ocid:
        where.append("a.ocid = ?")
        params.append(ocid)
    if case_id:
        where.append("a.case_id = ?")
        params.append(case_id)
    if category and category != "all":
        where.append("a.category = ?")
        params.append(category)
    if text and text.strip():
        where.append("(LOWER(a.note) LIKE ? OR LOWER(a.ocid) LIKE ?)")
        q = f"%{text.strip().lower()}%"
        params += [q, q]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.updated_at DESC"
    return _rows(sql, tuple(params))


def get_annotation(annotation_id: int) -> dict[str, Any] | None:
    return _one("SELECT * FROM annotations WHERE id = ?", (annotation_id,))


def create_annotation(
    ocid: str,
    note: str,
    category: str = "observation",
    case_id: int | None = None,
    author: str = "",
) -> dict[str, Any]:
    with transaction() as con:
        cur = con.execute(
            "INSERT INTO annotations (ocid,case_id,category,note,author,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (ocid.strip(), case_id, category, note.strip(), author.strip(), now_iso(), now_iso()),
        )
        aid = int(cur.lastrowid)
        _log(con, "annotation", aid, "create", f"{ocid} — {category}")
    _bump()
    return _one("SELECT * FROM annotations WHERE id = ?", (aid,)) or {}


def update_annotation(annotation_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"note", "category", "author", "case_id", "ocid"}
    sets, params = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(value.strip() if isinstance(value, str) else value)
    if not sets:
        return _one("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    sets.append("updated_at = ?")
    params += [now_iso(), annotation_id]
    with transaction() as con:
        cur = con.execute(f"UPDATE annotations SET {', '.join(sets)} WHERE id = ?", tuple(params))
        if cur.rowcount == 0:
            return None
        _log(con, "annotation", annotation_id, "update", ", ".join(fields.keys()))
    _bump()
    return _one("SELECT * FROM annotations WHERE id = ?", (annotation_id,))


def delete_annotation(annotation_id: int) -> bool:
    with transaction() as con:
        cur = con.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        ok = cur.rowcount > 0
        if ok:
            _log(con, "annotation", annotation_id, "delete", "")
    _bump()
    return ok


# ==========================================================================
# watchlists
# ==========================================================================
def list_watchlists() -> list[dict[str, Any]]:
    return _rows(
        "SELECT w.*, (SELECT COUNT(*) FROM watchlist_items i WHERE i.watchlist_id = w.id) AS n_items"
        " FROM watchlists w ORDER BY w.name"
    )


def get_watchlist(watchlist_id: int) -> dict[str, Any] | None:
    return _one("SELECT * FROM watchlists WHERE id = ?", (watchlist_id,))


def create_watchlist(name: str, description: str = "", color: str = "navy") -> dict[str, Any]:
    with transaction() as con:
        cur = con.execute(
            "INSERT INTO watchlists (name,description,color,created_at,updated_at) VALUES (?,?,?,?,?)",
            (name.strip(), description.strip(), color, now_iso(), now_iso()),
        )
        wid = int(cur.lastrowid)
        _log(con, "watchlist", wid, "create", name.strip())
    _bump()
    return get_watchlist(wid) or {}


def update_watchlist(watchlist_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "description", "color"}
    sets, params = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(value.strip() if isinstance(value, str) else value)
    if not sets:
        return get_watchlist(watchlist_id)
    sets.append("updated_at = ?")
    params += [now_iso(), watchlist_id]
    with transaction() as con:
        cur = con.execute(f"UPDATE watchlists SET {', '.join(sets)} WHERE id = ?", tuple(params))
        if cur.rowcount == 0:
            return None
        _log(con, "watchlist", watchlist_id, "update", ", ".join(fields.keys()))
    _bump()
    return get_watchlist(watchlist_id)


def delete_watchlist(watchlist_id: int) -> bool:
    with transaction() as con:
        row = con.execute("SELECT name FROM watchlists WHERE id = ?", (watchlist_id,)).fetchone()
        if not row:
            return False
        con.execute("DELETE FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,))
        con.execute("DELETE FROM watchlists WHERE id = ?", (watchlist_id,))
        _log(con, "watchlist", watchlist_id, "delete", row["name"])
    _bump()
    return True


def list_watchlist_items(watchlist_id: int) -> list[dict[str, Any]]:
    return _rows("SELECT * FROM watchlist_items WHERE watchlist_id = ? ORDER BY added_at DESC", (watchlist_id,))


def add_watchlist_items(watchlist_id: int, ocids: Any, note: str = "") -> int:
    rows = [(watchlist_id, o, (note or "").strip(), now_iso()) for o in clean_ocids(ocids)]
    if not rows:
        return 0
    with transaction() as con:
        if not con.execute("SELECT 1 FROM watchlists WHERE id = ?", (watchlist_id,)).fetchone():
            return -1
        before = con.execute(
            "SELECT COUNT(*) AS n FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,)
        ).fetchone()["n"]
        con.executemany(
            "INSERT OR IGNORE INTO watchlist_items (watchlist_id,ocid,note,added_at) VALUES (?,?,?,?)",
            rows,
        )
        after = con.execute(
            "SELECT COUNT(*) AS n FROM watchlist_items WHERE watchlist_id = ?", (watchlist_id,)
        ).fetchone()["n"]
        con.execute("UPDATE watchlists SET updated_at = ? WHERE id = ?", (now_iso(), watchlist_id))
        added = int(after) - int(before)
        if added:
            _log(con, "watchlist", watchlist_id, "add items", f"{added} added")
    _bump()
    return added


def update_watchlist_item(item_id: int, note: str) -> dict[str, Any] | None:
    with transaction() as con:
        cur = con.execute("UPDATE watchlist_items SET note = ? WHERE id = ?", ((note or "").strip(), item_id))
        if cur.rowcount == 0:
            return None
        _log(con, "watchlist_item", item_id, "update", (note or "").strip())
    _bump()
    return _one("SELECT * FROM watchlist_items WHERE id = ?", (item_id,))


def delete_watchlist_item(item_id: int) -> bool:
    with transaction() as con:
        cur = con.execute("DELETE FROM watchlist_items WHERE id = ?", (item_id,))
        ok = cur.rowcount > 0
        if ok:
            _log(con, "watchlist_item", item_id, "delete", "")
    _bump()
    return ok


# ==========================================================================
# saved views
# ==========================================================================
def list_saved_views() -> list[dict[str, Any]]:
    return _rows("SELECT * FROM saved_views ORDER BY name")


def get_saved_view(view_id: int) -> dict[str, Any] | None:
    return _one("SELECT * FROM saved_views WHERE id = ?", (view_id,))


def create_saved_view(name: str, payload: dict, description: str = "") -> dict[str, Any]:
    with transaction() as con:
        cur = con.execute(
            "INSERT INTO saved_views (name,description,payload,created_at,updated_at) VALUES (?,?,?,?,?)",
            (name.strip(), description.strip(), json.dumps(payload or {}, default=str), now_iso(), now_iso()),
        )
        vid = int(cur.lastrowid)
        _log(con, "view", vid, "create", name.strip())
    _bump()
    return get_saved_view(vid) or {}


def update_saved_view(view_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "description", "payload"}
    sets, params = [], []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            params.append(json.dumps(value, default=str) if key == "payload" else str(value).strip())
    if not sets:
        return get_saved_view(view_id)
    sets.append("updated_at = ?")
    params += [now_iso(), view_id]
    with transaction() as con:
        cur = con.execute(f"UPDATE saved_views SET {', '.join(sets)} WHERE id = ?", tuple(params))
        if cur.rowcount == 0:
            return None
        _log(con, "view", view_id, "update", ", ".join(fields.keys()))
    _bump()
    return get_saved_view(view_id)


def delete_saved_view(view_id: int) -> bool:
    with transaction() as con:
        row = con.execute("SELECT name FROM saved_views WHERE id = ?", (view_id,)).fetchone()
        if not row:
            return False
        con.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))
        _log(con, "view", view_id, "delete", row["name"])
    _bump()
    return True


# ==========================================================================
# activity + maintenance
# ==========================================================================
def recent_activity(limit: int = 40) -> list[dict[str, Any]]:
    return _rows("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))


def summary() -> dict[str, Any]:
    with transaction() as con:
        counts = {
            table: int(con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
            for table in ("cases", "annotations", "watchlists", "watchlist_items", "saved_views")
        }
    return {
        "counts": counts,
        "cases_by_status": case_stats(),
        "revision": revision(),
        "db_path": str(DB_PATH),
        "vocab": {
            "case_status": CASE_STATUS,
            "case_priority": CASE_PRIORITY,
            "annotation_category": ANNOTATION_CATEGORY,
            "watchlist_colors": WATCHLIST_COLORS,
        },
    }


def reset() -> None:
    """Delete every workspace row. Exposed in the UI as 'clear workspace'."""
    with transaction() as con:
        for table in ("annotations", "watchlist_items", "watchlists", "cases", "saved_views", "activity"):
            con.execute(f"DELETE FROM {table}")
        con.execute(
            "DELETE FROM sqlite_sequence WHERE name IN"
            " ('cases','annotations','watchlists','watchlist_items','saved_views','activity')"
        )
        _log(con, "workspace", None, "reset", "all workspace rows deleted")
    _bump()
