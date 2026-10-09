"""Analyst workspace for the Streamlit dashboard.

Reads and writes the same SQLite store the FastAPI backend exposes at
``/api/workspace/*`` (``src/mtender/workspace.py``), so a case opened here is
visible in the React UI and vice versa. The pipeline snapshot is never modified.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import layout
from dashboard.components.metrics import kpi_row
from dashboard.components.tables import interactive_table
from dashboard.utils.formatting import DISCLAIMER, fmt_int
from src.mtender import workspace as ws

PRIORITY_TONE = {"low": "muted", "medium": "info", "high": "warn", "critical": "bad"}
STATUS_TONE = {
    "open": "info",
    "in review": "warn",
    "escalated": "bad",
    "closed": "muted",
    "dismissed": "muted",
}


@st.cache_data(show_spinner=False)
def _read(revision: int, kind: str, status: str, q: str):
    """Cached read, keyed on the store revision so any write invalidates it."""
    if kind == "cases":
        return ws.list_cases(status=status, text=q)
    if kind == "annotations":
        return ws.list_annotations(category=status, text=q)
    if kind == "watchlists":
        return ws.list_watchlists()
    if kind == "views":
        return ws.list_saved_views()
    return []


@st.cache_data(show_spinner=False)
def _activity(revision: int) -> list[dict]:
    return ws.recent_activity(15)


def _clear() -> None:
    _read.clear()
    _activity.clear()


def render(df, bundle) -> None:
    layout.page_header(
        "Analyst workspace",
        "Investigation cases, notes and watchlists. Stored in SQLite under "
        "<code>data/workspace/</code>, separate from the research pipeline output, so the ETL "
        "artefacts stay read-only and reproducible. Shared with the FastAPI backend, so a case "
        "opened here appears in the React UI too.",
        kicker="workspace",
    )
    layout.disclaimer(
        "Workspace entries are analyst working notes about published procurement data. A risk "
        "band is a statistical signal, not a finding, and a note is not an allegation."
    )

    counts = ws.summary()["counts"]
    rev = ws.revision()
    kpi_row(
        [
            ("Cases", fmt_int(counts["cases"]), "Investigation files.", "neutral", None),
            ("Annotations", fmt_int(counts["annotations"]), "Notes attached to a procedure OCID.", "info", None),
            ("Watchlists", fmt_int(counts["watchlists"]), f"{fmt_int(counts['watchlist_items'])} procedures tracked.", "info", None),
            ("Saved views", fmt_int(counts["saved_views"]), "Reusable filter configurations.", "muted", None),
        ],
        key="ws_kpi",
    )

    tab_cases, tab_notes, tab_lists, tab_views, tab_log = st.tabs(
        ["Cases", "Annotations", "Watchlists", "Saved views", "Activity"]
    )

    with tab_cases:
        _cases(rev)
    with tab_notes:
        _annotations(rev)
    with tab_lists:
        _watchlists(rev)
    with tab_views:
        _views(rev)
    with tab_log:
        layout.section("Recent activity", "Every create, update and delete is recorded.")
        interactive_table(pd.DataFrame(_activity(rev)), key="ws_log", download_stem="activity")


def _header(toolbar) -> None:
    c1, c2 = st.columns([3, 2])
    with c1:
        layout.section("Create", "Fill in the form and submit.")
    with c2:
        toolbar()


# --------------------------------------------------------------------------
def _cases(rev: int) -> None:
    c1, c2 = st.columns([3, 2])
    with c1:
        layout.section("New case", "A case groups the procedures under investigation.")
    with c2:
        f_title = st.text_input("Title", key="ws_case_title", placeholder="Repeat awards to one supplier")
        f_priority = st.selectbox("Priority", ws.CASE_PRIORITY, key="ws_case_priority")
        f_status = st.selectbox("Status", ws.CASE_STATUS, key="ws_case_status")
        f_owner = st.text_input("Owner", key="ws_case_owner", placeholder="analyst")
        f_summary = st.text_area("Summary", key="ws_case_summary", height=70)
        f_ocids = st.text_area(
            "Procedures (OCIDs)", key="ws_case_ocids", height=70,
            help="One per line, or separated by commas. Pasted text is split automatically.",
        )

    if st.button("Create case", type="primary", key="ws_case_create"):
        if len(f_title.strip()) < 3:
            st.error("A case needs a title of at least 3 characters.")
        else:
            created = ws.create_case(
                title=f_title,
                status=f_status,
                priority=f_priority,
                owner=f_owner,
                summary=f_summary,
                ocids=f_ocids,
            )
            _clear()
            st.success(f"Created {created.get('ref', '')}.")
            for key in ("ws_case_title", "ws_case_summary", "ws_case_ocids", "ws_case_owner"):
                st.session_state.pop(key, None)
            st.rerun()

    layout.rule()
    layout.section(
        "Cases",
        "Ordered by status urgency, then by the most recent change.",
    )
    c1, c2 = st.columns([1, 2])
    with c1:
        f_status_filter = st.selectbox(
            "Status", ["all"] + ws.CASE_STATUS, key="ws_case_filter_status"
        )
    with c2:
        f_search = st.text_input("Search", key="ws_case_filter_q", placeholder="title, ref, owner…")

    cases = _read(rev, "cases", f_status_filter, f_search)
    if not cases:
        layout.empty_state("No cases", "Create one above, or clear the filters.")
        return

    for case in cases:
        with st.expander(f"{case['ref']} — {case['title']}"):
            c1, c2, c3 = st.columns([3, 2, 1])
            with c1:
                st.markdown(
                    layout.badges_html(
                        [
                            (case["status"], STATUS_TONE.get(case["status"], "neutral")),
                            (case["priority"], PRIORITY_TONE.get(case["priority"], "neutral")),
                        ]
                    ),
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"Updated {case['updated_at']} · owner {case['owner'] or '—'}"
                )
            with c2:
                e_title = st.text_input("Title", value=case["title"], key=f"e_title_{case['id']}")
                e_status = st.selectbox(
                    "Status",
                    ws.CASE_STATUS,
                    index=ws.CASE_STATUS.index(case["status"]),
                    key=f"e_status_{case['id']}",
                )
                e_priority = st.selectbox(
                    "Priority",
                    ws.CASE_PRIORITY,
                    index=ws.CASE_PRIORITY.index(case["priority"]),
                    key=f"e_priority_{case['id']}",
                )
            with c3:
                st.write("")
                st.write("")
                if st.button("Save", key=f"e_save_{case['id']}"):
                    ws.update_case(
                        case["id"],
                        {"title": e_title, "status": e_status, "priority": e_priority},
                    )
                    _clear()
                    st.rerun()
                if st.button("Delete", key="e_del", help="Deletes the case; its notes are kept."):
                    ws.delete_case(case["id"])
                    _clear()
                    st.rerun()

            if case["summary"]:
                st.markdown(f"**Summary.** {case['summary']}")
            ocids = ws.case_ocids(case)
            st.caption(f"{len(ocids)} procedure(s) linked")
            if ocids:
                st.code(", ".join(ocids[:20]) + (" …" if len(ocids) > 20 else ""))
            notes = ws.list_annotations(case_id=case["id"])
            if notes:
                st.markdown("**Notes**")
                interactive_table(pd.DataFrame(notes), key=f"ws_case_notes_{case['id']}", max_rows=200)


# --------------------------------------------------------------------------
def _annotations(rev: int) -> None:
    c1, c2 = st.columns([3, 2])
    with c1:
        layout.section("New annotation", "A note attached to one procedure OCID.")
    with c2:
        f_ocid = st.text_input("OCID", key="ws_ann_ocid", placeholder="ocds-…")
        f_category = st.selectbox("Category", ws.ANNOTATION_CATEGORY, key="ws_ann_cat")
        f_author = st.text_input("Author", key="ws_ann_author")
        f_note = st.text_area("Note", key="ws_ann_note", height=70)
        case_options = {c["ref"]: c["id"] for c in ws.list_cases()}
        f_case = st.selectbox("Link to case", ["(none)"] + list(case_options), key="ws_ann_case")

    if st.button("Add note", type="primary", key="ws_ann_create"):
        if not f_ocid.strip() or not f_note.strip():
            st.error("Both an OCID and a note are required.")
        else:
            ws.create_annotation(
                ocid=f_ocid,
                note=f_note,
                category=f_category,
                case_id=case_options.get(f_case),
                author=f_author,
            )
            _clear()
            st.success("Note added.")
            for key in ("ws_ann_ocid", "ws_ann_note"):
                st.session_state.pop(key, None)
            st.rerun()

    layout.rule()
    c1, c2 = st.columns([1, 2])
    with c1:
        f_cat_filter = st.selectbox("Category", ["all"] + ws.ANNOTATION_CATEGORY, key="ws_ann_filter_cat")
    with c2:
        f_q = st.text_input("Search", key="ws_ann_filter_q", placeholder="note text or OCID…")

    notes = _read(rev, "annotations", f_cat_filter, f_q)
    if not notes:
        layout.empty_state("No annotations", "Add one above.")
        return
    frame = pd.DataFrame(notes).rename(
        columns={
            "ocid": "OCID",
            "case_ref": "Case",
            "category": "Category",
            "note": "Note",
            "author": "Author",
            "updated_at": "Updated",
        }
    )
    keep = [c for c in ("OCID", "Category", "Note", "Case", "Author", "Updated", "id") if c in frame.columns]
    interactive_table(frame[keep], key="ws_ann_table", download_stem="annotations")

    st.caption("Delete a note by its id:")
    ids = [int(r["id"]) for r in notes[:50]]
    if ids:
        to_delete = st.selectbox("Note id", ["—"] + [str(i) for i in ids], key="ws_ann_del")
        if to_delete != "—" and st.button("Delete note", key="ws_ann_del_btn"):
            ws.delete_annotation(int(to_delete))
            _clear()
            st.rerun()


# --------------------------------------------------------------------------
def _watchlists(rev: int) -> None:
    c1, c2 = st.columns([3, 2])
    with c1:
        layout.section("New watchlist", "A named collection of procedures to return to.")
    with c2:
        f_name = st.text_input("Name", key="ws_wl_name", placeholder="Mega suppliers")
        f_color = st.selectbox(
            "Colour", list(ws.WATCHLIST_COLORS), format_func=lambda c: c.title(), key="ws_wl_color"
        )
        f_desc = st.text_input("Description", key="ws_wl_desc")

    if st.button("Create watchlist", type="primary", key="ws_wl_create"):
        if not f_name.strip():
            st.error("A watchlist needs a name.")
        else:
            try:
                ws.create_watchlist(name=f_name, description=f_desc, color=f_color)
                _clear()
                st.success("Watchlist created.")
                st.session_state.pop("ws_wl_name", None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001 - UNIQUE violation surfaces here
                st.error(f"Could not create: {exc}")

    layout.rule()
    lists = _read(rev, "watchlists", "", "")
    if not lists:
        layout.empty_state("No watchlists", "Create one above.")
        return

    for wl in lists:
        hex_color = ws.WATCHLIST_COLORS.get(wl["color"], "#1e3a5f")
        with st.expander(f"{wl['name']} — {wl['n_items']} procedure(s)"):
            st.markdown(
                f'<span class="badge solid" style="background:{hex_color}">{wl["color"]}</span> '
                f'<span class="muted">{wl["description"]}</span>',
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([3, 1])
            with c1:
                f_ocids = st.text_area(
                    "Add OCIDs", key=f"ws_wl_add_{wl['id']}", height=70,
                    help="One per line or comma separated. Duplicates already listed are ignored.",
                )
            with c2:
                st.write("")
                if st.button("Add", key=f"ws_wl_addbtn_{wl['id']}"):
                    added = ws.add_watchlist_items(wl["id"], f_ocids)
                    _clear()
                    st.success(f"Added {added} (duplicates ignored).")
                    st.rerun()
                if st.button("Delete list", key=f"ws_wl_del_{wl['id']}"):
                    ws.delete_watchlist(wl["id"])
                    _clear()
                    st.rerun()

            items = ws.list_watchlist_items(wl["id"])
            if items:
                interactive_table(
                    pd.DataFrame(items), key=f"ws_wl_items_{wl['id']}", max_rows=500,
                    download_stem=f"watchlist_{wl['id']}",
                )
                sel = st.selectbox(
                    "Remove item id", ["—"] + [str(i["id"]) for i in items],
                    key=f"ws_wl_rm_{wl['id']}",
                )
                if sel != "—" and st.button("Remove", key=f"ws_wl_rmbtn_{wl['id']}"):
                    ws.delete_watchlist_item(int(sel))
                    _clear()
                    st.rerun()


# --------------------------------------------------------------------------
def _views(rev: int) -> None:
    import json

    c1, c2 = st.columns([3, 2])
    with c1:
        layout.section(
            "New saved view",
            "A named filter configuration. The payload is JSON, so the same slice of the "
            "dashboard can be recalled exactly.",
        )
    with c2:
        f_name = st.text_input("Name", key="ws_v_name")
        f_desc = st.text_input("Description", key="ws_v_desc")
        f_payload = st.text_area(
            "Payload (JSON)", key="ws_v_payload", height=90,
            placeholder='{"methods": ["open"], "risk": "Anomalous"}',
        )

    if st.button("Save view", type="primary", key="ws_v_create"):
        payload: dict = {}
        if f_payload.strip():
            try:
                parsed = json.loads(f_payload)
                if not isinstance(parsed, dict):
                    raise ValueError("payload must be a JSON object")
                payload = parsed
            except Exception as exc:  # noqa: BLE001
                st.error(f"Payload is not valid JSON: {exc}")
                payload = None
        if payload is not None:
            if not f_name.strip():
                st.error("A view needs a name.")
            else:
                try:
                    ws.create_saved_view(name=f_name, payload=payload, description=f_desc)
                    _clear()
                    st.success("View saved.")
                    st.session_state.pop("ws_v_name", None)
                    st.session_state.pop("ws_v_payload", None)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not save: {exc}")

    layout.rule()
    views = _read(rev, "views", "", "")
    if not views:
        layout.empty_state("No saved views", "Save one above.")
        return
    interactive_table(pd.DataFrame(views), key="ws_v_table", download_stem="saved_views")

    ids = [int(v["id"]) for v in views]
    c1, c2 = st.columns([2, 1])
    with c1:
        to_delete = st.selectbox("View to delete", ["—"] + [str(i) for i in ids], key="ws_v_del")
    with c2:
        st.write("")
        if to_delete != "—" and st.button("Delete view", key="ws_v_delbtn"):
            ws.delete_saved_view(int(to_delete))
            _clear()
            st.rerun()
