"""Step 07 - explainability for the tabular anomaly models.

Uses permutation importance and univariate ANOVA significance rather than
SHAP: the models here are tree/one-class models on 19 tabular features, and
exact SHAP values for LOF / One-Class SVM are undefined, so a TreeExplainer on
the Isolation Forest is used for the attribution layer.

Grad-CAM is deliberately not applied. It is defined for convolutional networks
on images; on tabular procurement data it has no meaningful analogue, which is
discussed in the thesis rather than faked.

Usage:
    .venv/bin/python scripts/07_explainability.py
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, FIGURES, MODELS, RESULTS, TABLES  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS, UNAVAILABLE  # noqa: E402
from src.mtender.mongo_client import utcnow_iso  # noqa: E402

#: Sampling for the explanation step is seeded so the reported importances are
#: reproducible across runs.
RANDOM_STATE = 42


def main() -> int:
    warnings.filterwarnings("ignore")
    path = DATA_FEATURES / "features.csv"
    scores_path = TABLES / "tender_anomaly_scores.csv"
    if not path.exists() or not scores_path.exists():
        print("ERROR: run 04_export_snapshot.py and 06_detect_anomalies.py first")
        return 1

    df = pd.read_csv(path, low_memory=False)
    scores = pd.read_csv(scores_path, low_memory=False)
    cols = [c for c in FEATURE_COLUMNS if c in df.columns]

    merged = df.merge(scores[["ocid", "consensus", "n_models_flagging", "max_score"]], on="ocid", how="inner")
    print(f"merged {len(merged):,} tenders with scores")

    merged.to_csv(TABLES / "features_with_scores.csv", index=False)

    # -- distribution of each indicator: anomalous vs typical ---------------
    rows = []
    for col in cols:
        a = pd.to_numeric(merged.loc[merged["consensus"] == 1, col], errors="coerce").dropna()
        n = pd.to_numeric(merged.loc[merged["consensus"] == 0, col], errors="coerce").dropna()
        rows.append(
            {
                "feature": col,
                "mean_flagged": round(float(a.mean()), 6) if len(a) else None,
                "mean_normal": round(float(n.mean()), 6) if len(n) else None,
                "median_flagged": round(float(a.median()), 6) if len(a) else None,
                "median_normal": round(float(n.median()), 6) if len(n) else None,
                "n_flagged": int(len(a)),
                "n_normal": int(len(n)),
            }
        )
    dist = pd.DataFrame(rows)
    dist["separation"] = (dist["mean_flagged"] - dist["mean_normal"]).abs()
    dist = dist.sort_values("separation", ascending=False)
    dist.to_csv(TABLES / "feature_profiles_by_flag.csv", index=False)
    print("\nstrongest separators (flagged vs normal):")
    print(dist.head(12).to_string(index=False))

    # -- red-flag co-occurrence among the top flagged procurements ----------
    top = merged[merged["n_models_flagging"] >= 2]
    print(f"\nflagged by >=2 models: {len(top):,} "
          f"({len(top)/max(len(merged),1):.2%} of the dataset)")
    flags = [
        "single_bidder", "no_bid_data", "short_deadline", "amended",
        "cancelled", "no_award_after_tender", "multi_supplier_award",
        "accelerated_like", "long_deadline",
    ]
    flags = [f for f in flags if f in merged.columns]
    cooc = pd.DataFrame(
        {
            "flag": flags,
            "n_flagged_tenders": [int(top[f].sum()) for f in flags],
            "pct_of_flagged": [round(float(top[f].mean()) * 100, 2) if len(top) else 0.0 for f in flags],
            "pct_of_all": [round(float(merged[f].mean()) * 100, 2) for f in flags],
        }
    ).sort_values("pct_of_flagged", ascending=False)
    cooc.to_csv(TABLES / "red_flag_prevalence.csv", index=False)
    print("\nred-flag prevalence:")
    print(cooc.to_string(index=False))

    # -- SHAP on the Isolation Forest, if the model file exists -------------
    shap_status = "not computed"
    shap_table = None
    model_file = MODELS / "anomaly_models.joblib"
    if model_file.exists():
        try:
            import joblib

            bundle = joblib.load(model_file)
            iso = bundle["isolation_forest"]
            try:
                import shap

                explainer = shap.TreeExplainer(iso)
                # A seeded random sample, not .head(): the snapshot is sorted by
                # ocid and an MTender ocid embeds its publication timestamp, so
                # the first rows are the oldest procurements in the history and
                # would explain the model using 2018 alone.
                sample = merged.sample(n=min(2000, len(merged)), random_state=RANDOM_STATE)
                values = explainer.shap_values(sample[cols].values)
                if isinstance(values, list):
                    values = values[0]
                shap_table = (
                    pd.DataFrame({"feature": cols, "mean_abs_shap": np.abs(values).mean(axis=0)})
                    .sort_values("mean_abs_shap", ascending=False)
                )
                shap_table.to_csv(TABLES / "shap_feature_importance.csv", index=False)
                shap_status = f"computed on {len(sample)} rows, shap {shap.__version__}"
                print("\nSHAP mean |value| (Isolation Forest):")
                print(shap_table.head(12).to_string(index=False))
            except ImportError:
                shap_status = "shap not installed - permutation importance used instead"
        except Exception as exc:  # noqa: BLE001
            shap_status = f"failed: {exc}"

    # -- permutation importance (model-agnostic fallback) -------------------
    perm_rows = []
    if model_file.exists():
        import joblib
        from sklearn.inspection import permutation_importance

        bundle = joblib.load(model_file)
        iso = bundle["isolation_forest"]
        sample = merged.sample(n=min(5000, len(merged)), random_state=RANDOM_STATE)
        r = permutation_importance(
            iso, sample[cols].values, iso.predict(sample[cols].values), n_repeats=10,
            random_state=42, scoring="roc_auc", n_jobs=-1,
        )
        perm = pd.DataFrame(
            {"feature": cols, "perm_importance_mean": r.importances_mean, "perm_importance_std": r.importances_std}
        ).sort_values("perm_importance_mean", ascending=False)
        perm.to_csv(TABLES / "permutation_importance.csv", index=False)
        perm_rows = perm.head(12).to_dict("records")

    # -- figures ------------------------------------------------------------
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        top_n = min(8, len(dist))
        fig, axes = plt.subplots(2, 4, figsize=(18, 8))
        for ax, (_, row) in zip(axes.flat, dist.head(top_n).iterrows()):
            col = row["feature"]
            vals = pd.to_numeric(merged[col], errors="coerce").dropna()
            if vals.empty:
                ax.set_visible(False)
                continue
            upper = vals.quantile(0.99)
            bins = np.linspace(min(vals.min(), 0), max(upper, 1e-9), 40)
            ax.hist(vals.clip(upper=max(upper, 1e-9)), bins=bins, alpha=0.55, label="normal")
            flagged = pd.to_numeric(
                merged.loc[merged["consensus"] == 1, col], errors="coerce"
            ).dropna().clip(upper=max(upper, 1e-9))
            ax.hist(flagged, bins=bins, alpha=0.65, label="flagged")
            ax.set_title(col, fontsize=9)
            ax.tick_params(labelsize=7)
        axes.flat[0].legend(fontsize=7)
        for ax in list(axes.flat)[top_n:]:
            ax.set_visible(False)
        fig.suptitle("Corruption-risk indicators: flagged vs normal procurements", fontsize=12)
        fig.tight_layout()
        fig.savefig(FIGURES / "feature_profiles.png", dpi=140)
        print(f"\nfigure -> {FIGURES/'feature_profiles.png'}")
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")

    summary = {
        "stage": "explainability",
        "generated_at": utcnow_iso(),
        "n_merged_rows": len(merged),
        "n_flagged_by_2plus_models": int(len(top)),
        "shap_status": shap_status,
        "grad_cam": "not applicable: ConvGradCAM requires a convolutional image model; "
                    "the tabular models here have no spatial feature map, so it is "
                    "discussed as a limitation rather than faked",
        "unavailable_indicators": UNAVAILABLE,
        "strongest_separators": dist.head(10).to_dict("records"),
        "permutation_importance_top": perm_rows,
    }
    (RESULTS / "mongo" / "explainability_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nsummary -> {RESULTS/'mongo'/'explainability_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
