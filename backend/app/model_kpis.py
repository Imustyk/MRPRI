"""KPI catalogue and live verification for the four anomaly detectors.

Why this module exists
----------------------
The methodology page states *how* the detectors were built; this module states
what each detector is held to (the catalogue) and whether the scores currently
being served still satisfy it (the checks). Both are produced from one place so
the catalogue cannot drift away from the data: every number in the ``live``
block is recomputed from the served corpus when the report is built, never
copied from the detection run.

What is deliberately absent: precision / recall / F1
-----------------------------------------------------
Real MTender procurements carry no ground-truth anomaly labels (labels exist
only for the synthetic dataset, see ``adapter.UNAVAILABLE``), so those metrics
are not computable on this corpus. They are reported as ``available: false``
with the reason instead of being imported from an evaluation that ran on other
data. The checks therefore verify things that *are* observable here: verdict
presence, threshold reproduction, count consistency, and artefact paths.

The contamination band
----------------------
``scripts/06_detect_anomalies.py`` declares ``contamination = 0.05`` for
Isolation Forest, LOF and One-Class SVM - an assumption stated in advance, not
a finding. The observed share on the served corpus is accepted within a 3
percentage-point tolerance around it (``CONTAMINATION_TOLERANCE``): the two
neighbourhood models are fitted on a bounded 20k sample, so their share on the
full corpus sits next to the declared value rather than exactly on it. A wider
gap means the served scores no longer match the declared run.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .config import RESULTS, ROOT

#: Contamination declared by ``scripts/06_detect_anomalies.py`` for the three
#: fitted detectors. Stated before the run, so it is a KPI and not a result.
DECLARED_CONTAMINATION = 0.05

#: The 3% band the observed flagged share may deviate from the declared
#: contamination by, in share units (0.03 = 3 percentage points).
CONTAMINATION_TOLERANCE = 0.03

#: The MAD baseline flags ``score > z_threshold`` (scripts/06).
Z_THRESHOLD = 5.0

#: Consensus means flagged by at least this many of the four detectors.
CONSENSUS_MIN = 3

#: Detection-run summary written by scripts/06; the source of the recorded
#: values the live recomputation is compared against.
RUN_SUMMARY_PATH = RESULTS / "mongo" / "detection_summary.json"

#: Allowed difference between a live flagged share and the one recorded in the
#: run summary, in percentage points. Both are rounded to 3 decimals there.
RUN_REPRO_TOLERANCE_PP = 0.1

Pass = "pass"
Fail = "fail"
Skip = "skip"

#: The four detectors of this project, in the order scripts/06 fits them.
#: ``row_score_field`` is where the raw score lands in ``project_tender`` output
#: (``adapter``), which is what the live checks read.
DETECTORS: list[dict[str, Any]] = [
    {
        "key": "statistical_mad_zscore",
        "label": "MAD z-score baseline",
        "family": "robust univariate statistics",
        "score_field": "score_statistical_mad_zscore",
        "flag_field": "flag_statistical_mad_zscore",
        "row_score_field": "rule_score",
        "threshold": {"kind": "rule", "name": "z_threshold", "value": Z_THRESHOLD},
        "params": {
            "z_threshold": Z_THRESHOLD,
            "excluded": "binary red flags and spike-like bounded ratios (reported separately)",
        },
        # A rule has no fitted state to point at.
        "artifact": {
            "path": None,
            "members": [],
            "note": "stateless rule: no fitted artefact exists to path-check",
        },
    },
    {
        "key": "isolation_forest",
        "label": "Isolation Forest",
        "family": "tree ensemble",
        "score_field": "score_isolation_forest",
        "flag_field": "flag_isolation_forest",
        "row_score_field": "iso_score",
        "threshold": {
            "kind": "contamination",
            "name": "contamination",
            "value": DECLARED_CONTAMINATION,
        },
        "params": {"n_estimators": 300, "contamination": DECLARED_CONTAMINATION, "random_state": 42},
        "artifact": {
            "path": "results/models/anomaly_models.joblib",
            "members": ["isolation_forest", "scaler", "feature_columns"],
            "note": None,
        },
    },
    {
        "key": "local_outlier_factor",
        "label": "Local Outlier Factor",
        "family": "neighbourhood density",
        "score_field": "score_local_outlier_factor",
        "flag_field": "flag_local_outlier_factor",
        "row_score_field": "lof_score",
        "threshold": {
            "kind": "contamination",
            "name": "contamination",
            "value": DECLARED_CONTAMINATION,
        },
        "params": {
            "n_neighbors": 20,
            "contamination": DECLARED_CONTAMINATION,
            "novelty": True,
            "fitted_on": 20000,
        },
        # scripts/06 persists only the scaler, Isolation Forest and the PCA
        # projection; the neighbourhood models are refitted on every run.
        "artifact": {
            "path": None,
            "members": [],
            "note": "not persisted: refitted on a 20k sample by scripts/06 on every run",
        },
    },
    {
        "key": "one_class_svm",
        "label": "One-Class SVM",
        "family": "kernel density",
        "score_field": "score_one_class_svm",
        "flag_field": "flag_one_class_svm",
        "row_score_field": "svm_score",
        "threshold": {"kind": "contamination", "name": "nu", "value": DECLARED_CONTAMINATION},
        "params": {
            "kernel": "rbf",
            "nu": DECLARED_CONTAMINATION,
            "gamma": "scale",
            "fitted_on": 20000,
        },
        "artifact": {
            "path": None,
            "members": [],
            "note": "not persisted: refitted on a 20k sample by scripts/06 on every run",
        },
    },
]

#: Guard against a catalogue whose keys were reordered: the checks address rows
#: by key, and MODEL_KEYS is the contract the score documents use. Asserted in
#: tests/test_model_kpis.py rather than at import time.


def _load_run_summary() -> dict:
    """Detection-run summary written by scripts/06, or ``{}`` if absent."""
    try:
        if RUN_SUMMARY_PATH.exists() and RUN_SUMMARY_PATH.stat().st_size:
            data = json.loads(RUN_SUMMARY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _artifact_check(detector: dict) -> tuple[str, str]:
    """Does the declared model path resolve to the artefact the KPI names?

    Existence alone is not enough: the bundle is rewritten by every run, so the
    members the detector depends on and the contamination stored inside it are
    compared against the catalogue as well. A path that cannot be read is a
    failure, not a pass - "the file is probably fine" is how a KPI page rots.
    """
    artifact = detector.get("artifact") or {}
    path_text = artifact.get("path")
    if not path_text:
        return Skip, artifact.get("note") or "no persisted artefact for this detector"
    path = ROOT / path_text
    if not path.exists():
        return Fail, f"{path_text} not found; re-run scripts/06_detect_anomalies.py"
    try:
        import joblib
    except Exception as exc:  # pragma: no cover - joblib ships with sklearn
        return Skip, f"joblib unavailable, cannot inspect {path_text} ({exc})"
    try:
        bundle = joblib.load(path)
    except Exception as exc:  # noqa: BLE001 - a corrupt bundle must not 500 the API
        return Fail, f"{path_text} exists but cannot be read: {exc}"
    if not isinstance(bundle, dict):
        return Fail, f"{path_text} is not a model bundle"
    members = artifact.get("members") or []
    missing = [m for m in members if m not in bundle]
    if missing:
        return Fail, f"{path_text} is missing {', '.join(missing)}"
    threshold = detector.get("threshold") or {}
    if threshold.get("kind") == "contamination" and "contamination" in bundle:
        stored = float(bundle["contamination"])
        if not math.isclose(stored, float(threshold["value"]), rel_tol=0.0, abs_tol=1e-9):
            return Fail, (
                f"{path_text} stores contamination={stored} while the catalogue "
                f"declares {threshold['value']}"
            )
    return Pass, f"{path_text} holds {', '.join(members)} and matches the declared parameters"


def _live_counts(rows: list[dict], detectors: list[dict]) -> tuple[dict[str, dict], dict]:
    """One pass over the served rows: per-detector tallies plus global counts.

    A row counts as *scored* when the projection carries either a percentile or
    a model count - i.e. a score document exists for it. Everything below is
    derived from that definition, so "scored and cleared" is always counted
    separately from "never scored".
    """
    keys = [d["key"] for d in detectors]
    live: dict[str, dict] = {
        key: {
            "n_scored": 0,
            "n_flagged": 0,
            "n_flag_missing": 0,
            "n_flagged_without_score": 0,
            "flagged_score_sum": 0.0,
            "flagged_score_n": 0,
            "cleared_score_sum": 0.0,
            "cleared_score_n": 0,
            "n_rule_checked": 0,
            "n_rule_mismatch": 0,
        }
        for key in keys
    }
    score_fields = {d["key"]: d["row_score_field"] for d in detectors}
    rule_thresholds = {
        d["key"]: float(d["threshold"]["value"])
        for d in detectors
        if d.get("threshold", {}).get("kind") == "rule"
    }
    agg = {
        "n_rows": len(rows),
        "n_scored": 0,
        "n_rows_missing_flags": 0,
        "n_count_checked": 0,
        "n_count_mismatch": 0,
        "n_consensus_checked": 0,
        "n_consensus_mismatch": 0,
        "n_risk_checked": 0,
        "n_risk_out_of_bounds": 0,
    }

    for row in rows:
        if row.get("risk_score") is None and row.get("n_models_flagging") is None:
            continue
        agg["n_scored"] += 1

        flags = row.get("model_flags")
        if not isinstance(flags, dict):
            flags = {}
        verdicts = {key: flags.get(key) for key in keys}
        if any(v is None for v in verdicts.values()):
            agg["n_rows_missing_flags"] += 1

        n_models = row.get("n_models_flagging")
        if n_models is not None and all(v is not None for v in verdicts.values()):
            agg["n_count_checked"] += 1
            if int(n_models) != sum(1 for v in verdicts.values() if v):
                agg["n_count_mismatch"] += 1

        consensus = row.get("consensus_flag")
        if consensus is not None and n_models is not None:
            agg["n_consensus_checked"] += 1
            if bool(consensus) != (int(n_models) >= CONSENSUS_MIN):
                agg["n_consensus_mismatch"] += 1

        risk = row.get("risk_score")
        if risk is not None:
            agg["n_risk_checked"] += 1
            if not 0.0 <= float(risk) <= 100.0:
                agg["n_risk_out_of_bounds"] += 1

        for key in keys:
            state = live[key]
            verdict = verdicts[key]
            if verdict is None:
                state["n_flag_missing"] += 1
                continue
            state["n_scored"] += 1

            score = row.get(score_fields[key])
            finite = (
                isinstance(score, (int, float))
                and not isinstance(score, bool)
                and math.isfinite(float(score))
            )
            if verdict:
                state["n_flagged"] += 1
                if finite:
                    state["flagged_score_sum"] += float(score)
                    state["flagged_score_n"] += 1
                else:
                    state["n_flagged_without_score"] += 1
            elif finite:
                state["cleared_score_sum"] += float(score)
                state["cleared_score_n"] += 1

            # A rule-shaped threshold can be re-derived from the score, so the
            # flag and the score must agree on every row where both exist.
            rule_value = rule_thresholds.get(key)
            if rule_value is not None and finite:
                state["n_rule_checked"] += 1
                if bool(verdict) != (float(score) > rule_value):
                    state["n_rule_mismatch"] += 1

    return live, agg


def build_kpi_report(
    rows: list[dict],
    detectors: list[dict] | None = None,
    run_summary: dict | None = None,
) -> dict:
    """Catalogue + checks for the detectors, over the rows actually served.

    ``detectors`` and ``run_summary`` are injectable so the checks can be tested
    against a tiny synthetic corpus and a temporary artefact path instead of
    depending on the live detection run.
    """
    detectors = DETECTORS if detectors is None else detectors
    if run_summary is None:
        run_summary = _load_run_summary()

    live, agg = _live_counts(rows, detectors)
    keys = [d["key"] for d in detectors]
    recorded = {
        m.get("model"): m
        for m in (run_summary.get("models") or [])
        if isinstance(m, dict) and m.get("model")
    }

    checks: list[dict] = []

    def add(cid: str, label: str, status: str, detail: str, detector: str | None = None) -> None:
        checks.append(
            {"id": cid, "label": label, "status": status, "detail": detail, "detector": detector}
        )

    def share(state: dict) -> float | None:
        """Observed flagged share in percent, matching the run summary's units."""
        return state["n_flagged"] / state["n_scored"] * 100.0 if state["n_scored"] else None

    # -- per detector: catalogue entry + live figures ------------------------
    catalogue: list[dict] = []
    for det in detectors:
        key = det["key"]
        state = live[key]
        n = state["n_scored"]
        flagged = state["n_flagged"]
        pct = share(state)
        mean_flagged = (
            state["flagged_score_sum"] / state["flagged_score_n"]
            if state["flagged_score_n"]
            else None
        )
        mean_cleared = (
            state["cleared_score_sum"] / state["cleared_score_n"]
            if state["cleared_score_n"]
            else None
        )
        art_status, art_detail = _artifact_check(det)
        artifact = det.get("artifact") or {}
        rec = recorded.get(key)

        catalogue.append(
            {
                "key": key,
                "label": det["label"],
                "family": det["family"],
                "score_field": det["score_field"],
                "flag_field": det["flag_field"],
                "row_score_field": det["row_score_field"],
                "threshold": det["threshold"],
                "params": det["params"],
                "artifact": {
                    "path": artifact.get("path"),
                    "members": artifact.get("members") or [],
                    "note": artifact.get("note"),
                    "status": art_status,
                    "detail": art_detail,
                },
                "live": {
                    "n_scored": n,
                    "n_flagged": flagged,
                    "pct_flagged": round(pct, 3) if pct is not None else None,
                    "mean_flagged": round(mean_flagged, 6) if mean_flagged is not None else None,
                    "mean_cleared": round(mean_cleared, 6) if mean_cleared is not None else None,
                    "n_flag_missing": state["n_flag_missing"],
                },
                "run_recorded": (
                    {
                        "n_flagged": rec.get("n_flagged"),
                        "pct_flagged": rec.get("pct_flagged"),
                    }
                    if rec
                    else None
                ),
            }
        )

        # 1. verdict present on every scored row
        if agg["n_scored"] == 0:
            status, detail = Skip, "no scored rows are being served"
        elif n == 0:
            status, detail = Fail, (
                f"{agg['n_scored']:,} rows are scored but none carries flag_{key}"
            )
        elif state["n_flag_missing"]:
            status, detail = Fail, (
                f"{state['n_flag_missing']:,} scored rows carry no flag_{key} "
                "(score document exists without this detector's verdict)"
            )
        else:
            status, detail = Pass, f"{n:,} scored rows carry a 0/1 verdict; 0 missing"
        add("flags:" + key, "Verdict stored for every scored row", status, detail, key)

        # 2. the declared threshold reproduces the flag
        threshold = det["threshold"]
        if threshold["kind"] == "contamination":
            if pct is None:
                status, detail = Skip, "no scored rows to measure a share over"
            else:
                observed = pct / 100.0
                gap = observed - float(threshold["value"])
                status = Pass if abs(gap) <= CONTAMINATION_TOLERANCE else Fail
                detail = (
                    f"observed {pct:.3f}% flagged vs declared "
                    f"{float(threshold['value']) * 100:.1f}% "
                    f"({gap * 100:+.3f} pp, tolerance +/-{CONTAMINATION_TOLERANCE * 100:.0f} pp)"
                )
            add(
                "threshold:" + key,
                f"Flagged share inside the contamination band ({threshold['name']})",
                status,
                detail,
                key,
            )
        else:
            checked = state["n_rule_checked"]
            if checked == 0:
                status, detail = Skip, "no rows carry both this flag and its score"
            elif state["n_rule_mismatch"]:
                status, detail = Fail, (
                    f"{state['n_rule_mismatch']:,} of {checked:,} rows disagree with "
                    f"flag == (score > {threshold['value']})"
                )
            else:
                status, detail = Pass, (
                    f"flag == (score > {threshold['value']}) on all {checked:,} rows checked"
                )
            add(
                "threshold:" + key,
                f"Flag reproduces the declared {threshold['name']}",
                status,
                detail,
                key,
            )

        # 3. scores and verdicts tell the same story
        if n == 0:
            status, detail = Skip, "no scored rows"
        elif state["n_flagged_without_score"]:
            status, detail = Fail, (
                f"{state['n_flagged_without_score']:,} flagged rows have no finite "
                f"{det['row_score_field']}"
            )
        elif mean_flagged is None or mean_cleared is None:
            status, detail = Skip, "one side of the comparison (flagged / cleared) is empty"
        elif mean_flagged <= mean_cleared:
            status, detail = Fail, (
                f"flagged mean score {mean_flagged:.4f} is not above the cleared mean "
                f"{mean_cleared:.4f}"
            )
        else:
            status, detail = Pass, (
                f"flagged mean {mean_flagged:.4f} > cleared mean {mean_cleared:.4f} "
                f"over {n:,} scored rows"
            )
        add("score:" + key, "Scores agree with the verdict", status, detail, key)

        # 4. the declared model path resolves
        add(
            "artifact:" + key,
            "Declared model path resolves to the artefact",
            art_status,
            art_detail,
            key,
        )

    # -- corpus-level consistency -------------------------------------------
    if agg["n_rows"] == 0:
        add("coverage", "Corpus carries detector output", Skip, "no rows served")
    elif agg["n_scored"] == 0:
        add(
            "coverage",
            "Corpus carries detector output",
            Fail,
            "0 of "
            f"{agg['n_rows']:,} served rows have a score document; every record "
            "would read as unscored",
        )
    else:
        add(
            "coverage",
            "Corpus carries detector output",
            Pass,
            f"{agg['n_scored']:,} of {agg['n_rows']:,} served rows have detector output",
        )

    if agg["n_count_checked"] == 0:
        add(
            "count_consistency",
            "n_models_flagging equals the number of set verdicts",
            Skip,
            "no row carries all four verdicts and a model count",
        )
    elif agg["n_count_mismatch"]:
        add(
            "count_consistency",
            "n_models_flagging equals the number of set verdicts",
            Fail,
            f"{agg['n_count_mismatch']:,} of {agg['n_count_checked']:,} rows disagree",
        )
    else:
        add(
            "count_consistency",
            "n_models_flagging equals the number of set verdicts",
            Pass,
            f"consistent on all {agg['n_count_checked']:,} rows checked",
        )

    if agg["n_consensus_checked"] == 0:
        add(
            "consensus_consistency",
            f"consensus == (n_models_flagging >= {CONSENSUS_MIN})",
            Skip,
            "no row carries both a consensus flag and a model count",
        )
    elif agg["n_consensus_mismatch"]:
        add(
            "consensus_consistency",
            f"consensus == (n_models_flagging >= {CONSENSUS_MIN})",
            Fail,
            f"{agg['n_consensus_mismatch']:,} of {agg['n_consensus_checked']:,} rows disagree",
        )
    else:
        add(
            "consensus_consistency",
            f"consensus == (n_models_flagging >= {CONSENSUS_MIN})",
            Pass,
            f"consistent on all {agg['n_consensus_checked']:,} rows checked",
        )

    if agg["n_risk_checked"] == 0:
        add("percentile_bounds", "Anomaly percentile stays within 0-100", Skip, "no scored rows")
    elif agg["n_risk_out_of_bounds"]:
        add(
            "percentile_bounds",
            "Anomaly percentile stays within 0-100",
            Fail,
            f"{agg['n_risk_out_of_bounds']:,} rows fall outside 0-100",
        )
    else:
        add(
            "percentile_bounds",
            "Anomaly percentile stays within 0-100",
            Pass,
            f"all {agg['n_risk_checked']:,} scored rows are inside the range",
        )

    # -- live recomputation vs the recorded detection run --------------------
    reproduced: list[str] = []
    diffs: list[str] = []
    for key in keys:
        rec = recorded.get(key)
        if not rec or rec.get("pct_flagged") is None:
            continue
        n = live[key]["n_scored"]
        if not n:
            continue
        live_pct = live[key]["n_flagged"] / n * 100.0
        rec_pct = float(rec["pct_flagged"])
        if abs(live_pct - rec_pct) > RUN_REPRO_TOLERANCE_PP:
            diffs.append(f"{key}: live {live_pct:.3f}% vs recorded {rec_pct:.3f}%")
        else:
            reproduced.append(key)
    if diffs:
        add(
            "run_reproduction",
            "Live flagged shares match the recorded detection run",
            Fail,
            "; ".join(diffs),
        )
    elif reproduced:
        add(
            "run_reproduction",
            "Live flagged shares match the recorded detection run",
            Pass,
            f"{len(reproduced)} detectors within {RUN_REPRO_TOLERANCE_PP} pp of the "
            "recorded run",
        )
    else:
        add(
            "run_reproduction",
            "Live flagged shares match the recorded detection run",
            Skip,
            f"no detection-run summary at {RUN_SUMMARY_PATH.relative_to(ROOT)}",
        )

    run_block = None
    if run_summary.get("run_id"):
        run_block = {
            "run_id": run_summary.get("run_id"),
            "generated_at": run_summary.get("generated_at"),
            "n_rows": run_summary.get("n_rows"),
            "contamination_assumption": run_summary.get("contamination_assumption"),
            "preprocessing": run_summary.get("preprocessing"),
            "source": str(RUN_SUMMARY_PATH.relative_to(ROOT)),
        }

    n_failed = sum(1 for c in checks if c["status"] == Fail)
    n_skipped = sum(1 for c in checks if c["status"] == Skip)
    return {
        # A "false" here means at least one KPI failed, not that metrics are
        # missing: see ``metrics`` below for the precision/recall statement.
        "ok": n_failed == 0,
        "n_rows": agg["n_rows"],
        "n_scored": agg["n_scored"],
        "n_checks": len(checks),
        "n_failed": n_failed,
        "n_skipped": n_skipped,
        "contamination": {
            "declared": DECLARED_CONTAMINATION,
            "tolerance": CONTAMINATION_TOLERANCE,
        },
        "consensus_min": CONSENSUS_MIN,
        "run": run_block,
        "detectors": catalogue,
        "checks": checks,
        "metrics": {
            "available": False,
            "reason": (
                "real procurements carry no ground-truth anomaly labels, so "
                "precision/recall/F1 are not computable on this corpus; the checks "
                "verify verdicts, thresholds, counts and artefact paths instead"
            ),
        },
    }
