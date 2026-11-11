#!/usr/bin/env python3
"""Step 36 - blinded expert-review export (Phase 5, 2026-10-20).

Builds the three evaluation groups the brief requires, blinded:

1. ``module_selected``  - cases selected by the experimental risk-module
   indicators (``scripts/34``): top-N by ``n_module_hits`` (ties: prior
   pair awards, then ocid), rows with at least one determined module hit;
2. ``v0_selected``      - cases selected by the production ensemble:
   ``n_models_flagging >= 3``, top-N by ``max_score``, excluding every case
   already in group 1 (one case belongs to exactly one group);
3. ``matched_control``  - random procedures matched 1:1 to the
   module-selected cases on **(procedure group, event year, contract-value
   quartile within that group)**, seed 42, without replacement, drawn from a
   pool disjoint from both selected groups.

**Blinding.** Reviewers receive ``expert_review_cases.csv``: shuffled rows,
opaque ``case_id`` values, and *observable procurement facts only* - titles,
parties, dates, values, bidder counts, MTender links. The file contains no
scores, votes, bands, module hits, ranks or group labels; a programmatic
column check fails loudly if any model-origin column ever appears. The
``case_id -> group`` mapping lives in ``expert_review_key.csv``, kept apart
from reviewers and used only after collection to unblind.

**No manufactured assessments.** ``expert_review_template.csv`` is written
header-only: no reviewer answers exist yet, and none are invented here. The
scientific results stay *pending* until qualified reviewers actually review
(``docs/EXPERT_REVIEW_PROTOCOL.md``).

Outputs (results/ is gitignored):

* ``results/tables/expert_review_cases.csv``     - blinded, reviewer-facing
* ``results/tables/expert_review_key.csv``       - unblinding key (not for reviewers)
* ``results/tables/expert_review_template.csv``  - header-only answer form
* ``results/methodology/expert_review_export.json`` - config, sizes, blinding
  checks, metric definitions, ``status: pending``.

Usage::

    .venv/bin/python scripts/36_export_expert_review.py [--n 100] [--seed 42]
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

FEATURES_CSV = ROOT / "data/features/features.csv"
SCORES_CSV = ROOT / "results/tables/tender_anomaly_scores.csv"
MODULE_CSV = ROOT / "results/tables/risk_module_indicators.csv"

#: Reviewer-facing facts: nothing here reveals which model selected a case.
BLINDED_COLUMNS = [
    "ocid",
    "title",
    "status",
    "procurement_method",
    "procurement_method_details",
    "buyer_name",
    "winner_name",
    "cpv_primary",
    "published_date",
    "tender_start",
    "award_date",
    "estimated_value",
    "award_value",
    "award_total",
    "n_bidders",
    "bid_window_days",
    "mtender_url",
]

#: Any of these substrings in a reviewer-facing column name = model origin
#: leaking through; the export refuses to run (and the tests assert this).
DISALLOWED_SUBSTRINGS = (
    "score", "flag", "vote", "band", "consensus", "hit", "module", "group",
    "rank", "percentile", "anomaly", "model",
)

TEMPLATE_COLUMNS = [
    "case_id",
    "reviewable",  # deserves further investigation: 0/1
    "indicators_observed",  # which observable indicator triggered concern
    "documents_sufficient",  # supporting documents sufficient: 0/1/2 (2 = unknown)
    "explainable",  # alert is explainable: 0/1
    "false_alarm",  # appears to be a false alarm: 0/1
    "confidence",  # reviewer confidence 1-5
    "review_time_minutes",
    "reviewer_id",
    "comments",
]

GROUP_RULES = {
    "module_selected": (
        "top-N by n_module_hits (scripts/34; ties: pair_prior_awards, then "
        "ocid); rows with n_module_known >= 1"
    ),
    "v0_selected": (
        "n_models_flagging >= 3 (production ensemble rule, unchanged); "
        "top-N by max_score; excludes every module_selected case"
    ),
    "matched_control": (
        "random pool minus both selected groups; matched 1:1 to "
        "module_selected on (procedure group, event year, contract-value "
        "quartile within group), seed-fixed, without replacement"
    ),
}

METRIC_DEFINITIONS = {
    "reviewable_case_precision": (
        "share of cases the reviewer marks reviewable (0/1), reported per "
        "group with buyer-cluster bootstrap 95% CIs"
    ),
    "lift_over_controls": (
        "reviewable_case_precision(group) / "
        "reviewable_case_precision(matched_control); undefined while the "
        "control precision is 0"
    ),
    "inter_reviewer_agreement": (
        "pairwise Cohen's kappa on the reviewable judgement "
        "(src.mtender.eval_metrics.cohen_kappa); reported only when at least "
        "two reviewers see overlapping cases"
    ),
    "confidence_intervals": (
        "percentile bootstrap clustered by buyer (procedures of one buyer "
        "are not independent reviews)"
    ),
    "average_review_time": "mean of review_time_minutes per group",
    "per_indicator_breakdown": (
        "reviewable share grouped by the indicator the reviewer names - "
        "needs free-text coding, reported descriptively"
    ),
}

DISCLAIMER = (
    "Blinded review measures reviewability and review utility of indicators; "
    "a reviewable case is still only a potential risk requiring independent "
    "examination by a competent authority - never evidence of corruption."
)


def event_year(frame: pd.DataFrame) -> pd.Series:
    """Publication -> tender start -> award date (documented fallback chain)."""
    y = pd.to_datetime(frame["published_date"], errors="coerce", utc=True).dt.year
    y = y.fillna(
        pd.to_datetime(frame["tender_start"], errors="coerce", utc=True).dt.year
    )
    y = y.fillna(
        pd.to_datetime(frame["award_date"], errors="coerce", utc=True).dt.year
    )
    return y


def contract_value(frame: pd.DataFrame) -> pd.Series:
    """award_total -> award_value fallback; never imputed."""
    money = pd.Series(np.nan, index=frame.index, dtype="float64")
    for col in ("award_total", "award_value"):
        if col in frame.columns:
            money = money.fillna(pd.to_numeric(frame[col], errors="coerce"))
    return money


def quartile_within_group(frame: pd.DataFrame) -> pd.Series:
    """Value quartile (rank-based, robust to duplicates) inside each group."""
    out = pd.Series(np.nan, index=frame.index, dtype="float64")
    money = contract_value(frame)
    for grp, idx in frame.groupby("group", sort=False).groups.items():
        sub = pd.Index(idx)
        ok = sub[money.loc[sub].notna() & (money.loc[sub] > 0)]
        if len(ok) >= 8:
            out.loc[ok] = pd.qcut(
                money.loc[ok].rank(method="first"), 4, labels=[1, 2, 3, 4]
            ).astype("float64")
    return out


def build_groups(
    tab: pd.DataFrame, n: int, seed: int
) -> tuple[pd.DataFrame, dict]:
    """Construct the three blinded groups; returns group-labelled frame + meta.

    Every case lands in exactly one group; module cases without a matchable
    stratum (missing year/value) are dropped from *all* groups so that the
    selected and control arms stay 1:1 (dropped counts are reported).
    """
    rng = np.random.default_rng([seed, 1])

    eligible = tab[(tab["n_module_known"] >= 1) & tab["stratum_ok"]]
    n_module_dropped_no_stratum = int(
        (tab["n_module_known"] >= 1).sum() - len(eligible)
    )
    module_all = eligible.sort_values(
        ["n_module_hits", "pair_prior_awards", "ocid"],
        ascending=[False, False, True],
        na_position="last",
    )
    # group 1: the top-N experimental cases (ranked, matchable ones only)
    module_pick = module_all.head(n)

    # group 2: production-critical, top-N, never overlapping group 1
    v0_pool = tab[
        (tab["n_models_flagging"] >= 3)
        & ~tab["ocid"].isin(set(module_pick["ocid"]))
    ].sort_values(["max_score", "ocid"], ascending=[False, True])
    v0_pick = v0_pool.head(n)

    # group 3: matched controls for group 1 (same stratum, disjoint pool)
    sel_groups = {
        k: v.index.to_numpy()
        for k, v in module_pick.groupby(["group", "event_year", "qtile"])
    }
    pool = tab[
        ~tab["ocid"].isin(set(module_pick["ocid"]) | set(v0_pick["ocid"]))
        & tab["stratum_ok"]
    ]
    pool_groups = {
        k: v.index.to_numpy()
        for k, v in pool.groupby(["group", "event_year", "qtile"])
    }

    matched_module: list[int] = []
    controls: list[int] = []
    stratum_exhausted = 0
    for key, idxs in sel_groups.items():
        candidates = pool_groups.get(key, np.empty(0, dtype=idxs.dtype))
        take = min(len(idxs), len(candidates))
        stratum_exhausted += len(idxs) - take
        keep = rng.permutation(len(idxs))[:take]
        draw = rng.permutation(len(candidates))[:take]
        matched_module.extend(idxs[keep].tolist())
        controls.extend(candidates[draw].tolist())

    frames = [
        tab.loc[matched_module].assign(group_label="module_selected"),
        tab.loc[v0_pick.index].assign(group_label="v0_selected"),
        tab.loc[controls].assign(group_label="matched_control"),
    ]
    merged = pd.concat(frames, ignore_index=True)

    meta = {
        "n_requested_per_group": n,
        "seed": seed,
        "group_sizes": {
            "module_selected": int(len(frames[0])),
            "v0_selected": int(len(frames[1])),
            "matched_control": int(len(frames[2])),
        },
        "n_module_cases_dropped_missing_year_or_quartile": n_module_dropped_no_stratum,
        "n_module_cases_dropped_stratum_exhausted": stratum_exhausted,
        "n_v0_overlap_excluded_from_v0_group": int(
            tab[(tab["n_models_flagging"] >= 3)].shape[0] - len(v0_pool)
        ),
        "matching_strata": ["procedure group", "event year",
                            "value quartile within group"],
        "controls_disjoint_from_selected": True,
        "one_group_per_case": True,
    }
    return merged, meta


def assert_blinded(columns: list[str]) -> list[str]:
    """Return offending column names; the export aborts if any exist."""
    offenders = [
        c for c in columns
        for bad in DISALLOWED_SUBSTRINGS
        if bad in c.lower()
    ]
    return sorted(set(offenders))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=100, help="cases per group")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", type=Path, default=ROOT / "results")
    args = ap.parse_args(argv)

    for required in (FEATURES_CSV, SCORES_CSV):
        if not required.exists():
            print(f"ERROR: missing input {required}", file=sys.stderr)
            return 1
    if not MODULE_CSV.exists():
        print(
            f"ERROR: {MODULE_CSV} not found - run scripts/34_risk_modules.py "
            "first (the experimental group is defined by its output)",
            file=sys.stderr,
        )
        return 1

    usecols = [
        "ocid", "tender_id", "title", "status", "procurement_method",
        "procurement_method_details", "buyer_name", "winner_name",
        "cpv_primary", "published_date", "tender_start", "award_date",
        "estimated_value", "award_value", "award_total", "n_bidders",
        "bid_window_days",
    ]
    feat = pd.read_csv(FEATURES_CSV, usecols=lambda c: c in set(usecols))
    scores = pd.read_csv(SCORES_CSV, usecols=["ocid", "max_score",
                                              "n_models_flagging"])
    module = pd.read_csv(
        MODULE_CSV,
        usecols=["ocid", "n_module_hits", "n_module_known", "pair_prior_awards"],
    )
    tab = feat.merge(scores, on="ocid", how="left").merge(
        module, on="ocid", how="left"
    )
    tab["group"] = tab["procurement_method_details"].astype(str).map(
        lambda d: "direct" if d == "directaward" else (
            "open_tender" if d in (
                "opentender", "licitație_deschisă", "restrictedtender",
                "testminicompetition",
            ) else (
                "microvalue" if d == "microvalue" else (
                    "smallvalue" if d in (
                        "smallvalue", "procedură_de_valoare_mică",
                    ) else "other"
                )
            )
        )
    )
    tab["event_year"] = event_year(tab)
    tab["qtile"] = quartile_within_group(tab)
    tab["stratum_ok"] = tab["event_year"].notna() & tab["qtile"].notna()

    cases, meta = build_groups(tab, args.n, args.seed)
    cases["mtender_url"] = (
        "https://public.mtender.gov.md/tenders/" + cases["ocid"].astype(str)
    )

    # --- blinding: facts only, shuffled, opaque ids ---------------------- #
    # The internal frame legitimately carries model columns; only the
    # reviewer-facing export must be clean. Verify the requested fact columns
    # all exist, then screen exactly what gets exported.
    missing_cols = sorted(set(BLINDED_COLUMNS) - set(cases.columns))
    if missing_cols:
        print(f"ERROR: blinded fact columns missing from data: {missing_cols}",
              file=sys.stderr)
        return 1

    rng = np.random.default_rng([args.seed, 2])
    cases = cases.iloc[rng.permutation(len(cases))].reset_index(drop=True)
    cases.insert(0, "case_id", [f"ER-{i:04d}" for i in range(1, len(cases) + 1)])

    blinded = cases[["case_id"] + BLINDED_COLUMNS].copy()
    offenders = assert_blinded(list(blinded.columns))
    if offenders:
        print(f"ERROR: model-origin columns survived: {offenders}",
              file=sys.stderr)
        return 1

    key = cases[["case_id", "group_label", "ocid"]].rename(
        columns={"group_label": "group"}
    )
    key["selection_rule"] = key["group"].map(GROUP_RULES)

    template = pd.DataFrame(columns=TEMPLATE_COLUMNS)

    meth = args.outdir / "methodology"
    tables = args.outdir / "tables"
    meth.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    blinded_path = tables / "expert_review_cases.csv"
    key_path = tables / "expert_review_key.csv"
    template_path = tables / "expert_review_template.csv"
    blinded.to_csv(blinded_path, index=False)
    key.to_csv(key_path, index=False)
    template.to_csv(template_path, index=False)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "script": "scripts/36_export_expert_review.py",
        "config": {"n_per_group": args.n, "seed": args.seed},
        "groups": meta,
        "blinding": {
            "exported_columns": ["case_id"] + BLINDED_COLUMNS,
            "withheld_check": {
                "disallowed_substrings": list(DISALLOWED_SUBSTRINGS),
                "offenders_found": offenders,
                "status": "pass",
            },
            "rows_shuffled": True,
            "case_id_scheme": "ER-NNNN assigned after shuffle (opaque)",
            "key_file": "results/tables/expert_review_key.csv (keep away "
            "from reviewers; unblind only after collection)",
            "model_origin_never_exposed": True,
        },
        "files": {
            "cases": "results/tables/expert_review_cases.csv",
            "key": "results/tables/expert_review_key.csv",
            "template": "results/tables/expert_review_template.csv",
        },
        "template_rows": int(len(template)),
        "metric_definitions": METRIC_DEFINITIONS,
        "status": "pending - no qualified reviewers available; the answer "
        "template is empty by design and no assessment is manufactured",
        "disclaimer": DISCLAIMER,
    }
    (meth / "expert_review_export.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    print(f"[36] groups: {meta['group_sizes']} (requested {args.n}/group)")
    print(f"[36] dropped: no-stratum="
          f"{meta['n_module_cases_dropped_missing_year_or_quartile']} "
          f"stratum-exhausted={meta['n_module_cases_dropped_stratum_exhausted']} "
          f"v0-overlap-excluded={meta['n_v0_overlap_excluded_from_v0_group']}")
    print(f"[36] blinding check: pass ({len(BLINDED_COLUMNS)} fact columns, "
          "0 offenders)")
    print(f"[36] wrote {blinded_path}")
    print(f"[36] wrote {key_path}")
    print(f"[36] wrote {template_path} (0 rows - no manufactured assessments)")
    print(f"[36] wrote {meth / 'expert_review_export.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
