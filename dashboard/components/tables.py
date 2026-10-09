from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st


def _to_excel(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="export")
    return buf.getvalue()


def _width_kwargs() -> dict:
    """Support both the new width= and the deprecated use_container_width= APIs."""
    import inspect

    try:
        params = inspect.signature(st.dataframe).parameters
    except (TypeError, ValueError):
        return {}
    return {"width": "stretch"} if "width" in params else {"use_container_width": True}


def interactive_table(
    df: pd.DataFrame,
    *,
    key: str,
    caption: str | None = None,
    max_rows: int = 5000,
    download_stem: str = "filtered",
    column_config: dict | None = None,
) -> None:
    if caption:
        st.caption(caption)
    view = df.head(max_rows)
    if len(df) > max_rows:
        st.caption(f"Showing the first {max_rows:,} of {len(df):,} rows. Download includes the full filtered set.")
    st.dataframe(
        view,
        hide_index=True,
        column_config=column_config,
        key=f"{key}_grid",
        **_width_kwargs(),
    )
    csv = df.to_csv(index=False).encode("utf-8")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download filtered data (CSV)",
            data=csv,
            file_name=f"{download_stem}.csv",
            mime="text/csv",
            key=f"{key}_csv",
        )
    with c2:
        try:
            xlsx = _to_excel(df)
            st.download_button(
                "Download filtered data (Excel)",
                data=xlsx,
                file_name=f"{download_stem}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{key}_xlsx",
            )
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Excel export unavailable: {exc}")
