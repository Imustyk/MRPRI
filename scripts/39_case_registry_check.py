#!/usr/bin/env python3
"""Third external label, step 2: the case-registry CHECK of production v0 (MTA-0016).

MEASUREMENT ONLY - not a cycle: production stays v0, nothing is retrained or
retuned, votes/bands/thresholds are untouched, `data/raw/**`, `backend/`,
`frontend/` and `scripts/00..11` are read-only here.

The label
---------
A procedure is positive when it matched a registry record with
``link_basis in {procedure_id_in_source, contract_number}`` (MTA-0017 item 3:
``buyer_period_only`` and empty ``link_basis`` rows enter the registry but
NEVER the label) AND ``evidence_level in {A, B, C}`` AND
``match_confidence in {high, medium}`` (``name_fuzzy``/low-confidence
candidates never enter). ``evidence_level = D`` never enters the label.

TWO VERSIONS (MTA-0017): metrics are computed for ALL A–C records (the
MTA-0016 headline, top level of the JSON) and for ONLY
``verified_by_human = true`` records (``summary["verified_only"]``) - the
author marks rows manually and both versions are gated independently
(>=30 positives, >=10 clusters each).

TEMPORAL PROTECTION (pre-registered): only procedures PUBLISHED STRICTLY
BEFORE the case's ``first_publication_date`` can be labelled, and procedures
matched to a case but published on/after that date are EXCLUDED from the
comparison population entirely. Features and scores are NEVER recomputed from
post-date data: the ranking is the FIXED production artefact
``results/tables/tender_anomaly_scores.csv::max_score``. The honest
limitation is stated in every output: those artefacts were built from the
frozen full-corpus snapshot, so award-side fields of ``features.csv`` may
carry post-publication information; the protection here is population-level,
not a feature-level rebuild.

Metrics (pre-registered)
------------------------
ROC-AUC, precision@100/200/500, lift over the base rate; cluster bootstrap
CIs (1000 reps, seed 42) resampling SUPPLIERS and BUYERS (the label is
entity-level). Required comparisons: size-only (``log_award_total``),
bidders-only (``n_bidders_log``), a random ranking (1000 repeats, q97.5) and
random 5%-within-group flags exactly like ``scripts/28`` (4 independent
random flaggers per «band x type» group, votes as score, 200 repeats).
Separate descriptive cuts: A vs B/C, high vs medium confidence.

Verdict (the SAME а/б/в rule as the ANSC check, ``scripts/31``), withheld
entirely when positives < 30 or positive clusters < 10 («выборка мала» -
descriptive table only).

Outputs:
    results/methodology/case_registry_check.json
    reports/case_registry_check.md

Usage:
    .venv/bin/python scripts/39_case_registry_check.py \
        [--registry ...] [--features ...] [--scores ...] [--random-repeats 1000] \
        [--flag-repeats 200] [--raw-scan] [--rebuild-contract-index]
"""
from __future__ import annotations

import argparse
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

REGISTRY_CSV = ROOT / "data" / "external" / "case_registry.csv"
OUT_JSON = RESULTS / "methodology" / "case_registry_check.json"
OUT_MD = ROOT / "reports" / "case_registry_check.md"
BANDS_JSON = RESULTS / "methodology" / "v5_group_bands.json"

SEED = 42
N_BOOT = 1000
RANDOM_REPEATS = 1000      # random-ranking control, q97.5
FLAG_REPEATS = 200         # random-5%-within-group control (scripts/28)
FLAG_RATE = 0.05
FLAG_SEED = 7700
TOP_K = (100, 200, 500)
MIN_POSITIVES = 30
MIN_CLUSTERS = 10

DISCLAIMER = ("Индикатор потенциального риска, а не доказательство "
              "коррупции/нарушения. Требуется проверка компетентным органом.")
LIMITATIONS = [
    "Метка реестра смещена к крупным и громким случаям — сравнение с "
    "«только размер» обязательно и приведено.",
    "Журналистские материалы (C) — не доказательство нарушения.",
    "Результат показывает приоритизацию, а не наличие коррупции.",
    "Временная защита — популяционная: признаки и оценки v0 не "
    "пересчитываются из данных после first_publication_date; поля наград в "
    "features.csv — снимок поздней даты.",
    DISCLAIMER,
]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


S28 = _load_script("28_random_flags_control.py")
S31 = _load_script("31_ansc_external_check.py")


# ---------------------------------------------------------------------------
# label + population (temporal protection)
# ---------------------------------------------------------------------------

def _cluster_key(df: pd.DataFrame, primary: str, fallback_id: str,
                 fallback_name: str, none_value: str = "<no-entity>") -> np.ndarray:
    """The scripts/31 cluster chain: identifier -> id -> name -> placeholder."""
    out = df[primary].astype("string") if primary in df.columns \
        else pd.Series(pd.NA, index=df.index, dtype="string")
    for col in (fallback_id, fallback_name):
        if col in df.columns:
            out = out.fillna(df[col].astype("string"))
    return out.fillna(none_value).to_numpy()


def build_label_population(per_case: list[dict], corpus: pd.DataFrame,
                           evidence: tuple[str, ...] = ("A", "B", "C"),
                           confidence: tuple[str, ...] = ("high", "medium"),
                           verified_only: bool = False,
                           ) -> tuple[pd.DataFrame | None, dict]:
    """Positives + comparison frame under the pre-registered temporal guard.

    A registry record only contributes when it is label-grade for the requested
    cut (evidence/confidence), has a parseable ``first_publication_date`` and
    matched procedures; with ``verified_only=True`` it must ALSO carry
    ``verified_by_human = true`` (MTA-0017 second version). Positives are its
    matched procedures with ``published_date < first_publication_date``; a
    procedure matched to a case but published on/after that date is dropped
    from the population entirely (it cannot evidence a case that was already
    public). The population is further restricted to
    ``published_date < max(cutoff)`` so no negative row postdates every case
    it could have been associated with.
    """
    case_cut: dict[str, pd.Timestamp] = {}
    n_candidate_pairs = 0
    used_cases = 0
    for rec in per_case:
        if not rec["label_grade"] or rec["evidence_level"] not in evidence \
                or rec["match_confidence"] not in confidence:
            continue
        if verified_only and not rec.get("verified_by_human"):
            continue
        cutoff = pd.to_datetime(rec.get("first_publication_date"), errors="coerce")
        if pd.isna(cutoff):
            continue
        cutoff = cutoff.tz_localize(None)
        used_cases += 1
        for ocid in rec["procedure_ids"]:
            n_candidate_pairs += 1
            prev = case_cut.get(ocid)
            case_cut[ocid] = min(cutoff, prev) if prev is not None else cutoff
    info: dict = {
        "n_label_cases_used": used_cases,
        "n_matched_pairs": n_candidate_pairs,
        "evidence_cut": list(evidence),
        "confidence_cut": list(confidence),
        "verified_only": bool(verified_only),
        "verified_note": ("только записи с verified_by_human=true "
                          "(автор подтвердил вручную)"
                          if verified_only else
                          "все пригодные записи A–C (версия MTA-0016)"),
    }
    if not case_cut:
        info["reason"] = (
            "нет подтверждённых человеком записей (verified_by_human=true) "
            "пригодных для метки" if verified_only
            else "нет пригодных записей реестра (метка пуста)")
        return None, info

    published = (pd.to_datetime(corpus["published_date"], utc=True,
                                errors="coerce").dt.tz_localize(None))
    ocids = corpus["ocid"].astype(str).to_numpy()

    max_cutoff = max(case_cut.values())
    in_window = (published < max_cutoff).fillna(False).to_numpy()
    undated = published.isna().to_numpy()

    matched_case_cutoff = np.array([case_cut.get(o) for o in ocids],
                                   dtype=object)
    post_publication = np.zeros(len(corpus), dtype=bool)
    for i, cutoff in enumerate(matched_case_cutoff):
        stamp = published.iloc[i]
        if cutoff is not None and pd.notna(stamp) and stamp >= cutoff:
            post_publication[i] = True

    y = np.zeros(len(corpus), dtype=int)
    for row_i in positive_rows_predating_case(case_cut, ocids, published):
        y[row_i] = 1

    keep = in_window & ~post_publication & ~undated
    frame = corpus.loc[keep].copy()
    frame["y"] = y[keep]
    info.update({
        "max_cutoff": max_cutoff.strftime("%Y-%m-%d"),
        "n_population": int(keep.sum()),
        "n_positives": int(frame["y"].sum()),
        "n_dropped_post_publication": int(post_publication.sum()),
        "n_dropped_undated": int(undated.sum()),
        "n_dropped_outside_window": int((~in_window & ~post_publication
                                         & ~undated).sum()),
        "base_rate": (round(float(frame["y"].mean()), 8)
                      if len(frame) else None),
        "temporal_guard": ("published_date < first_publication_date "
                           "каждого случая; строки после даты публикации "
                           "случая исключены из популяции; признаки/оценки "
                           "не пересчитываются"),
    })
    return frame, info


def positive_rows_predating_case(case_cut: dict[str, pd.Timestamp],
                                 ocids: np.ndarray,
                                 published: pd.Series) -> list[int]:
    """Row positions whose ocid is label-grade AND predates its case."""
    idx_by_ocid: dict[str, list[int]] = {}
    for i, o in enumerate(ocids):
        idx_by_ocid.setdefault(o, []).append(i)
    out: list[int] = []
    for ocid, cutoff in case_cut.items():
        for i in idx_by_ocid.get(ocid, ()):
            stamp = published.iloc[i]
            if pd.notna(stamp) and stamp < cutoff:
                out.append(i)
    return out


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def ranking_block(y: np.ndarray, score: np.ndarray,
                  cluster_supplier: np.ndarray, cluster_buyer: np.ndarray,
                  n_boot: int = N_BOOT) -> dict:
    """AUC + cluster CIs (supplier, buyer) + precision@k + lift@k."""
    from src.mtender.eval_metrics import lift_at_k, precision_at_k
    from src.mtender.eval_metrics import roc_auc as _auc
    precision = {f"precision_at_{k}": (round(precision_at_k(y, score, k), 6)
                                       if len(y) else None) for k in TOP_K}
    lift = {f"lift_at_{k}": (round(lift_at_k(y, score, k), 4) if len(y)
                             else None) for k in TOP_K}
    block = {
        "roc_auc": (round(_auc(y, score), 6) if np.unique(y).size > 1 else None),
        "cluster_ci_supplier": S31.cluster_bootstrap_auc(y, score,
                                                         cluster_supplier,
                                                         n_boot=n_boot),
        "cluster_ci_buyer": S31.cluster_bootstrap_auc(y, score, cluster_buyer,
                                                      n_boot=n_boot),
        "precision": precision,
        "lift": lift,
        "base_rate": (round(float(np.mean(y)), 8) if len(y) else None),
        "n_procedures": int(len(y)),
        "positives": int(np.sum(y)),
    }
    return block


def random_flag_control(y: np.ndarray, groups: np.ndarray,
                        repeats: int = FLAG_REPEATS, rate: float = FLAG_RATE,
                        seed: int = FLAG_SEED) -> dict:
    """scripts/28 control (a): 4 independent random 5%-flaggers per group.

    The votes (0..4) are used as a score, so the control answers the question
    «can random within-group flags, carrying the SAME normalisation idea as
    v6, produce as much measured association as v0's ranking?».
    """
    uniq, sizes = np.unique(groups, return_counts=True)
    idx_lists = [np.flatnonzero(groups == g) for g in uniq]
    aucs: list[float] = []
    precs: dict[int, list[float]] = {k: [] for k in TOP_K}
    from src.mtender.eval_metrics import precision_at_k, roc_auc
    for rep in range(repeats):
        rng = np.random.default_rng(seed + rep)
        votes, _ = S28.control_a_votes(idx_lists, sizes, rng)
        if np.unique(y).size > 1:
            aucs.append(float(roc_auc(y, votes)))
        for k in TOP_K:
            precs[k].append(float(precision_at_k(y, votes, k)))
    return {
        "repeats": repeats, "rate": rate, "seed": f"{seed}+i",
        "auc": S28._stats(aucs),
        "precision": {f"precision_at_{k}": S28._stats(v) for k, v in precs.items()},
        "method": ("4 независимых случайных флагера по 5% каждой группы "
                   "(голоса 0..4 как оценка), как в scripts/28 контроль (а)"),
    }


def _ci_str(block: dict | list | None) -> str:
    """CI pair of a bootstrap block (or a bare CI list) as text."""
    if isinstance(block, list):
        return f"[{block[0]}, {block[1]}]" if len(block) == 2 else "—"
    ci = (block or {}).get("ci")
    return f"[{ci[0]}, {ci[1]}]" if ci else "—"


def small_sample_gate(y: np.ndarray, cluster_supplier: np.ndarray,
                      cluster_buyer: np.ndarray) -> dict:
    """Pre-registered power gate: <30 positives or <10 clusters -> no verdict."""
    pos = y.astype(bool)
    n_pos = int(pos.sum())
    n_sup = int(np.unique(cluster_supplier[pos]).size) if n_pos else 0
    n_buy = int(np.unique(cluster_buyer[pos]).size) if n_pos else 0
    enough = n_pos >= MIN_POSITIVES and min(n_sup, n_buy) >= MIN_CLUSTERS
    return {
        "positives": n_pos, "clusters_supplier_positives": n_sup,
        "clusters_buyer_positives": n_buy, "min_positives": MIN_POSITIVES,
        "min_clusters": MIN_CLUSTERS, "enough_power": bool(enough),
        "warning": (None if enough else
                    "выборка мала: публикуется только описательная таблица, "
                    "вердикт не выдаётся"),
    }


def decide_verdict(v0: dict, size_auc: float, bidders_auc: float,
                   random_q975: float, flag_control: dict) -> dict:
    """The SAME а/б/в rule as scripts/31, minus the leakage branch.

    The ANSC check's «determined by leakage» branch has no analogue here: the
    case-registry check never refits anything, so there is no no-leak
    diagnostic ranking; the temporal guard is population-level and its
    limitation is stated instead.
    """
    point = v0["point"]
    lo, hi = v0["ci"]
    determined_by_baseline = point <= max(size_auc, bidders_auc) \
        or point <= random_q975
    flag_hi = flag_control["auc"].get("p97_5")
    determined_by_flag_control = (flag_hi is not None and point <= flag_hi)
    if lo > 0.5 and not determined_by_baseline:
        code, text = "а", (
            "кластерный ДИ целиком выше 0,5, v0 лучше размера, числа "
            "участников и случайного ранжирования — на реестре случаев v0 "
            "обнаруживает то, чего не объясняют размер и конкуренция")
    elif lo <= 0.5 <= hi:
        code, text = "б", (
            "ДИ включает 0,5 — на этой метке сигнал неотличим от случайного")
    else:
        reasons = []
        if hi < 0.5:
            reasons.append("ДИ ниже 0,5")
        if determined_by_baseline:
            reasons.append("результат определяется размером/участниками/"
                           "случайным ранжированием")
        code, text = "в", ("; ".join(reasons) or "критерии (а) и (б) не "
                           "выполнены") + " — метка объясняется размером, " \
            "конкуренцией или случайностью"
    return {"code": code, "text": text,
            "determined_by_baseline": bool(determined_by_baseline),
            "determined_by_flag_control": bool(determined_by_flag_control)}


# ---------------------------------------------------------------------------
# one label version (metrics stack)
# ---------------------------------------------------------------------------

def compute_version(per_case: list[dict], corpus: pd.DataFrame,
                    scores: pd.DataFrame, feats: pd.DataFrame, args,
                    verified_only: bool) -> dict:
    """The whole metric stack for ONE label version (MTA-0017).

    ``verified_only=False`` - all eligible A-C records (the MTA-0016
    headline); ``True`` - only ``verified_by_human = true`` records. Every
    version is gated independently (>=30 positives, >=10 clusters). The
    descriptive ``cuts`` are computed for the all-A-C version only
    (pre-registered cuts stay on it); the random-5%-flags control uses each
    version's own frame/groups.
    """
    tag = "только verified_by_human=true" if verified_only else "все A–C"
    frame, info = build_label_population(per_case, corpus,
                                         verified_only=verified_only)
    if frame is None or info["n_positives"] == 0:
        why = info.get("reason") or "нет позитивов до first_publication_date"
        print(f"[{tag}] МЕТКА ПУСТА: {why}", flush=True)
        return {
            "status": "no_label",
            "label": info,
            "warning": (f"метка пуста ({tag}): {why} — расчёт метрик "
                        "невозможен, вердикт не выдаётся"),
            "verdict": {"code": None,
                        "text": "метка пуста — вердикт не выдаётся",
                        "text_full": (f"Метка пуста ({tag}): {why} — "
                                      "вердикт не выдаётся. " + DISCLAIMER)},
        }

    frame = frame.merge(scores, on="ocid", how="left", validate="one_to_one")
    if frame["max_score"].isna().any():
        raise SystemExit("v0-оценки потерялись при соединении по ocid")
    frame = frame.merge(feats, on="ocid", how="left", validate="one_to_one")

    y = frame["y"].to_numpy().astype(int)
    score_v0 = frame["max_score"].to_numpy().astype(float)
    cluster_supplier = _cluster_key(frame, "winner_identifier", "winner_id",
                                    "winner_name")
    cluster_buyer = _cluster_key(frame, "buyer_identifier", "buyer_id",
                                 "buyer_name")

    gate = small_sample_gate(y, cluster_supplier, cluster_buyer)
    print(f"[{tag}] популяция {info['n_population']:,}, "
          f"позитивов {info['n_positives']}, кластеры поставщиков среди "
          f"позитивов {gate['clusters_supplier_positives']}, заказчиков "
          f"{gate['clusters_buyer_positives']}", flush=True)

    v0 = ranking_block(y, score_v0, cluster_supplier, cluster_buyer,
                       n_boot=args.n_boot)
    size_scores = pd.to_numeric(frame["log_award_total"],
                                errors="coerce").fillna(0).to_numpy()
    bidders_scores = pd.to_numeric(frame["n_bidders_log"],
                                   errors="coerce").fillna(0).to_numpy()
    size_block = ranking_block(y, size_scores, cluster_supplier, cluster_buyer,
                               n_boot=args.n_boot)
    bidders_block = ranking_block(y, bidders_scores, cluster_supplier,
                                  cluster_buyer, n_boot=args.n_boot)
    random_block = S31.random_auc_baseline(y, repeats=args.random_repeats)
    print(f"[{tag}] v0 AUC {v0['roc_auc']} supplier-CI "
          f"{v0['cluster_ci_supplier']['ci']}; размер {size_block['roc_auc']}; "
          f"участники {bidders_block['roc_auc']}; случайность q97.5 "
          f"{random_block['q975']}", flush=True)

    # groups for the random-5%-flags control: v5 bands when available
    try:
        edges = json.loads(BANDS_JSON.read_text(encoding="utf-8"))["band_edges"]
    except (OSError, KeyError, json.JSONDecodeError):
        edges = None
    s20 = _load_script("20_cycle_framework.py")
    try:
        group_labels, gmeta = s20.build_group_labels(
            frame[["log_award_value", "procurement_method_details"]], edges=edges)
    except Exception as exc:  # noqa: BLE001 - tiny/degenerate frames fall back
        group_labels = np.full(len(frame), "all")
        gmeta = {"edges_source": f"fallback: единая группа ({exc})"}
    flag_block = random_flag_control(y, np.asarray(group_labels),
                                     repeats=args.flag_repeats)
    print(f"[{tag}] случайные флаги 5%: AUC медиана "
          f"{flag_block['auc'].get('median')} "
          f"[{flag_block['auc'].get('p2_5')}; {flag_block['auc'].get('p97_5')}]",
          flush=True)

    # --- separate cuts (descriptive, no verdict; all-A-C version only) ------
    cuts: dict[str, dict] = {}
    if not verified_only:
        for name, ev, conf in (("только A", ("A",), ("high", "medium")),
                               ("B и C", ("B", "C"), ("high", "medium")),
                               ("только high", ("A", "B", "C"), ("high",)),
                               ("только medium", ("A", "B", "C"), ("medium",))):
            sub, sub_info = build_label_population(per_case, corpus, evidence=ev,
                                                   confidence=conf)
            if sub is None or sub_info.get("n_positives", 0) == 0:
                cuts[name] = {"status": "no_label",
                              **{k: sub_info.get(k) for k in
                                 ("n_label_cases_used", "reason")}}
                continue
            sub = sub.merge(scores, on="ocid", how="left",
                            validate="one_to_one")
            ys = sub["y"].to_numpy().astype(int)
            sup = _cluster_key(sub, "winner_identifier", "winner_id",
                               "winner_name")
            buy = _cluster_key(sub, "buyer_identifier", "buyer_id", "buyer_name")
            cuts[name] = {
                "n_positives": sub_info["n_positives"],
                "n_population": sub_info["n_population"],
                "roc_auc": (round(S31.roc_auc(ys, sub["max_score"]
                                              .to_numpy().astype(float)), 6)
                            if np.unique(ys).size > 1 else None),
                "cluster_ci_supplier": S31.cluster_bootstrap_auc(
                    ys, sub["max_score"].to_numpy().astype(float), sup,
                    n_boot=args.n_boot)["ci"],
                "cluster_ci_buyer": S31.cluster_bootstrap_auc(
                    ys, sub["max_score"].to_numpy().astype(float), buy,
                    n_boot=args.n_boot)["ci"],
            }
            print(f"[{tag}] нарезка «{name}»: позитивов "
                  f"{sub_info['n_positives']}, AUC {cuts[name]['roc_auc']}",
                  flush=True)

    verdict = None
    if gate["enough_power"] and np.unique(y).size > 1:
        verdict = decide_verdict(v0["cluster_ci_supplier"], size_block["roc_auc"],
                                 bidders_block["roc_auc"], random_block["q975"],
                                 flag_block)
        verdict_text = (
            f"Вывод ({verdict['code']}): {verdict['text']}. Метка означает "
            "«случай упомянут в открытом источнике», а не нарушение; решение "
            "о перенастройке здесь не принимается — это измерение, а не цикл "
            "приёмки. " + DISCLAIMER)
    else:
        verdict_text = (f"Вердикт не выдаётся ({tag}): «выборка мала» "
                        "(<30 позитивов или <10 кластеров) — только "
                        "описательная таблица. " + DISCLAIMER)
    print(f"[{tag}] {verdict_text}", flush=True)

    return {
        "status": "ok",
        "label": info,
        "v0_external": v0,
        "baselines": {
            "log_award_total": size_block,
            "n_bidders_log": bidders_block,
            "random_ranking": random_block,
            "random_flags_5pct_within_group": flag_block,
            "group_edges_source": gmeta.get("edges_source"),
        },
        "cuts": cuts,
        "power_gate": gate,
        "verdict": {**verdict, "text_full": verdict_text} if verdict else
                   {"code": None, "text_full": verdict_text},
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default=str(REGISTRY_CSV))
    ap.add_argument("--features", default=str(DATA_FEATURES / "features.csv"))
    ap.add_argument("--scores", default=str(TABLES / "tender_anomaly_scores.csv"))
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-md", default=str(OUT_MD))
    ap.add_argument("--random-repeats", type=int, default=RANDOM_REPEATS)
    ap.add_argument("--flag-repeats", type=int, default=FLAG_REPEATS)
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--raw-scan", action="store_true",
                    help="как в scripts/38: индекс номеров договоров из "
                         "локальных data/raw/ocds_packages (только чтение)")
    ap.add_argument("--rebuild-contract-index", action="store_true",
                    help="перестроить кэш results/methodology/"
                         "contract_index.json (подразумевает --raw-scan)")
    args = ap.parse_args()
    t0 = time.time()

    s38 = _load_script("38_case_registry_match.py")
    raw = pd.read_csv(args.registry, dtype="string", keep_default_na=False)
    registry, validation = s38.validate_registry(raw)
    corpus = s38.load_corpus(args.features)
    # The SAME contract-index policy as scripts/38, so both artefacts agree.
    contract_index = None
    index_origin = "не строился (нет записей link_basis=contract_number)"
    needs_index = any(
        s38._clean(r.get("link_basis")) == "contract_number"
        for _, r in registry[registry["_valid"]].iterrows())
    if needs_index and (args.raw_scan or args.rebuild_contract_index):
        contract_index, index_origin = s38.load_contract_index(
            rebuild=args.rebuild_contract_index)
    elif needs_index:
        index_origin = ("скан data/raw отключён — номера договоров "
                        "разрешаются по объявленным procedure_ids")
    per_case, _proc, match_summary = s38.match_cases(
        registry, corpus, contract_index=contract_index)

    scores = pd.read_csv(args.scores, usecols=["ocid", "max_score"],
                         dtype={"ocid": "string"}, low_memory=False)
    feats = pd.read_csv(args.features,
                        usecols=["ocid", "log_award_total", "n_bidders_log",
                                 "procurement_method_details",
                                 "log_award_value"],
                        dtype={"ocid": "string"}, low_memory=False)

    # Two pre-registered versions (MTA-0017): all A-C, then verified only.
    all_block = compute_version(per_case, corpus, scores, feats, args,
                                verified_only=False)
    verified_block = compute_version(per_case, corpus, scores, feats, args,
                                     verified_only=True)

    summary: dict = {
        "task": "MTA-0016/MTA-0017",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame": ("measurement only - production v0 unchanged, no retraining, "
                  "no retuning, no network"),
        "registry": {"path": args.registry,
                     "n_rows": validation["n_rows"],
                     "n_valid": validation["n_valid"],
                     "n_rejected": validation["n_rejected"]},
        "contract_index": {"used": contract_index is not None,
                           "origin": index_origin},
        "matching": match_summary,
        "pre_registered": {
            "seed": SEED, "n_boot": args.n_boot,
            "random_repeats": args.random_repeats,
            "flag_repeats": args.flag_repeats, "flag_rate": FLAG_RATE,
            "top_k": list(TOP_K),
            "min_positives": MIN_POSITIVES, "min_clusters": MIN_CLUSTERS,
            "label_rule": ("link_basis in {procedure_id_in_source, "
                           "contract_number} AND evidence A-C AND "
                           "match_confidence high/medium; buyer_period_only, "
                           "пустой link_basis, D and fuzzy/low never enter"),
            "versions": ["все A–C (заголовок MTA-0016)",
                         "только verified_by_human=true (MTA-0017)"],
            "temporal_guard": (all_block.get("label") or {}).get(
                "temporal_guard"),
            "verdict_rule": ("тот же а/б/в, что в scripts/31 (без ветки "
                             "утечки: здесь ничего не переобучается); каждая "
                             "версия гейтится отдельно"),
        },
        "disclaimer": DISCLAIMER,
        "limitations": LIMITATIONS,
    }
    summary.update(all_block)          # status/label/v0_external/baselines/...
    summary["verified_only"] = verified_block
    summary["seconds"] = round(time.time() - t0, 1)
    _write_outputs(summary, args)
    if all_block["status"] == "no_label":
        print("МЕТКА ПУСТА: реестр не содержит пригодных записей — "
              "описательный вывод без метрик и вердикта.", flush=True)
    print(f"json  -> {args.out_json}", flush=True)
    print(f"report -> {args.out_md}", flush=True)
    return 0


def _write_outputs(summary: dict, args) -> None:
    """Write the JSON (already assembled) and the Markdown report."""
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    info = summary.get("label") or {}
    lines = [
        "# MTA-0016/MTA-0017: третья внешняя проверка — реестр случаев из "
        "открытых источников (только измерение)",
        "",
        f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
        "**Только измерение**: production остаётся v0, ничего не "
        "переобучается и не перенастраивается, голоса/полосы/пороги не "
        "меняются, сеть не используется.",
        "",
        *sum(([f"- {t}"] for t in LIMITATIONS), []),
        "",
        "## 1. Метка и временная защита (предзаписано)",
        "",
        "- позитив = процедура, сопоставленная с записью реестра "
        "`link_basis` ∈ {`procedure_id_in_source`, `contract_number`} "
        "(MTA-0017, п. 3: `buyer_period_only` и пустой `link_basis` в метку "
        "не входят) AND `evidence_level` A–C AND `match_confidence` "
        "high/medium (`name_fuzzy`/low — только кандидаты, в метку не "
        "входят; D — никогда);",
        f"- временная защита: {info.get('temporal_guard', '—')};",
        f"- всего записей реестра: {summary['registry']['n_rows']} "
        f"(принято {summary['registry']['n_valid']}); "
        f"записей в метке: {summary['matching']['n_matched_label_grade']};",
        "- версии расчёта (MTA-0017): **все A–C** (заголовок) и **только "
        "`verified_by_human = true`** (автор подтверждает записи вручную); "
        "каждая версия гейтится отдельно;",
        f"- популяция сравнения: {info['n_population']:,} процедур "
        f"(позитивов {info['n_positives']}, базовая доля "
        f"{info['base_rate']}); исключено после даты публикации случая: "
        f"{info.get('n_dropped_post_publication', 0)}."
        if info.get("n_population") else
        "- популяция сравнения: не определена (метка пуста).",
        "",
    ]

    def metrics_table(block: dict) -> list[str]:
        v0 = block["v0_external"]
        sup_lo, sup_hi = v0["cluster_ci_supplier"]["ci"] or ("—", "—")
        buy_lo, buy_hi = v0["cluster_ci_buyer"]["ci"] or ("—", "—")
        return [
            "| метрика | значение |",
            "|---|---|",
            f"| ROC-AUC (v0, max_score) | {v0['roc_auc']} |",
            f"| ДИ кластерный по поставщикам | [{sup_lo}, {sup_hi}] |",
            f"| ДИ кластерный по заказчикам | [{buy_lo}, {buy_hi}] |",
            *[f"| precision@{k} | {v0['precision'][f'precision_at_{k}']} |"
              for k in TOP_K],
            *[f"| lift@{k} (над базовой долей) | {v0['lift'][f'lift_at_{k}']} |"
              for k in TOP_K],
        ]

    def gate_lines(block: dict) -> list[str]:
        gate = block["power_gate"]
        verdict = block.get("verdict") or {}
        return [
            f"Позитивов: {gate['positives']}; кластеров среди позитивов — "
            f"поставщиков {gate['clusters_supplier_positives']}, заказчиков "
            f"{gate['clusters_buyer_positives']} (порог: ≥ "
            f"{gate['min_positives']} и ≥ {gate['min_clusters']}).",
            "",
            f"**{verdict.get('text_full', '—')}**",
            "",
        ]

    if summary.get("status") == "no_label":
        verified = summary.get("verified_only") or {}
        lines += [
            "## 2. Результат",
            "",
            f"**Метка пуста** — {summary.get('warning', '')} "
            "(сейчас реестр — шаблон без записей). Метрики и вердикт не "
            "выдаются, чтобы не измерять пустоту. Как только записи "
            "появятся, `scripts/39` посчитает метрики автоматически.",
            "",
            "Вторая версия (только `verified_by_human=true`): "
            + (verified.get("warning") or "—") + ".",
            "",
            "## 3. Артефакты",
            "",
            "`results/methodology/case_registry_check.json`, этот отчёт. "
            "Схема реестра: `docs/case_registry_schema.md`. "
            "Наполнение: `scripts/41_case_registry_ingest.py`.",
            "",
            DISCLAIMER, "",
        ]
    else:
        baselines = summary["baselines"]
        cuts = summary.get("cuts") or {}
        verified = summary.get("verified_only") or {}
        lines += [
            "## 2. Метрики v0 против метки реестра (версия: все A–C)",
            "",
            *metrics_table(summary),
            "",
            "## 3. Обязательные сравнения",
            "",
            "| базовое ранжирование | ROC-AUC |",
            "|---|---|",
            f"| только размер (log_award_total) | "
            f"{baselines['log_award_total']['roc_auc']} |",
            f"| только участники (n_bidders_log) | "
            f"{baselines['n_bidders_log']['roc_auc']} |",
            f"| случайный ранжирование "
            f"({baselines['random_ranking']['repeats']} повторов, q97.5) | "
            f"{baselines['random_ranking']['q975']} (медиана "
            f"{baselines['random_ranking']['mean']}) |",
            f"| случайные флаги 5% внутри группы "
            f"({baselines['random_flags_5pct_within_group']['repeats']} "
            f"повторов, AUC медиана [p2.5; p97.5]) | "
            f"{baselines['random_flags_5pct_within_group']['auc'].get('median')} "
            f"[{baselines['random_flags_5pct_within_group']['auc'].get('p2_5')}; "
            f"{baselines['random_flags_5pct_within_group']['auc'].get('p97_5')}] |",
            "",
            "## 4. Нарезки (описательно, без вердикта)",
            "",
            "| нарезка | позитивов | ROC-AUC | ДИ (поставщики) |",
            "|---|---|---|---|",
            *[f"| {name} | {c.get('n_positives', 0)} | {c.get('roc_auc')} | "
              f"{_ci_str(c.get('cluster_ci_supplier'))} |"
              for name, c in cuts.items()],
            "",
            "## 5. Мощность и вердикт (версия: все A–C)",
            "",
            *gate_lines(summary),
            "## 6. Версия только verified_by_human=true (MTA-0017)",
            "",
        ]
        if verified.get("status") == "no_label":
            lines += [
                f"Версия пуста: {verified.get('warning', '—')} — автор ещё "
                "не подтвердил ни одной пригодной записи. Метрики и вердикт "
                "для этой версии не выдаются.",
                "",
            ]
        else:
            v_label = verified["label"]
            lines += [
                f"Записей в метке (подтверждено человеком): "
                f"{v_label.get('n_label_cases_used')}; "
                f"популяция {v_label['n_population']:,} "
                f"(позитивов {v_label['n_positives']}).",
                "",
                *metrics_table(verified),
                "",
                *gate_lines(verified),
            ]
        lines += [
            "## 7. Артефакты",
            "",
            "`results/methodology/case_registry_check.json`, этот отчёт. "
            "Разборы случаев: `reports/case_studies.md` "
            "(`scripts/40_case_registry_studies.py`).",
            "",
            DISCLAIMER, "",
        ]
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
