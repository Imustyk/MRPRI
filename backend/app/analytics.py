"""Server-side distribution and correlation analytics.

The React client cannot pull 152k rows through ``/api/tenders`` (which is capped
at 500 per page for table rendering), and a correlation matrix over the full
corpus is not something the browser should compute anyway. So every aggregate
here is computed in Python from the already-loaded rows and returned small.

Only columns the ETL genuinely produces are offered. Anything MTender does not
publish is reported as unavailable with a reason rather than as a zero.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

#: Numeric columns of the projected tender contract, with a label and the
#: reason to exclude each one if the data turns out to be absent.
FEATURES: dict[str, dict[str, str]] = {
    "award_total_mdl": {"label": "Award total (MDL)", "group": "financial"},
    "award_value_mdl": {"label": "First award value (MDL)", "group": "financial"},
    "estimated_value_mdl": {"label": "Estimated value (MDL)", "group": "financial"},
    "estimate_to_award_ratio": {"label": "Award / estimate ratio", "group": "financial"},
    "value_vs_cpv_median": {"label": "Value vs CPV median", "group": "financial"},
    "n_bidders": {"label": "Distinct bidders", "group": "competition"},
    "n_bid_records": {"label": "Bid records (per lot)", "group": "competition"},
    "n_lots": {"label": "Lots", "group": "competition"},
    "n_awards": {"label": "Awards", "group": "competition"},
    "bid_window_days": {"label": "Bidding window (days)", "group": "procedural"},
    "single_bidder": {"label": "Single bidder (0/1)", "group": "competition"},
    "short_deadline": {"label": "Short deadline (0/1)", "group": "procedural"},
    "winner_share_of_buyer_awards": {"label": "Winner share of buyer awards", "group": "behavioural"},
    "buyer_supplier_repeat_share": {"label": "Repeat pair share", "group": "behavioural"},
    "risk_score": {"label": "Anomaly percentile", "group": "model"},
    "iso_score": {"label": "Isolation Forest score", "group": "model"},
    "lof_score": {"label": "LOF score", "group": "model"},
    "svm_score": {"label": "One-Class SVM score", "group": "model"},
    "rule_score": {"label": "MAD z-score", "group": "model"},
}

#: Categorical columns usable as a grouping variable.
CATEGORIES: dict[str, str] = {
    "risk_level": "Risk band",
    "procedure": "Procedure type",
    "procurement_method": "Procurement method",
    "status": "Status",
    "buyer_locality": "Procurer locality",
    "cpv_code": "CPV code",
    "buyer_id": "Procurer",
    "winner_id": "Supplier",
}

#: Time columns, newest-format first, for the date pickers.
DATES = {
    "published_at": "Published",
    "list_date": "Listed",
    "tender_start": "Tender start",
    "bid_deadline": "Bidding deadline",
    "award_date": "Award date",
}

#: Below this many non-missing values a correlation is not reported.
MIN_PAIRS = 30


def _frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    data = {c: [r.get(c) for r in rows] for c in columns}
    df = pd.DataFrame(data)
    for c in columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.replace([np.inf, -np.inf], np.nan)


def feature_catalog(rows: list[dict]) -> dict[str, Any]:
    """Per-feature coverage and a five-number summary, for the picker UI."""
    cols = [c for c in FEATURES if rows and c in rows[0]]
    if not cols:
        return {"features": [], "categories": [], "dates": {}}
    df = _frame(rows, cols)
    n = len(df)
    out = []
    for col in cols:
        s = df[col]
        present = s.notna().sum()
        entry: dict[str, Any] = {
            "key": col,
            "label": FEATURES[col]["label"],
            "group": FEATURES[col]["group"],
            "n": int(present),
            "missing_rate": round(1 - present / n, 4) if n else None,
            "available": int(present) >= MIN_PAIRS,
        }
        if present:
            q = s.quantile([0.25, 0.5, 0.75])
            entry["summary"] = {
                "min": _f(s.min()),
                "p25": _f(q.loc[0.25]),
                "median": _f(q.loc[0.5]),
                "p75": _f(q.loc[0.75]),
                "max": _f(s.max()),
                "mean": _f(s.mean()),
                "std": _f(s.std()),
                "zeros": int((s == 0).sum()),
            }
        out.append(entry)
    cats = [
        {"key": k, "label": v, "n_levels": _n_levels(rows, k)}
        for k, v in CATEGORIES.items()
        if rows and k in rows[0]
    ]
    return {
        "features": out,
        "categories": cats,
        "dates": DATES,
        "min_pairs": MIN_PAIRS,
        "n_rows": n,
    }


def _f(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)


def _n_levels(rows: list[dict], key: str) -> int:
    return len({r.get(key) for r in rows if r.get(key)})


def correlations(
    rows: list[dict],
    columns: list[str],
    method: str = "pearson",
    min_abs: float = 0.0,
    top: int = 20,
) -> dict[str, Any]:
    """Correlation matrix plus a ranked pair table.

    Uses pairwise-complete observations, so a feature that is missing for part
    of the corpus is compared on the rows where *both* features exist. The
    per-pair sample size is returned because a correlation computed on 40 rows
    is not comparable with one computed on 150k.
    """
    cols = [c for c in columns if c in FEATURES]
    if len(cols) < 2:
        return {"columns": [], "matrix": [], "pairs": [], "n": 0, "method": method}
    df = _frame(rows, cols)
    usable = [c for c in cols if df[c].notna().sum() >= MIN_PAIRS]
    if len(usable) < 2:
        return {"columns": [], "matrix": [], "pairs": [], "n": len(df), "method": method}
    df = df[usable]
    corr = df.corr(method=method, min_periods=MIN_PAIRS)

    pairs = []
    for i, a in enumerate(usable):
        for b in usable[i + 1 :]:
            r = corr.loc[a, b]
            if pd.isna(r):
                continue
            both = df[[a, b]].dropna()
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "r": round(float(r), 4),
                    "abs_r": round(abs(float(r)), 4),
                    "direction": "positive" if r > 0 else "negative",
                    "n": int(len(both)),
                }
            )
    pairs.sort(key=lambda d: -d["abs_r"])
    if min_abs > 0:
        pairs = [p for p in pairs if p["abs_r"] >= min_abs]

    return {
        "columns": usable,
        "labels": [FEATURES[c]["label"] for c in usable],
        "matrix": [[None if pd.isna(v) else round(float(v), 4) for v in row] for row in corr.to_numpy()],
        "pairs": pairs[:top],
        "n": int(len(df)),
        "method": method,
        "min_pairs": MIN_PAIRS,
    }


def distribution(
    rows: list[dict],
    column: str,
    bins: int = 40,
    group: str | None = None,
    log_x: bool = False,
    scale: str = "auto",
) -> dict[str, Any]:
    """Histogram bins, empirical CDF and a five-number summary for one column."""
    if column not in FEATURES or not rows:
        return {"column": column, "bins": [], "ecdf": [], "summary": None, "groups": []}
    df = _frame(rows, [column])
    series = df[column]
    summary = None
    if series.notna().any():
        q = series.quantile([0.25, 0.5, 0.75, 0.9, 0.99])
        iqr = float(q.loc[0.75] - q.loc[0.25])
        lo, hi = float(q.loc[0.25] - 1.5 * iqr), float(q.loc[0.75] + 1.5 * iqr)
        summary = {
            "min": _f(series.min()),
            "p25": _f(q.loc[0.25]),
            "median": _f(q.loc[0.5]),
            "p75": _f(q.loc[0.75]),
            "p90": _f(q.loc[0.9]),
            "p99": _f(q.loc[0.99]),
            "max": _f(series.max()),
            "mean": _f(series.mean()),
            "std": _f(series.std()),
            "iqr_outlier_rate": round(float(((series < lo) | (series > hi)).mean()), 4),
            "zeros": int((series == 0).sum()),
            "negative": int((series < 0).sum()),
            "n": int(series.notna().sum()),
            # how lopsided the distribution is; this is what forces log bins
            "skew_ratio": _f(float(series.max() / series.median())) if series.median() else None,
        }

    work = df[column]
    if log_x:
        work = work[work > 0]
    edges, counts, used_scale = _histogram(work.dropna().to_numpy(), bins, scale)

    ecdf = []
    s = work.dropna().sort_values()
    if len(s):
        step = max(len(s) // 400, 1)
        sample = s.iloc[::step]
        ecdf = [[_f(v), round(i / len(s), 4)] for i, v in enumerate(sample, start=1)]
        if ecdf:
            ecdf[-1][1] = 1.0

    groups = []
    if group and group in CATEGORIES and rows and group in rows[0]:
        sub = _frame(rows, [column])
        sub["__g"] = [r.get(group) for r in rows]
        sub = sub.dropna(subset=[column])
        counts = sub["__g"].value_counts()
        for key in counts[counts >= 20].head(12).index:
            vals = sub.loc[sub["__g"] == key, column]
            groups.append(
                {
                    "key": key,
                    "label": key,
                    "n": int(vals.notna().sum()),
                    "median": _f(vals.median()),
                    "p25": _f(vals.quantile(0.25)),
                    "p75": _f(vals.quantile(0.75)),
                    "mean": _f(vals.mean()),
                    "share": round(float(len(vals) / max(len(sub), 1)), 4),
                }
            )
        groups.sort(key=lambda g: -(g["median"] if g["median"] is not None else -math.inf))

    return {
        "column": column,
        "label": FEATURES[column]["label"],
        "bins": [
            {"x0": _f(a), "x1": _f(b), "n": int(c), "mid": _f((a + b) / 2)}
            for a, b, c in zip(edges[:-1], edges[1:], counts)
        ],
        "ecdf": ecdf,
        "summary": summary,
        "groups": groups,
        "group_by": group,
        "log_x": log_x,
        "scale": used_scale,
    }


def _histogram(values: np.ndarray, bins: int, scale: str = "auto") -> tuple[list, list, str]:
    """Bin edges and counts, choosing a scale that survives heavy skew.

    Award values in this corpus reach ~5e13 MDL while the median is under
    2e4, so equal-width bins drop 117,823 of 117,824 values into the first bar
    and the histogram is a single spike. Log or quantile bins are used instead
    whenever the data is that skewed.
    """
    values = values[np.isfinite(values)]
    if values.size == 0:
        return [0.0, 1.0], [0], "linear"
    lo, hi = float(values.min()), float(values.max())
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0, 1.0], [0], "linear"
    if hi <= lo:
        return [lo, lo + 1.0], [int(values.size)], "linear"

    positives = values[values > 0]
    if scale == "auto":
        median = float(np.median(values))
        scale = "log" if median > 0 and hi / median > 1000 and positives.size > values.size * 0.9 else "linear"
    if scale == "log" and positives.size >= 10 and positives.min() > 0:
        logs = np.log10(positives)
        lo_l, hi_l = float(logs.min()), float(logs.max())
        if hi_l <= lo_l:
            return [lo, hi], [int(values.size)], "linear"
        counts, edges = np.histogram(logs, bins=min(bins, 60), range=(lo_l, hi_l))
        edges = [float(10**e) for e in edges]
        return edges, [int(c) for c in counts], "log"
    if scale == "quantile":
        qs = np.linspace(0, 1, min(bins, 60) + 1)
        edges = np.unique(np.quantile(values, qs))
        if edges.size < 2:
            return [lo, hi], [int(values.size)], "linear"
        counts, _ = np.histogram(values, bins=edges)
        return [float(e) for e in edges], [int(c) for c in counts], "quantile"

    counts, edges = np.histogram(values, bins=min(bins, 200), range=(lo, hi))
    return [float(e) for e in edges], [int(c) for c in counts], "linear"


def scatter(
    rows: list[dict],
    x: str,
    y: str,
    group: str | None = None,
    limit: int = 4000,
    log_x: bool = False,
    log_y: bool = False,
) -> dict[str, Any]:
    """Down-sampled paired points plus a least-squares fit for the reference line."""
    if x not in FEATURES or y not in FEATURES or not rows:
        return {"points": [], "x": x, "y": y, "fit": None, "n": 0}
    df = _frame(rows, [x, y])
    pairs = df.dropna()
    if log_x:
        pairs = pairs[pairs[x] > 0]
    if log_y:
        pairs = pairs[pairs[y] > 0]
    n_total = int(len(pairs))
    if n_total == 0:
        return {"points": [], "x": x, "y": y, "fit": None, "n": 0}

    if group and group in CATEGORIES and rows and group in rows[0]:
        pairs = pairs.assign(__g=[r.get(group) for r in rows][: len(pairs)])

    # Deterministic stride instead of random sampling, so repeated calls with
    # the same filters return the same points and the chart does not jump.
    step = max(n_total // limit, 1)
    view = pairs.iloc[::step]
    if group:
        groups = [g for g in view["__g"].value_counts().head(8).index]
        view = view[view["__g"].isin(groups)]
    points = [
        {
            "x": _f(r[x]),
            "y": _f(r[y]),
            "g": (r["__g"] if group else None),
        }
        for _, r in view.iterrows()
    ]

    xs = pairs[x].to_numpy(dtype=float)
    ys = pairs[y].to_numpy(dtype=float)
    fit = None
    if len(xs) >= 10 and np.ptp(xs) > 0:
        slope, intercept = np.polyfit(xs, ys, 1)
        corr = float(np.corrcoef(xs, ys)[0, 1]) if np.ptp(ys) > 0 else None
        fit = {
            "slope": round(float(slope), 6),
            "intercept": round(float(intercept), 4),
            "r": round(corr, 4) if corr is not None and math.isfinite(corr) else None,
            "x_min": _f(xs.min()),
            "x_max": _f(xs.max()),
        }

    return {
        "points": points,
        "x": x,
        "y": y,
        "x_label": FEATURES[x]["label"],
        "y_label": FEATURES[y]["label"],
        "group": group,
        "fit": fit,
        "n": n_total,
        "sampled": len(points),
    }


def group_compare(
    rows: list[dict],
    value: str,
    group: str,
    limit: int = 14,
    min_n: int = 20,
) -> dict[str, Any]:
    """Per-group distribution stats — the data behind a violin or box plot."""
    if value not in FEATURES or group not in CATEGORIES or not rows:
        return {"value": value, "group": group, "groups": []}
    df = _frame(rows, [value])
    df["__g"] = [r.get(group) for r in rows]
    df = df.dropna(subset=[value])
    if df.empty:
        return {"value": value, "group": group, "groups": []}
    counts = df["__g"].value_counts()
    keep = counts[counts >= min_n].head(limit).index
    out = []
    for key in keep:
        vals = df.loc[df["__g"] == key, value]
        q = vals.quantile([0.25, 0.5, 0.75])
        iqr = float(q.loc[0.75] - q.loc[0.25])
        lo, hi = float(q.loc[0.25] - 1.5 * iqr), float(q.loc[0.75] + 1.5 * iqr)
        out.append(
            {
                "key": key,
                "n": int(vals.notna().sum()),
                "min": _f(vals.min()),
                "p25": _f(q.loc[0.25]),
                "median": _f(q.loc[0.5]),
                "p75": _f(q.loc[0.75]),
                "max": _f(vals.max()),
                "mean": _f(vals.mean()),
                "outlier_rate": round(float(((vals < lo) | (vals > hi)).mean()), 4),
            }
        )
    out.sort(key=lambda g: -(g["median"] or -math.inf))
    return {
        "value": value,
        "value_label": FEATURES[value]["label"],
        "group": group,
        "group_label": CATEGORIES[group],
        "groups": out,
        "n": int(len(df)),
        "dropped_groups": int(len(counts) - len(keep)),
    }


def crosstab(rows: list[dict], a: str, b: str, limit: int = 18, value: str | None = None) -> dict[str, Any]:
    """Two-way count matrix, optionally valued — the source for a heatmap."""
    if a not in CATEGORIES or b not in CATEGORIES or not rows:
        return {"a": a, "b": b, "rows": [], "cols": [], "matrix": []}
    if value and value not in FEATURES:
        value = None
    cols: list[Any] = [a, b] + ([value] if value else [])
    df = pd.DataFrame({c: [r.get(c) for r in rows] for c in cols})
    if value:
        df[value] = pd.to_numeric(df[value], errors="coerce")
        df = df.dropna(subset=[a, b, value])
        table = df.pivot_table(index=a, columns=b, values=value, aggfunc="sum", fill_value=0)
    else:
        df = df.dropna(subset=[a, b])
        table = df.pivot_table(index=a, columns=b, aggfunc="size", fill_value=0)
    if table.empty:
        return {"a": a, "b": b, "rows": [], "cols": [], "matrix": []}

    # keep the busiest levels so the matrix stays legible
    row_tot = table.sum(axis=1).sort_values(ascending=False)
    col_tot = table.sum(axis=0).sort_values(ascending=False)
    table = table.loc[row_tot.index[:limit], col_tot.index[:limit]]
    return {
        "a": a,
        "b": b,
        "a_label": CATEGORIES[a],
        "b_label": CATEGORIES[b],
        "value": value,
        "rows": [str(i) for i in table.index],
        "cols": [str(c) for c in table.columns],
        "matrix": [[_f(v) for v in row] for row in table.to_numpy()],
        "max": _f(table.to_numpy().max()),
        "dropped": int(len(row_tot) - len(table.index)),
    }


def timeseries(
    rows: list[dict],
    date_field: str = "list_date",
    grain: str = "month",
    group: str | None = None,
    value: str = "award_total_mdl",
) -> dict[str, Any]:
    """Bucketed time series, optionally split by a category."""
    if date_field not in DATES or not rows:
        return {"buckets": [], "grain": grain}
    if value not in FEATURES:
        value = "award_total_mdl"
    df = pd.DataFrame(
        {
            "d": [r.get(date_field) for r in rows],
            "v": pd.to_numeric([r.get(value) for r in rows], errors="coerce"),
            "g": [r.get(group) for r in rows] if group else None,
        }
    )
    df["d"] = pd.to_datetime(df["d"], errors="coerce", utc=True, format="mixed")
    df = df.dropna(subset=["d"])
    if df.empty:
        return {"buckets": [], "grain": grain}
    rule = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS"}.get(grain, "MS")
    df["period"] = df["d"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period(
        {"D": "D", "W": "W", "MS": "M", "QS": "Q", "YS": "Y"}[rule]
    ).dt.to_timestamp()
    df["v"] = df["v"].fillna(0.0)

    if group:
        pivot = df.pivot_table(index="period", columns="g", values="v", aggfunc="sum", fill_value=0)
        top = df["g"].value_counts().head(8).index
        pivot = pivot[[c for c in pivot.columns if c in top]]
        buckets = [
            {"period": str(idx.date()), **{str(k): _f(v) for k, v in row.items()}}
            for idx, row in pivot.iterrows()
        ]
        return {"buckets": buckets, "grain": grain, "group": group, "series": [str(c) for c in pivot.columns], "date_field": date_field, "value": value}

    grouped = df.groupby("period")["v"].agg(["sum", "size"])
    buckets = [
        {"period": str(idx.date()), "value": _f(r["sum"]), "n": int(r["size"])}
        for idx, r in grouped.iterrows()
    ]
    return {"buckets": buckets, "grain": grain, "group": None, "series": ["value"], "date_field": date_field, "value": value}
