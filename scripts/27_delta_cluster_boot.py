#!/usr/bin/env python3
"""Paired delta ROC-AUC of ``v4b_datafix_keep_duplicate`` vs ``v0_baseline``
on the tuning split, with BOTH bootstrap flavours.

The cycle protocol (`scripts/20`) reports the paired delta with the
PROCEDURE-level bootstrap: resampling individual procedures. The AAP label is
assigned at the SUPPLIER level (all procedures of an interdicted supplier are
positive), so procedures of one supplier are not independent and the honest
uncertainty is the CLUSTER bootstrap that resamples suppliers with their
procedures (`src/mtender/eval_metrics.py`, ``bootstrap_ci`` documents the same
reasoning). This script recomputes both intervals for the v4b-vs-v0 delta on
tuning (2018-2021) so that the artefacts carry the honest interval next to
the procedure one.

Outputs:
  results/methodology/delta_v4b_vs_v0_boot.json
  a short block on stdout

The variant machinery (corpus loading, ``apply_datafix``, ``fit_ensemble``) is
imported from ``scripts/20_cycle_framework.py`` — nothing is reimplemented.
"""
from __future__ import annotations

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


def main() -> int:
    warnings.filterwarnings("ignore")
    t0 = time.time()
    s20 = _load_script("20_cycle_framework.py")

    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    labels, _ = build_label_table()
    df = df.merge(labels[["ocid", "is_aap_positive"]], on="ocid", how="left")
    y = df["is_aap_positive"].fillna(0).astype(int).to_numpy()
    year = pd.to_datetime(df["published_date"], errors="coerce").dt.year
    tuning = year.between(*TUNING).fillna(False).to_numpy()

    df_fix = s20.apply_datafix(df)
    X0 = (df[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0))
    Xb = (df_fix[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0))

    stage06 = s20._load_stage06()
    rank_v0 = s20.fit_ensemble(X0, stage06)["max_score"]
    rank_v4b = s20.fit_ensemble(Xb, stage06)["max_score"]

    y_t = y[tuning]
    r0 = rank_v0[tuning]
    rb = rank_v4b[tuning]
    cluster = (df_fix.loc[tuning, "winner_id"].astype("string")
               .fillna("<no-winner>").to_numpy())

    rng = np.random.default_rng(SEED)
    units, encoded = np.unique(cluster, return_inverse=True)
    members = {u: np.flatnonzero(encoded == u) for u in range(len(units))}

    proc_draws, clus_draws = [], []
    n = y_t.size
    for _ in range(N_BOOT):
        proc_draws.append(rng.integers(0, n, size=n))
        picked = rng.integers(0, len(units), size=len(units))
        clus_draws.append(np.concatenate([members[u] for u in picked]))

    out = {
        "variant": "v4b_datafix_keep_duplicate vs v0_baseline",
        "split": f"tuning {TUNING[0]}-{TUNING[1]}",
        "positives": int(y_t.sum()),
        "n_procedures": int(n),
        "n_supplier_clusters": int(len(units)),
        "seed": SEED,
        "n_boot": N_BOOT,
        "procedure_bootstrap": _paired_delta_ci(y_t, rb, r0, proc_draws),
        "cluster_bootstrap_by_supplier": _paired_delta_ci(y_t, rb, r0,
                                                          clus_draws),
        "seconds": round(time.time() - t0, 1),
    }
    path = RESULTS / "methodology" / "delta_v4b_vs_v0_boot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nreport -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
