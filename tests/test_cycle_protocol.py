"""Regression tests for the iterative-cycle tooling (scripts 20-21).

Covers the two logic pieces that silently produced wrong numbers during the
first runs of the circularity check:

1. ``behavioural_from_pairs`` must reproduce ``src/mtender/features.py``
   exactly - the randomised control (shuffled buyer-supplier links) trusts it
   to recompute the four behavioural features from arbitrary pairs;
2. a constant feature must get ANOVA F = 0.0 rather than NaN, otherwise every
   downstream rank, Spearman correlation and verdict becomes garbage
   (``accelerated_like`` is all zeros in the real corpus).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_behavioural_from_pairs_matches_features_module():
    s21 = _load_script("21_circularity_check.py")

    buyers = ["b1", "b1", "b1", "b2", "b2", "b3"]
    winners = ["w1", "w1", "w2", "w1", "w2", "w2"]
    df = pd.DataFrame({"buyer_id": buyers, "winner_id": winners},
                      index=pd.RangeIndex(6))
    out = s21.behavioural_from_pairs(df["buyer_id"].to_numpy(),
                                     df["winner_id"].to_numpy(), df.index)

    # reference: the production builder on the same pairs
    from src.mtender import features as F
    built = F.add_behavioural_features(df.copy())
    for col in ("buyer_supplier_repeat_share", "winner_share_of_buyer_awards",
                "supplier_award_count_log", "supplier_win_concentration"):
        np.testing.assert_allclose(
            out[col].to_numpy(), built[col].to_numpy(), rtol=1e-12,
            err_msg=f"{col} diverges from the production feature builder")


def test_behavioural_shuffle_preserves_marginals():
    s21 = _load_script("21_circularity_check.py")
    rng = np.random.default_rng(7)
    n = 500
    buyers = rng.choice([f"b{i}" for i in range(20)], size=n)
    winners = rng.choice([f"w{i}" for i in range(15)], size=n)
    index = pd.RangeIndex(n)

    shuffled = rng.permutation(winners)
    orig = s21.behavioural_from_pairs(buyers, winners, index)
    shuf = s21.behavioural_from_pairs(buyers, shuffled, index)

    # winner award counts (marginal) survive the shuffle exactly
    np.testing.assert_allclose(orig["supplier_award_count_log"].sort_values().to_numpy(),
                               shuf["supplier_award_count_log"].sort_values().to_numpy())
    # pair-derived shares must change
    assert not np.allclose(orig["buyer_supplier_repeat_share"],
                           shuf["buyer_supplier_repeat_share"])


def test_anova_constant_feature_is_zero_not_nan():
    s21 = _load_script("21_circularity_check.py")
    rng = np.random.default_rng(3)
    X = pd.DataFrame({
        "constant": np.zeros(100),
        # a real separating signal: shifted means with within-group noise
        "signal": np.concatenate([rng.normal(2.0, 0.5, 10),
                                  rng.normal(0.0, 0.5, 90)]),
    })
    target = np.array([1] * 10 + [0] * 90)
    f_vals = s21.anova_f_per_feature(X, target)
    assert f_vals["constant"] == 0.0, "constant feature must be F=0, not NaN"
    assert np.isfinite(f_vals["signal"]) and f_vals["signal"] > 0


def test_anova_perfect_separation_is_not_zeroed():
    """Undefined F from perfect separation must stay maximal, not become 0."""
    s21 = _load_script("21_circularity_check.py")
    X = pd.DataFrame({"perfect": np.array([1.0] * 10 + [0.0] * 90)})
    target = np.array([1] * 10 + [0] * 90)
    f_vals = s21.anova_f_per_feature(X, target)
    assert f_vals["perfect"] > 1e10


def test_variant_prefix_resolution():
    """'v0' must resolve to 'v0_baseline'; an unknown name must be a hard error."""
    s20 = _load_script("20_cycle_framework.py")
    assert "v0_baseline" in s20.VARIANTS
    assert set(s20.VARIANTS) == {"v0_baseline", "v1_merge_duplicate",
                                 "v2_mean_rank", "v3_drop_behavioural",
                                 "v4_datafix", "v4b_datafix_keep_duplicate"}
    # only the duplicate column separates v1 from v0
    assert s20.VARIANTS["v1_merge_duplicate"]["drop"] == ["winner_share_of_buyer_awards"]
    # v4 = the v1 duplicate drop plus the measured data-artifact fixes
    assert s20.VARIANTS["v4_datafix"]["drop"] == ["winner_share_of_buyer_awards"]
    assert s20.VARIANTS["v4_datafix"]["datafix"] is True
    # v4b = the same fixes with the duplicate kept (isolates the data-fix effect)
    assert s20.VARIANTS["v4b_datafix_keep_duplicate"]["drop"] == []
    assert s20.VARIANTS["v4b_datafix_keep_duplicate"]["datafix"] is True
    # the constant feature is part of the production feature set (documents why
    # the ANOVA guard above matters)
    from src.mtender.features import FEATURE_COLUMNS
    assert "accelerated_like" in FEATURE_COLUMNS


def test_apply_datafix_merges_phantoms_and_caps():
    """v4: whitespace/case phantoms merge; caps and locality cleanup apply."""
    s20 = _load_script("20_cycle_framework.py")
    df = pd.DataFrame({
        "ocid": ["o1", "o2", "o3", "o4"],
        "buyer_id": ["MD-IDNO-1", "MD-IDNO-1", "MD-IDNO-2", None],
        "winner_id": ["MD-IDNO-9 ", "md-idno-9", "MD-IDNO-8", None],
        "buyer_locality": ["locality", "mun.Chişinău", " LOCALITY ", "or.Orhei"],
        "log_award_value": [8.0, 9.0, 10.0, 30.0],
        "log_award_total": [8.5, 9.5, 10.5, 31.0],
    })
    out = s20.apply_datafix(df, caps={"log_award_value": 12.0,
                                      "log_award_total": 13.0})
    # one supplier after the merge: buyer 1 repeated the same (split) winner
    assert out.loc[0, "buyer_supplier_repeat_share"] == 1.0
    assert out.loc[1, "buyer_supplier_repeat_share"] == 1.0
    # explicit ceilings applied
    assert out["log_award_value"].max() <= 12.0
    assert out["log_award_total"].max() <= 13.0
    # placeholder localities cleaned, real ones untouched
    assert pd.isna(out.loc[0, "buyer_locality"])
    assert pd.isna(out.loc[2, "buyer_locality"])
    assert out.loc[1, "buyer_locality"] == "mun.Chişinău"
    # the byte-identical duplicate stays a duplicate after the recompute
    pd.testing.assert_series_equal(out["winner_share_of_buyer_awards"],
                                   out["buyer_supplier_repeat_share"],
                                   check_names=False)


def test_stop_criteria_include_bias_audit_c6():
    """C6 (section E) is a documented threshold evaluated from the audit."""
    s20 = _load_script("20_cycle_framework.py")
    assert "max_unexplained_bias_deviations" in s20.STOP_CRITERIA

    payload = json.loads(
        (s20.RESULTS / "methodology" / "bias_audit.json").read_text(encoding="utf-8"))
    counts = payload["verdict_counts"]
    unexplained = counts.get("нарушение", 0) + counts.get("предупреждение", 0)
    ok, detail = s20.evaluate_c6_bias_audit()
    assert ok == (unexplained <= s20.STOP_CRITERIA["max_unexplained_bias_deviations"])
    assert "нарушение" in detail and "предупреждение" in detail


def test_c6_fails_without_audit_artefact(tmp_path):
    """A missing section-E audit must fail C6, never pass it silently."""
    s20 = _load_script("20_cycle_framework.py")
    ok, detail = s20.evaluate_c6_bias_audit(results_dir=tmp_path)
    assert ok is False
    assert "18_bias_audit" in detail


def test_stop_criteria_include_rag_c7():
    """C7 (RAG layer) is a documented threshold evaluated from rag_eval."""
    s20 = _load_script("20_cycle_framework.py")
    assert "min_rag_recall_at_3" in s20.STOP_CRITERIA
    assert "max_rag_hallucination_rate" in s20.STOP_CRITERIA

    payload = json.loads(
        (s20.RESULTS / "methodology" / "rag_eval.json").read_text(encoding="utf-8"))
    ok, detail = s20.evaluate_c7_rag()
    expected = (payload["hallucination"]["rate"]
                <= s20.STOP_CRITERIA["max_rag_hallucination_rate"]
                and payload["retrieval"]["recall_at_3"]
                >= s20.STOP_CRITERIA["min_rag_recall_at_3"])
    assert ok == expected
    assert "recall@3" in detail and "hallucination" in detail


def test_c7_fails_without_rag_artefact(tmp_path):
    """A missing rag_eval artefact must fail C7, never pass it silently."""
    s20 = _load_script("20_cycle_framework.py")
    ok, detail = s20.evaluate_c7_rag(results_dir=tmp_path)
    assert ok is False
    assert "26_rag_eval" in detail


def test_c7_fails_on_hallucinated_references(tmp_path):
    """Any hallucinated citation fails C7 - the criterion is a hard zero."""
    s20 = _load_script("20_cycle_framework.py")
    (tmp_path / "methodology").mkdir()
    payload = {"retrieval": {"recall_at_3": 1.0}, "hallucination": {"rate": 0.01}}
    (tmp_path / "methodology" / "rag_eval.json").write_text(
        json.dumps(payload), encoding="utf-8")
    ok, detail = s20.evaluate_c7_rag(results_dir=tmp_path)
    assert ok is False
    assert "hallucination_rate=0.01" in detail


def test_c7_fails_on_low_recall(tmp_path):
    """Recall@3 below the agent-proposed threshold fails C7."""
    s20 = _load_script("20_cycle_framework.py")
    (tmp_path / "methodology").mkdir()
    payload = {"retrieval": {"recall_at_3": 0.3}, "hallucination": {"rate": 0.0}}
    (tmp_path / "methodology" / "rag_eval.json").write_text(
        json.dumps(payload), encoding="utf-8")
    ok, detail = s20.evaluate_c7_rag(results_dir=tmp_path)
    assert ok is False
    assert "recall@3=0.3" in detail
