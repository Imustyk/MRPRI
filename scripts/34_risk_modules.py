#!/usr/bin/env python3
"""Phase 4 - risk-specific detection modules + direct-award evaluation track.

Reads the real corpus (``data/features/features.csv``, read-only) and the v0
scores table (read-only join), computes the four experimental indicator
modules from :mod:`src.mtender.risk_modules`, and reports:

* per-population indicator rates **as measured** - equal alert rates across
  procurement types are explicitly *not* a goal and are never engineered;
* the direct-award track: module-selected procedures vs 1:1 matched random
  controls (strata: event year x contract-value quartile within the direct
  population, seed 42), cluster bootstrap CIs by buyer, forward-looking
  reviewable follow-up patterns as *evaluation-only* outcomes;
* v0 critical alerts as a read-only reference baseline (production model is
  not retrained, rethresholded or modified).

Scientific limits honoured by construction:

* no legal procurement thresholds are assumed: ``threshold_interpretation``
  stays disabled in every output (no authoritative date-versioned threshold
  history exists in the corpus);
* forward-looking outcomes (``future_*``) are evaluation-only - never model
  inputs (``OUTCOME_NOTE`` is embedded in the JSON);
* a hit is an indicator of potential risk for human review, never evidence of
  wrongdoing; no causal claims;
* synthetic data is never involved: everything below is computed from the
  real corpus rows only.

Outputs (results/ is gitignored; artefacts are reproducible with this script):

* ``results/methodology/risk_modules.json``
* ``results/tables/risk_module_indicators.csv``
* ``results/tables/risk_module_cases.csv`` (top-N for expert review export)

Usage::

    .venv/bin/python scripts/34_risk_modules.py [--seed 42] [--boot 1000]
                                               [--top 200]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mtender.risk_modules import (  # noqa: E402
    DIRECT_DETAILS,
    MIN_GROUP_SIZE,
    OUTCOME_NOTE,
    OUTLIER_Z,
    REPEAT_WINDOW_DAYS,
    SPLIT_WINDOW_DAYS,
    contract_value,
    event_date,
    future_confirmation_indicators,
    indicator_metadata,
    module_indicators,
)

FEATURE_COLUMNS = (
    "ocid",
    "tender_id",
    "title",
    "status",
    "procurement_method_details",
    "buyer_id",
    "buyer_name",
    "winner_id",
    "winner_name",
    "cpv_primary",
    "award_date",
    "tender_start",
    "published_date",
    "award_total",
    "award_value",
    "n_bidders",
    "bid_window_days",
)

GROUP_OPEN = (
    "opentender",
    "licitație_deschisă",
    "restrictedtender",
    "testminicompetition",
)
GROUP_SMALL = ("smallvalue", "procedură_de_valoare_mică")

HIT_COLS = ("module_a_hit", "module_b_hit", "module_c_hit", "module_d_hit")
CONTINUOUS_COLS = (
    "buyer_prior_single_share",
    "buyer_prior_365d_count",
    "pair_prior_awards",
    "pair_buyer_share",
)
FUTURE_COLS = (
    "future_repeat_same_winner_365d",
    "future_same_buyer_cpv2_90d",
)
#: Existing ensemble rule, used read-only as a reference baseline (unchanged).
V0_CRITICAL_VOTES = 3

INDICATOR_TABLE_COLS = (
    "ocid",
    "tender_id",
    "group",
    "procurement_method_details",
    "status",
    "buyer_id",
    "winner_id",
    "cpv_primary",
    "award_date",
    "event_date",
    "event_year",
    "contract_value_mdl",
    "comp_single_bidder",
    "comp_no_bid_data",
    "comp_short_window",
    "buyer_prior_365d_count",
    "buyer_prior_single_share",
    "split_cluster_member",
    "split_cluster_n",
    "split_cluster_value_mdl",
    "split_same_supplier_share",
    "split_min_gap_days",
    "split_small_value_share",
    "pair_prior_awards",
    "buyer_prior_awards",
    "supplier_prior_awards",
    "supplier_prior_buyers",
    "pair_buyer_share",
    "supplier_dep_share",
    "pair_prior_365d",
    "val_group_n",
    "val_robust_z",
    "val_pctile",
    "module_a_hit",
    "module_b_hit",
    "module_c_hit",
    "module_d_hit",
    "n_module_hits",
    "n_module_known",
    "future_repeat_same_winner_365d",
    "future_same_buyer_cpv2_90d",
    "v0_n_models_flagging",
    "v0_critical",
)


def assign_group(details: pd.Series) -> pd.Series:
    """Map procedure details onto the four analysis populations + other."""
    d = details.astype(str).str.strip()
    grp = pd.Series("other", index=d.index, dtype=object)
    grp[d == DIRECT_DETAILS] = "direct"
    grp[d == "microvalue"] = "microvalue"
    grp[d.isin(GROUP_SMALL)] = "smallvalue"
    grp[d.isin(GROUP_OPEN)] = "open_tender"
    grp[d.isin(("", "nan", "None"))] = "unknown"
    return grp


def _rate(series: pd.Series) -> dict:
    known = int(series.notna().sum())
    hits = int((series == 1).sum())
    return {
        "n_known": known,
        "n_hits": hits,
        "hit_rate": (hits / known) if known else None,
    }


def population_stats(frame: pd.DataFrame) -> dict:
    """Per-population indicator rates as measured (no normalisation)."""
    out: dict = {"n_rows": int(len(frame))}
    yrs = pd.to_numeric(frame["event_year"], errors="coerce").dropna()
    out["event_year_range"] = (
        [int(yrs.min()), int(yrs.max())] if len(yrs) else None
    )
    for c in HIT_COLS:
        out[c] = _rate(frame[c])
    eligible = frame[frame["n_module_known"] >= 1]
    n_eligible = len(eligible)
    n_selected = int((eligible["n_module_hits"] >= 1).sum())
    out["module_selected"] = {
        "n_eligible": int(n_eligible),
        "n_selected": n_selected,
        "share": (n_selected / n_eligible) if n_eligible else None,
    }
    for c in CONTINUOUS_COLS:
        s = pd.to_numeric(frame[c], errors="coerce")
        out[c] = {
            "n_known": int(s.notna().sum()),
            "mean": float(s.mean()) if s.notna().any() else None,
        }
    return out


def _compare_arms(
    sel: pd.DataFrame,
    ctl: pd.DataFrame,
    col: str,
    seed: list[int],
    n_boot: int,
) -> dict:
    """Selected vs control rate for one outcome + buyer-cluster bootstrap CI.

    Point estimate and bootstrap both use rows with a known outcome *and* a
    known buyer (clustering unit), so the estimate and its CI describe the
    same population; exclusions are reported instead of silently mixed.
    """
    sub_s = sel[[col, "buyer_id"]].dropna()
    sub_c = ctl[[col, "buyer_id"]].dropna()
    n_excl = int(
        sel[col].notna().sum() - len(sub_s) + ctl[col].notna().sum() - len(sub_c)
    )
    if sub_s.empty or sub_c.empty:
        return {
            "selected_rate": None,
            "control_rate": None,
            "diff": None,
            "ci95": None,
            "n_selected_known": int(len(sub_s)),
            "n_control_known": int(len(sub_c)),
            "n_excluded_missing_buyer": n_excl,
            "n_cluster_buyers": 0,
            "n_valid_bootstrap": 0,
            "verdict": "insufficient_data",
        }

    agg_s = sub_s.groupby("buyer_id")[col].agg(["sum", "count"])
    agg_c = sub_c.groupby("buyer_id")[col].agg(["sum", "count"])
    buyers = agg_s.index.union(agg_c.index)
    agg_s = agg_s.reindex(buyers, fill_value=0.0)
    agg_c = agg_c.reindex(buyers, fill_value=0.0)
    sum_s = agg_s["sum"].to_numpy(dtype="float64")
    n_s = agg_s["count"].to_numpy(dtype="float64")
    sum_c = agg_c["sum"].to_numpy(dtype="float64")
    n_c = agg_c["count"].to_numpy(dtype="float64")

    n_buyers = len(buyers)
    rate_s = float(sum_s.sum() / n_s.sum())
    rate_c = float(sum_c.sum() / n_c.sum())

    rng = np.random.default_rng(seed)
    diffs = np.full(n_boot, np.nan, dtype="float64")
    chunk = 64
    for start in range(0, n_boot, chunk):
        m = min(chunk, n_boot - start)
        idx = rng.integers(0, n_buyers, size=(m, n_buyers))
        s_n = n_s[idx].sum(axis=1)
        c_n = n_c[idx].sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            r_s = np.where(s_n > 0, sum_s[idx].sum(axis=1) / np.maximum(s_n, 1), np.nan)
            r_c = np.where(c_n > 0, sum_c[idx].sum(axis=1) / np.maximum(c_n, 1), np.nan)
        diffs[start : start + m] = r_s - r_c
    valid = diffs[~np.isnan(diffs)]
    if len(valid):
        lo, hi = (float(x) for x in np.percentile(valid, [2.5, 97.5]))
        verdict = "ci_excludes_0" if (lo > 0.0 or hi < 0.0) else "ci_includes_0"
    else:
        lo, hi, verdict = None, None, "insufficient_data"

    return {
        "selected_rate": rate_s,
        "control_rate": rate_c,
        "diff": rate_s - rate_c,
        "ci95": [lo, hi],
        "n_selected_known": int(len(sub_s)),
        "n_control_known": int(len(sub_c)),
        "n_excluded_missing_buyer": n_excl,
        "n_cluster_buyers": int(n_buyers),
        "n_valid_bootstrap": int(len(valid)),
        "verdict": verdict,
    }


def match_direct_track(
    direct: pd.DataFrame,
    sel_mask: pd.Series,
    seed: int,
) -> tuple[list[int], list[int], dict]:
    """1:1 matched controls for the selected direct-award cases.

    Strata: event year x contract-value quartile (quartiles computed on the
    direct population only). Controls are drawn without replacement within
    each stratum from non-selected procedures; when a stratum has fewer
    controls than selected cases, the excess selected cases are dropped from
    the comparison (reported) so the arms stay 1:1. Deterministic for a seed.
    """
    rng = np.random.default_rng([seed, 0])
    money = direct["contract_value_mdl"]
    qtile = pd.Series(np.nan, index=direct.index, dtype="float64")
    has_money = money.notna() & (money > 0)
    if int(has_money.sum()) >= 8:
        qtile.loc[has_money] = pd.qcut(
            money.loc[has_money].rank(method="first"), 4, labels=[1, 2, 3, 4]
        ).astype("float64")
    direct = direct.assign(_qtile=qtile)
    stratum_ok = direct["event_year"].notna() & direct["_qtile"].notna()

    sel = direct[sel_mask & stratum_ok]
    dropped_no_stratum = int((sel_mask & ~stratum_ok).sum())
    pool = direct[~sel_mask & stratum_ok]

    sel_groups = {
        k: v.index.to_numpy() for k, v in sel.groupby(["event_year", "_qtile"])
    }
    pool_groups = {
        k: v.index.to_numpy() for k, v in pool.groupby(["event_year", "_qtile"])
    }

    matched_sel: list[int] = []
    controls: list[int] = []
    unmatched_sel = 0
    for key, sel_idx in sel_groups.items():
        candidates = pool_groups.get(key, np.empty(0, dtype=sel_idx.dtype))
        n_take = min(len(sel_idx), len(candidates))
        unmatched_sel += len(sel_idx) - n_take
        keep = rng.permutation(len(sel_idx))[:n_take]
        take = rng.permutation(len(candidates))[:n_take]
        matched_sel.extend(sel_idx[keep].tolist())
        controls.extend(candidates[take].tolist())

    meta = {
        "seed": seed,
        "strata": ["event year", "contract value quartile (direct population)"],
        "n_strata_used": len(sel_groups),
        "n_pool_controls_available": int(len(pool)),
        "n_selected_with_stratum": int(len(sel)),
        "n_selected_matched": len(matched_sel),
        "n_matched_controls": len(controls),
        "n_selected_dropped_stratum_exhausted": unmatched_sel,
        "n_selected_dropped_missing_year_or_quartile": dropped_no_stratum,
        "controls_disjoint_from_selected": True,
        "sampling": "without replacement within stratum",
    }
    return matched_sel, controls, meta


def _freq_summary(sel: pd.DataFrame, ctl: pd.DataFrame) -> dict:
    """Frequency/concentration context for the direct track (descriptive)."""
    out: dict = {}
    for c in ("buyer_prior_365d_count", "buyer_prior_single_share"):
        s = pd.to_numeric(sel[c], errors="coerce").dropna()
        r = pd.to_numeric(ctl[c], errors="coerce").dropna()
        out[f"{c}_median"] = {
            "selected": float(s.median()) if len(s) else None,
            "control": float(r.median()) if len(r) else None,
        }
    return out


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--features", type=Path, default=ROOT / "data/features/features.csv"
    )
    ap.add_argument(
        "--scores",
        type=Path,
        default=ROOT / "results/tables/tender_anomaly_scores.csv",
    )
    ap.add_argument("--outdir", type=Path, default=ROOT / "results")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--top", type=int, default=200)
    args = ap.parse_args(argv)

    if not args.features.exists():
        print(f"ERROR: features not found: {args.features}", file=sys.stderr)
        return 1

    df = pd.read_csv(args.features, usecols=lambda c: c in FEATURE_COLUMNS)
    n_rows = len(df)
    print(f"[34] features: {n_rows} rows from {args.features}")

    # --- event date provenance (award -> start -> publication) ------------ #
    award_known = pd.to_datetime(df["award_date"], errors="coerce", utc=True).notna()
    ed = event_date(df)
    prov = {
        "award_date": int(award_known.sum()),
        "fallback_only": int((ed.notna() & ~award_known).sum()),
        "missing": int(ed.isna().sum()),
        "fallback_note": (
            "rows without award_date use tender_start/published_date as the "
            "event timestamp (documented approximation)"
        ),
    }

    # --- module + evaluation-only outputs --------------------------------- #
    mods = module_indicators(df)
    fut = future_confirmation_indicators(df)

    tab = pd.DataFrame(
        {
            "ocid": df["ocid"],
            "tender_id": df["tender_id"],
            "title": df["title"] if "title" in df.columns else None,
            "status": df["status"] if "status" in df.columns else None,
            "procurement_method_details": df["procurement_method_details"],
            "buyer_id": df["buyer_id"],
            "buyer_name": df["buyer_name"] if "buyer_name" in df.columns else None,
            "winner_id": df["winner_id"] if "winner_id" in df.columns else None,
            "winner_name": df["winner_name"] if "winner_name" in df.columns else None,
            "cpv_primary": df["cpv_primary"],
            "award_date": df["award_date"],
            "event_date": ed,
            "event_year": ed.dt.year,
            "contract_value_mdl": contract_value(df),
            "group": assign_group(df["procurement_method_details"]),
        }
    )
    tab = pd.concat([tab, mods, fut], axis=1)

    # --- v0 reference baseline (read-only join) --------------------------- #
    v0_note = "scores table unavailable - v0 reference columns are null"
    if args.scores.exists():
        sc = pd.read_csv(args.scores, usecols=["ocid", "n_models_flagging"])
        sc = sc.drop_duplicates("ocid").set_index("ocid")["n_models_flagging"]
        tab["v0_n_models_flagging"] = tab["ocid"].map(sc)
        v0n = tab["v0_n_models_flagging"]
        tab["v0_critical"] = (
            v0n.ge(V0_CRITICAL_VOTES).astype("float64").where(v0n.notna())
        )
        v0_note = (
            f"n_models_flagging >= {V0_CRITICAL_VOTES} (existing ensemble rule, "
            "used read-only as a reference baseline)"
        )
    else:
        tab["v0_n_models_flagging"] = np.nan
        tab["v0_critical"] = np.nan

    # --- per-population rates as measured --------------------------------- #
    populations = {
        g: population_stats(tab[tab["group"] == g])
        for g in sorted(tab["group"].unique())
    }

    # --- direct-award track ------------------------------------------------ #
    direct = tab[tab["group"] == "direct"].copy()
    sel_mask = (direct["n_module_known"] >= 1) & (direct["n_module_hits"] >= 1)
    matched_sel, controls, match_meta = match_direct_track(
        direct, sel_mask, args.seed
    )
    sel_arm = direct.loc[matched_sel]
    ctl_arm = direct.loc[controls]

    outcomes: dict = {}
    for i, col in enumerate(list(FUTURE_COLS) + ["v0_critical"]):
        outcomes[col] = _compare_arms(
            sel_arm, ctl_arm, col, seed=[args.seed, 1 + i], n_boot=args.boot
        )

    direct_track = {
        "n_direct": int(len(direct)),
        "n_selected_total": int(sel_mask.sum()),
        "selection_rate": (
            float(sel_mask.sum() / len(direct)) if len(direct) else None
        ),
        "selection_rule": (
            "n_module_hits >= 1 among rows with at least one determined module "
            "hit (module A is undefined for direct awards by design)"
        ),
        "matching": match_meta,
        "outcomes": outcomes,
        "outcome_note": OUTCOME_NOTE,
        "frequency_context": _freq_summary(sel_arm, ctl_arm),
        "interpretation": (
            "descriptive comparison only: a measurable difference means the "
            "selected cases show reviewable follow-up patterns more often than "
            "matched controls; it is not evidence of wrongdoing"
        ),
    }

    # --- writes ------------------------------------------------------------- #
    meta = indicator_metadata()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "generated_at_utc": generated,
        "script": "scripts/34_risk_modules.py",
        "corpus": {
            "rows": n_rows,
            "event_date_provenance": prov,
            "event_year_range": [
                int(ed.dt.year.min()),
                int(ed.dt.year.max()),
            ],
        },
        "config": {
            "seed": args.seed,
            "bootstrap_replicates": args.boot,
            "top_cases": args.top,
            "split_window_days": SPLIT_WINDOW_DAYS,
            "repeat_window_days": REPEAT_WINDOW_DAYS,
            "min_group_size": MIN_GROUP_SIZE,
            "outlier_z": OUTLIER_Z,
            "v0_reference_rule": v0_note,
        },
        "indicator_metadata": meta,
        "populations": populations,
        "direct_track": direct_track,
        "limitations": [
            "no legal threshold history: threshold-based legal interpretation "
            "is disabled by construction",
            "module B clusters are retrospective (as-of-now), not "
            "point-in-time publication features",
            "rows without any event timestamp are excluded from the matching "
            "strata and reported",
            "forward-looking outcomes are evaluation-only and never inputs",
            "procedure-type coverage is not constant over time: the "
            "directaward label appears only from 2022 (99.99% of direct rows "
            "are 2023-2024), so cross-population rate comparisons span "
            "different eras; within the direct track both arms are matched "
            "within event year, so they are temporally comparable",
        ],
        "disclaimer": meta["disclaimer"],
    }

    meth_dir = args.outdir / "methodology"
    tables_dir = args.outdir / "tables"
    meth_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    json_path = meth_dir / "risk_modules.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    ind_path = tables_dir / "risk_module_indicators.csv"
    tab[[c for c in INDICATOR_TABLE_COLS if c in tab.columns]].to_csv(
        ind_path, index=False
    )

    cases_path = tables_dir / "risk_module_cases.csv"
    eligible = tab[tab["n_module_known"] >= 1]
    cases = eligible.sort_values(
        ["n_module_hits", "pair_prior_awards", "ocid"],
        ascending=[False, False, True],
        na_position="last",
    ).head(args.top)
    case_cols = [
        "ocid",
        "tender_id",
        "title",
        "status",
        "group",
        "procurement_method_details",
        "buyer_name",
        "winner_name",
        "cpv_primary",
        "award_date",
        "event_date",
        "contract_value_mdl",
        "n_module_hits",
        "n_module_known",
        "module_a_hit",
        "module_b_hit",
        "module_c_hit",
        "module_d_hit",
        "split_cluster_n",
        "split_same_supplier_share",
        "pair_prior_awards",
        "pair_buyer_share",
        "val_robust_z",
        "future_repeat_same_winner_365d",
        "future_same_buyer_cpv2_90d",
        "v0_n_models_flagging",
        "v0_critical",
    ]
    cases[[c for c in case_cols if c in cases.columns]].to_csv(
        cases_path, index=False
    )

    # --- stdout summary ----------------------------------------------------- #
    print(f"[34] event date provenance: {prov}")
    print("[34] hit rates by population (rate among known inputs):")
    for g, st in populations.items():
        cells = []
        for c in HIT_COLS:
            r = st[c]["hit_rate"]
            label = c.replace("module_", "").replace("_hit", "")  # a/b/c/d
            cells.append(f"{label}={'n/a' if r is None else f'{r:.4f}'}")
        selr = st["module_selected"]["share"]
        print(
            f"    {g:12s} n={st['n_rows']:6d}  "
            + "  ".join(cells)
            + f"  selected={'n/a' if selr is None else f'{selr:.4f}'}"
        )
    m = direct_track["matching"]
    print(
        f"[34] direct track: selected {direct_track['n_selected_total']}"
        f"/{direct_track['n_direct']} "
        f"({direct_track['selection_rate']:.4f}); matched "
        f"{m['n_selected_matched']}:{m['n_matched_controls']} "
        f"(dropped: stratum-exhausted={m['n_selected_dropped_stratum_exhausted']}, "
        f"no-stratum={m['n_selected_dropped_missing_year_or_quartile']})"
    )
    for col, res in outcomes.items():
        ci = res["ci95"]
        ci_txt = "n/a" if ci is None or ci[0] is None else f"[{ci[0]:.4f}, {ci[1]:.4f}]"
        print(
            f"[34]   {col}: sel={_fmt(res['selected_rate'])} "
            f"ctl={_fmt(res['control_rate'])} diff={_fmt(res['diff'])} "
            f"CI95={ci_txt} -> {res['verdict']}"
        )
    print(f"[34] wrote {json_path}")
    print(f"[34] wrote {ind_path}")
    print(f"[34] wrote {cases_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
