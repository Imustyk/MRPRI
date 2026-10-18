#!/usr/bin/env python3
"""Paired delta ROC-AUC of one cycle variant vs ``v0_baseline`` on the tuning
split, with BOTH bootstrap flavours.

The cycle protocol (`scripts/20`) reports the paired delta with the
PROCEDURE-level bootstrap: resampling individual procedures. The AAP label is
assigned at the SUPPLIER level (all procedures of an interdicted supplier are
positive), so procedures of one supplier are not independent and the honest
uncertainty is the CLUSTER bootstrap that resamples suppliers with their
procedures (`src/mtender/eval_metrics.py`, ``bootstrap_ci`` documents the same
reasoning). This script recomputes both intervals for a chosen variant against
v0 on tuning (2018-2021) so that the artefacts carry the honest interval next
to the procedure one.

Usage:
    .venv/bin/python scripts/27_delta_cluster_boot.py \
        [--variant v4b_datafix_keep_duplicate] [--baseline v0_baseline] \
        [--n-boot 1000] [--out <name.json>]

Defaults reproduce the cycle-4 measurement (v4b vs v0); cycle 5 runs
``--variant v5_group_percentile``. The variant machinery (corpus loading,
``apply_datafix``, ``build_group_labels``, ``fit_ensemble``) is imported from
``scripts/20_cycle_framework.py`` - nothing is reimplemented.

Outputs:
  results/methodology/delta_<variant>_vs_<baseline>_boot.json
  a short block on stdout
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
sys.path.insert(0, str(ROOT))

from src.mtender.config import DATA_FEATURES, RESULTS           # noqa: E402
from src.mtender.external_labels import build_label_table      # noqa: E402
from src.mtender.features import FEATURE_COLUMNS                # noqa: E402
from src.mtender.eval_metrics import roc_auc                    # noqa: E402

SEED = 42
N_BOOT = 1000
TUNING = (2018, 2021)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name.removesuffix(".py"), ROOT / "scripts" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _norm_winner(series: pd.Series) -> pd.Series:
    """Same supplier-id normalisation as ``apply_datafix`` (cluster keys)."""
    return (series.astype("string")
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
            .str.upper()
            .replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA}))


def _paired_delta_ci(y: np.ndarray, r_a: np.ndarray, r_b: np.ndarray,
                     idx_draws: list[np.ndarray]) -> dict:
    """Percentile CI of AUC(a) - AUC(b) over shared resampling draws."""
    point = float(roc_auc(y, r_a) - roc_auc(y, r_b))
    draws = []
    for idx in idx_draws:
        ya = y[idx]
        if ya.min() == ya.max():
            continue  # single-class resample carries no AUC
        draws.append(float(roc_auc(ya, r_a[idx]) - roc_auc(ya, r_b[idx])))
    arr = np.asarray(draws, dtype=float)
    return {"point": round(point, 6),
            "lo": round(float(np.quantile(arr, 0.025)), 6),
            "hi": round(float(np.quantile(arr, 0.975)), 6),
            "se": round(float(arr.std(ddof=1)), 6),
            "n_boot": int(arr.size)}


def _fit_variant(s20, spec: dict, df: pd.DataFrame, cols: list[str],
                 stage06, group_labels) -> np.ndarray:
    """The ranking of one cycle variant exactly as scripts/20 computes it."""
    df_use = s20.apply_datafix(df) if spec.get("datafix") else df
    X = df_use[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    kwargs = ({"groups": group_labels}
              if spec.get("rank", "").startswith("group_pct") else {})
    if spec.get("group_flags"):
        kwargs["group_flags"] = True
    return s20.fit_ensemble(X, stage06, **kwargs)[spec["rank"]]


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", default="v4b_datafix_keep_duplicate")
    ap.add_argument("--baseline", default="v0_baseline")
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--out", default=None,
                    help="output file name (default delta_<variant>_vs_<baseline>_boot.json)")
    args = ap.parse_args()

    t0 = time.time()
    s20 = _load_script("20_cycle_framework.py")
    spec_a = s20.VARIANTS[args.variant]
    spec_b = s20.VARIANTS[args.baseline]

    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    labels, _ = build_label_table()
    df = df.merge(labels[["ocid", "is_aap_positive"]], on="ocid", how="left")
    y = df["is_aap_positive"].fillna(0).astype(int).to_numpy()
    year = pd.to_datetime(df["published_date"], errors="coerce").dt.year
    tuning = year.between(*TUNING).fillna(False).to_numpy()

    group_labels, _ = s20.build_group_labels(df)
    stage06 = s20._load_stage06()
    rank_a = _fit_variant(s20, spec_a, df, cols, stage06, group_labels)
    rank_b = _fit_variant(s20, spec_b, df, cols, stage06, group_labels)

    y_t = y[tuning]
    ra, rb = rank_a[tuning], rank_b[tuning]
    cluster = (_norm_winner(df["winner_id"]).fillna("<no-winner>")
               .to_numpy()[tuning])

    rng = np.random.default_rng(SEED)
    units, encoded = np.unique(cluster, return_inverse=True)
    members = {u: np.flatnonzero(encoded == u) for u in range(len(units))}

    proc_draws, clus_draws = [], []
    n = y_t.size
    for _ in range(args.n_boot):
        proc_draws.append(rng.integers(0, n, size=n))
        picked = rng.integers(0, len(units), size=len(units))
        clus_draws.append(np.concatenate([members[u] for u in picked]))

    out = {
        "variant": f"{args.variant} vs {args.baseline}",
        "split": f"tuning {TUNING[0]}-{TUNING[1]}",
        "positives": int(y_t.sum()),
        "n_procedures": int(n),
        "n_supplier_clusters": int(len(units)),
        "seed": SEED,
        "n_boot": args.n_boot,
        "procedure_bootstrap": _paired_delta_ci(y_t, ra, rb, proc_draws),
        "cluster_bootstrap_by_supplier": _paired_delta_ci(y_t, ra, rb,
                                                          clus_draws),
        "seconds": round(time.time() - t0, 1),
    }
    short_a = args.variant.split("_")[0]
    short_b = args.baseline.split("_")[0]
    name = args.out or f"delta_{short_a}_vs_{short_b}_boot.json"
    path = RESULTS / "methodology" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nreport -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
