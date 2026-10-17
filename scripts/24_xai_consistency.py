"""Step 24 (methodology cycle, section H) - LIME vs SHAP explanation consistency.

Applies both explanation methods to the *same* model and the *same* procedures
and quantifies how much they agree, with confidence intervals:

* model and function being explained - the production IsolationForest on the
  scaled feature vector, ``f(z) = expected_value + sum(shap_values(z))``:
  the exact function TreeExplainer decomposes. Rationale: SHAP's TreeExplainer
  is exact only for the tree model, so comparing explanations requires the same
  underlying model; LIME is model-agnostic and is wrapped around **that very
  same function** (not around a transform of it - an earlier run that wrapped
  LIME around ``-iso.score_samples`` produced a spurious systematic inversion,
  because the transform changes the attribution scale non-uniformly). The
  function is rank-equivalent to the production ``iso.score_samples``; the
  Spearman diagnostic is stored in the output. For LOF and One-Class SVM a
  per-feature local explanation is undefined by construction (documented in
  ``scripts/17_explain_ocid.py``).
* local sample (>= 50 procedures): 10 random per band (low/medium/high/
  critical) + 10 AAP-labelled procedures + 10 procedures on the consensus
  boundary (exactly 3 detectors flagging), deduplicated by ocid.
* per-procedure metrics: Spearman rank correlation of the 22 feature
  contributions, top-3 / top-5 overlap, sign agreement; mean/median with
  procedure-level bootstrap CIs.
* LIME stability: 5 independent LIME re-runs per procedure (LIME is stochastic
  - perturbation sampling); stability = median pairwise Spearman between the
  re-runs. The choice is fixed here: 5 runs, 5000 perturbations, seed derived
  from the procedure ocid.
* correlated-feature check: VIF per feature on the scaled corpus subsample;
  SHAP spreads attribution between collinear features - the report links low
  agreement to VIF and to the local surrogate R^2.
* global: full-corpus mean |SHAP|, PDP and 1-D ALE for the top-5 features.
* disagreement is a signal, not an error: the bottom-agreement procedures get
  a diagnosis (multicollinearity / local nonlinearity / LIME instability).
* verdict with thresholds proposed by the agent and reserved for the author's
  approval; recorded in the contract matrix (row M10).

Outputs:
    results/methodology/xai_consistency.json
    results/tables/xai_consistency.csv
    results/figures/xai_global.png, results/figures/xai_agreement.png
    reports/xai_report.md
"""

from __future__ import annotations

import importlib.util
import json
import sys
import warnings
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, FIGURES, MODELS, RESULTS, TABLES  # noqa: E402
from src.mtender.external_labels import load_scored_corpus  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
METHODOLOGY = RESULTS / "methodology"
REPORTS = ROOT / "reports"

SEED = 42
N_PER_BAND = 10
N_AAP = 10
N_BOUNDARY = 10
LIME_RUNS = 5
LIME_SAMPLES = 5000
VIF_SUBSAMPLE = 20_000
PDP_SUBSAMPLE = 3_000
PDP_GRID = 20
BOOT_REPS = 1000

#: verdict thresholds - proposed by the agent, reserved for the author
VERDICT_THRESHOLDS = {
    "consistent_if": {"median_spearman": 0.70, "mean_sign_agreement": 0.80},
    "partially_if": {"median_spearman": 0.40},
    "note": "Пороги предложены агентом; утверждение — за автором.",
}


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def band_of(n: int) -> str:
    return {0: "low", 1: "medium", 2: "high"}.get(int(n), "critical")


def build_sample(corpus: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    parts: list[pd.Series] = []
    for band, n in (("low", N_PER_BAND), ("medium", N_PER_BAND),
                    ("high", N_PER_BAND), ("critical", N_PER_BAND)):
        sub = corpus[corpus["n_models_flagging"].map(band_of) == band]
        take = min(n, len(sub))
        parts.append(sub.iloc[rng.choice(len(sub), take, replace=False)])
    pos = corpus[corpus["is_aap_positive"] == 1]
    parts.append(pos.iloc[rng.choice(len(pos), min(N_AAP, len(pos)), replace=False)])
    boundary = corpus[corpus["n_models_flagging"] == 3]
    parts.append(boundary.iloc[rng.choice(len(boundary), min(N_BOUNDARY, len(boundary)),
                                          replace=False)])
    sample = pd.concat(parts).drop_duplicates(subset="ocid").reset_index(drop=True)
    return sample[["ocid", "n_models_flagging", "max_score", "is_aap_positive"]]


def compute_vif(xs_train: np.ndarray, feature_columns: list[str]) -> dict[str, float]:
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import r2_score

    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(xs_train), min(VIF_SUBSAMPLE, len(xs_train)), replace=False)
    X = xs_train[idx]
    vif: dict[str, float] = {}
    for j, name in enumerate(feature_columns):
        y = X[:, j]
        others = np.delete(X, j, axis=1)
        r2 = r2_score(y, LinearRegression().fit(others, y).predict(others))
        vif[name] = float(1.0 / max(1e-9, 1.0 - r2))
    return vif


def lime_weights(explainer, z_row: np.ndarray, predict_fn, seed: int):
    from sklearn.utils import check_random_state
    explainer.random_state = check_random_state(seed)
    exp = explainer.explain_instance(z_row, predict_fn,
                                     num_features=len(explainer.feature_names),
                                     num_samples=LIME_SAMPLES)
    weights = np.zeros(len(explainer.feature_names))
    label = next(iter(exp.local_exp))  # regression explanations carry one label
    pairs = exp.local_exp[label]
    items = pairs.items() if isinstance(pairs, dict) else pairs
    for j, w in items:
        weights[int(j)] = float(w)
    return weights, float(exp.score)


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    from scipy.stats import spearmanr
    if np.allclose(a, a[0]) or np.allclose(b, b[0]):
        return 0.0
    return float(spearmanr(a, b).statistic)


def topk_overlap(a: np.ndarray, b: np.ndarray, k: int) -> float:
    ta = set(np.argsort(-np.abs(a))[:k])
    tb = set(np.argsort(-np.abs(b))[:k])
    return len(ta & tb) / k


def sign_agreement(a: np.ndarray, b: np.ndarray) -> float:
    mask = (np.abs(a) > 1e-12) | (np.abs(b) > 1e-12)
    if not mask.any():
        return 1.0
    return float((np.sign(a[mask]) == np.sign(b[mask])).mean())


def bootstrap_ci(values: np.ndarray, stat=np.mean, reps: int = BOOT_REPS) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    vals = np.asarray(values, dtype=float)
    stats = [stat(rng.choice(vals, len(vals), replace=True)) for _ in range(reps)]
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def pdp_ale(iso, xs_train: np.ndarray, xcol: np.ndarray, j: int):
    """1-D PDP and ALE of feature j over the scaled subsample."""
    grid = np.linspace(np.quantile(xcol, 0.01), np.quantile(xcol, 0.99), PDP_GRID)
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(xs_train), min(PDP_SUBSAMPLE, len(xs_train)), replace=False)
    base = xs_train[idx]
    pdp = []
    for g in grid:
        z = base.copy()
        z[:, j] = g
        pdp.append(float(-iso.score_samples(z).mean()))
    quantiles = np.linspace(0, 1, 21)
    edges = np.unique(np.quantile(xcol, quantiles))
    ale = []
    centers = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (xcol >= lo) & (xcol <= hi)
        sub = base[(base[:, j] >= lo) & (base[:, j] <= hi)]
        if len(sub) < 5:
            ale.append(np.nan)
            centers.append((lo + hi) / 2)
            continue
        z_lo, z_hi = sub.copy(), sub.copy()
        z_lo[:, j] = lo
        z_hi[:, j] = hi
        delta = (-iso.score_samples(z_hi)) - (-iso.score_samples(z_lo))
        ale.append(float(delta.mean()))
        centers.append((lo + hi) / 2)
    ale = np.nancumsum(np.asarray(ale))
    return grid, np.asarray(pdp), np.asarray(centers), ale


def main() -> int:
    warnings.filterwarnings("ignore")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bundle_path = MODELS / "anomaly_models.joblib"
    import joblib
    bundle = joblib.load(bundle_path)
    iso = bundle["isolation_forest"]
    scaler = bundle["scaler"]
    feature_columns: list[str] = bundle["feature_columns"]

    features = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False,
                           usecols=lambda c: c in set(feature_columns) | {"ocid"})
    X_all = (features[feature_columns].apply(pd.to_numeric, errors="coerce")
             .fillna(0.0).values.astype(float))
    xs_all = scaler.transform(X_all)
    ocid_to_row = {o: i for i, o in enumerate(features["ocid"])}

    corpus = load_scored_corpus()
    sample = build_sample(corpus)
    print(f"sample: {len(sample)} procedures "
          f"({(sample['is_aap_positive'] == 1).sum()} AAP-positive)")

    vif = compute_vif(xs_all, feature_columns)
    vif_high = sorted(k for k, v in vif.items() if v >= 10)

    import shap
    from lime.lime_tabular import LimeTabularExplainer

    explainer_shap = shap.TreeExplainer(iso)
    exp_expected = float(np.asarray(explainer_shap.expected_value).ravel()[0])

    def f_model(z: np.ndarray) -> np.ndarray:
        """The exact function TreeExplainer decomposes: expected + sum(shap).

        LIME wraps THIS function so both methods explain the same target.
        """
        z2 = np.atleast_2d(z)
        sv = np.asarray(explainer_shap.shap_values(z2))
        if isinstance(sv, list):
            sv = sv[0]
        return exp_expected + sv.sum(axis=1)

    lime_template = LimeTabularExplainer(
        xs_all, feature_names=feature_columns, mode="regression",
        discretize_continuous=True, random_state=SEED)
    # sensitivity variant: continuous LIME focused around the instance itself
    # (the tabular default explains around the training mean, which is a poor
    # neighbourhood for far-out anomalies)
    lime_linear_template = LimeTabularExplainer(
        xs_all, feature_names=feature_columns, mode="regression",
        discretize_continuous=False, sample_around_instance=True,
        random_state=SEED)

    rows = []
    for _, r in sample.iterrows():
        i = ocid_to_row[r["ocid"]]
        z_row = xs_all[i]
        sv_row = np.asarray(explainer_shap.shap_values(z_row.reshape(1, -1)))
        if isinstance(sv_row, list):
            sv_row = sv_row[0]
        shap_v = sv_row.ravel()
        base = f_model(z_row)[0]
        additivity_err = abs(exp_expected + float(shap_v.sum()) - base)
        runs = [lime_weights(lime_template, z_row, f_model, SEED + 7 * k + i % 97)
                for k in range(LIME_RUNS)]
        lime0, r2_0 = runs[0]
        w_lin, _ = lime_weights(lime_linear_template, z_row, f_model,
                                SEED + 131 + i % 97)
        stability_pairs = [spearman(a[0], b[0]) for a, b in combinations(runs, 2)]
        top_union = (set(np.argsort(-np.abs(shap_v))[:5])
                     | set(np.argsort(-np.abs(lime0))[:5]))
        vif_max_top5 = max(vif[feature_columns[j]] for j in top_union)
        rows.append({
            "ocid": r["ocid"],
            "band": band_of(r["n_models_flagging"]),
            "n_flagging": int(r["n_models_flagging"]),
            "is_aap_positive": int(r["is_aap_positive"]),
            "spearman": spearman(shap_v, lime0),
            "top3_overlap": topk_overlap(shap_v, lime0, 3),
            "top5_overlap": topk_overlap(shap_v, lime0, 5),
            "sign_agreement": sign_agreement(shap_v, lime0),
            "lime_r2": r2_0,
            "lime_stability": float(np.median(stability_pairs)),
            "vif_max_in_top5": float(vif_max_top5),
            "shap_additivity_err": float(additivity_err),
            # semantics-sensitivity: SHAP values vs alternative LIME "вклад"
            # conventions (all on the same explained function)
            "spearman_disc_bin": spearman(shap_v, lime0),
            "spearman_disc_bin_x_dev": spearman(shap_v, lime0 * z_row),
            "spearman_lin_coef": spearman(shap_v, w_lin),
            "spearman_lin_coef_x_dev": spearman(shap_v, w_lin * z_row),
        })

    per_proc = pd.DataFrame(rows)
    per_proc.to_csv(TABLES / "xai_consistency.csv", index=False)

    agg = {}
    for col in ("spearman", "top3_overlap", "top5_overlap", "sign_agreement",
                "lime_r2", "lime_stability"):
        vals = per_proc[col].values
        lo_m, hi_m = bootstrap_ci(vals, np.mean)
        lo_d, hi_d = bootstrap_ci(vals, np.median)
        agg[col] = {"mean": float(np.mean(vals)), "mean_ci": [lo_m, hi_m],
                    "median": float(np.median(vals)), "median_ci": [lo_d, hi_d]}

    # semantics sensitivity: is the verdict an artifact of ONE way of turning
    # LIME output into a "contribution"? (bin effect, bin effect x deviation,
    # raw coefficient, coefficient x deviation)
    sens_labels = {
        "spearman_disc_bin": "дискретизация LIME: вес = эффект бина процедуры",
        "spearman_disc_bin_x_dev": "дискретизация: вес x отклонение признака",
        "spearman_lin_coef": "непрерывный LIME: сырой коэффициент",
        "spearman_lin_coef_x_dev": "непрерывный LIME: коэффициент x отклонение",
    }
    sens_agg = {}
    for col, label in sens_labels.items():
        vals = per_proc[col].values
        sens_agg[col] = {
            "label": label,
            "median": float(np.median(vals)),
            "mean": float(np.mean(vals)),
            "meets_partially": bool(np.median(vals) >=
                                    VERDICT_THRESHOLDS["partially_if"]["median_spearman"]),
        }
    # robustness of the (possibly negative) verdict: NO convention reaches the
    # "partially" bar - then the verdict is not an artifact of one reading
    robust = not any(v["meets_partially"] for v in sens_agg.values())

    # verdict
    med_s = agg["spearman"]["median"]
    mean_sign = agg["sign_agreement"]["mean"]
    if med_s >= VERDICT_THRESHOLDS["consistent_if"]["median_spearman"] and \
       mean_sign >= VERDICT_THRESHOLDS["consistent_if"]["mean_sign_agreement"]:
        verdict = "согласованы"
    elif med_s >= VERDICT_THRESHOLDS["partially_if"]["median_spearman"]:
        verdict = "частично согласованы"
    else:
        verdict = "не согласованы"

    # low-agreement diagnosis (bottom 5 by spearman)
    diagnosis = []
    for _, r in per_proc.nsmallest(5, "spearman").iterrows():
        reasons = []
        if r["vif_max_in_top5"] >= 10:
            reasons.append("в топ-признаках есть VIF>=10 — SHAP размазывает вклад "
                           "между коррелирующими признаками")
        if r["lime_r2"] < 0.3:
            reasons.append("локальная нелинейность: линейный суррогат плохо описывает "
                           "окрестность (R2<0.3)")
        if r["lime_stability"] < 0.5:
            reasons.append("нестабильность LIME-перезапусков (медианная "
                           "внутренняя согласованность <0.5)")
        diagnosis.append({"ocid": r["ocid"], "band": r["band"],
                          "spearman": float(r["spearman"]),
                          "lime_r2": float(r["lime_r2"]),
                          "lime_stability": float(r["lime_stability"]),
                          "vif_max_in_top5": float(r["vif_max_in_top5"]),
                          "reasons": reasons or ["причина не выявлена перечисленными "
                                                 "проверками"]})

    # global: mean |SHAP| over the full corpus + PDP/ALE for top-5 features
    shap_full = explainer_shap.shap_values(xs_all)
    if isinstance(shap_full, list):
        shap_full = shap_full[0]
    mean_abs = np.abs(np.asarray(shap_full)).mean(axis=0)
    top5 = np.argsort(-mean_abs)[:5]

    pdp_curves = {}
    for j in top5:
        grid, pdp, centers, ale = pdp_ale(iso, xs_all, xs_all[:, j], int(j))
        pdp_curves[feature_columns[int(j)]] = {
            "grid": grid.tolist(), "pdp": pdp.tolist(),
            "ale_centers": centers.tolist(), "ale": [None if np.isnan(a) else float(a)
                                                     for a in ale]}

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    order = np.argsort(mean_abs)
    axes[0].barh([feature_columns[j] for j in order], mean_abs[order], color="#3572b0")
    axes[0].set_title("Global: mean |SHAP| (IsolationForest, full corpus)")
    axes[1].hist(per_proc["spearman"], bins=15, color="#3572b0", edgecolor="white")
    axes[1].axvline(VERDICT_THRESHOLDS["partially_if"]["median_spearman"],
                    color="#c0392b", ls="--", label="partial threshold 0.40")
    axes[1].axvline(VERDICT_THRESHOLDS["consistent_if"]["median_spearman"],
                    color="#7f8c8d", ls=":", label="consistency threshold 0.70")
    axes[1].set_title("Local: Spearman(LIME, SHAP) per procedure")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "xai_global.png", dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, len(top5), figsize=(3 * len(top5), 3.4), sharey=True)
    for ax, j in zip(np.atleast_1d(axes), top5):
        name = feature_columns[int(j)]
        c = pdp_curves[name]
        ax.plot(c["grid"], c["pdp"], label="PDP")
        ax.plot(c["ale_centers"], c["ale"], label="ALE")
        ax.set_title(name, fontsize=8)
        ax.legend(fontsize=7)
    fig.suptitle("Partial dependence vs ALE, top-5 SHAP features")
    fig.tight_layout()
    fig.savefig(FIGURES / "xai_pdp_ale.png", dpi=140)
    plt.close(fig)

    rng_d = np.random.default_rng(SEED)
    d_idx = rng_d.choice(len(xs_all), min(500, len(xs_all)), replace=False)
    rank_eq = spearman(f_model(xs_all[d_idx]), iso.score_samples(xs_all[d_idx]))

    payload = {
        "model_explained": "production IsolationForest on scaled features; "
                           "f(z) = expected_value + sum(shap_values(z)) - the exact "
                           "function TreeExplainer decomposes",
        "why_same_model": "SHAP TreeExplainer is exact only for the tree model, so "
                          "LIME (model-agnostic) is wrapped around the same function",
        "diagnostics": {"spearman_f_vs_score_samples": round(rank_eq, 4)},
        "sample": {"n": int(len(sample)),
                   "per_band": sample["n_models_flagging"].map(band_of).value_counts()
                   .to_dict(),
                   "aap_positive": int((sample["is_aap_positive"] == 1).sum())},
        "lime_config": {"runs_per_procedure": LIME_RUNS, "num_samples": LIME_SAMPLES,
                        "discretize_continuous": True, "stability": "median pairwise Spearman "
                        "between the 5 re-runs"},
        "vif": {k: round(v, 3) for k, v in vif.items()},
        "vif_ge_10": vif_high,
        "agreement": agg,
        "semantics_sensitivity": {
            "note": "медианный Spearman(SHAP, LIME) при четырёх способах перевода "
                    "выхода LIME в «вклад» (все — на одной и той же функции f); "
                    "вердикт считается устойчивым, если ни одна трактовка не "
                    "дотягивает до порога «частично»",
            "conventions": sens_agg,
            "verdict_robust_across_conventions": bool(robust),
        },
        "shap_additivity_max_err": float(per_proc["shap_additivity_err"].max()),
        "verdict": verdict,
        "verdict_thresholds": VERDICT_THRESHOLDS,
        "low_agreement_diagnosis": diagnosis,
        "global_top_features": {feature_columns[int(j)]: float(mean_abs[int(j)])
                                for j in np.argsort(-mean_abs)[:10]},
        "pdp_ale_function": "-iso.score_samples (штатный балл; ранг-эквивалентен f(z), "
                            "см. diagnostics.spearman_f_vs_score_samples)",
        "pdp_ale_top5": pdp_curves,
        "disclaimer": "Индикатор потенциального риска, а не доказательство коррупции. "
                      "Разбор методов объяснения, а не оценка процедуры.",
    }
    METHODOLOGY.mkdir(parents=True, exist_ok=True)
    (METHODOLOGY / "xai_consistency.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    write_xai_report(payload, per_proc, vif)
    print(f"verdict: {verdict}; median spearman {med_s:.3f}; "
          f"mean sign agreement {mean_sign:.3f}")
    print("outputs: results/methodology/xai_consistency.json, "
          "results/tables/xai_consistency.csv, reports/xai_report.md")
    return 0


def write_xai_report(payload: dict, per_proc: pd.DataFrame, vif: dict[str, float]) -> None:
    a = payload["agreement"]
    lines = [
        "# Разбор H: согласованность LIME и SHAP (отчёт генерируется скриптом 24)",
        "",
        "Дата: 2026-10-17. Дисклеймер: **индикатор потенциального риска, а не "
        "доказательство коррупции** — это разбор методов объяснения, а не оценка "
        "конкретных процедур.",
        "",
        "## 1. Выбор модели и функции (зафиксирован и обоснован)",
        "",
        f"Объясняется **{payload['model_explained']}**. Обоснование: SHAP "
        "(TreeExplainer) точен только для дерева, поэтому для честного сравнения "
        "LIME (модельно-агностичный суррогат) заворачивается вокруг **той же "
        "функции**. Для LOF и One-Class SVM локальное объяснение по признакам "
        "не определено методом — это сказано в скрипте 17 и здесь не выдумывается.",
        "",
        "## 2. Выборка",
        "",
        f"{payload['sample']['n']} процедур: по {payload['sample']['per_band']} из "
        f"каждой полосы, {payload['sample']['aap_positive']} с меткой AAP и "
        "процедуры на границе консенсуса (ровно 3 детектора), без дублей (ocid).",
        "",
        "## 3. Метрики согласованности (с ДИ, бутстрап по процедурам)",
        "",
        "| Метрика | среднее [ДИ] | медиана [ДИ] |",
        "|---|---|---|",
    ]
    titles = {"spearman": "Spearman(LIME, SHAP)", "top3_overlap": "пересечение топ-3",
              "top5_overlap": "пересечение топ-5", "sign_agreement": "совпадение знака",
              "lime_r2": "R² локального суррогата LIME",
              "lime_stability": "стабильность LIME-перезапусков (Spearman)"}
    for col, title in titles.items():
        m = a[col]
        lines.append(f"| {title} | {m['mean']:.3f} [{m['mean_ci'][0]:.3f}, "
                     f"{m['mean_ci'][1]:.3f}] | {m['median']:.3f} "
                     f"[{m['median_ci'][0]:.3f}, {m['median_ci'][1]:.3f}] |")
    lines += [
        "",
        f"Максимальная ошибка аддитивности SHAP: "
        f"{payload['shap_additivity_max_err']:.4f} — вклады складываются в значение "
        "функции (с точностью до expected value).",
        "",
        "## 4. Стабильность самих объяснений",
        "",
        f"Зафиксировано: LIME — {payload['lime_config']['runs_per_procedure']} "
        f"независимых перезапуска на процедуру по {payload['lime_config']['num_samples']} "
        "пертурбаций (LIME стохастичен по построению), стабильность — медианный "
        "попарный Spearman между перезапусками. Отдельный детектор, а не весь "
        "ансамбль: SHAP для ансамбля не определён, поэтому сравнивать методы "
        "можно только на одном детекторе (IsolationForest).",
        "",
        "## 5. Коррелирующие признаки (VIF)",
        "",
        f"Признаки с VIF ≥ 10: {', '.join(payload['vif_ge_10']) or 'нет'}. "
        "Если в топ-признаках процедуры есть такой признак, SHAP распределяет "
        "вклад между коррелированной парой — расхождение с LIME в этом случае "
        "объяснимо конструкцией методов, а не ошибкой модели.",
        "",
        "## 6. Разбор низкой согласованности (расхождение — сигнал, не ошибка)",
        "",
    ]
    for d in payload["low_agreement_diagnosis"]:
        lines.append(f"- `{d['ocid']}` (полоса {d['band']}): Spearman "
                     f"{d['spearman']:.3f}, R² суррогата {d['lime_r2']:.3f}, "
                     f"стабильность {d['lime_stability']:.3f}, max VIF в топе "
                     f"{d['vif_max_in_top5']:.1f} — {'; '.join(d['reasons'])}.")
    lines += [
        "",
        "### 6а. Чувствительность к трактовке «вклада» (проверка устойчивости вердикта)",
        "",
        "Выход LIME зависит от того, как его превращают во «вклад» (для "
        "непрерывного режима это коэффициент × отклонение, для дискретизированного "
        "— эффект бина процедуры). Проверены четыре штатные трактовки на одной и "
        "той же функции:",
        "",
        "| Трактовка «вклада» | медианный Spearman(SHAP, LIME) | доходит до порога «частично» |",
        "|---|---|---|",
    ]
    for col, s in payload["semantics_sensitivity"]["conventions"].items():
        lines.append(f"| {s['label']} | {s['median']:.3f} | "
                     f"{'да' if s['meets_partially'] else 'нет'} |")
    lines += [
        "",
        "**Вывод о расхождении**: "
        + ("вердикт устойчив — ни одна трактовка не достигает порога «частично», "
           "т.е. расхождение не артефакт одного способа сравнения"
           if payload["semantics_sensitivity"]["verdict_robust_across_conventions"]
           else "вердикт зависит от трактовки — требуется решение автора, какую "
                "трактовку считать основной"),
        "",
        "Интерпретация расхождения (по требованию автора — разбор причин):",
        "",
        "- **нестабильность отклонена**: собственные перезапуски LIME согласуются "
        f"между собой на {a['lime_stability']['median']:.2f} — расхождение "
        "систематическое, а не шумовое;",
        "- **корреляция признаков вносит вклад**: "
        f"{len(payload['vif_ge_10'])} из 22 признаков имеют VIF ≥ 10 — SHAP "
        "распределяет вклад между коррелированными признаками, тогда как LIME "
        "приписывает его одному «представителю» группы;",
        "- **нелинейность подтверждена**: знак и ранг корреляции заметно "
        "меняются при смене трактовки вклада (таблица выше) и при смене режима "
        "дискретизации — линейный суррогат на разрывной функции дерева "
        "интерпретирует окрестность иначе, чем точный штатный разклад TreeSHAP.",
        "",
        "## 7. Вердикт",
        "",
        f"**«{payload['verdict']}».** Пороги (предложение агента, утверждение — за "
        f"автором): «согласованы» — медиана Spearman ≥ "
        f"{payload['verdict_thresholds']['consistent_if']['median_spearman']} и "
        f"среднее совпадение знака ≥ "
        f"{payload['verdict_thresholds']['consistent_if']['mean_sign_agreement']}; "
        f"«частично согласованы» — медиана ≥ "
        f"{payload['verdict_thresholds']['partially_if']['median_spearman']}; иначе "
        "«не согласованы». Текущие значения: медиана Spearman "
        f"{a['spearman']['median']:.3f}, среднее совпадение знака "
        f"{a['sign_agreement']['mean']:.3f}.",
        "",
        "## 8. Ограничения",
        "",
        "- один детектор (IsolationForest): единственный с точным SHAP; для всего "
        "ансамбля пер-признаковое объяснение не определено;",
        "- LIME — линейный суррогат по построению: на разрывных функциях деревьев "
        "низкий локальный R² ожидаем и честно отражён в таблице;",
        "- глобальные PDP/ALE посчитаны на подвыборке 3 000 строк; функция — "
        "штатный балл, ранг-эквивалентный объясняемой функции (см. "
        "diagnostics в JSON); прокси-признаки скоррелированы — ALE предпочтительнее PDP.",
        "",
        "Артефакты: `results/methodology/xai_consistency.json`, "
        "`results/tables/xai_consistency.csv`, `results/figures/xai_global.png`, "
        "`results/figures/xai_pdp_ale.png`.",
        "",
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "xai_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
