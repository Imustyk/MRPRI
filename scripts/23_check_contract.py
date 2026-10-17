"""Step 23 - contract matrix check: does the model satisfy the acceptance contract?

``docs/contract_matrix.yaml`` is the frozen agreement between the business and
the model: every KPI (business or model) carries a data source, a metric, an
acceptance threshold and the status recorded at the last full run. The model
is **accepted only when every row is "met" or a documented
"not_verifiable"**; any "unmet" row fails the contract.

This script recomputes every verifiable status from the artefacts of the last
cycle and fails (exit 1) with a readable message when:

* any row is "unmet"                          -> the model is NOT accepted,
* a row's artefact is missing                 -> "у метрики нет источника",
* a recorded status no longer matches         -> the matrix is stale,
* a model KPI has no (existing) business KPI  -> broken contract link,
* a "not_verifiable" row lacks a documented reason + doc reference.

Usage:
    .venv/bin/python scripts/23_check_contract.py          # exit 1 while the contract is unsatisfied
    .venv/bin/python scripts/23_check_contract.py --soft   # report only, always exit 0
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "contract_matrix.yaml"

COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}

#: protected attributes the model may never use (section E / legal review)
PROTECTED_TOKENS = ("gender", "sex", "ethnic", "nationality", "religion",
                    "national", "age", "birthdate", "cetatenie", "genul")
#: the only documented structural proxy with |r| >= 0.3 (definitional, E.4)
DOCUMENTED_PROXIES = ["supplier_award_count_log"]


# --------------------------------------------------------------------------
# metric loaders: each returns the recomputed value from the last cycle's
# artefact; FileNotFoundError in the message means "источник отсутствует"
# --------------------------------------------------------------------------
def check_precision_at_200_all(root: Path) -> float:
    df = pd.read_csv(root / "results/tables/external_metrics.csv")
    rows = df[(df["ranking_rule"] == "production_max_score")
              & (df["period"] == "all") & (df["metric"] == "precision@200")]
    if rows.empty:
        raise FileNotFoundError("external_metrics.csv: no production precision@200 row")
    return float(rows["value"].iloc[0])


def check_recall_at_200_all(root: Path) -> float:
    df = pd.read_csv(root / "results/tables/external_metrics.csv")
    rows = df[(df["ranking_rule"] == "production_max_score")
              & (df["period"] == "all") & (df["metric"] == "recall@200")]
    if rows.empty:
        raise FileNotFoundError("external_metrics.csv: no production recall@200 row")
    return float(rows["value"].iloc[0])


def check_pr_auc_ratio_all(root: Path) -> float:
    df = pd.read_csv(root / "results/tables/external_metrics.csv")
    part = df[(df["ranking_rule"] == "production_max_score") & (df["period"] == "all")]
    auc = part[part["metric"] == "pr_auc"]["value"]
    base = part[part["metric"] == "pr_auc_base_rate"]["value"]
    if auc.empty or base.empty or float(base.iloc[0]) == 0:
        raise FileNotFoundError("external_metrics.csv: pr_auc / pr_auc_base_rate rows missing")
    return float(auc.iloc[0]) / float(base.iloc[0])


def check_auc_tuning_ci_hi(root: Path) -> float:
    """Worst (cluster-bootstrap) upper CI edge of the tuning AUC."""
    df = pd.read_csv(root / "results/tables/external_metrics.csv")
    rows = df[(df["ranking_rule"] == "production_max_score")
              & (df["period"] == "2018-2021") & (df["metric"] == "roc_auc")]
    if rows.empty or rows["ci_hi"].isna().all():
        raise FileNotFoundError("external_metrics.csv: no tuning ROC-AUC rows with CIs")
    return float(rows["ci_hi"].max())


def check_band_label_monotonic(root: Path) -> float:
    df = pd.read_csv(root / "results/tables/aap_label_by_band.csv")
    order = ["low", "medium", "high", "critical"]
    shares = df.set_index("band")["share_positive"]
    if not all(b in shares.index for b in order):
        raise FileNotFoundError("aap_label_by_band.csv: band rows missing")
    seq = [float(shares[b]) for b in order]
    return 1.0 if all(a < b for a, b in zip(seq, seq[1:])) else 0.0


def check_drift_psi_max(root: Path) -> float:
    df = pd.read_csv(root / "results/tables/drift_periods.csv")
    if "psi" not in df.columns or df["psi"].dropna().empty:
        raise FileNotFoundError("drift_periods.csv: no psi column/values")
    return float(df["psi"].max())


def check_bias_unexplained_count(root: Path) -> float:
    import json
    payload = json.loads((root / "results/methodology/bias_audit.json").read_text("utf-8"))
    counts = payload.get("verdict_counts") or {}
    return float(counts.get("нарушение", 0) + counts.get("предупреждение", 0))


def check_consensus_lift_min_period(root: Path) -> float:
    df = pd.read_csv(root / "results/tables/threshold_sweep.csv")
    rows = df[(df["rule"] == "votes>=3")
              & (df["period"].isin(["2018-2021", "2022-2024"]))]
    if rows.empty or rows["lift"].dropna().empty:
        raise FileNotFoundError("threshold_sweep.csv: no votes>=3 period rows with lift")
    return float(rows["lift"].min())


def check_cost_ratio_vs_no_flag_tuning_c200(root: Path) -> float:
    df = pd.read_csv(root / "results/tables/threshold_sweep.csv")
    part = df[df["period"] == "2018-2021"]
    rule = part[part["rule"] == "votes>=3"]["cost_miss_200"]
    base = part[part["rule"] == "baseline:no_flag"]["cost_miss_200"]
    if rule.empty or base.empty or float(base.iloc[0]) == 0:
        raise FileNotFoundError("threshold_sweep.csv: cost rows for 2018-2021 missing")
    return float(rule.iloc[0]) / float(base.iloc[0])


def check_kappa_mean(root: Path) -> float:
    import json
    payload = json.loads((root / "results/methodology/agreement_matrix.json").read_text("utf-8"))
    return float(payload["mean_pairwise_kappa"])


def check_seed_top200_jaccard_mean(root: Path) -> float:
    import json
    payload = json.loads((root / "results/methodology/robustness_seeds.json").read_text("utf-8"))
    return float(payload["jaccard_top200_vs_baseline"]["mean"])


def check_seed_consensus_cv_pct(root: Path) -> float:
    import json
    payload = json.loads((root / "results/methodology/robustness_seeds.json").read_text("utf-8"))
    return float(payload["consensus_count"]["cv_pct"])


def check_refit_matches_production(root: Path) -> float:
    """Jaccard between a full-corpus refit and the shipped production ranking."""
    import json
    payload = json.loads((root / "results/methodology/cycle_framework.json").read_text("utf-8"))
    agreement = payload["variants"]["v0_baseline"]["production_agreement"]
    return float(agreement["jaccard_refit_vs_shipped"])


def check_protected_attributes_absent(root: Path) -> float:
    """1.0 only if no protected attribute is a feature AND the |r|>=0.3 proxy
    list is exactly the documented (definitional) one."""
    import json
    from src.mtender.features import FEATURE_COLUMNS
    lower = [c.lower() for c in FEATURE_COLUMNS]
    if any(tok in name for name in lower for tok in PROTECTED_TOKENS):
        return 0.0
    payload = json.loads((root / "results/methodology/bias_audit.json").read_text("utf-8"))
    proxies = payload.get("structural_proxies") or []
    return 1.0 if list(proxies) == DOCUMENTED_PROXIES else 0.0


def check_explanation_any_ocid(root: Path) -> float:
    """Functional check of the right to an explanation (scripts/17)."""
    scores = root / "results/tables/tender_anomaly_scores.csv"
    if not scores.exists():
        raise FileNotFoundError("tender_anomaly_scores.csv missing: no ocid to explain")
    ocid = pd.read_csv(scores, usecols=["ocid"]).iloc[0]["ocid"]
    proc = subprocess.run(
        [sys.executable, str(root / "scripts/17_explain_ocid.py"), "--ocid", str(ocid)],
        capture_output=True, text=True, timeout=300, cwd=root)
    ok = proc.returncode == 0 and len(proc.stdout) >= 200
    return 1.0 if ok else 0.0


def check_xai_spearman_median(root: Path) -> float:
    """Median Spearman(LIME, SHAP) over the section-H procedure sample."""
    path = root / "results/methodology/xai_consistency.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        return float(payload["agreement"]["spearman"]["median"])
    except KeyError as exc:
        raise FileNotFoundError(f"{path}: agreement.spearman.median missing") from exc


def check_rag_coverage_high_critical(root: Path) -> float:
    """Share of high/critical procedures whose explanation cites the corpus."""
    path = root / "results/rag/pipeline_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        return float(payload["coverage_share"])
    except KeyError as exc:
        raise FileNotFoundError(f"{path}: coverage_share missing") from exc


def check_rag_recall_at_3(root: Path) -> float:
    """Retrieval recall@3 of the normative layer on the self-supervised set."""
    path = root / "results/methodology/rag_eval.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        return float(payload["retrieval"]["recall_at_3"])
    except KeyError as exc:
        raise FileNotFoundError(f"{path}: retrieval.recall_at_3 missing") from exc


def check_rag_hallucination_rate(root: Path) -> float:
    """Share of citations that fail verbatim re-verification (must be 0)."""
    path = root / "results/methodology/rag_eval.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        return float(payload["hallucination"]["rate"])
    except KeyError as exc:
        raise FileNotFoundError(f"{path}: hallucination.rate missing") from exc


REGISTRY: dict[str, Callable[[Path], float]] = {
    "precision_at_200_all": check_precision_at_200_all,
    "recall_at_200_all": check_recall_at_200_all,
    "pr_auc_ratio_all": check_pr_auc_ratio_all,
    "auc_tuning_ci_hi": check_auc_tuning_ci_hi,
    "band_label_monotonic": check_band_label_monotonic,
    "drift_psi_max": check_drift_psi_max,
    "bias_unexplained_count": check_bias_unexplained_count,
    "consensus_lift_min_period": check_consensus_lift_min_period,
    "cost_ratio_vs_no_flag_tuning_c200": check_cost_ratio_vs_no_flag_tuning_c200,
    "kappa_mean": check_kappa_mean,
    "seed_top200_jaccard_mean": check_seed_top200_jaccard_mean,
    "seed_consensus_cv_pct": check_seed_consensus_cv_pct,
    "refit_matches_production": check_refit_matches_production,
    "protected_attributes_absent": check_protected_attributes_absent,
    "explanation_any_ocid": check_explanation_any_ocid,
    "xai_spearman_median": check_xai_spearman_median,
    "rag_coverage_high_critical": check_rag_coverage_high_critical,
    "rag_recall_at_3": check_rag_recall_at_3,
    "rag_hallucination_rate": check_rag_hallucination_rate,
}


# --------------------------------------------------------------------------
# structural validation (shared with tests)
# --------------------------------------------------------------------------
VALID_STATUS = {"met", "unmet", "not_verifiable"}


def validate_structure(rows: list[dict]) -> list[str]:
    """Contract-link and schema problems, independent of the artefacts."""
    problems: list[str] = []
    biz_ids = {r["id"] for r in rows if r.get("type") == "business"}
    seen: set[str] = set()
    for row in rows:
        rid = row.get("id", "<no id>")
        if rid in seen:
            problems.append(f"{rid}: duplicate row id")
        seen.add(rid)
        if row.get("type") not in {"business", "model"}:
            problems.append(f"{rid}: type must be business|model, got {row.get('type')!r}")
        if row.get("status") not in VALID_STATUS:
            problems.append(f"{rid}: status must be met|unmet|not_verifiable, got {row.get('status')!r}")
        if row.get("type") == "model":
            linked = row.get("linked_to") or []
            if not linked:
                problems.append(f"{rid}: model KPI must reference >= 1 business KPI")
            for ref in linked:
                if ref not in biz_ids:
                    problems.append(f"{rid}: linked business KPI {ref!r} does not exist")
        verifiable = row.get("verifiable", True)
        if verifiable is False:
            if not row.get("reason") or not row.get("doc_ref"):
                problems.append(f"{rid}: not_verifiable requires documented reason + doc_ref")
        else:
            if not row.get("check"):
                problems.append(f"{rid}: verifiable row has no check id")
            elif row["check"] not in REGISTRY:
                problems.append(f"{rid}: check {row['check']!r} is not in the registry")
            if row.get("comparator") not in COMPARATORS:
                problems.append(f"{rid}: unknown comparator {row.get('comparator')!r}")
    return problems


def evaluate_rows(rows: list[dict], root: Path) -> list[dict]:
    """Recompute each row; returns per-row outcome dicts (never raises)."""
    out = []
    for row in rows:
        rec = {"id": row["id"], "title": row.get("title", ""),
               "recorded": row.get("status"), "computed": None,
               "value": None, "error": None}
        if row.get("verifiable", True) is False:
            rec["computed"] = "not_verifiable"
        else:
            artifact = root / row.get("artifact", "")
            if not row.get("artifact") or not artifact.exists():
                rec["error"] = f"у метрики нет источника: {row.get('artifact')}"
            else:
                try:
                    value = REGISTRY[row["check"]](root)
                    ok = COMPARATORS[row["comparator"]](value, float(row["limit"]))
                    rec["value"] = float(value)
                    rec["computed"] = "met" if ok else "unmet"
                except FileNotFoundError as exc:
                    rec["error"] = f"у метрики нет источника: {exc}"
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = f"метрика не пересчиталась: {exc}"
        out.append(rec)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--soft", action="store_true",
                    help="report only; always exit 0")
    args = ap.parse_args(argv)

    import yaml
    matrix = yaml.safe_load(MATRIX.read_text("utf-8"))
    rows = matrix["rows"]
    frozen = (matrix.get("meta") or {}).get("frozen_at", "?")

    print(f"== contract matrix ({MATRIX.relative_to(ROOT)}, frozen {frozen}) ==")
    problems = validate_structure(rows)
    evaluations = evaluate_rows(rows, ROOT)

    for rec in evaluations:
        line = f"{rec['id']:<4} {str(rec['computed']):<14} {rec['title']}"
        if rec["value"] is not None:
            line += f"  [value={rec['value']:.6g}]"
        if rec["error"]:
            line += f"  <- {rec['error']}"
            problems.append(f"{rec['id']}: {rec['error']}")
        elif rec["recorded"] != rec["computed"]:
            problems.append(
                f"{rec['id']}: матрица устарела — записан {rec['recorded']}, "
                f"пересчитано {rec['computed']} (обновите docs/contract_matrix.yaml)")
        print(line)

    counts = {s: sum(1 for r in evaluations if r["computed"] == s) for s in VALID_STATUS}
    print(f"\nИтог: met={counts['met']}, unmet={counts['unmet']}, "
          f"not_verifiable={counts['not_verifiable']} (всего {len(rows)} строк)")

    if problems:
        print("\nПРОБЛЕМЫ МАТРИЦЫ (исправить саму матрицу/артефакты):")
        for p in problems:
            print(f"  - {p}")

    unmet = [r for r in evaluations if r["computed"] == "unmet"]
    if unmet:
        print("\nНЕ ВЫПОЛНЕНО (модель НЕ принята по матрице контракта):")
        for r in unmet:
            print(f"  - {r['id']} {r['title']}")

    contract_ok = not problems and not unmet
    if contract_ok:
        print("\nКОНТРАКТ СХОДИТСЯ: все строки «выполнено» или документировано "
              "«не проверяемо» — модель принята.")
        return 0
    print("\nКОНТРАКТ НЕ СХОДИТСЯ: см. строки выше. Модель не считается принятой.")
    return 0 if args.soft else 1


if __name__ == "__main__":
    raise SystemExit(main())
