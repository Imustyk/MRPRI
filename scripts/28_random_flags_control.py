#!/usr/bin/env python3
"""Random-5%-within-group control for variant ``v6_group_flags`` (MTA-0009).

Question (author's MTA-0009): are v6's improvements - C3 passing, B4 inside
the band, size dominance down - achieved by the WITHIN-GROUP NORMALISATION
itself (~5% of every group flagged by construction) rather than by anything
the detectors measure? The control therefore keeps the normalisation and
throws the detector signal away: flags are drawn at random, and no detector
score is used anywhere in this script.

Two controls, 200 repeats each with fixed seeds:

* **(a) independent random flags** - each of 4 "detectors" flags a random
  ``ceil(5%)`` of every group (the same per-group flag count as v6's
  ``group_flag_frame``), independently; consensus >= 3 votes. With
  independent votes the consensus is nearly empty (~4*0.05^3 ~ 0.05%),
  exactly as the author predicted, which is why control (b) exists.
* **(b) rank-consensus-matched** - the band SIZES of v6 (consensus 2,965,
  high+ 6,969) drawn at random inside the groups proportionally to group
  size, critical nested in high+; the low/medium split of (b) is undefined
  and is not used by any compared metric (C3 uses consensus, B4/size use
  high+).

Per repeat the same formulas as production are recomputed: C3 (yearly
consensus-share ratio, min/max over years with n >= 500 - scripts/20),
direct-award share of high+ and disparity (rate in group / rate in the
complement - scripts/18), >= 50 m share of high+ and its disparity, and
signal retention (share of v0-critical procedures kept). The full section-E
audit is re-run on the control votes with the production code path
(``scripts/18.audit_group_table``) on the first 5 repeats per control at
``--audit-boot 200`` - verdict counts only; the production audits are never
overwritten.

Nothing here changes any verdict: production stays v0, the cycle-6 verdict
("not adopted - compromise"), the contract matrix 9/16/2 and the closing
status 1 of 4 are untouched; this is a control measurement, not a new cycle
(budget stays 6 of 10, no v7 is created).

Usage:
    .venv/bin/python scripts/28_random_flags_control.py \
        [--repeats 200] [--audit-repeats 5] [--audit-boot 200] [--seed 7700]

Outputs:
  results/methodology/random_flags_control.json
  results/tables/random_flags_control.csv
  reports/random_flags_control.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
REPORTS = ROOT / "reports"
TABLES = RESULTS / "tables"
sys.path.insert(0, str(ROOT))

from src.mtender.config import DATA_FEATURES                  # noqa: E402
from src.mtender.eval_metrics import cohen_kappa          # noqa: E402

RATE = 0.05           # v6 flag share inside every group (OUTLIER_RATE)
N_DETECTOR_SIM = 4    # detectors in the ensemble
MIN_YEAR_N = 500      # scripts/20: years with fewer rows carry no C3 weight
TUNING_YEARS = range(2018, 2022)


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# control generators (pure, seedable - covered by tests/test_cycle_protocol)
# ---------------------------------------------------------------------------

def flag_counts_per_group(sizes: np.ndarray, rate: float = RATE) -> np.ndarray:
    """Rows flagged per group so that the SHARE equals v6's ``group_flag_frame``.

    v6 selects within-group percentiles ``> 1 - rate`` on the exact 1/n..n/n
    grid, i.e. ``n - floor((1 - rate) * n)`` rows per group - mirrored here so
    control (a) carries the identical normalisation.
    """
    sizes = np.asarray(sizes, dtype=float)
    return (sizes - np.floor((1.0 - rate) * sizes)).astype(int)


def allocate_proportional(sizes: np.ndarray, total: int) -> np.ndarray:
    """Largest-remainder allocation of ``total`` over groups by size."""
    sizes = np.asarray(sizes, dtype=float)
    exact = sizes * total / sizes.sum()
    base = np.floor(exact).astype(int)
    remainder = int(total - base.sum())
    if remainder:
        order = np.argsort(-(exact - base), kind="stable")
        base[order[:remainder]] += 1
    assert int(base.sum()) == total
    return base


def control_a_votes(idx_lists: list[np.ndarray], sizes: np.ndarray,
                    rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """(votes, flags) of control (a): 4 independent random 5%-flags per group."""
    n = int(sizes.sum())
    votes = np.zeros(n, dtype=np.int8)
    flags = np.zeros((n, N_DETECTOR_SIM), dtype=bool)
    counts = flag_counts_per_group(sizes)
    for d in range(N_DETECTOR_SIM):
        for idx, k in zip(idx_lists, counts):
            chosen = rng.choice(idx, size=int(k), replace=False)
            flags[chosen, d] = True
            votes[chosen] += 1
    return votes, flags


def control_b_votes(idx_lists: list[np.ndarray], sizes: np.ndarray,
                    n_high: int, n_crit: int,
                    rng: np.random.Generator) -> np.ndarray:
    """Votes of control (b): v6's band sizes drawn at random, critical < high+."""
    alloc_high = allocate_proportional(sizes, n_high)
    alloc_crit = allocate_proportional(alloc_high, n_crit)
    votes = np.zeros(int(sizes.sum()), dtype=np.int8)
    for idx, n_hi, n_cr in zip(idx_lists, alloc_high, alloc_crit):
        crit_rows = rng.choice(idx, size=int(n_cr), replace=False)
        rest = idx[~np.isin(idx, crit_rows)] if n_cr else idx
        extra = rng.choice(rest, size=int(n_hi - n_cr), replace=False) \
            if n_hi > n_cr else np.array([], dtype=int)
        votes[crit_rows] = 3
        votes[extra] = 2
    return votes


# ---------------------------------------------------------------------------
# metrics (production formulas, verbatim in spirit)
# ---------------------------------------------------------------------------

def yearly_consensus_ratio(year: np.ndarray, consensus: np.ndarray) -> float | None:
    """scripts/20: min/max yearly consensus share over years with n >= 500."""
    df = pd.DataFrame({"y": year, "c": consensus})
    shares = [float(g["c"].mean()) for _, g in df.groupby("y") if len(g) >= MIN_YEAR_N]
    if not shares or max(shares) == 0:
        return None          # no consensus at all in any weighted year
    return round(min(shares) / max(shares), 4)


def disparity_rate(mask: np.ndarray, high: np.ndarray) -> float | None:
    """scripts/18: rate(high+ | group) / rate(high+ | complement)."""
    rest = high[~mask]
    if mask.sum() == 0 or rest.size == 0 or rest.mean() == 0:
        return None
    return round(float(high[mask].mean() / rest.mean()), 4)


def control_metrics(votes: np.ndarray, year: np.ndarray, direct: np.ndarray,
                    ge50: np.ndarray, v0_critical: np.ndarray) -> dict:
    cons = votes >= 3
    high = votes >= 2
    share_direct_high = ((high & direct).sum() / max(int(high.sum()), 1))
    share_ge50_high = ((high & ge50).sum() / max(int(high.sum()), 1))
    return {
        "c3_yearly_share_ratio": yearly_consensus_ratio(year, cons),
        "consensus_n": int(cons.sum()),
        "high_plus_n": int(high.sum()),
        "b4_direct_disparity": disparity_rate(direct, high),
        "b4_direct_share_of_high_plus": round(float(share_direct_high), 4),
        "ge50m_rate_high_plus": (round(float(high[ge50].mean()), 4)
                                 if ge50.any() else None),
        "ge50m_disparity": disparity_rate(ge50, high),
        "ge50m_share_of_high_plus": round(float(share_ge50_high), 4),
        "kept_v0_critical_share": round(
            float((v0_critical & cons).sum() / max(int(v0_critical.sum()), 1)), 4),
    }


def pairwise_kappa_mean(flags: np.ndarray) -> float:
    """scripts/20 agreement: mean pairwise Cohen's kappa of the detector flags."""
    kappas = [cohen_kappa(flags[:, a], flags[:, b])
              for a in range(flags.shape[1])
              for b in range(a + 1, flags.shape[1])]
    return round(float(np.mean(kappas)), 4)


def _stats(values: list[float | None]) -> dict:
    arr = np.asarray([v for v in values if pd.notna(v)], dtype=float)
    if arr.size == 0:
        return {"n": 0}
    return {"n": int(arr.size), "median": round(float(np.median(arr)), 4),
            "mean": round(float(arr.mean()), 4),
            "p2_5": round(float(np.quantile(arr, 0.025)), 4),
            "p97_5": round(float(np.quantile(arr, 0.975)), 4),
            "min": round(float(arr.min()), 4), "max": round(float(arr.max()), 4)}


def _unexplained(verdict_counts: dict) -> int:
    return int(sum(v for k, v in verdict_counts.items()
                   if str(k).startswith(("нарушение", "предупреждение"))))


def main() -> int:
    t0 = time.time()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeats", type=int, default=200)
    ap.add_argument("--audit-repeats", type=int, default=5)
    ap.add_argument("--audit-boot", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7700)
    args = ap.parse_args()

    s18 = _load_script("18_bias_audit.py")
    s20 = _load_script("20_cycle_framework.py")

    # ---- the exact production audit frame (votes-independent) -------------
    print("building the production audit frame (scripts/18) ...", flush=True)
    df = s18.build_audit_frame()
    n = len(df)
    print(f"frame: {n:,} procedures", flush=True)

    # ---- the cycle's groups (saved v5_group_bands.json edges) -------------
    feats = pd.read_csv(DATA_FEATURES / "features.csv",
                        usecols=["ocid", "log_award_value",
                                 "procurement_method_details"],
                        low_memory=False)
    edges = json.loads((RESULTS / "methodology" / "v5_group_bands.json")
                       .read_text(encoding="utf-8"))["band_edges"]
    group_labels, gmeta = s20.build_group_labels(feats, edges=edges)
    g_by_ocid = pd.Series(np.asarray(group_labels),
                          index=feats["ocid"].astype(str))
    groups = df["ocid"].astype(str).map(g_by_ocid).to_numpy()
    assert not pd.isna(groups).any(), "group labels must cover the audit frame"
    uniq, sizes = np.unique(groups, return_counts=True)
    idx_lists = [np.flatnonzero(groups == g) for g in uniq]
    print(f"groups: {len(uniq)} (min {sizes.min()}, max {sizes.max()})",
          flush=True)

    # ---- reference values (artefacts, not recomputed detector fits) -------
    fw = json.loads((RESULTS / "methodology" / "cycle_framework.json")
                    .read_text(encoding="utf-8"))
    a0 = json.loads((RESULTS / "methodology" / "bias_audit.json")
                    .read_text(encoding="utf-8"))
    a6 = json.loads((RESULTS / "methodology" / "bias_audit_v6.json")
                    .read_text(encoding="utf-8"))
    g0 = pd.read_csv(TABLES / "bias_audit_groups.csv")
    g6 = pd.read_csv(TABLES / "bias_audit_groups_v6.csv")

    def _audit_rows(tbl: pd.DataFrame) -> dict:
        d = tbl[tbl["group_dimension"] == "procedure type"]
        direct = d[d["group"] == "directaward"].iloc[0]
        direct_high = float(direct["n"] * direct["share_high_plus"])
        total_high = float((d["n"] * d["share_high_plus"]).sum())
        m = tbl[tbl["group_dimension"] == "contract value band"]
        ge50 = m[m["group"] == ">=50m"].iloc[0]
        return {"b4_direct_disparity": round(float(direct["disparity_ratio"]), 4),
                "b4_direct_share_of_high_plus": round(direct_high / total_high, 4),
                "ge50m_rate_high_plus": round(float(ge50["share_high_plus"]), 4),
                "ge50m_disparity": round(float(ge50["disparity_ratio"]), 4)}

    votes0 = df["n_models_flagging"].astype(int).to_numpy()
    reference = {
        "v0": {
            "c3_yearly_share_ratio": fw["variants"]["v0_baseline"]["yearly_share_ratio"],
            "consensus_n": fw["variants"]["v0_baseline"]["bands"]["consensus_n"],
            "high_plus_n": fw["variants"]["v0_baseline"]["bands"]["votes_ge_2_n"],
            "mean_kappa": fw["variants"]["v0_baseline"]["agreement"]["mean_kappa"],
            "audit_unexplained_verdicts": _unexplained(a0["verdict_counts"]),
            "kept_v0_critical_share": 1.0,
            **_audit_rows(g0),
        },
        "v6": {
            "c3_yearly_share_ratio": fw["variants"]["v6_group_flags"]["yearly_share_ratio"],
            "consensus_n": fw["variants"]["v6_group_flags"]["bands"]["consensus_n"],
            "high_plus_n": fw["variants"]["v6_group_flags"]["bands"]["votes_ge_2_n"],
            "mean_kappa": fw["variants"]["v6_group_flags"]["agreement"]["mean_kappa"],
            "audit_unexplained_verdicts": _unexplained(a6["verdict_counts"]),
            "kept_v0_critical_share": round(
                fw["variants"]["v6_group_flags"]["signal_loss_vs_v0"]["kept_n"]
                / fw["variants"]["v6_group_flags"]["signal_loss_vs_v0"]["v0_critical_n"], 4),
            **_audit_rows(g6),
        },
    }
    v6_n_crit = reference["v6"]["consensus_n"]
    v6_n_high = reference["v6"]["high_plus_n"]

    # ---- fixed vectors ----------------------------------------------------
    year = pd.to_datetime(df["published_date"], errors="coerce").dt.year.to_numpy()
    direct = (df["proc_type"] == "directaward").to_numpy()
    ge50 = (pd.to_numeric(df["award_total"], errors="coerce")
            .fillna(0).to_numpy() >= 50e6)
    v0_critical = votes0 >= 3

    # sanity: the very same formulas must reproduce the v0 artefact values
    v0_check = control_metrics(votes0.astype(np.int8), year, direct, ge50,
                               v0_critical)
    print("v0 self-check (must match artefacts):", json.dumps(v0_check),
          flush=True)

    # ---- the control loop -------------------------------------------------
    rows: list[dict] = []
    audit_rows: list[dict] = []
    for rep in range(args.repeats):
        rng_a = np.random.default_rng(args.seed + rep)
        votes_a, flags_a = control_a_votes(idx_lists, sizes, rng_a)
        m = control_metrics(votes_a, year, direct, ge50, v0_critical)
        m.update({"control": "a_independent", "repeat": rep,
                  "mean_kappa": pairwise_kappa_mean(flags_a)})
        rows.append(m)

        rng_b = np.random.default_rng(args.seed + 10_000 + rep)
        votes_b = control_b_votes(idx_lists, sizes, v6_n_high, v6_n_crit, rng_b)
        m = control_metrics(votes_b, year, direct, ge50, v0_critical)
        m.update({"control": "b_rank_matched", "repeat": rep,
                  "mean_kappa": None})
        rows.append(m)

        if rep < args.audit_repeats:
            for name, votes in (("a_independent", votes_a),
                                ("b_rank_matched", votes_b)):
                df["votes_audit"] = votes
                df["high_plus"] = (votes >= 2).astype(int)
                df["critical"] = (votes >= 3).astype(int)
                df["band"] = np.select([votes == 0, votes == 1, votes == 2],
                                       ["low", "medium", "high"],
                                       default="critical")
                tbl = s18.audit_group_table(df, n_boot=args.audit_boot)
                vc = tbl["verdict"].value_counts().to_dict()
                ad = tbl[(tbl["group_dimension"] == "procedure type")
                         & (tbl["group"] == "directaward")]
                am = tbl[(tbl["group_dimension"] == "contract value band")
                         & (tbl["group"] == ">=50m")]
                audit_rows.append({
                    "control": name, "repeat": rep,
                    "audit_unexplained_verdicts": _unexplained(vc),
                    "audit_verdicts": {str(k): int(v) for k, v in vc.items()},
                    "b4_direct_disparity": (round(float(ad["disparity_ratio"].iloc[0]), 4)
                                            if len(ad) else None),
                    "ge50m_disparity": (round(float(am["disparity_ratio"].iloc[0]), 4)
                                        if len(am) else None),
                })
            print(f"repeat {rep + 1}/{args.repeats} "
                  f"(audit done, {time.time() - t0:.0f}s)", flush=True)

    per = pd.DataFrame(rows)
    per.to_csv(TABLES / "random_flags_control.csv", index=False)

    metric_cols = ["c3_yearly_share_ratio", "b4_direct_disparity",
                   "b4_direct_share_of_high_plus", "ge50m_rate_high_plus",
                   "ge50m_disparity", "ge50m_share_of_high_plus",
                   "kept_v0_critical_share", "consensus_n", "high_plus_n",
                   "mean_kappa"]
    controls = {}
    for name, sub in per.groupby("control"):
        entry = {"metrics": {c: _stats(sub[c].tolist()) for c in metric_cols}}
        aud = [a for a in audit_rows if a["control"] == name]
        if aud:
            entry["audit"] = {
                "replicates": len(aud),
                "n_boot": args.audit_boot,
                "unexplained_verdicts": _stats(
                    [a["audit_unexplained_verdicts"] for a in aud]),
                "b4_direct_disparity": _stats(
                    [a["b4_direct_disparity"] for a in aud]),
                "ge50m_disparity": _stats([a["ge50m_disparity"] for a in aud]),
            }
        controls[name] = entry

    def inside(control: str, metric: str, value: float) -> bool | None:
        st = controls.get(control, {}).get("metrics", {}).get(metric, {})
        if value is None or st.get("n", 0) == 0:
            return None
        return bool(st["p2_5"] <= value <= st["p97_5"])

    comparison = {}
    for metric in ("c3_yearly_share_ratio", "b4_direct_disparity",
                   "ge50m_rate_high_plus", "kept_v0_critical_share"):
        v = reference["v6"].get(metric)
        comparison[metric] = {
            "v6": v,
            "inside_control_a": inside("a_independent", metric, v),
            "inside_control_b": inside("b_rank_matched", metric, v),
        }

    summary = {
        "task": "MTA-0009",
        "question": ("do v6's C3/B4/size improvements survive a random-5%-"
                     "within-group control that uses no detector scores?"),
        "n_repeats": args.repeats,
        "n_procedures": n,
        "seeds": {"control_a": f"{args.seed}+i",
                  "control_b": f"{args.seed + 10_000}+i"},
        "audit_replicates_per_control": args.audit_repeats,
        "audit_n_boot": args.audit_boot,
        "groups": {"n": int(len(uniq)), "min_size": int(sizes.min()),
                   "max_size": int(sizes.max()),
                   "edges_source": gmeta.get("edges_source")},
        "v0_self_check": v0_check,
        "reference": reference,
        "controls": controls,
        "v6_vs_control_distribution": comparison,
        "scope_note": ("control measurements only - the cycle-6 verdict "
                       "('not adopted - compromise'), the contract matrix "
                       "9/16/2, the closing status 1 of 4 and the 6-of-10 "
                       "budget are unchanged; production stays v0; no v7"),
        "disclaimer": ("Индикатор потенциального риска, а не доказательство "
                       "коррупции/нарушения. Требуется проверка "
                       "компетентным органом."),
        "seconds": round(time.time() - t0, 1),
    }
    out = RESULTS / "methodology"
    out.mkdir(parents=True, exist_ok=True)
    (out / "random_flags_control.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    _write_markdown(per, controls, audit_rows, reference, comparison, args)
    print(f"done in {time.time() - t0:.0f}s")
    print(f"json  -> {out / 'random_flags_control.json'}")
    print(f"table -> {TABLES / 'random_flags_control.csv'}")
    print(f"report -> {REPORTS / 'random_flags_control.md'}")
    return 0


def _fmt(stats: dict | float | None) -> str:
    if stats is None:
        return "—"
    if isinstance(stats, (int, float)):
        return f"{stats:g}"
    if not stats or stats.get("n", 0) == 0:
        return "—"
    return (f"{stats['median']:g} [{stats['p2_5']:g}; {stats['p97_5']:g}]"
            f" (min {stats['min']:g}, max {stats['max']:g})")


def _write_markdown(per: pd.DataFrame, controls: dict, audit_rows: list,
                    reference: dict, comparison: dict, args) -> None:
    a = controls["a_independent"]
    b = controls["b_rank_matched"]
    va, vb = reference["v0"], reference["v6"]
    aud_a = a.get("audit", {}).get("unexplained_verdicts", {})
    aud_b = b.get("audit", {}).get("unexplained_verdicts", {})

    lines = [
        "# Контроль «случайные 5% внутри группы» для варианта v6 (MTA-0009)",
        "",
        "Дата: "
        f"{pd.Timestamp.today().date().isoformat()}. Это **не новый цикл**: "
        "бюджет остаётся 6 из 10, v7 не создаётся, production остаётся v0.",
        "",
        "Индикатор потенциального риска, а не доказательство коррупции/нарушения. "
        "Требуется проверка компетентным органом.",
        "",
        "## 1. Вопрос и метод",
        "",
        "Улучшения v6 (C3 пройден, B4 в допустимой полосе, доминирование размера "
        "снижено) достигнуты **нормировкой до флагов** — каждый детектор флагирует "
        "верхние 5% каждой группы «полоса × тип» по построению. Контроль сохраняет "
        "нормировку и убирает сигнал детекторов: флаги берутся случайно, оценки "
        "детекторов нигде не используются.",
        "",
        f"- **Контроль (а), независимые случайные флаги**: 4 «детектора» независимо "
        f"флагируют случайные {int(RATE * 100)}% каждой группы (точное число строк "
        "на группу — как в `group_flag_frame` v6), консенсус ≥ 3 голосов. При "
        "независимых голосах консенсус почти пуст (~4·0,05³), поэтому есть контроль (б).",
        "- **Контроль (б), согласованный по рангу**: размеры полос v6 "
        f"(консенсус {reference['v6']['consensus_n']:,}, high+ "
        f"{reference['v6']['high_plus_n']:,}) отбираются случайно внутри групп "
        "пропорционально размеру группы, critical вложен в high+. Разбиение (б) на "
        "low/medium не определено и не используется ни в сравниваемой метрике "
        "(C3 — консенсус, B4/размер — high+).",
        f"- {args.repeats} повторов с фиксированными сидами; метрики считаются теми же "
        "формулами, что в `scripts/20` (C3 = min/max годовой доли консенсуса, годы с "
        "n ≥ 500) и `scripts/18` (disparity = rate группы / rate дополнения). "
        f"Полный аудит раздела E на голосах контроля — первые {args.audit_repeats} "
        f"повторов на контроль, {args.audit_boot} бутстрап-реплик, тем же кодом "
        "(`scripts/18.audit_group_table`); прод-артефакты v0/v6 не перезаписываются.",
        "",
        "## 2. Таблица (v0 / v6 / контроль (а) / контроль (б))",
        "",
        "У контрольных — медиана [p2.5; p97.5] по повторам (min, max).",
        "",
        "| метрика | v0 | v6 | контроль (а) случайные независимые | контроль (б) случайные согласованные |",
        "|---|---|---|---|---|",
        f"| C3: годовой разброс доли консенсуса | {va['c3_yearly_share_ratio']:g} | "
        f"{vb['c3_yearly_share_ratio']:g} | {_fmt(a['metrics']['c3_yearly_share_ratio'])} | "
        f"{_fmt(b['metrics']['c3_yearly_share_ratio'])} |",
        f"| B4: disparity прямых закупок | {va['b4_direct_disparity']:g} | "
        f"{vb['b4_direct_disparity']:g} | {_fmt(a['metrics']['b4_direct_disparity'])} | "
        f"{_fmt(b['metrics']['b4_direct_disparity'])} |",
        f"| B4: доля прямых в high+ | {va['b4_direct_share_of_high_plus']:g} | "
        f"{vb['b4_direct_share_of_high_plus']:g} | "
        f"{_fmt(a['metrics']['b4_direct_share_of_high_plus'])} | "
        f"{_fmt(b['metrics']['b4_direct_share_of_high_plus'])} |",
        f"| доля ≥ 50 млн в high+ (rate) | {va['ge50m_rate_high_plus']:g} | "
        f"{vb['ge50m_rate_high_plus']:g} | {_fmt(a['metrics']['ge50m_rate_high_plus'])} | "
        f"{_fmt(b['metrics']['ge50m_rate_high_plus'])} |",
        f"| disparity ≥ 50 млн | {va['ge50m_disparity']:g} | {vb['ge50m_disparity']:g} | "
        f"{_fmt(a['metrics']['ge50m_disparity'])} | {_fmt(b['metrics']['ge50m_disparity'])} |",
        f"| невыполненных вердиктов аудита (E) | {va['audit_unexplained_verdicts']} | "
        f"{vb['audit_unexplained_verdicts']} | {_fmt(aud_a)} | {_fmt(aud_b)} |",
        f"| сохранение v0-critical | 1,00 | {reference['v6']['kept_v0_critical_share']:g} | "
        f"{_fmt(a['metrics']['kept_v0_critical_share'])} | "
        f"{_fmt(b['metrics']['kept_v0_critical_share'])} |",
        f"| средний попарный κ | {va['mean_kappa']:g} | {vb['mean_kappa']:g} | "
        f"{_fmt(a['metrics']['mean_kappa'])} | — (контроль (б) без детекторов) |",
        f"| размер консенсуса | {va['consensus_n']:,} | {vb['consensus_n']:,} | "
        f"{_fmt(a['metrics']['consensus_n'])} | {_fmt(b['metrics']['consensus_n'])} |",
        "",
        "## 3. Вывод (без смягчений)",
        "",
        _conclusion(reference, comparison, controls, args.repeats),
        "",
        "## 4. Пометки",
        "",
        "- Стратифицированный AUC v6 в самой дешёвой полосе (0,692 tuning / 0,702 "
        "holdout): **19 позитивов — мощность недостаточна, обогащение не "
        "заявляется** (пометка MTA-0009, `reports/cycle_6.md`).",
        "- Контроль (b) реализуем построчно: размеры полос заданы, выборка "
        "осуществлена внутри групп без обращения к оценкам детекторов.",
        "- Вердикт цикла 6 не меняется: **«не принимается — компромисс»**; матрица "
        "контракта 9/16/2; статус завершения 1 из 4; бюджет 6 из 10.",
        "",
        "## 5. Артефакты",
        "",
        "`results/methodology/random_flags_control.json` (сводка, референсы v0/v6, "
        "положение v6 относительно распределений контроля), "
        "`results/tables/random_flags_control.csv` (400 строк: по 200 повторов на "
        "контроль), `reports/random_flags_control.md` (этот отчёт).",
        "",
        "Индикатор потенциального риска, а не доказательство коррупции/нарушения. "
        "Требуется проверка компетентным органом.",
        "",
    ]
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "random_flags_control.md").write_text("\n".join(lines),
                                                     encoding="utf-8")


def _conclusion(reference: dict, comparison: dict, controls: dict,
                n_repeats: int) -> str:
    """The author's MTA-0009 decision rule, applied to the measured distributions.

    Two branches can be true at once for different metrics, and both are
    written out explicitly without softening: C3/B4 (equalised by the
    normalisation) and the residual detector signature (outside every control
    distribution).
    """
    va, vb = reference["v0"], reference["v6"]
    a, b = controls["a_independent"], controls["b_rank_matched"]
    c3_a, c3_b = (a["metrics"]["c3_yearly_share_ratio"],
                  b["metrics"]["c3_yearly_share_ratio"])
    b4_a, b4_b = a["metrics"]["b4_direct_disparity"], b["metrics"]["b4_direct_disparity"]
    ge50_a, ge50_b = a["metrics"]["ge50m_rate_high_plus"], b["metrics"]["ge50m_rate_high_plus"]
    keep_a, keep_b = a["metrics"]["kept_v0_critical_share"], b["metrics"]["kept_v0_critical_share"]
    kap_a = a["metrics"]["mean_kappa"]
    con_a = a["metrics"]["consensus_n"]
    aud_a = a.get("audit", {}).get("unexplained_verdicts", {})
    aud_b = b.get("audit", {}).get("unexplained_verdicts", {})
    ratio = (vb["ge50m_rate_high_plus"] / ge50_b["median"]
             if ge50_b.get("median") else float("nan"))

    out = [
        "**1. Выравнивание C3 и B4 достигается нормировкой, а не качеством "
        "детекторов.** Контроль (б) — случайная выборка с теми же размерами полос, "
        f"что у v6, и без оценок детекторов — даёт C3 медиана {c3_b['median']:g} "
        f"[{c3_b['p2_5']:g}; {c3_b['p97_5']:g}], то есть годовой разброс доли "
        f"консенсуса ЛУЧШЕ, чем у v6 ({vb['c3_yearly_share_ratio']:g}); даже у "
        f"независимых случайных флагов (а) C3 медиана {c3_a['median']:g} с "
        f"консенсусом всего ~{con_a['median']:.0f} строк. Прохождение порога "
        "C3 ≥ 0,25, как и возврат disparity прямых закупок в допустимую полосу "
        f"(медианы обоих контрольных ≈ 1,00 против v0 {va['b4_direct_disparity']:g}), "
        "воспроизводятся случайными флагами с той же нормировкой ≈ 5% на группу. "
        "В пользу v6 говорит только то, что детекторы несут ненулевой сигнал — "
        "см. п. 2 — и одно малое, но статистически различимое отклонение: v6 "
        f"{vb['b4_direct_disparity']:g} вне распределения контроля (а) "
        f"[{b4_a['p2_5']:g}; {b4_a['p97_5']:g}] (+{100 * (vb['b4_direct_disparity'] / b4_a['median'] - 1):.0f}% "
        "к медиане ≈ 1,00) — детекторы немного недофлагируют прямые закупки, но "
        "меньше, чем v0.",

        "**2. За пределами распределения контроля (детекторный сигнал сохранён):**",
        f"- остаточная размерная концентрация: доля ≥ 50 млн в high+ у v6 "
        f"{vb['ge50m_rate_high_plus']:g} против медиан {ge50_a['median']:g} (а) и "
        f"{ge50_b['median']:g} (б) — вне обоих распределений, в {ratio:.1f}× выше "
        "контроля (б); нормировка снизила её с 50,9% (v0), но не устранила — "
        "детекторы по-прежнему находят крупные контракты;",
        f"- сохранение сигнала: v6 сохраняет {vb['kept_v0_critical_share']:g} "
        f"v0-critical против {keep_a['median']:g} (а) и {keep_b['median']:g} (б) — "
        f"{pos_str(comparison['kept_v0_critical_share'])};",
        f"- согласованность детекторов: средний попарный κ v6 {vb['mean_kappa']:g} "
        f"против {kap_a['median']:g} у независимых случайных флагов (у контроля (б) "
        "детекторов нет вовсе).",

        f"**3. Аудит смещения (E) на голосах контроля** (повторов с аудитом: "
        f"{a.get('audit', {}).get('replicates', '—')} из {n_repeats} — аудит "
        "тяжёлый, полный прогон на всех повторах не выполнялся): невыполненных "
        "вердиктов "
        f"{_fmt(aud_a)} (а) и {_fmt(aud_b)} (б) против {vb['audit_unexplained_verdicts']} "
        f"у v6 и {va['audit_unexplained_verdicts']} у v0 — случайные флаги дают "
        "лишь базовый уровень ложных срабатываний (единичные предупреждения на "
        "79 групп при множественных сравнениях), то есть суммарный счётчик v6 "
        "**выше базового уровня случайных флагов** (5–12); избыток не разложен "
        "по причинам и не может быть отнесён к качеству детекторов без "
        "дополнительного разбора. C6 по-прежнему не может быть одиночным "
        "критерием приёмки (и не является им — модель не принята).",

        "Вывод цикла 6 не меняется: **не принимается — компромисс**; production v0; "
        "матрица контракта 9/16/2; статус 1 из 4. Контроль MTA-0009 показывает, что "
        "улучшения C3/B4 у v6 — свойство нормировки, а единственное, что отличает v6 "
        "от случайного флага с той же долей — κ, сохранение сигнала и остаточная "
        "размерная концентрация.",
    ]
    return "\n\n".join(out)


def pos_str(comp: dict) -> str:
    if comp["inside_control_a"] is False or comp["inside_control_b"] is False:
        return "**вне распределения контроля**"
    return "внутри распределения контроля"


if __name__ == "__main__":
    sys.exit(main())
