"""Unit tests for scripts/32_noise_sensitivity.py (synthetic data only).

Covers: perturbation determinism and invariants, dependency-consistent
re-derivation of features, metric formulas (Spearman/Jaccard/top-K/
transitions/KS), metric bounds on synthetic reference vs perturbed frames,
the frozen-model guard rails, and standalone execution of the script.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "32_noise_sensitivity.py"
    spec = importlib.util.spec_from_file_location("noise32", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


ns = _load_module()


def _synthetic_sources(n: int = 400, seed: int = 0) -> pd.DataFrame:
    """A small frame with every source column the perturbations may touch."""
    rng = np.random.default_rng(seed)
    award = rng.uniform(1e3, 5e6, n).round(2)
    return pd.DataFrame(
        {
            "ocid": [f"ocds-md-{i}" for i in range(n)],
            "award_value": award,
            "award_total": award * rng.choice([1.0, 1.5], n),
            "estimated_value": award * rng.uniform(0.8, 1.3, n),
            "cpv_primary": rng.choice(["33100000-1", "45000000-9", "71000000-8"], n),
            "n_awards_with_value": rng.integers(1, 4, n),
            "n_bidders": rng.integers(0, 8, n),
            "n_suppliers": rng.integers(0, 4, n),
            "tender_start": pd.date_range("2020-01-01", periods=n, freq="D")
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tender_end": (pd.date_range("2020-01-01", periods=n, freq="D")
                           + pd.to_timedelta(rng.integers(1, 120, n), unit="D"))
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_amendments": rng.integers(0, 3, n),
            "status": rng.choice(["complete", "active", "cancelled"], n),
            "procurement_method_details": rng.choice(
                ["open", "direct", "restricted"], n),
            "buyer_identifier": rng.integers(100, 200, n),
        }
    )


# -- metric primitives -------------------------------------------------------


def test_band_of_maps_votes_to_production_bands():
    got = ns.band_of(np.array([0, 1, 2, 3, 4, 9]))
    assert got.tolist() == [0, 1, 2, 3, 3, 3]


def test_spearman_perfect_and_inverse_and_ties():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    assert ns.spearman(a, a) == pytest.approx(1.0)
    assert ns.spearman(a, -a) == pytest.approx(-1.0)
    ties = np.array([1.0, 1.0, 2.0, 3.0])
    rho = ns.spearman(a, ties)
    assert -1.0 < rho < 1.0


def test_spearman_constant_input_is_nan():
    assert np.isnan(ns.spearman(np.ones(10), np.arange(10.0)))


def test_bootstrap_ci_reproducible_and_brackets_point_estimate():
    rng = np.random.default_rng(1)
    a = rng.normal(size=500)
    b = a + rng.normal(0, 0.1, 500)
    lo1, hi1 = ns.spearman_bootstrap_ci(a, b, reps=50, seed=7)
    lo2, hi2 = ns.spearman_bootstrap_ci(a, b, reps=50, seed=7)
    assert (lo1, hi1) == (lo2, hi2)
    assert lo1 <= ns.spearman(a, b) <= hi1


def test_jaccard_edge_cases():
    assert ns.jaccard([True, True], [True, True]) == 1.0
    assert ns.jaccard([True, False], [False, True]) == 0.0
    assert ns.jaccard([False, False], [False, False]) == 1.0  # both empty
    assert ns.jaccard([True, True, False], [True, False, False]) == pytest.approx(0.5)


def test_topk_overlap_bounds():
    rank = np.arange(100.0)
    assert ns.topk_overlap(rank, rank, 10) == 1.0
    assert ns.topk_overlap(rank, rank[::-1], 10) == 0.0
    val = ns.topk_overlap(rank, np.roll(rank, 5), 10)
    assert 0.0 < val < 1.0


def test_transition_matrix_counts():
    orig = np.array([0, 0, 1, 2, 3])
    pert = np.array([0, 1, 1, 3, 3])
    m = ns.transition_matrix(orig, pert)
    assert m.shape == (4, 4)
    assert m.sum() == 5
    assert m[0, 0] == 1 and m[0, 1] == 1 and m[3, 3] == 1


def test_ks_statistic_bounds_and_identity():
    a = np.array([1.0, 2.0, 3.0])
    assert ns.ks_statistic(a, a) == 0.0
    b = np.array([10.0, 11.0, 12.0])
    assert ns.ks_statistic(a, b) == pytest.approx(1.0)


# -- perturbations -----------------------------------------------------------


def test_perturb_deterministic_per_seed_and_seed_sensitive():
    df = _synthetic_sources()
    p1 = ns.perturb_sources(df, "noise_small", 3)
    p2 = ns.perturb_sources(df, "noise_small", 3)
    p3 = ns.perturb_sources(df, "noise_small", 4)
    pd.testing.assert_frame_equal(p1, p2)
    assert not np.allclose(p1["award_value"], p3["award_value"])


def test_perturb_invariants_ids_cpv_status_untouched():
    df = _synthetic_sources()
    for regime in ("round", "noise_small", "noise_moderate",
                   "missing_1pct", "missing_5pct"):
        p = ns.perturb_sources(df, regime, 0)
        for col in ("ocid", "cpv_primary", "status", "procurement_method_details",
                    "tender_start", "buyer_identifier"):
            assert p[col].equals(df[col]), f"{regime}: {col} changed"


def test_perturb_monetary_stays_positive_and_small_noise_is_small():
    df = _synthetic_sources()
    small = ns.perturb_sources(df, "noise_small", 0)
    mod = ns.perturb_sources(df, "noise_moderate", 0)
    for regime_df in (small, mod):
        assert (regime_df["award_value"].dropna() > 0).all()
    rel_small = (small["award_value"] / df["award_value"] - 1).abs()
    rel_mod = (mod["award_value"] / df["award_value"] - 1).abs()
    assert rel_small.quantile(0.95) < 0.05   # +/-1% noise: 95% inside +/-5%
    assert rel_mod.quantile(0.99) < 0.30     # +/-5% noise: 99% inside +/-30%


def test_round_regime_is_deterministic_and_rounds_to_10k():
    df = _synthetic_sources()
    p = ns.perturb_sources(df, "round", 0)
    q = ns.perturb_sources(df, "round", 99)
    pd.testing.assert_frame_equal(p, q)
    vals = p["award_value"].dropna()
    assert np.all(np.mod(vals, 1e4) == 0.0)


def test_counts_stay_non_negative_integers():
    df = _synthetic_sources()
    for regime in ("noise_small", "noise_moderate"):
        p = ns.perturb_sources(df, regime, 1)
        for col in ("n_bidders", "n_suppliers", "n_amendments"):
            v = p[col].dropna()
            assert (v >= 0).all()
            assert np.all(v == v.astype(int))


def test_missing_regimes_mask_sources_as_nan():
    df = _synthetic_sources(n=4000)
    p = ns.perturb_sources(df, "missing_5pct", 2)
    assert p["award_value"].isna().mean() == pytest.approx(0.05, abs=0.02)
    assert p["n_bidders"].isna().mean() == pytest.approx(0.05, abs=0.02)
    assert p["tender_end"].isna().mean() == pytest.approx(0.05, abs=0.02)
    # untouched rows keep the original value
    keep = p["award_value"].notna()
    assert np.allclose(p.loc[keep, "award_value"], df.loc[keep, "award_value"])


def test_unknown_regime_raises():
    with pytest.raises(ValueError):
        ns.perturb_sources(_synthetic_sources(), "hurricane", 0)


# -- dependency-consistent re-derivation -------------------------------------


def test_recompute_features_consistent_with_perturbed_sources():
    df = _synthetic_sources()
    pert = ns.perturb_sources(df, "noise_moderate", 5)
    feats = ns.recompute_features(pert)
    # derived financial features follow the perturbed award, not the original
    award = pd.to_numeric(pert["award_value"], errors="coerce")
    assert np.allclose(
        feats["log_award_value"], np.log1p(award.clip(lower=0)), atol=1e-9)
    # binary competition flags stay internally consistent after count jitter
    n_bidders = pd.to_numeric(pert["n_bidders"], errors="coerce").fillna(0)
    assert np.array_equal(feats["single_bidder"].to_numpy(), (n_bidders == 1).to_numpy())
    assert np.array_equal(feats["no_bid_data"].to_numpy(), (n_bidders == 0).to_numpy())
    # behavioural columns are carried through untouched
    ref_feats = ns.recompute_features(df)
    for col in ("buyer_supplier_repeat_share", "winner_share_of_buyer_awards",
                "supplier_win_concentration", "supplier_award_count_log"):
        assert col not in pert.columns  # not sources -> never perturbed
        assert col in ref_feats.columns


def test_missing_block_follows_etl_fill_conventions():
    df = _synthetic_sources(n=200)
    pert = df.copy()
    pert[["award_value", "award_total", "estimated_value",
          "n_awards_with_value"]] = np.nan
    feats = ns.recompute_features(pert)
    # award block missing -> logs 0, ratio features 1.0, multi-award 0
    assert (feats["log_award_value"] == 0.0).all()
    assert (feats["value_vs_cpv_median"] == 1.0).all()
    assert (feats["estimate_to_award_ratio"] == 1.0).all()
    assert (feats["multi_award_tender"] == 0).all()


# -- metrics on synthetic frames ---------------------------------------------


def _fake_scores(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    votes = rng.integers(0, 5, n)
    score = rng.random(n)
    return pd.DataFrame(
        {"max_score": score, "n_models_flagging": votes,
         "band": ns.band_of(votes),
         **{f"score_{name}": rng.random(n) for name in (
             "statistical_mad_zscore", "isolation_forest",
             "local_outlier_factor", "one_class_svm")}}
    )


def test_run_metrics_bounds_and_internal_consistency():
    ref = _fake_scores(2000, seed=1)
    pert = ref.copy()
    pert["max_score"] = np.roll(ref["max_score"].to_numpy(), 7)
    m, transitions, tm = ns.run_metrics(
        ref, pert, bootstrap_reps=20, seed=0,
        value_edges=[1e5, 1e6], type_labels=np.full(len(ref), "open"),
        award_values=np.full(len(ref), 5e5))
    assert 0.0 <= m["spearman_max_score"] <= 1.0
    assert m["spearman_ci_low"] <= m["spearman_max_score"] <= m["spearman_ci_high"]
    for k in ns.TOP_K:
        assert 0.0 <= m[f"topk_overlap_{k}"] <= 1.0
    assert sum(t["count"] for t in transitions) == len(ref)
    assert tm.sum() == len(ref)
    assert m["band_change_pct"] == pytest.approx(
        100.0 * (ref["band"].to_numpy() != pert["band"].to_numpy()).mean())
    assert m["ks_max_score"] == pytest.approx(0.0, abs=1e-9)  # a rotation keeps the multiset


def test_run_metrics_identical_frames_are_perfectly_stable():
    ref = _fake_scores(1500, seed=2)
    m, _, _ = ns.run_metrics(
        ref, ref.copy(), bootstrap_reps=10, seed=0,
        value_edges=[1.0], type_labels=np.full(len(ref), "open"),
        award_values=np.linspace(1e3, 1e6, len(ref)))
    assert m["spearman_max_score"] == pytest.approx(1.0)
    assert m["band_change_pct"] == 0.0
    assert m["jaccard_high_plus"] == 1.0
    assert m["topk_overlap_500"] == 1.0


def test_score_frozen_requires_feature_columns():
    # guard rail: the frozen scorer must fail loudly on an empty frame
    df = _synthetic_sources(n=5)

    class _Dummy:
        @staticmethod
        def statistical_baseline(frame, cols, z_threshold=5.0):
            out = pd.DataFrame({"score": 0.0, "n_red_flags": 0, "is_anomaly": 0},
                               index=frame.index)
            out.attrs.update(binary_features=[], spiked_features=[],
                             scored_features=list(cols))
            return out

    with pytest.raises(Exception):
        # no fitted scaler/model is supplied -> transform/predict must fail
        ns.score_frozen(ns.recompute_features(df), _Dummy(), None, None, None, None)


# -- script hygiene ----------------------------------------------------------


def test_script_has_no_network_imports():
    text = (ROOT / "scripts" / "32_noise_sensitivity.py").read_text(encoding="utf-8")
    for banned in ("import requests", "import httpx", "urllib.request",
                   "socket", "storage.mtender"):
        assert banned not in text


def test_script_help_runs_standalone():
    proc = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "32_noise_sensitivity.py"),
         "--help"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "perturbation" in proc.stdout


def test_procedure_type_labels_top_n_and_other():
    types = pd.Series(["open"] * 50 + ["direct"] * 20 + ["restricted"] * 5 + [np.nan] * 3)
    labels, top = ns.procedure_type_labels(types, top_n=2)
    assert top == ["open", "direct"]
    assert labels.shape == (78,)
    assert (labels == "other").sum() == 8  # restricted + unknown
    assert (labels == "open").sum() == 50


def test_hypotheses_pre_registered_constants():
    assert ns.HYPOTHESES == {
        "H1_noise_small_rho": 0.99,
        "H2_noise_moderate_rho": 0.97,
        "H2_noise_moderate_top200": 0.80,
    }
