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
import pytest

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
                                 "v4_datafix", "v4b_datafix_keep_duplicate",
                                 "v5_group_percentile", "v6_group_flags"}
    # only the duplicate column separates v1 from v0
    assert s20.VARIANTS["v1_merge_duplicate"]["drop"] == ["winner_share_of_buyer_awards"]
    # v4 = the v1 duplicate drop plus the measured data-artifact fixes
    assert s20.VARIANTS["v4_datafix"]["drop"] == ["winner_share_of_buyer_awards"]
    assert s20.VARIANTS["v4_datafix"]["datafix"] is True
    # v4b = the same fixes with the duplicate kept (isolates the data-fix effect)
    assert s20.VARIANTS["v4b_datafix_keep_duplicate"]["drop"] == []
    assert s20.VARIANTS["v4b_datafix_keep_duplicate"]["datafix"] is True
    # v5 changes ONLY the ranking (within-group percentile); features/votes
    # stay exactly v0's - one change per cycle
    assert s20.VARIANTS["v5_group_percentile"]["drop"] == []
    assert s20.VARIANTS["v5_group_percentile"]["rank"] == "group_pct_max"
    assert "datafix" not in s20.VARIANTS["v5_group_percentile"]
    # v6: normalisation BEFORE the flags - within-group top-5% flags, audited
    # on its own votes (bias_audit_v6.json; production audit untouched)
    assert s20.VARIANTS["v6_group_flags"]["drop"] == []
    assert s20.VARIANTS["v6_group_flags"]["rank"] == "group_pct_max"
    assert s20.VARIANTS["v6_group_flags"]["group_flags"] is True
    assert s20.VARIANTS["v6_group_flags"]["audit"] == "bias_audit_v6.json"
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


def test_group_labels_are_deterministic():
    """v5: same frame in -> same band edges, same labels, same counters."""
    s20 = _load_script("20_cycle_framework.py")
    rng = np.random.default_rng(3)
    n = 1000
    df = pd.DataFrame({
        "log_award_value": rng.integers(1_000, 40_000_000,
                                        size=n).astype(float),
        "procurement_method_details": rng.choice(
            ["directaward", "opentender", "microvalue"], size=n),
    })
    labels_a, meta_a = s20.build_group_labels(df)
    labels_b, meta_b = s20.build_group_labels(df)
    assert meta_a["band_edges"] == meta_b["band_edges"]
    assert meta_a["group_sizes"] == meta_b["group_sizes"]
    assert meta_a["groups_merged_small"] == meta_b["groups_merged_small"]
    np.testing.assert_array_equal(labels_a, labels_b)
    # 5 quantile bands -> 6 edges (data-derived, no randomness anywhere)
    assert len(meta_a["band_edges"]) == 6
    assert meta_a["n_groups"] == len(meta_a["group_sizes"])
    assert sum(meta_a["group_sizes"].values()) == n
    # every final group either meets the floor or is counted as left small
    small = [g for g, c in meta_a["group_sizes"].items()
             if c < s20.GROUP_MIN_N]
    assert len(small) == meta_a["groups_left_small"]


def test_group_percentile_is_uniform_within_group():
    """v5 statistic: inside a group percentiles are exactly the 1/n..n/n grid."""
    s20 = _load_script("20_cycle_framework.py")
    scores = pd.DataFrame({"mad": [1.0, 5.0, 3.0, 4.0, 2.0, 10.0],
                           "if": [2.0, 1.0, 4.0, 3.0, 5.0, 9.0]})
    groups = np.array(["g1", "g1", "g1", "g2", "g2", "g2"])
    out = s20.group_percentile_max(scores, groups)
    # g1: mad pct = (1/3, 3/3, 2/3), if pct = (2/3, 1/3, 3/3) -> max row-wise
    np.testing.assert_allclose(out[:3], [2 / 3, 1.0, 1.0])
    # g2: mad pct = (2/3, 1/3, 3/3), if pct = (1/3, 2/3, 3/3)
    np.testing.assert_allclose(out[3:], [2 / 3, 2 / 3, 1.0])
    # uniformity by construction: within a group the per-detector percentiles
    # are the equidistant grid 1/n .. n/n (rank-based)
    pct_g1 = scores.iloc[:3].rank(pct=True)
    for col in ("mad", "if"):
        np.testing.assert_allclose(np.sort(pct_g1[col].to_numpy()),
                                   np.arange(1, 4) / 3)


def test_small_groups_merge_with_counters():
    """v5: groups under the floor merge - same type first, fallback recorded."""
    s20 = _load_script("20_cycle_framework.py")
    # single band (all values equal) -> no same-type candidate, the thin
    # group must fall back to the largest group of the same band
    df = pd.DataFrame({
        "log_award_value": [10.0] * 50 + [10.0] * 550,
        "procurement_method_details": ["tiny"] * 50 + ["big"] * 550,
    })
    labels, meta = s20.build_group_labels(df, n_bands=2, min_n=100)
    assert meta["groups_merged_fallback"] == 1
    assert meta["group_sizes"] == {"big|b0": 600}
    assert set(labels) == {"big|b0"}
    # same-type path: type "t" spans two bands, the thin band moves into the
    # nearest band of the same type
    df2 = pd.DataFrame({
        "log_award_value": [1.0] * 50 + [2.0] * 300 + [3.0] * 300,
        "procurement_method_details": ["t"] * 650,
    })
    labels2, meta2 = s20.build_group_labels(df2, n_bands=2, min_n=100)
    assert meta2["groups_merged_small"] == 1
    assert meta2["groups_merged_fallback"] == 0
    assert meta2["group_sizes"] == {"t|b1": 650}
    assert set(labels2) == {"t|b1"}


def test_v5_block_in_cycle_artefact_if_present():
    """When the cycle artefact carries v5 its group/size metadata must exist."""
    s20 = _load_script("20_cycle_framework.py")
    path = s20.RESULTS / "methodology" / "cycle_framework.json"
    if not path.exists():
        pytest.skip("cycle artefact not present")
    payload = json.loads(path.read_text(encoding="utf-8"))
    block = (payload.get("variants") or {}).get("v5_group_percentile")
    if block is None:
        pytest.skip("v5 not part of the measured artefact yet")
    for key in ("group_percentile", "size_composition", "external",
                "agreement", "stability", "drift", "stop_criteria_passed"):
        assert key in block
    gp = block["group_percentile"]
    assert gp["n_groups"] >= 1
    assert gp["groups_merged_small"] >= 0
    assert len(gp["band_edges"]) >= 2
    sc = block["size_composition"]
    for slice_name in ("tuning", "all"):
        assert 0.0 <= sc[slice_name]["top200_share_ge_50m"] <= 1.0
        assert 0.0 <= sc[slice_name]["corpus_share_ge_50m"] <= 1.0


def test_group_labels_accept_saved_edges():
    """MTA-0008: passing the SAVED band edges reproduces the cycle's groups."""
    s20 = _load_script("20_cycle_framework.py")
    df = pd.DataFrame({"log_award_value": [1.0, 2.0, 3.0] * 100,
                       "procurement_method_details": ["t"] * 300})
    labels_a, meta_a = s20.build_group_labels(df, n_bands=2, min_n=10)
    labels_b, meta_b = s20.build_group_labels(df, edges=meta_a["band_edges"],
                                              min_n=10)
    np.testing.assert_array_equal(labels_a, labels_b)
    assert meta_a["edges_source"].startswith("quantiles")
    assert meta_b["edges_source"].startswith("provided")
    assert meta_a["band_edges"] == meta_b["band_edges"]


def test_group_flags_are_top5_within_group():
    """v6: the flag is the top 5% INSIDE the group - equal share by construction."""
    s20 = _load_script("20_cycle_framework.py")
    n = 200
    rng = np.random.default_rng(7)
    scores = pd.DataFrame({"mad": rng.permutation(np.arange(1, n + 1)).astype(float),
                           "if": rng.permutation(np.arange(1, n + 1)).astype(float)})
    groups = np.array(["g1"] * 100 + ["g2"] * 100)
    ff = s20.group_flag_frame(scores, groups, 0.05)
    # no ties -> exactly the top 5 rows of every group per detector
    for col in ("mad", "if"):
        for g in ("g1", "g2"):
            assert int(ff.loc[groups == g, col].sum()) == 5
    # the flag share is identical across groups BY CONSTRUCTION - the side
    # effect the author asked to record: a whole-group anomaly is invisible
    shares = ff.groupby(groups).mean()
    assert (shares["mad"] == 0.05).all()
    assert (shares["if"] == 0.05).all()


def _blk(t_auc, t_ci, h_auc, h_ci, kappa=0.25):
    """Minimal variant block for completion_status (scripts/22)."""
    return {"agreement": {"mean_kappa": kappa},
            "external": {"tuning_2018_2021": {"roc_auc": t_auc,
                                              "roc_auc_ci": list(t_ci)},
                         "holdout_2022_2024": {"roc_auc": h_auc,
                                               "roc_auc_ci": list(h_ci)}}}


def test_completion_status_stably_negative_not_credited():
    """MTA-0008: a stably negative association fails condition (2).

    No sign flip (both AUCs below 0.5) but a CI entirely below 0.5 is a
    significant anti-association - it is NOT credited as period stability.
    """
    s22 = _load_script("22_cycle_dynamics.py")
    key = "устойчивость и знак внешней связи по периодам (ДИ не ниже 0,5)"
    # healthy: positive association, overlapping CIs, no flip -> passes
    ok = s22.completion_status(
        {"a": _blk(0.55, [0.51, 0.59], 0.56, [0.52, 0.60])})
    assert ok["checks"][key] is True
    assert ok["anti_associated"] == {}
    # v5-like: no flip (0.43 / 0.42) but both CIs lie below 0.5 -> fails
    v5 = s22.completion_status(
        {"a": _blk(0.43, [0.387, 0.471], 0.4248, [0.396, 0.452])})
    assert v5["checks"][key] is False
    assert v5["anti_associated"] == {"a": ["tuning_2018_2021",
                                           "holdout_2022_2024"]}
    assert v5["sign_flips"] == []
    # a classical sign flip still fails (and its negative tuning half counts)
    fl = s22.completion_status(
        {"a": _blk(0.43, [0.39, 0.47], 0.56, [0.52, 0.60])})
    assert fl["checks"][key] is False
    assert fl["sign_flips"] == ["a"]
    assert "tuning_2018_2021" in fl["anti_associated"]["a"]


def test_v6_block_in_cycle_artefact_if_present():
    """When the cycle artefact carries v6 its audit/side-effect blocks must exist."""
    s20 = _load_script("20_cycle_framework.py")
    path = s20.RESULTS / "methodology" / "cycle_framework.json"
    if not path.exists():
        pytest.skip("cycle artefact not present")
    payload = json.loads(path.read_text(encoding="utf-8"))
    block = (payload.get("variants") or {}).get("v6_group_flags")
    if block is None:
        pytest.skip("v6 not part of the measured artefact yet")
    for key in ("group_vote_stats", "b4_directaward", "auc_by_cost_band",
                "signal_loss_vs_v0", "group_percentile", "external",
                "stability", "stop_criteria_passed"):
        assert key in block
    gv = block["group_vote_stats"]
    # the corpus share is a weighted average of the per-group shares
    assert (gv["min_group"]["share"] <= gv["corpus_share_consensus"]
            <= gv["max_group"]["share"])
    # direct procurement is the majority of the corpus (51.5%)
    assert block["b4_directaward"]["corpus_share"] > 0.5
    sl = block["signal_loss_vs_v0"]
    assert sl["kept_n"] + sl["lost_n"] <= sl["v0_critical_n"]
