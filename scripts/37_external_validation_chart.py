#!/usr/bin/env python3
"""Step 37 - reproducible charts for the external-validation deliverables.

Reads the artefacts written by ``scripts/35`` (never re-derives or fabricates
values) and renders two deterministic figures into ``docs/figures/``:

1. ``external_validation_baselines.png``      - per label, ROC-AUC point +
   cluster-bootstrap 95% CI for every pre-registered rule (chance line 0.5);
2. ``external_validation_paired_vs_v0.png``   - per label, the paired AUC
   difference vs the production score with its CI and the pre-registered
   ``ci_excludes_0 / ci_includes_0`` verdict against the zero line.

The charts visualise measured numbers only: no smoothing, no rounding, no
value is invented, and the figure captions state the bootstrap unit.

Usage::

    .venv/bin/python scripts/37_external_validation_chart.py \
        [--baselines ...] [--framework ...] [--outdir docs/figures]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BASELINES_CSV = ROOT / "results/tables/external_baselines.csv"
FRAMEWORK_JSON = ROOT / "results/methodology/external_validation_framework.json"
FIGURES_DIR = ROOT / "docs/figures"

RULE_LABELS = {
    "v0_max_score": "v0 (production)",
    "amount": "amount (exposure)",
    "n_bidders_fewer": "fewer bidders (pre-registered)",
    "value_within_cpv": "value vs CPV",
    "single_bidder": "single bidder",
    "votes": "votes >= 3",
    "random": "random",
    "module_hits": "module hits (experimental)",
}
LABEL_TITLES = {
    "aap": "AAP supplier-interdiction label",
    "ansc": "ANSC complaints label",
}
HIGHLIGHT = {"v0_max_score": "#d95f02", "module_hits": "#1f78b4"}


def _plot_auc_panel(ax, frame, label: str, meta: dict) -> None:
    """One label's ROC-AUC forest (points + cluster-bootstrap CIs)."""
    sub = frame[
        (frame["metric"] == "roc_auc") & (frame["label"] == label)
    ].copy()
    sub = sub.sort_values("point", ascending=True)
    y = range(len(sub))
    ax.axvline(0.5, color="grey", lw=1, ls="--", zorder=1)
    for yi, (_, row) in zip(y, sub.iterrows()):
        color = HIGHLIGHT.get(row["rule"], "black")
        lw = 2.5 if row["rule"] in HIGHLIGHT else 1.5
        ax.errorbar(
            row["point"], yi,
            xerr=[[row["point"] - row["ci_lo"]], [row["ci_hi"] - row["point"]]],
            fmt="o", color=color, lw=lw, capsize=3, zorder=3,
        )
    ax.set_yticks(list(y))
    ax.set_yticklabels(
        [RULE_LABELS.get(r, r) for r in sub["rule"]],
        fontsize=9,
    )
    for tick, rule in zip(ax.get_yticklabels(), sub["rule"]):
        if rule in HIGHLIGHT:
            tick.set_color(HIGHLIGHT[rule])
            tick.set_fontweight("bold")
    title = LABEL_TITLES.get(label, label)
    if meta:
        cluster = str(meta.get("cluster_unit", "?")).split(" (")[0]
        title += (
            f"\n{meta.get('n_rows', '?')} procedures, "
            f"{meta.get('positives', '?')} positives, clustered by {cluster}"
        )
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("ROC-AUC (point [cluster-bootstrap 95% CI])")
    lo = float(sub["ci_lo"].min())
    hi = float(sub["ci_hi"].max())
    span = max(hi - lo, 0.1)
    ax.set_xlim(lo - 0.08 * span, hi + 0.08 * span)
    ax.grid(axis="x", alpha=0.3)


def _plot_paired_panel(ax, framework: dict, label: str) -> None:
    """One label's paired AUC difference vs v0 against the zero line."""
    paired = framework["paired_vs_v0"][label]
    rows = sorted(
        ((rule, v["roc_auc"]) for rule, v in paired.items()
         if isinstance(v.get("roc_auc"), dict) and v["roc_auc"].get("ci")),
        key=lambda kv: kv[1]["diff"],
    )
    for yi, (rule, res) in enumerate(rows):
        excludes = res["verdict"] == "ci_excludes_0"
        color = "#d95f02" if rule == "module_hits" else "black"
        ax.errorbar(
            res["diff"], yi,
            xerr=[[res["diff"] - res["ci"][0]], [res["ci"][1] - res["diff"]]],
            fmt="o", color=color, lw=2 if excludes else 1.5, capsize=3,
            zorder=3, alpha=1.0 if excludes else 0.65,
        )
        verdict = "excludes 0" if excludes else "includes 0"
        ax.annotate(
            verdict, (res["ci"][1], yi), xytext=(6, 0),
            textcoords="offset points", va="center", fontsize=8,
            color="#b2182b" if excludes else "grey",
            fontweight="bold" if excludes else "normal",
        )
    ax.axvline(0.0, color="grey", lw=1, ls="--", zorder=1)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([RULE_LABELS.get(r, r) for r, _ in rows], fontsize=9)
    ax.set_title(
        f"{LABEL_TITLES.get(label, label)}: paired ROC-AUC difference vs v0",
        fontsize=10,
    )
    ax.set_xlabel("Δ ROC-AUC (rule − v0), cluster-bootstrap 95% CI")
    ax.grid(axis="x", alpha=0.3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baselines", type=Path, default=BASELINES_CSV)
    parser.add_argument("--framework", type=Path, default=FRAMEWORK_JSON)
    parser.add_argument("--outdir", type=Path, default=FIGURES_DIR)
    args = parser.parse_args(argv)

    for path in (args.baselines, args.framework):
        if not path.exists():
            print(f"ERROR: artefact missing: {path} "
                  f"(regenerate with scripts/35_external_validation.py)",
                  file=sys.stderr)
            return 1

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    frame = pd.read_csv(args.baselines)
    framework = json.loads(args.framework.read_text(encoding="utf-8"))
    labels = [l for l in ("aap", "ansc")
              if (frame["label"] == l).any()]
    if not labels:
        print("ERROR: no known labels in the baselines table", file=sys.stderr)
        return 1

    cluster_units = framework.get("cluster_units") or {}
    args.outdir.mkdir(parents=True, exist_ok=True)

    # --- figure 1: ROC-AUC forest ------------------------------------------
    fig, axes = plt.subplots(1, len(labels), figsize=(6.4 * len(labels), 5.2))
    axes = [axes] if len(labels) == 1 else list(axes)
    for ax, label in zip(axes, labels):
        meta = dict(framework["labels"].get(label) or {})
        meta["cluster_unit"] = cluster_units.get(label, "?")
        _plot_auc_panel(ax, frame, label, meta)
    fig.suptitle(
        "External validation: pre-registered rules, cluster-bootstrap CIs "
        "(scripts/35, B=1000, seed 42)", fontsize=11,
    )
    fig.text(
        0.5, 0.005,
        "Measurement only: anomaly indicators are not evidence of corruption; "
        "labels are weak proxies (sanction list / complaint filed).",
        ha="center", fontsize=8, style="italic", color="grey",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    auc_path = args.outdir / "external_validation_baselines.png"
    fig.savefig(auc_path, dpi=150)
    plt.close(fig)

    # --- figure 2: paired differences vs v0 --------------------------------
    fig, axes = plt.subplots(1, len(labels), figsize=(6.8 * len(labels), 5.2))
    axes = [axes] if len(labels) == 1 else list(axes)
    for ax, label in zip(axes, labels):
        _plot_paired_panel(ax, framework, label)
    fig.suptitle(
        "Paired comparison vs the production score: adoption requires the CI "
        "to exclude 0 in the rule's favour", fontsize=11,
    )
    fig.tight_layout(rect=(0, 0.01, 1, 0.95))
    paired_path = args.outdir / "external_validation_paired_vs_v0.png"
    fig.savefig(paired_path, dpi=150)
    plt.close(fig)

    print(f"[37] wrote {auc_path}")
    print(f"[37] wrote {paired_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
