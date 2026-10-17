"""Step 16 (methodology cycle, step 3) - feature contribution, circularity, ablation.

Produces the required table ``feature -> contribution -> verdict`` and, more
importantly, *tests* the two circularity suspicions instead of asserting them:

C1. ANOVA significance against the consensus flag.
    The flag is built from these same features, so a large F proves that the
    detectors used the feature, not that the feature means anything. Two
    controls are run: (a) columns that are **not** fed to the detectors
    (``n_lots``, ``n_items``, ``n_contracts``) are put through the identical
    test - if they also come out "significant at 0.01", the test measures
    correlation with the construction; (b) a seeded Gaussian noise column is
    *added* to the detector inputs and the whole consensus is rebuilt - a
    placebo that has no procurement meaning whatsoever.

C2. Permutation importance scored against the model's own predictions
    (``scripts/07`` uses ``iso.predict`` as the target). This is self-agreement
    by construction. The same permutations are re-scored against the *external*
    AAP label, and the two rankings are compared.

Ablation: each feature group and each behavioural feature is removed, the four
detectors are re-fitted (seed 42, same parameters as ``scripts/06``), and the
effect is measured three ways - consensus size, Jaccard against the production
consensus, and the external metrics from step 2.

Feature removal is an irreversible change to the production model, so this
script **does not remove anything**: it writes the ablation evidence and the
verdict table, and the decision stays a recommendation (rule 6 of the brief).

Usage:
    .venv/bin/python scripts/16_feature_ablation.py
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, FIGURES, RESULTS, TABLES  # noqa: E402
from src.mtender.eval_metrics import jaccard, precision_at_k, pr_auc, roc_auc  # noqa: E402
from src.mtender.external_labels import build_label_table  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS  # noqa: E402

SEED = 42
OUTLIER_RATE = 0.05
FIT_CAP = 20000

FEATURE_GROUPS = {
    "financial": [
        "log_award_value", "log_award_total", "value_vs_cpv_median",
        "value_zscore_cpv", "estimate_to_award_ratio", "multi_award_tender",
    ],
    "competition": [
        "n_bidders_log", "single_bidder", "no_bid_data", "multi_supplier_award",
    ],
    "procedural": [
        "bid_window_days", "short_deadline", "long_deadline", "n_amendments",
        "amended", "accelerated_like", "cancelled", "no_award_after_tender",
    ],
    "behavioural": [
        "buyer_supplier_repeat_share", "winner_share_of_buyer_awards",
        "supplier_win_concentration", "supplier_award_count_log",
    ],
}

#: Columns deliberately NOT given to the detectors: the C1(a) control group.
UNUSED_COLUMNS = ["n_lots", "n_items", "n_contracts"]


def _load_stage06():
    path = Path(__file__).resolve().parents[1] / "scripts" / "06_detect_anomalies.py"
    spec = importlib.util.spec_from_file_location("stage06_detect", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def fit_sample(n_rows: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(n_rows, size=FIT_CAP, replace=False))


def fit_variant(df: pd.DataFrame, cols: list[str], stage06, noise: np.ndarray | None = None):
    """Run all four detectors on exactly ``cols`` (plus an optional noise column).

    Returns ``{"votes", "consensus", "max_score", "n_*"}`` - the same objects
    scripts/06 derives, so the ablation measures the production rule and not a
    re-implementation of it.
    """
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import OneClassSVM

    X = df[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    if noise is not None:
        X = X.copy()
        X["__placebo_noise__"] = noise
    Xs = StandardScaler().fit_transform(X.values)

    mad = stage06.statistical_baseline(X, list(X.columns))
    mad_flag = mad["is_anomaly"].to_numpy().astype(int)

    iso = IsolationForest(n_estimators=300, contamination=OUTLIER_RATE,
                          random_state=SEED, n_jobs=4)
    iso.fit(Xs)
    iso_flag = (iso.predict(Xs) == -1).astype(int)

    rows = fit_sample(len(Xs), SEED)
    lof = LocalOutlierFactor(n_neighbors=20, contamination=OUTLIER_RATE, novelty=True)
    lof.fit(Xs[rows])
    lof_flag = (lof.predict(Xs) == -1).astype(int)

    svm = OneClassSVM(kernel="rbf", nu=OUTLIER_RATE, gamma="scale")
    svm.fit(Xs[rows])
    svm_flag = (svm.predict(Xs) == -1).astype(int)

    det_scores = pd.DataFrame({
        "mad": mad["score"].to_numpy(),
        "if": -iso.score_samples(Xs),
        "lof": -lof.score_samples(Xs),
        "svm": -svm.decision_function(Xs),
    })
    max_score = det_scores.rank(pct=True).max(axis=1).to_numpy()
    votes = mad_flag + iso_flag + lof_flag + svm_flag
    return {
        "votes": votes,
        "consensus": (votes >= 3).astype(np.uint8),
        "max_score": max_score,
        "iso": iso,
        "scaler_cols": list(X.columns),
        "Xs": Xs,
        "n_mad": int(mad_flag.sum()),
        "n_if": int(iso_flag.sum()),
        "n_lof": int(lof_flag.sum()),
        "n_svm": int(svm_flag.sum()),
    }


def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-permutation", action="store_true",
                    help="skip the 22 x rescoring permutation experiment (saves ~2 min)")
    args = ap.parse_args()

    t_start = time.time()
    stage06 = _load_stage06()

    df = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    labels, label_summary = build_label_table()
    # production scores are exported sorted by n_models_flagging, features.csv is
    # sorted by ocid: the join MUST be on ocid, never positional (see
    # src/mtender/external_labels.load_scored_corpus for why).
    prod = pd.read_csv(
        TABLES / "tender_anomaly_scores.csv",
        usecols=["ocid", "n_models_flagging", "consensus", "max_score"],
        low_memory=False,
    )
    df = df.merge(labels[["ocid", "is_aap_positive"]], on="ocid", how="left")
    df = df.merge(prod, on="ocid", how="left", validate="one_to_one")
    if df["n_models_flagging"].isna().any():
        raise SystemExit("scored rows lost during the ocid join")

    y = df["is_aap_positive"].fillna(0).astype(int).to_numpy()

    baseline_votes = df["n_models_flagging"].fillna(0).astype(int).to_numpy()
    baseline_consensus = df["consensus"].fillna(0).astype(int).to_numpy().astype(bool)
    baseline_max = df["max_score"].to_numpy()
    # self-check: the stored consensus column must equal votes >= 3 in this row order
    assert np.array_equal(baseline_consensus, baseline_votes >= 3), "row alignment broken"

    def ext_metrics(max_score: np.ndarray, votes: np.ndarray) -> dict:
        mask = votes >= 3
        return {
            "roc_auc_external": round(roc_auc(y, max_score), 6),
            "pr_auc_external": round(pr_auc(y, max_score), 6),
            "precision_at_1000_external": round(precision_at_k(y, max_score, 1000), 6),
            "consensus_precision_external": (
                round(float(y[mask].mean()), 6) if mask.any() else None
            ),
            "n_consensus": int(mask.sum()),
        }

    base_ext = ext_metrics(baseline_max, baseline_votes)
    print(f"baseline: consensus {base_ext['n_consensus']:,}, "
          f"external AUC {base_ext['roc_auc_external']}", flush=True)

    # ------------------------------------------------------------------
    # C1(a): the ANOVA test applied to columns the detectors never saw
    # ------------------------------------------------------------------
    from sklearn.feature_selection import f_classif

    control_rows = []
    for col in UNUSED_COLUMNS:
        if col not in df.columns:
            continue
        values = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        f_val, p_val = f_classif(values.to_numpy().reshape(-1, 1), baseline_consensus)
        control_rows.append({
            "column": col,
            "fed_to_detectors": False,
            "f_statistic": float(np.nan_to_num(f_val, nan=0.0)[0]),
            "p_value": float(np.nan_to_num(p_val, nan=1.0)[0]),
            "significant_at_0.01": bool(np.nan_to_num(p_val, nan=1.0)[0] < 0.01),
        })

    used_anova = pd.read_csv(TABLES / "feature_significance.csv")
    # 'significant_at_0.01' is not a valid identifier, so rename before itertuples
    # (otherwise pandas substitutes positional names and the attribute lookup lies).
    used_anova.columns = ["feature", "f_statistic", "p_value", "significant_at_0_01"]
    used_rows = [
        {"column": r.feature, "fed_to_detectors": True,
         "f_statistic": r.f_statistic, "p_value": r.p_value,
         "significant_at_0.01": bool(r.significant_at_0_01)}
        for r in used_anova.itertuples()
    ]
    c1a = pd.DataFrame(used_rows + control_rows)
    c1a.to_csv(TABLES / "circularity_anova_controls.csv", index=False)

    # ------------------------------------------------------------------
    # C1(b): placebo column fed into the detectors, consensus rebuilt
    # ------------------------------------------------------------------
    print("placebo refit (noise column fed to all four detectors)...", flush=True)
    rng = np.random.default_rng(20261017)
    noise = rng.standard_normal(len(df))
    placebo = fit_variant(df, cols, stage06, noise=noise)
    f_noise, p_noise = f_classif(
        noise.reshape(-1, 1).astype(float), placebo["consensus"].astype(int)
    )
    placebo_result = {
        "placebo_column": "standard normal N(0,1), seed 20261017",
        "fed_to_detectors": True,
        "meaning": "no procurement meaning whatsoever",
        "f_statistic": float(np.nan_to_num(f_noise, nan=0.0)[0]),
        "p_value": float(np.nan_to_num(p_noise, nan=1.0)[0]),
        "significant_at_0.01": bool(np.nan_to_num(p_noise, nan=1.0)[0] < 0.01),
        "consensus_size_with_placebo": int(placebo["consensus"].sum()),
        "jaccard_consensus_vs_production": round(
            jaccard(placebo["consensus"].astype(bool), baseline_consensus), 6),
        "external_auc_with_placebo": round(roc_auc(y, placebo["max_score"]), 6),
    }

    # ------------------------------------------------------------------
    # C2: permutation importance - self-agreement vs external label
    # ------------------------------------------------------------------
    perm_rows = []
    if not args.skip_permutation:
        print("permutation experiment (22 features x IF rescoring)...", flush=True)
        iso_fit = fit_variant(df, cols, stage06)  # seed-42 IF on the production columns
        iso = iso_fit["iso"]
        Xs = iso_fit["Xs"]
        base_score = -iso.score_samples(Xs)
        base_flag = (iso.predict(Xs) == -1).astype(int)
        base_self_auc = roc_auc(base_flag, base_score)
        base_ext_auc = roc_auc(y, base_score)
        perm_rng = np.random.default_rng(SEED)
        for i, col in enumerate(cols):
            Xp = Xs.copy()
            Xp[:, i] = perm_rng.permutation(Xp[:, i])
            sc = -iso.score_samples(Xp)
            flag_perm = (iso.predict(Xp) == -1).astype(int)
            perm_rows.append({
                "feature": col,
                "perm_drop_auc_vs_own_predictions": round(base_self_auc - roc_auc(base_flag, sc), 6),
                "perm_drop_auc_vs_external_label": round(base_ext_auc - roc_auc(y, sc), 6),
                "self_auc_baseline": round(base_self_auc, 6),
                "external_auc_baseline": round(base_ext_auc, 6),
            })
        pd.DataFrame(perm_rows).to_csv(TABLES / "permutation_external.csv", index=False)

    # ------------------------------------------------------------------
    # ablation: drop groups / key features, re-fit, measure
    # ------------------------------------------------------------------
    ablation_specs: list[tuple[str, list[str]]] = []
    for group, members in FEATURE_GROUPS.items():
        ablation_specs.append((f"drop_group:{group}", [c for c in cols if c not in members]))
    for single in ("buyer_supplier_repeat_share", "winner_share_of_buyer_awards",
                   "supplier_win_concentration", "supplier_award_count_log",
                   "n_amendments", "bid_window_days"):
        if single in cols:
            ablation_specs.append((f"drop_feature:{single}", [c for c in cols if c != single]))
    ablation_specs.append((
        "drop_both_share_columns",
        [c for c in cols if c not in ("winner_share_of_buyer_awards",
                                      "buyer_supplier_repeat_share")],
    ))

    ablation_rows = [{
        "variant": "baseline_production",
        "n_features": len(cols),
        "n_consensus": base_ext["n_consensus"],
        "jaccard_consensus_vs_baseline": 1.0,
        "roc_auc_external": base_ext["roc_auc_external"],
        "pr_auc_external": base_ext["pr_auc_external"],
        "precision_at_1000_external": base_ext["precision_at_1000_external"],
        "consensus_precision_external": base_ext["consensus_precision_external"],
        "delta_roc_auc_external": 0.0,
        "delta_n_consensus": 0,
        "seconds": 0.0,
    }]

    for name, variant_cols in ablation_specs:
        t0 = time.time()
        print(f"ablation {name} ({len(variant_cols)} features)...", flush=True)
        res = fit_variant(df, variant_cols, stage06)
        ext = ext_metrics(res["max_score"], res["votes"])
        ablation_rows.append({
            "variant": name,
            "n_features": len(variant_cols),
            "n_consensus": ext["n_consensus"],
            "jaccard_consensus_vs_baseline": round(
                jaccard(res["consensus"].astype(bool), baseline_consensus), 6),
            "roc_auc_external": ext["roc_auc_external"],
            "pr_auc_external": ext["pr_auc_external"],
            "precision_at_1000_external": ext["precision_at_1000_external"],
            "consensus_precision_external": ext["consensus_precision_external"],
            "delta_roc_auc_external": round(
                ext["roc_auc_external"] - base_ext["roc_auc_external"], 6),
            "delta_n_consensus": ext["n_consensus"] - base_ext["n_consensus"],
            "seconds": round(time.time() - t0, 1),
        })
        pd.DataFrame(ablation_rows).to_csv(TABLES / "feature_ablation.csv", index=False)

    ablation = pd.DataFrame(ablation_rows)

    # ------------------------------------------------------------------
    # contribution table + verdicts
    # ------------------------------------------------------------------
    shap_imp = pd.read_csv(TABLES / "shap_feature_importance.csv")
    shap_col = [c for c in shap_imp.columns if c != "feature"][0]
    shap_map = dict(zip(shap_imp["feature"], shap_imp[shap_col]))

    perm_self = pd.read_csv(TABLES / "permutation_importance.csv")
    perm_self_map = dict(zip(perm_self["feature"], perm_self["perm_importance_mean"]))

    perm_ext = (pd.DataFrame(perm_rows) if perm_rows else pd.DataFrame())
    perm_ext_map = (dict(zip(perm_ext["feature"], perm_ext["perm_drop_auc_vs_external_label"]))
                    if len(perm_ext) else {})

    dup_share = df["winner_share_of_buyer_awards"].astype(float)
    dup_repeat = df["buyer_supplier_repeat_share"].astype(float)
    dup_equal_frac = float((np.isclose(dup_share, dup_repeat, equal_nan=True)).mean())
    dup_corr = float(dup_share.corr(dup_repeat))

    group_of = {f: g for g, members in FEATURE_GROUPS.items() for f in members}

    rows = []
    for col in cols:
        values = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        f_used, p_used = f_classif(values.to_numpy().reshape(-1, 1), baseline_consensus.astype(int))
        auc_ext = roc_auc(y, values.to_numpy())
        # direction-free discrimination: 0.5 = no signal
        disc_ext = round(abs(auc_ext - 0.5) * 2, 6)
        grp = group_of.get(col, "other")
        grp_variant = f"drop_group:{grp}"
        grp_row = ablation[ablation["variant"] == grp_variant]
        rows.append({
            "feature": col,
            "group": grp,
            "anova_f_vs_consensus_circular": round(float(np.nan_to_num(f_used, nan=0.0)[0]), 3),
            "anova_p_vs_consensus_circular": float(np.nan_to_num(p_used, nan=1.0)[0]),
            "shap_mean_abs": round(float(shap_map.get(col, np.nan)), 6)
            if shap_map.get(col) is not None else None,
            "permutation_vs_self_circular": round(float(perm_self_map.get(col, np.nan)), 6)
            if col in perm_self_map else None,
            "permutation_vs_external": round(float(perm_ext_map[col]), 6)
            if col in perm_ext_map else None,
            "univariate_auc_external": round(auc_ext, 6),
            "univariate_discrimination_external": disc_ext,
            "group_ablation_delta_auc_external": float(grp_row["delta_roc_auc_external"].iloc[0])
            if len(grp_row) else None,
            "group_ablation_jaccard": float(grp_row["jaccard_consensus_vs_baseline"].iloc[0])
            if len(grp_row) else None,
        })
    contrib = pd.DataFrame(rows)

    # verdicts: rule-based, documented, and never applied to production code
    def verdict_for(r) -> tuple[str, str]:
        if r.feature == "winner_share_of_buyer_awards":
            return ("объединить", "дубликат buyer_supplier_repeat_share: "
                    f"идентичны в {dup_equal_frac:.1%} строк (corr={dup_corr:.4f}), "
                    "пара даёт один и тот же вклад дважды")
        if r.feature == "buyer_supplier_repeat_share":
            return ("оставить (одна копия пары)", "самый сильный разделитель "
                    "запрещённых поставщиков вовне корпуса; вторая копия подлежит объединению")
        if r.univariate_discrimination_external >= 0.08:
            return ("оставить", "непустой внешний сигнал (|AUC-0.5|*2 >= 0.08)")
        if (r.group_ablation_jaccard is not None and r.group_ablation_jaccard >= 0.98
                and (r.permutation_vs_external is None
                     or abs(r.permutation_vs_external) < 0.005)):
            return ("под вопросом", "удаление группы почти не меняет консенсус "
                    "(Jaccard >= 0.98) и не влияет на внешние метрики")
        if (r.permutation_vs_self_circular is not None
                and r.permutation_vs_self_circular > 0.01
                and r.univariate_discrimination_external < 0.04):
            return ("под вопросом", "важен только для собственных предсказаний модели "
                    "(круговая логика), во внешней выборке сигнала нет")
        return ("оставить", "участвует в построении консенсуса, "
                "внешний сигнал неотличим от нуля - оснований удалять нет")

    verdicts = contrib.apply(lambda r: verdict_for(r), axis=1)
    contrib["verdict"] = [v[0] for v in verdicts]
    contrib["verdict_reason"] = [v[1] for v in verdicts]
    contrib = contrib.sort_values(
        ["univariate_discrimination_external"], ascending=False)
    contrib.to_csv(TABLES / "feature_contribution.csv", index=False)

    # ------------------------------------------------------------------
    # correlation between the two "importance" rankings: C2 summary
    # ------------------------------------------------------------------
    rank_contrast = {}
    if len(perm_ext):
        both = contrib.dropna(subset=["permutation_vs_self_circular",
                                      "permutation_vs_external"])
        if len(both) > 3:
            rank_contrast = {
                "spearman_self_vs_external_permutation": round(float(
                    both["permutation_vs_self_circular"].corr(
                        both["permutation_vs_external"], method="spearman")), 4),
                "top5_by_self": list(both.nlargest(5, "permutation_vs_self_circular")["feature"]),
                "top5_by_external": list(both.nlargest(5, "permutation_vs_external")["feature"]),
            }

    anova_vs_external = contrib.copy()
    rank_corr = float(
        anova_vs_external["anova_f_vs_consensus_circular"].rank()
        .corr(anova_vs_external["univariate_discrimination_external"].rank(),
              method="spearman")
    )

    summary = {
        "n_features": len(cols),
        "feature_groups": {g: m for g, m in FEATURE_GROUPS.items()},
        "duplicate_check": {
            "columns": ["buyer_supplier_repeat_share", "winner_share_of_buyer_awards"],
            "identical_fraction": round(dup_equal_frac, 6),
            "pearson_corr": round(dup_corr, 6),
            "finding": ("the two columns are the same ratio under two names; both enter "
                        "the detectors and both appear in the ANOVA table with identical F"
                        if dup_equal_frac > 0.999 else "columns differ"),
        },
        "circularity_c1_anova": {
            "controls_not_fed_to_detectors": control_rows,
            "share_used_columns_significant_at_0_01": float(
                c1a[c1a["fed_to_detectors"]]["significant_at_0.01"].mean()),
            "share_unused_columns_significant_at_0_01": float(
                c1a[~c1a["fed_to_detectors"]]["significant_at_0.01"].mean())
            if (~c1a["fed_to_detectors"]).any() else None,
            "placebo": placebo_result,
            "spearman_rank_f_vs_external_discrimination": round(rank_corr, 4),
            "verdict": (
                "ANOVA against the consensus flag is a construction check (does the "
                "detectors' output reflect this feature?) and must not be reported as "
                "evidence that the feature marks anything anomalous outside the model."
            ),
        },
        "circularity_c2_permutation": {
            **rank_contrast,
            "script07_target": "iso.predict (the model's own verdict)",
            "verdict": (
                "permutation importance against the model's own predictions is "
                "self-agreement; the external-label version is the only one that speaks "
                "to validity, and its uncertainty is large (633 positives)."
            ),
        },
        "ablation": {
            "variants": ablation_rows,
            "note": (
                "No feature was removed from the production model. These are candidate "
                "changes with their measured effect, for the author to approve (rule 6)."
            ),
        },
        "external_label": {
            "positive_procedures": int(y.sum()),
            "note": label_summary["limitation"],
        },
        "seconds_total": round(time.time() - t_start, 1),
        "disclaimer": "Indicators of potential risk, not evidence of corruption.",
    }
    out_dir = RESULTS / "methodology"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "feature_verdicts.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\nANOVA controls (columns NOT fed to the detectors):")
    print(c1a[~c1a["fed_to_detectors"]].to_string(index=False))
    print("\nplacebo:")
    print(json.dumps(placebo_result, indent=2, ensure_ascii=False))
    print("\nablation:")
    print(ablation.to_string(index=False))
    print("\ncontribution / verdicts:")
    print(contrib[["feature", "group", "anova_f_vs_consensus_circular",
                   "univariate_auc_external", "permutation_vs_self_circular",
                   "permutation_vs_external", "verdict"]].to_string(index=False))
    print(f"\ntable  -> {TABLES / 'feature_contribution.csv'}")
    print(f"table  -> {TABLES / 'feature_ablation.csv'}")
    print(f"table  -> {TABLES / 'circularity_anova_controls.csv'}")
    print(f"report -> {out_dir / 'feature_verdicts.json'}")
    _plot(contrib, ablation)
    return 0


def _plot(contrib: pd.DataFrame, ablation: pd.DataFrame) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")
        return
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.4))

    ax = axes[0]
    ax.scatter(contrib["anova_f_vs_consensus_circular"].clip(lower=1),
               contrib["univariate_discrimination_external"], s=18, alpha=0.7)
    for r in contrib.nlargest(6, "anova_f_vs_consensus_circular").itertuples():
        ax.annotate(r.feature, (max(r.anova_f_vs_consensus_circular, 1),
                                r.univariate_discrimination_external), fontsize=6)
    ax.set_xscale("log")
    ax.set_xlabel("ANOVA F vs consensus flag (circular by construction)")
    ax.set_ylabel("univariate discrimination vs AAP label |AUC-0.5|*2")
    ax.set_title("Two answers to 'is this feature important?'")

    ax = axes[1]
    if "permutation_vs_external" in contrib.columns and contrib["permutation_vs_external"].notna().any():
        sub = contrib.dropna(subset=["permutation_vs_self_circular", "permutation_vs_external"])
        ax.scatter(sub["permutation_vs_self_circular"], sub["permutation_vs_external"], s=18)
        for r in sub.nlargest(4, "permutation_vs_self_circular").itertuples():
            ax.annotate(r.feature, (r.permutation_vs_self_circular,
                                    r.permutation_vs_external), fontsize=6)
        ax.set_xlabel("permutation drop, target = model's own predictions")
        ax.set_ylabel("permutation drop, target = external AAP label")
    ax.set_title("Self-agreement vs external effect")

    ax = axes[2]
    sub = ablation[ablation["variant"] != "baseline_production"].sort_values(
        "delta_roc_auc_external")
    colors = ["tab:red" if abs(v) > 0.01 else "tab:blue" for v in sub["delta_roc_auc_external"]]
    ax.barh(sub["variant"], sub["delta_roc_auc_external"], color=colors)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("delta external ROC-AUC vs baseline")
    ax.set_title("Ablation effect on the external metric")

    fig.suptitle("Feature contribution and circularity controls - indicator of potential "
                 "risk, not evidence of corruption", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "feature_verdicts.png", dpi=140)
    print(f"figure -> {FIGURES / 'feature_verdicts.png'}")


if __name__ == "__main__":
    raise SystemExit(main())
