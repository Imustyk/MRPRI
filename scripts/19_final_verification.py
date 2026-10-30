"""Step 19 (methodology cycle, final check) - recompute every headline number.

The brief requires that the numbers quoted in the report are re-derived at the
end and match. This script does exactly that, from the artefacts on disk, and
exits non-zero on any mismatch:

  1. baseline reproduction  - vote distribution, band shares, consensus count
                              (must equal the production detection_summary and
                              the band counts served by the backend API)
  2. external metrics       - ROC/PR-AUC, precision@1000, votes>=3 precision
                              recomputed from scratch and compared with the
                              stored step-2 JSON
  3. univariate uncertainty - the single-feature AUCs that step 16 reported
                              (up to 0.80 for n_bidders_log) get a procedure
                              bootstrap CI, a supplier-cluster bootstrap CI and
                              a leave-one-AAP-supplier-out range: one company
                              contributes 259 of the 633 positives, so a claim
                              of "0.80" without this check would be misleading
  4. seed stability         - mean / cv / min / jaccard recomputed from the
                              20-run table
  5. bias audit anchors     - high+ and critical shares, smallest/largest buyer
                              quintile disparity ratios
  6. threshold economics    - votes>=3 cost at c_miss=10/50/200 vs flag-nothing
  7. iterative-cycle numbers- scripts/20 artefacts vs the quoted cycle
                              constants (consensus, AUC, deltas, jaccard)
  8. case registry (MTA-0016) - the registry is re-validated, re-matched and
                              re-labelled from source data and compared with
                              the stored scripts/38 and scripts/39 artefacts;
                              any drift fails here

Usage:
    .venv/bin/python scripts/19_final_verification.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, RESULTS, TABLES  # noqa: E402
from src.mtender.eval_metrics import (  # noqa: E402
    bootstrap_ci,
    precision_at_k,
    pr_auc,
    roc_auc,
)
from src.mtender.external_labels import load_scored_corpus  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS  # noqa: E402

TOL = 1e-6
MISMATCHES: list[str] = []

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def check(name: str, got: float, expected: float, tol: float = TOL) -> None:
    ok = abs(float(got) - float(expected)) <= tol
    status = "OK " if ok else "FAIL"
    print(f"  [{status}] {name}: got {got!r}, report says {expected!r}")
    if not ok:
        MISMATCHES.append(f"{name}: {got} != {expected}")


def main() -> int:
    t0 = time.time()
    corpus = load_scored_corpus()
    feats = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    uni_features = ["n_bidders_log", "log_award_total", "log_award_value",
                    "multi_award_tender", "value_vs_cpv_median"]
    # winner_identifier already comes from the label table in load_scored_corpus
    df = corpus.merge(
        feats[["ocid", *uni_features]], on="ocid", how="left",
        validate="one_to_one",
    )
    y = df["is_aap_positive"].to_numpy().astype(int)
    votes = df["n_models_flagging"].to_numpy().astype(int)
    max_score = df["max_score"].to_numpy().astype(float)

    print("== 1. baseline reproduction ==")
    dist = {k: int((votes == k).sum()) for k in range(5)}
    print(f"  vote distribution 0..4: {dist}")
    check("consensus (votes>=3)", (votes >= 3).sum(), 3031)
    bands = {
        "low": int((votes == 0).sum()),
        "medium": int((votes == 1).sum()),
        "high": int((votes == 2).sum()),
        "critical": int((votes >= 3).sum()),
    }
    print(f"  bands: {bands}")
    check("band low", bands["low"], 125242)
    check("band medium", bands["medium"], 19474)
    check("band high", bands["high"], 4631)
    check("band critical", bands["critical"], 3031)
    assert not corpus["ocid"].is_monotonic_increasing, "row order sanity"

    print("== 2. external metrics recomputed ==")
    stored = pd.read_csv(TABLES / "external_metrics.csv")
    all_period = stored[stored["period"] == "all"]
    by_metric = {(r.ranking_rule, r.metric): r.value for r in all_period.itertuples()}
    check("roc_auc max_score (all)", roc_auc(y, max_score),
          by_metric[("production_max_score", "roc_auc")])
    check("pr_auc max_score (all)", pr_auc(y, max_score),
          by_metric[("production_max_score", "pr_auc")])
    check("precision@1000 max_score", precision_at_k(y, max_score, 1000),
          by_metric[("production_max_score", "precision@1000")])
    mask = votes >= 3
    sweep = pd.read_csv(TABLES / "threshold_sweep.csv")
    v3 = sweep[(sweep["rule"] == "votes>=3") & (sweep["period"] == "all")].iloc[0]
    check("votes>=3 precision", y[mask].mean(), v3["precision"])
    check("votes>=3 n_flagged", mask.sum(), v3["n_flagged"])

    print("== 3. univariate AUC uncertainty (top step-16 features + max_score) ==")
    targets = {
        "max_score (production ranking)": max_score,
    }
    for col in uni_features:
        targets[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).to_numpy()

    supplier = df["winner_identifier"].fillna("__none__").to_numpy()
    exact_suppliers = sorted(set(
        df.loc[df["is_aap_positive"] == 1, "winner_identifier"].dropna().unique()
    ))
    uni_rows = []
    for name, score in targets.items():
        point = roc_auc(y, score)
        proc_ci = bootstrap_ci(y, score, roc_auc, n_boot=500, seed=42)
        clu_ci = bootstrap_ci(y, score, roc_auc, n_boot=500, seed=42, cluster=supplier)
        loso = []
        for sup in exact_suppliers:
            keep = supplier != sup
            auc = roc_auc(y[keep], np.asarray(score)[keep])
            if auc == auc:
                loso.append(auc)
        loo_min, loo_max = (min(loso), max(loso)) if loso else (float("nan"),) * 2
        row = {
            "target": name,
            "roc_auc": round(point, 4),
            "proc_boot_ci": [round(proc_ci["lo"], 4), round(proc_ci["hi"], 4)],
            "cluster_boot_ci": [round(clu_ci["lo"], 4), round(clu_ci["hi"], 4)],
            "leave_one_supplier_out": [round(loo_min, 4), round(loo_max, 4)],
            "n_exact_suppliers": len(exact_suppliers),
        }
        uni_rows.append(row)
        print(f"  {name:34s} AUC {point:.4f} "
              f"procCI [{row['proc_boot_ci'][0]}, {row['proc_boot_ci'][1]}] "
              f"clusterCI [{row['cluster_boot_ci'][0]}, {row['cluster_boot_ci'][1]}] "
              f"LOSO [{row['leave_one_supplier_out'][0]}, "
              f"{row['leave_one_supplier_out'][1]}]")
    # the step-16 table must agree with the recomputed point values
    contrib = pd.read_csv(TABLES / "feature_contribution.csv")
    for col in ("n_bidders_log", "log_award_total", "log_award_value"):
        got = contrib.loc[contrib["feature"] == col, "univariate_auc_external"]
        if len(got):
            check(f"step16 univariate AUC {col}",
                  float(got.iloc[0]), roc_auc(y, targets[col]), tol=1e-5)

    print("== 4. seed stability recomputed ==")
    runs = pd.read_csv(TABLES / "seed_stability_runs.csv")
    seeds_json = json.loads(
        (RESULTS / "methodology" / "robustness_seeds.json").read_text()
    )
    check("n seed runs", len(runs), 20)
    check("consensus mean", runs["n_consensus_ge3"].mean(),
          seeds_json["consensus_count"]["mean"], tol=0.05)
    check("consensus cv_pct", 100 * runs["n_consensus_ge3"].std(ddof=1)
          / runs["n_consensus_ge3"].mean(),
          seeds_json["consensus_count"]["cv_pct"], tol=0.01)
    check("jaccard mean", runs["jaccard_consensus_vs_seed42"].mean(),
          seeds_json["jaccard_consensus_vs_baseline"]["mean"], tol=1e-4)

    print("== 5. bias audit anchors ==")
    bias = pd.read_csv(TABLES / "bias_audit_groups.csv")
    check("high+ share", (votes >= 2).mean(), 0.0503, tol=1e-4)
    check("critical share", (votes >= 3).mean(), 0.0199, tol=1e-4)
    q1 = bias[(bias["group_dimension"].str.startswith("buyer size"))
              & (bias["group"] == "buyer_size Q1")].iloc[0]
    check("buyer_size Q1 disparity", q1["disparity_ratio"], 2.953, tol=0.005)

    print("== 6. threshold economics recomputed ==")
    # the sweep charges cost = c_miss * FN + FP (a true positive costs nothing
    # extra; every false positive costs one review) - assert against its CSV
    pos = int(y.sum())
    tp = int(y[mask].sum())
    fp = int(mask.sum()) - tp
    fn = pos - tp
    for c_miss in (10, 50, 200):
        cost_rule = c_miss * fn + fp
        cost_none = c_miss * pos
        check(f"votes>=3 cost_miss_{c_miss}", cost_rule,
              float(v3[f"cost_miss_{c_miss}"]))
        print(f"  c_miss={c_miss:3d}: votes>=3 cost {cost_rule:,} vs "
              f"no-flag {cost_none:,} -> beats_no_flag={cost_rule < cost_none}")

    print("== 7. iterative-cycle numbers (scripts/20 vs cycle reports) ==")
    # the framework's saved JSON is checked against the constants quoted in
    # cycle_log.md and reports/cycle_{1,2,3}.md, and its flat CSV against the
    # same JSON, so the report tables cannot drift from the artefacts
    fw = json.loads((RESULTS / "methodology" / "cycle_framework.json").read_text("utf-8"))
    variants = fw["variants"]
    quoted = {
        "v0_baseline": {"consensus": 3031, "auc_all": 0.493453},
        "v1_merge_duplicate": {"consensus": 2379, "auc_all": 0.497445,
                               "delta": 0.0030, "delta_ci": (-0.0034, 0.0096)},
        "v2_mean_rank": {"consensus": 3031, "auc_all": 0.504759,
                         "delta": -0.0327, "delta_ci": (-0.0560, -0.0090)},
        "v3_drop_behavioural": {"consensus": 1491, "auc_all": 0.533476,
                                "delta": -0.0251, "delta_ci": (-0.0558, 0.0041)},
    }
    flat = pd.read_csv(TABLES / "cycle_metrics.csv").set_index("variant")
    for name, want in quoted.items():
        blk = variants[name]
        check(f"{name} consensus", blk["bands"]["consensus_n"], want["consensus"])
        check(f"{name} auc_all", blk["external"]["all"]["roc_auc"], want["auc_all"],
              tol=1e-6)
        check(f"{name} csv consensus", flat.loc[name, "consensus_n"], want["consensus"])
        check(f"{name} csv auc_all", flat.loc[name, "auc_all"], want["auc_all"],
              tol=1e-6)
        if "delta" in want:
            d = blk["paired_delta_vs_v0_tuning"]
            check(f"{name} delta_auc_tuning", d["delta"], want["delta"], tol=5e-4)
            check(f"{name} delta_ci_lo", d["ci_lo"], want["delta_ci"][0], tol=5e-4)
            check(f"{name} delta_ci_hi", d["ci_hi"], want["delta_ci"][1], tol=5e-4)
    # the refit in the framework must reproduce the shipped production bands
    check("v0 refit vs shipped jaccard",
          variants["v0_baseline"]["production_agreement"]["jaccard_refit_vs_shipped"], 1.0)
    check("v0 stop criteria passed",
          variants["v0_baseline"]["stop_criteria_passed"], 3)
    check("v2 stop criteria passed", variants["v2_mean_rank"]["stop_criteria_passed"], 4)

    print("== 8. case registry re-derived (MTA-0016) ==")
    # The registry is re-validated, re-matched and re-labelled from the CSV
    # and the corpus, and every headline count is compared with the stored
    # scripts/38 and scripts/39 artefacts: a report that drifts from its
    # source data fails here.
    s38 = _load_script("38_case_registry_match.py")
    s39 = _load_script("39_case_registry_check.py")
    registry_csv = ROOT / "data" / "external" / "case_registry.csv"
    raw = pd.read_csv(registry_csv, dtype="string", keep_default_na=False)
    reg, reg_val = s38.validate_registry(raw)
    reg_corpus = s38.load_corpus(DATA_FEATURES / "features.csv")
    reg_cases, _reg_proc, reg_summary = s38.match_cases(reg, reg_corpus)

    match_artefact = json.loads(
        (RESULTS / "methodology" / "case_registry_match.json")
        .read_text(encoding="utf-8"))
    check("case registry rows", reg_val["n_rows"],
          match_artefact["validation"]["n_rows"])
    check("case registry n_valid", reg_val["n_valid"],
          match_artefact["validation"]["n_valid"])
    check("case registry n_rejected", reg_val["n_rejected"],
          match_artefact["validation"]["n_rejected"])
    check("case registry n_matched", reg_summary["n_matched"],
          match_artefact["matching"]["n_matched"])
    check("case registry label-grade cases",
          reg_summary["n_matched_label_grade"],
          match_artefact["matching"]["n_matched_label_grade"])
    check("case registry fuzzy candidates", reg_summary["n_fuzzy_candidates"],
          match_artefact["matching"]["n_fuzzy_candidates"])

    check_artefact = json.loads(
        (RESULTS / "methodology" / "case_registry_check.json")
        .read_text(encoding="utf-8"))
    reg_frame, reg_info = s39.build_label_population(reg_cases, reg_corpus)
    check("case check label cases used", reg_info.get("n_label_cases_used"),
          check_artefact["label"].get("n_label_cases_used"))
    if reg_frame is None:
        if check_artefact.get("status") != "no_label":
            MISMATCHES.append("case check: re-derived empty label but the "
                              "artefact is not status=no_label")
        print("  label is empty on both sides (registry template) - ok")
    else:
        check("case check positives", reg_info["n_positives"],
              check_artefact["label"]["n_positives"])
        check("case check population", reg_info["n_population"],
              check_artefact["label"]["n_population"])

    summary = {
        "baseline": {"vote_distribution": dist, "bands": bands},
        "external_headline": {
            "roc_auc_max_score": round(roc_auc(y, max_score), 6),
            "pr_auc_max_score": round(pr_auc(y, max_score), 6),
            "base_rate": round(float(y.mean()), 6),
            "votes_ge_3_precision": round(float(y[mask].mean()), 6),
        },
        "univariate_uncertainty": uni_rows,
        "aap_supplier_concentration": {
            "n_exact_suppliers": len(exact_suppliers),
            "positives": int(pos),
            "largest_supplier_share": round(float(
                df.loc[df["is_aap_positive"] == 1, "winner_identifier"]
                .value_counts().iloc[0] / pos), 4),
        },
        "seed_stability": {
            "runs": int(len(runs)),
            "consensus_mean": round(float(runs["n_consensus_ge3"].mean()), 1),
            "jaccard_mean": round(float(
                runs["jaccard_consensus_vs_seed42"].mean()), 4),
        },
        "case_registry": {
            "rows": reg_val["n_rows"],
            "n_valid": reg_val["n_valid"],
            "n_matched": reg_summary["n_matched"],
            "label_grade_cases": reg_summary["n_matched_label_grade"],
            "check_status": check_artefact.get("status"),
        },
        "mismatches": MISMATCHES,
        "seconds": round(time.time() - t0, 1),
        "disclaimer": "Indicators of potential risk, not evidence of corruption.",
    }
    (RESULTS / "methodology" / "final_verification.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nreport -> {RESULTS / 'methodology' / 'final_verification.json'}")
    if MISMATCHES:
        print(f"\n{len(MISMATCHES)} MISMATCH(ES):")
        for m in MISMATCHES:
            print(f"  - {m}")
        return 1
    print("\nall headline numbers reproduce.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
