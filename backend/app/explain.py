"""Deterministic, layered explanation for one scored procedure.

The layers mirror the requirement to keep five things apart:

1. observed procurement facts (what the record actually says),
2. triggered risk indicators (explicit rules from the ETL),
3. statistical anomaly contributions (per-detector verdicts + percentiles),
4. supporting references (artefacts and reports, with availability flags),
5. limitations and uncertainty (including the known SHAP/LIME disagreement).

Everything here is a pure function of the served row and precomputed
population statistics: the same inputs always yield the same explanation, so
it is auditable. No value is ever invented - missing data is reported as
missing (``None`` / ``available: false``), never imputed. Nothing in this
module may claim causality: an explanation says *why the model scored a
record unusually*, not why anything happened.
"""

from __future__ import annotations

from .config import ROOT
from .store import percentile

#: Row score field per detector key (MODEL_KEYS order as in scripts/06).
DETECTOR_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("statistical_mad_zscore", "MAD robust z-score", "rule_score"),
    ("isolation_forest", "Isolation Forest", "iso_score"),
    ("local_outlier_factor", "Local Outlier Factor", "lof_score"),
    ("one_class_svm", "One-Class SVM", "svm_score"),
)

#: Observed facts shown on the detail view: (row key, English label).
#: Only keys present with a non-null value are emitted - absent fields are
#: reported in the limitations layer instead of being defaulted.
FACT_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "Procedure title"),
    ("procedure", "Procedure type"),
    ("status", "Status"),
    ("cpv_code", "CPV code"),
    ("published_at", "Published"),
    ("tender_start", "Tender start"),
    ("bid_deadline", "Bid deadline"),
    ("award_date", "Award decision"),
    ("estimated_value_mdl", "Estimated value (MDL)"),
    ("award_value_mdl", "Award value (MDL)"),
    ("award_total_mdl", "Award total over lots (MDL)"),
    ("n_bidders", "Distinct bidders"),
    ("bid_window_days", "Bidding window (days)"),
    ("n_lots", "Lots"),
    ("n_awards", "Awards"),
    ("buyer_name", "Contracting authority"),
    ("buyer_locality", "Buyer locality"),
    ("winner_name", "Supplier"),
    ("winner_idno", "Supplier IDNO"),
    ("tender_id", "MTender tender ID"),
    ("ocid", "OCID"),
)

DISCLAIMER = (
    "Anomaly score = indicator of potential risk, not evidence of corruption or "
    "violation. Verification by a competent authority is required."
)


def _reference(path: str, label: str, is_api: bool = False) -> dict:
    """Reference with an explicit availability flag (never a fabricated cite)."""
    available = True if is_api else (ROOT / path).exists()
    return {"label": label, "path": path, "available": available}


def build_explanation(
    row: dict,
    stats: dict,
    *,
    xai_verdict: str | None = None,
    scoring_run_id: str | None = None,
    scoring_generated_at: str | None = None,
) -> dict:
    """Layered explanation payload for ``GET /api/tenders/{id}/explanation``.

    ``stats`` comes from ``store.load_population_stats()``; the function has
    no I/O of its own so tests can feed fixtures directly.
    """
    sorted_cols: dict[str, list[float]] = stats.get("sorted") or {}
    flag_rates: dict[str, dict] = stats.get("flag_rates") or {}

    # --- layer 1: observed facts -----------------------------------------
    facts = []
    for key, label in FACT_FIELDS:
        if key not in row or row[key] is None or row[key] == "":
            continue
        item = {"field": key, "label": label, "value": row[key]}
        if key in sorted_cols:
            pct = percentile(sorted_cols[key], row.get(key))
            if pct is not None:
                item["percentile"] = pct
        facts.append(item)

    # --- layer 2: triggered risk indicators ------------------------------
    # ``row["flags"]`` carries the human labels of triggered FLAG_FEATURES
    # (see adapter.project_tender), so membership is tested by label, not by
    # the raw field name.
    triggered_labels = set(row.get("flags") or [])
    indicator_items = []
    for key, rate in flag_rates.items():
        label = rate.get("label") or key
        triggered = label in triggered_labels
        indicator_items.append(
            {
                "key": key,
                "label": label,
                "triggered": triggered,
                "corpus_rate": rate.get("rate"),
                "corpus_n": rate.get("n"),
            }
        )
    # triggered first, then stable key order - deterministic rendering
    indicator_items.sort(key=lambda i: (not i["triggered"], i["key"]))

    # --- layer 3: statistical contributions ------------------------------
    detectors = []
    for key, label, field in DETECTOR_FIELDS:
        verdict_raw = (row.get("model_flags") or {}).get(key)
        if verdict_raw is None:
            verdict = "unscored"
        else:
            verdict = "flagged" if verdict_raw else "not_flagged"
        score = row.get(field)
        detectors.append(
            {
                "key": key,
                "label": label,
                "verdict": verdict,
                "score": score,
                "score_percentile": percentile(sorted_cols.get(field) or [], score),
            }
        )

    # --- layer 4: references ---------------------------------------------
    references = [
        _reference(
            "/api/explainability",
            "Global explainability (permutation importance, SHAP, SHAP vs LIME)",
            is_api=True,
        ),
        _reference(
            "results/tables/permutation_importance.csv",
            "Permutation importance (all 22 features)",
        ),
        _reference(
            "results/tables/shap_feature_importance.csv",
            "SHAP feature importance (Isolation Forest only)",
        ),
        _reference(
            "results/methodology/xai_consistency.json",
            "SHAP vs LIME consistency measurement",
        ),
        _reference(
            "reports/audit_2026-10/NOISE_SENSITIVITY_REPORT.md",
            "Input-noise sensitivity of score ranks",
        ),
        _reference("docs/model_card.md", "Model card (MTA-0004)"),
    ]

    # --- layer 5: limitations --------------------------------------------
    limitations = [
        DISCLAIMER,
        "Explanations are model-internal reasons for an unusual score; they are "
        "not causal proof of any wrongdoing.",
        "SHAP and LIME disagree on this model"
        + (f' (measured verdict: "{xai_verdict}")' if xai_verdict else "")
        + "; treat single attributions with caution.",
        "Per-row attributions exist only for the Isolation Forest; LOF, "
        "One-Class SVM and MAD have verdicts but no per-row attribution.",
        "Score ranks below the top-200 are noise-sensitive (input-noise audit); "
        "review lists of cases, not exact positions.",
        "Fields MTender does not publish are shown as unavailable, never imputed.",
    ]
    if row.get("risk_score") is None:
        limitations.insert(
            1,
            "This record was never scored by the detection run - it is not "
            "examined, and 'unscored' is not a clearance.",
        )

    missing_facts = [
        f"{label} (field '{key}' absent)"
        for key, label in FACT_FIELDS
        if key not in row or row[key] is None or row[key] == ""
    ]
    if missing_facts:
        limitations.append(
            "Not present in this record: " + "; ".join(missing_facts[:8])
            + ("; ..." if len(missing_facts) > 8 else "")
        )

    return {
        "tender_id": row.get("tender_id"),
        "ocid": row.get("ocid"),
        "model_version": "v0",
        "scoring_run_id": scoring_run_id,
        "scoring_generated_at": scoring_generated_at,
        "consensus": {
            "band": row.get("risk_level"),
            "risk_score": row.get("risk_score"),
            "n_models_flagging": row.get("n_models_flagging"),
        },
        "layers": [
            {"id": "facts", "items": facts},
            {"id": "indicators", "items": indicator_items},
            {"id": "detectors", "items": detectors},
            {"id": "references", "items": references},
            {"id": "limitations", "items": [{"text": t} for t in limitations]},
        ],
        "disclaimer": DISCLAIMER,
    }
