#!/usr/bin/env python3
"""Second external check: the «procedure contested» label (MTA-0013).

MEASUREMENT ONLY - not a cycle: production stays v0, the budget stays 6 of 10,
no v7 exists, votes and bands are untouched, nothing is retrained for
production, and nothing is downloaded (local raw OCDS + existing artefacts
only - this script has no network imports at all; regression-tested).

Label (author's MTA-0013 definition): ``contested = 1`` when the procedure
carries at least one OCDS document with ``documentType == "complaints"`` at
ANY level (tender / awards[] / contracts[] / planning). Documents are
deduplicated by ``(ocid, url or title)`` and procedures by ``ocid`` - the
raw OCDS contains duplicate document rows; the number of removed rows is
reported.

Population: a complaint is only possible where there is competition, so the
MAIN population is competitive procedures ``n_bidders >= 2``, where
``n_bidders`` is the number of unique ``tenderers`` identifiers across
``tender.bids.details[]`` of the compiled OCDS release
(``src/mtender/ocds.py``). Direct awards and other non-competitive
procedures are excluded from the main population and reported separately.

The v0 ranking is the FIXED production artefact
(``results/tables/tender_anomaly_scores.csv::max_score``) - it is measured,
never recomputed. The leakage diagnostic re-fits the SAME ``scripts/20``
code path (``fit_ensemble``) WITHOUT the ``LEAKAGE_SUSPECT`` features and
writes only into this script's own JSON - a diagnostic, not a new version.

Outputs: ``results/methodology/ansc_external_check.json`` (aggregates only -
no personal data of individuals is persisted).

Usage:
    .venv/bin/python scripts/31_ansc_external_check.py [--limit-scan N]
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mtender.config import DATA_FEATURES, RESULTS, TABLES  # noqa: E402
from src.mtender.eval_metrics import roc_auc  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS  # noqa: E402
from src.mtender.ocds import merge_compiled_releases  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "ocds_packages"
OUT_JSON = RESULTS / "methodology" / "ansc_external_check.json"
BANDS_JSON = RESULTS / "methodology" / "v5_group_bands.json"
PROD_SCORES = TABLES / "tender_anomaly_scores.csv"

# --- pre-registered constants (fixed in reports/ansc_external_check.md BEFORE
# the measurement; do not change them after seeing the numbers) ---------------
SEED = 42
N_BOOT = 1000
RANDOM_REPEATS = 200
TOP_K = (100, 200, 500)
MIN_POSITIVES_PER_GROUP = 50
LABEL_DOCTYPE = "complaints"
COMPETITIVE_MIN_BIDDERS = 2

#: Features whose value can change AFTER a complaint is filed/decided -
#: award counts, amendments, statuses, award amounts (post-decision
#: information). Exactly 10 of the 22 production features; criterion and list
#: are pre-registered in the report.
LEAKAGE_SUSPECT = [
    "multi_award_tender", "amended", "n_amendments",
    "cancelled", "no_award_after_tender",
    "log_award_value", "log_award_total", "estimate_to_award_ratio",
    "value_vs_cpv_median", "value_zscore_cpv",
]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def doc_key(ocid: str, doc: dict) -> tuple[str, str]:
    """Dedup key of a document: its url, falling back to title."""
    return (ocid, str(doc.get("url") or doc.get("title") or ""))


def build_contested_label(raw_dir: Path, limit: int = 0) -> tuple[set[str], dict]:
    """Scan the raw OCDS (read-only) for documentType == "complaints".

    Returns ``(contested_ocids, stats)`` with document/procedure dedup
    counters.
    """
    files = sorted(raw_dir.glob("*.json.gz"))
    if limit:
        files = files[:limit]
    docs_rows = 0
    docs_unique: set[tuple[str, str]] = set()
    procs: set[str] = set()
    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                package = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        compiled = merge_compiled_releases(package)
        if not compiled:
            continue
        ocid = compiled.get("ocid") or path.name[:-8]
        found = False
        containers = [compiled.get("tender"), compiled.get("planning")]
        for kind in ("awards", "contracts"):
            containers.extend(item for item in (compiled.get(kind) or [])
                              if isinstance(item, dict))
        for container in containers:
            if not isinstance(container, dict):
                continue
            for doc in container.get("documents") or []:
                if isinstance(doc, dict) and \
                        doc.get("documentType") == LABEL_DOCTYPE:
                    docs_rows += 1
                    docs_unique.add(doc_key(ocid, doc))
                    found = True
        if found:
            procs.add(ocid)
    # 36 planning-notice packages carry a "-PN-" suffixed compiled ocid while
    # the corpus and the production ranking index the SAME procedure under
    # the base MD ocid (the package file name); register the alias so the
    # label joins to the ranking (the same identity-artefact logic as v4).
    aliases = {p.split("-PN-")[0] for p in procs if "-PN-" in p} - procs
    stats = {
        "documents_rows": docs_rows,
        "documents_unique": len(docs_unique),
        "documents_removed_duplicate": docs_rows - len(docs_unique),
        "procedures": len(procs),
        "pn_ocid_aliases_added": len(aliases),
        "expected_from_mta0012": 1665,
    }
    return procs | aliases, stats


def cluster_bootstrap_auc(y: np.ndarray, scores: np.ndarray, clusters: np.ndarray,
                          n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """AUC CI from a bootstrap over CLUSTERS (all rows of a drawn cluster)."""
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    clusters = np.asarray(clusters).astype(str)
    uniq = np.unique(clusters)
    idx_by = {c: np.flatnonzero(clusters == c) for c in uniq}
    rng = np.random.default_rng(seed)
    aucs: list[float] = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by[c] for c in pick])
        if np.unique(y[idx]).size < 2:
            continue
        aucs.append(roc_auc(y[idx], scores[idx]))
    arr = np.asarray(aucs)
    return {
        "point": round(roc_auc(y, scores), 6) if np.unique(y).size > 1 else None,
        "ci": [round(float(np.quantile(arr, 0.025)), 6),
               round(float(np.quantile(arr, 0.975)), 6)] if arr.size else None,
        "n_boot": int(arr.size),
        "n_clusters": int(len(uniq)),
        "method": f"cluster bootstrap by buyer, {n_boot} reps, seed {seed}",
    }


def procedure_bootstrap_auc(y: np.ndarray, scores: np.ndarray,
                            n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Row (procedure) bootstrap, shown next to the cluster CI for scale."""
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    rng = np.random.default_rng(seed)
    aucs: list[float] = []
    n = len(y)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        if np.unique(y[idx]).size < 2:
            continue
        aucs.append(roc_auc(y[idx], scores[idx]))
    arr = np.asarray(aucs)
    return {
        "point": round(roc_auc(y, scores), 6) if np.unique(y).size > 1 else None,
        "ci": [round(float(np.quantile(arr, 0.025)), 6),
               round(float(np.quantile(arr, 0.975)), 6)] if arr.size else None,
        "n_boot": int(arr.size),
        "method": f"procedure bootstrap, {n_boot} reps, seed {seed}",
    }


def precision_at_k(y: np.ndarray, scores: np.ndarray, k: int) -> float | None:
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    if not len(y):
        return None
    order = np.argsort(-scores, kind="stable")[: min(k, len(y))]
    return round(float(y[order].mean()), 6)


def random_auc_baseline(y: np.ndarray, repeats: int = RANDOM_REPEATS,
                        seed: int = SEED) -> dict:
    """AUC distribution of RANDOM rankings on the same rows."""
    y = np.asarray(y, dtype=int)
    rng = np.random.default_rng(seed)
    aucs = [roc_auc(y, rng.random(len(y))) for _ in range(repeats)]
    arr = np.asarray(aucs)
    return {
        "repeats": repeats,
        "mean": round(float(arr.mean()), 6),
        "std": round(float(arr.std(ddof=1)), 6),
        "q025": round(float(np.quantile(arr, 0.025)), 6),
        "q975": round(float(np.quantile(arr, 0.975)), 6),
    }


def stratified_auc(y: np.ndarray, scores: np.ndarray, groups: np.ndarray,
                   min_positives: int = MIN_POSITIVES_PER_GROUP) -> dict:
    """AUC per «cost band x procedure type» group; low-power groups flagged."""
    y = np.asarray(y, dtype=int)
    scores = np.asarray(scores, dtype=float)
    groups = np.asarray(groups).astype(str)
    out: dict[str, dict] = {}
    for g in sorted(np.unique(groups)):
        mask = groups == g
        n = int(mask.sum())
        pos = int(y[mask].sum())
        if pos < min_positives or np.unique(y[mask]).size < 2:
            out[g] = {"n": n, "positives": pos,
                      "auc": None, "note": "мощность недостаточна "
                                            f"(<{min_positives} позитивов)"}
        else:
            out[g] = {"n": n, "positives": pos,
                      "auc": round(roc_auc(y[mask], scores[mask]), 6)}
    return out


def decide_verdict(v0_cluster: dict, size_auc: float, bidders_auc: float,
                   noleak_cluster: dict, random_q975: float) -> dict:
    """Pre-registered conclusion rule (а/б/в) from the report."""
    point = v0_cluster["point"]
    lo, hi = v0_cluster["ci"]
    determined_by_baseline = point <= max(size_auc, bidders_auc) \
        or point <= random_q975
    noleak_lo, noleak_hi = noleak_cluster["ci"]
    determined_by_leakage = (lo > 0.5) and (noleak_lo <= 0.5 <= noleak_hi)
    if lo > 0.5 and not determined_by_baseline and not determined_by_leakage:
        code, text = "а", (
            "кластерный ДИ целиком выше 0,5, v0 лучше размера и числа "
            "участников и не определяется утечкой — на спорных процедурах v0 "
            "обнаруживает то, чего не объясняют размер и конкуренция")
    elif lo <= 0.5 <= hi:
        code, text = "б", (
            "ДИ включает 0,5 — на этой метке сигнал неотличим от случайного")
    else:
        reasons = []
        if hi < 0.5:
            reasons.append("ДИ ниже 0,5")
        if determined_by_baseline:
            reasons.append("результат определяется размером/участниками")
        if determined_by_leakage:
            reasons.append("результат определяется утечкой признаков")
        code, text = "в", ("; ".join(reasons) or "критерии (а) и (б) не "
                           "выполнены") + (
            " — метка объясняется размером, конкуренцией или утечкой")
    return {"code": code, "text": text,
            "determined_by_baseline": bool(determined_by_baseline),
            "determined_by_leakage": bool(determined_by_leakage)}


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit-scan", type=int, default=0,
                    help="scan only the first N raw packages (development)")
    args = ap.parse_args()
    t0 = time.time()

    label_ocids, label_stats = build_contested_label(RAW_DIR, args.limit_scan)
    print(f"label: {label_stats['procedures']} procedures "
          f"(expected ~{label_stats['expected_from_mta0012']}); "
          f"documents rows {label_stats['documents_rows']} -> unique "
          f"{label_stats['documents_unique']} (removed dups "
          f"{label_stats['documents_removed_duplicate']})", flush=True)

    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    prod = pd.read_csv(PROD_SCORES, usecols=["ocid", "max_score"],
                       low_memory=False)
    df = df.merge(prod, on="ocid", how="left", validate="one_to_one")
    df["contested"] = df["ocid"].isin(label_ocids).astype(int)

    n_bidders = pd.to_numeric(df["n_bidders"], errors="coerce").fillna(0)
    competitive = (n_bidders >= COMPETITIVE_MIN_BIDDERS).to_numpy()
    y_all = df["contested"].to_numpy()
    buyer = (df["buyer_identifier"].astype("string").fillna(df["buyer_id"])
             .astype("string").fillna(df["buyer_name"])
             .astype("string").fillna("UNKNOWN").to_numpy())

    def pop_block(mask: np.ndarray) -> dict:
        return {"n_procedures": int(mask.sum()),
                "positives": int(y_all[mask].sum()),
                "base_rate": round(float(y_all[mask].mean()), 6)
                if mask.sum() else None}

    populations = {
        "весь корпус": pop_block(np.ones(len(df), dtype=bool)),
        "основная популяция — конкурентные (n_bidders >= 2)":
            pop_block(competitive),
        "неконкурентные (n_bidders < 2, включая прямые закупки)":
            pop_block(~competitive),
    }
    print("populations:", json.dumps(populations, ensure_ascii=False),
          flush=True)

    main_mask = competitive
    y = y_all[main_mask]
    score_v0 = df["max_score"].to_numpy()[main_mask]
    clusters = buyer[main_mask]

    v0_cluster = cluster_bootstrap_auc(y, score_v0, clusters)
    v0_proc = procedure_bootstrap_auc(y, score_v0)

    size_scores = pd.to_numeric(df["log_award_total"],
                                errors="coerce").fillna(0).to_numpy()[main_mask]
    bidders_scores = pd.to_numeric(df["n_bidders_log"],
                                   errors="coerce").fillna(0).to_numpy()[main_mask]
    size_block = {
        "auc": round(roc_auc(y, size_scores), 6),
        "cluster_ci": cluster_bootstrap_auc(y, size_scores, clusters)["ci"],
    }
    bidders_block = {
        "auc": round(roc_auc(y, bidders_scores), 6),
        "cluster_ci": cluster_bootstrap_auc(y, bidders_scores, clusters)["ci"],
    }
    random_block = random_auc_baseline(y)
    print(f"v0 AUC {v0_cluster['point']} cluster-CI {v0_cluster['ci']}; "
          f"size {size_block['auc']}; bidders {bidders_block['auc']}; "
          f"random q975 {random_block['q975']}", flush=True)

    precision = {f"precision_at_{k}": precision_at_k(y, score_v0, k)
                 for k in TOP_K}

    # --- stratification: the SAME «band x type» groups as v5/v6 --------------
    s20 = _load_script("20_cycle_framework.py")
    band_edges = json.loads(BANDS_JSON.read_text(encoding="utf-8"))["band_edges"]
    group_labels, group_meta = s20.build_group_labels(df, edges=band_edges)
    strat = stratified_auc(y_all[main_mask], score_v0,
                           np.asarray(group_labels)[main_mask])
    enough = {g: v for g, v in strat.items() if v.get("auc") is not None}
    print(f"groups: {len(strat)} total, {len(enough)} with >= "
          f"{MIN_POSITIVES_PER_GROUP} positives", flush=True)

    # --- leakage diagnostic: same code path, suspect features removed --------
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    noleak_cols = [c for c in cols if c not in LEAKAGE_SUSPECT]
    X_base = df[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    stage06 = s20._load_stage06()
    fit = s20.fit_ensemble(X_base[noleak_cols], stage06)
    noleak_rank = fit["max_score"][main_mask]
    noleak_cluster = cluster_bootstrap_auc(y, noleak_rank, clusters)
    noleak_proc = procedure_bootstrap_auc(y, noleak_rank)
    print(f"no-leak ({len(noleak_cols)} features) AUC {noleak_cluster['point']} "
          f"cluster-CI {noleak_cluster['ci']}", flush=True)

    verdict = decide_verdict(v0_cluster, size_block["auc"],
                             bidders_block["auc"], noleak_cluster,
                             random_block["q975"])
    verdict_text = (
        f"Вывод ({verdict['code']}): {verdict['text']}. "
        "Метка означает «спорная процедура» (есть документ жалобы), а не "
        "нарушение; результат не является поводом для перестройки порогов, и "
        "решение о замене v0 здесь не принимается — это измерение, а не цикл "
        "приёмки. Индикатор потенциального риска, а не доказательство "
        "коррупции/нарушения. Требуется проверка компетентным органом.")
    print(verdict_text, flush=True)

    summary = {
        "task": "MTA-0013",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame": ("measurement only - production v0 unchanged, no v7, budget "
                  "6/10, no network"),
        "pre_registered": {
            "seed": SEED, "n_boot": N_BOOT, "random_repeats": RANDOM_REPEATS,
            "top_k": list(TOP_K),
            "min_positives_per_group": MIN_POSITIVES_PER_GROUP,
            "label_rule": "documentType == 'complaints' at any OCDS level",
            "competitive_rule": "n_bidders >= 2 (unique tenderers over "
                                "tender.bids.details[])",
            "leakage_criterion": "value can change after the complaint is "
                                 "filed/decided: award counts, amendments, "
                                 "statuses, award amounts",
        },
        "label": label_stats,
        "populations": populations,
        "v0_external": {"cluster_by_buyer": v0_cluster,
                        "procedure": v0_proc,
                        "precision": precision,
                        "base_rate_main_population":
                            populations["основная популяция — конкурентные "
                                        "(n_bidders >= 2)"]["base_rate"]},
        "baselines": {"log_award_total": size_block,
                      "n_bidders_log": bidders_block,
                      "random": random_block},
        "stratified_by_group": {
            "n_groups": len(strat),
            "n_groups_with_power": len(enough),
            "min_positives": MIN_POSITIVES_PER_GROUP,
            "groups": strat,
        },
        "leakage": {
            "suspect_features": LEAKAGE_SUSPECT,
            "n_suspect": len(LEAKAGE_SUSPECT),
            "n_noleak_features": len(noleak_cols),
            "noleak_cluster_by_buyer": noleak_cluster,
            "noleak_procedure": noleak_proc,
            "determined_by_leakage": verdict["determined_by_leakage"],
            "note": ("diagnostic only - re-fit via scripts/20 code path; no "
                     "cycle framework, votes, bands or production artefacts "
                     "were written or changed"),
        },
        "verdict": {**verdict, "text_full": verdict_text},
        "outputs": {"json": str(OUT_JSON.relative_to(ROOT))},
        "disclaimer": ("Индикатор потенциального риска, а не доказательство "
                       "коррупции/нарушения. Требуется проверка компетентным "
                       "органом."),
        "seconds": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"written {OUT_JSON.relative_to(ROOT)} "
          f"({summary['seconds']} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
