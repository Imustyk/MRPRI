"""Tests for the experimental risk-specific modules (added 2026-10-20).

Each test pins one scientific contract of ``src/mtender/risk_modules.py``:

* module C is strictly prior-only (same-day events never see each other,
  frame order is irrelevant, no future backfill);
* module B clusters only same-buyer/same-CPV2 events inside the documented
  window, and known "no cluster" is ``0`` while unknown inputs are ``NaN``;
* module A is scoped to competition-expecting populations;
* module D needs a real priced distribution (min group size, MAD > 0) and is
  never called overpricing;
* forward-looking outcomes are computed but explicitly evaluation-only;
* threshold-based legal interpretation is disabled in metadata.

Synthetic frames only - no real data, no model training, no network.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.mtender.risk_modules import (
    DIRECT_DETAILS,
    MIN_GROUP_SIZE,
    OPEN_DETAILS,
    REPEAT_WINDOW_DAYS,
    SPLIT_WINDOW_DAYS,
    competition_indicators,
    future_confirmation_indicators,
    indicator_metadata,
    module_indicators,
    network_indicators,
    splitting_indicators,
    value_distribution_indicators,
)


# --------------------------------------------------------------------------- #
# Module C - prior-only network
# --------------------------------------------------------------------------- #

def _pair_frame(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "buyer_id": ["b1"] * len(dates),
            "winner_id": ["w1"] * len(dates),
            "award_date": dates,
        }
    )


def test_network_same_day_events_never_see_each_other():
    out = network_indicators(_pair_frame(["2021-01-01", "2021-01-01", "2021-06-01"]))
    # the two same-day rows both read the empty pre-batch state
    assert out["pair_prior_awards"].tolist() == [0.0, 0.0, 2.0]
    # both same-day rows have 0 prior awards of this buyer -> share undefined
    assert np.isnan(out["pair_buyer_share"].iloc[:2]).all()
    assert out["pair_buyer_share"].iloc[2] == 1.0
    assert out["net_c_hit"].tolist() == [0.0, 0.0, 1.0]


def test_network_is_frame_order_independent():
    shuffled = _pair_frame(["2021-06-01", "2021-01-01", "2021-02-01"])
    out = network_indicators(shuffled)  # t3, t1, t2 as rows 0, 1, 2
    assert out["pair_prior_awards"].tolist() == [2.0, 0.0, 1.0]


def test_network_no_future_backfill_when_later_awards_added():
    early = _pair_frame(["2021-01-01", "2021-02-01"])
    with_future = _pair_frame(["2021-01-01", "2021-02-01", "2021-06-01"])
    a = network_indicators(early)
    b = network_indicators(with_future)
    # adding a later award must not move the earlier rows
    assert b["pair_prior_awards"].iloc[:2].tolist() == a["pair_prior_awards"].tolist()
    assert b["pair_prior_awards"].iloc[2] == 2.0


def test_network_prior_counts_and_unknowns():
    df = pd.DataFrame(
        {
            "buyer_id": ["b1", "b1", "b1"],
            "winner_id": ["w1", None, "w2"],
            "award_date": ["2021-01-01", "2021-02-01", "2021-03-01"],
        }
    )
    out = network_indicators(df)
    # row without a winner: everything unknown, including the hit
    assert out.iloc[1].drop("net_c_hit").isna().all()
    assert np.isnan(out["net_c_hit"].iloc[1])
    # new supplier: pair prior 0 of buyer's 1 known award -> share 0.0
    assert out["pair_prior_awards"].iloc[2] == 0.0
    assert out["buyer_prior_awards"].iloc[2] == 1.0
    assert out["pair_buyer_share"].iloc[2] == 0.0
    assert out["net_c_hit"].iloc[2] == 0.0
    # unknown supplier dependency (no prior awards) is NaN, not 0
    assert np.isnan(out["supplier_dep_share"].iloc[2])


def test_network_repeat_window_is_365_days():
    # t0, t0+100d, t0+400d for the same pair
    out = network_indicators(
        _pair_frame(["2021-01-01", "2021-04-11", "2022-02-05"])
    )
    assert out["pair_prior_365d"].tolist() == [0.0, 1.0, 1.0]
    assert out["pair_prior_awards"].tolist() == [0.0, 1.0, 2.0]
    assert REPEAT_WINDOW_DAYS == 365


def test_network_requires_positional_index():
    df = _pair_frame(["2021-01-01", "2021-06-01"]).iloc[[0, 1]]
    df.index = [0, 5]
    with pytest.raises(ValueError, match="RangeIndex"):
        network_indicators(df)


# --------------------------------------------------------------------------- #
# Module B - splitting
# --------------------------------------------------------------------------- #

def _split_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "buyer_id": ["b1", "b1", "b1", "b2", "b1"],
            "winner_id": ["w1", "w1", "w1", "w1", "w1"],
            "cpv_primary": [
                "45000000-9",
                "45211300-9",
                "45211300-9",
                "45211300-9",
                "30000000-2",
            ],
            "award_date": [
                "2021-01-01",
                "2021-02-01",
                "2021-04-15",
                "2021-02-10",
                "2021-02-01",
            ],
            "award_total": [100.0, 200.0, 300.0, 400.0, 500.0],
        }
    )


def test_splitting_cluster_window_and_counts():
    out = splitting_indicators(_split_frame())
    # key (b1, "45") has 01-01, 02-01, 04-15; +/-90d decides membership
    assert out["split_cluster_member"].tolist() == [1.0, 1.0, 1.0, 0.0, 0.0]
    assert out["split_cluster_n"].iloc[0] == 2.0   # 04-15 is 104 days away
    assert out["split_cluster_n"].iloc[1] == 3.0   # 02-01 sees both neighbours
    assert out["split_cluster_n"].iloc[2] == 2.0   # 04-15 excludes 01-01
    assert out["split_min_gap_days"].tolist()[:3] == [31.0, 31.0, 73.0]
    assert out["split_cluster_value_mdl"].tolist()[:3] == [300.0, 600.0, 500.0]
    # different buyer (row 3) and different CPV2 (row 4): definite "no cluster"
    assert np.isnan(out["split_cluster_n"].iloc[3])
    assert np.isnan(out["split_same_supplier_share"].iloc[3])


def test_splitting_same_supplier_share_and_hit():
    out = splitting_indicators(_split_frame())
    assert out["split_same_supplier_share"].tolist()[:3] == [1.0, 1.0, 1.0]
    assert out["split_b_hit"].tolist() == [1.0, 1.0, 1.0, 0.0, 0.0]
    assert SPLIT_WINDOW_DAYS == 90


def test_splitting_small_value_share_uses_buyers_own_quartile():
    out = splitting_indicators(_split_frame())
    # b1's own values: [100, 200, 300, 500] -> q25 = 175 (pandas linear)
    assert out["split_small_value_share"].iloc[0] == pytest.approx(0.5)   # 100<=175 of 2
    assert out["split_small_value_share"].iloc[1] == pytest.approx(1 / 3)  # of 3
    assert out["split_small_value_share"].iloc[2] == 0.0  # 200,300 > 175


def test_splitting_unknown_inputs_stay_nan():
    df = pd.DataFrame(
        {
            "buyer_id": ["b1", "b1"],
            "winner_id": [None, None],
            "cpv_primary": ["45000000-9", "45000000-9"],
            "award_date": ["2021-01-01", "2021-02-01"],
            "award_total": [100.0, 200.0],
        }
    )
    out = splitting_indicators(df)
    # cluster is known, supplier is not -> hit undetermined (NaN), not 0
    assert out["split_cluster_member"].tolist() == [1.0, 1.0]
    assert out["split_same_supplier_share"].isna().all()
    assert out["split_b_hit"].isna().all()


def test_splitting_missing_date_is_unknown_not_zero():
    df = pd.DataFrame(
        {
            "buyer_id": ["b1"],
            "winner_id": ["w1"],
            "cpv_primary": ["45000000-9"],
            "award_date": [None],
            "award_total": [100.0],
        }
    )
    out = splitting_indicators(df)
    assert out["split_cluster_member"].isna().all()
    assert out["split_b_hit"].isna().all()


# --------------------------------------------------------------------------- #
# Module A - competition (population-scoped)
# --------------------------------------------------------------------------- #

def _comp_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "buyer_id": ["b1"] * 4,
            "winner_id": ["w1"] * 4,
            "award_date": [
                "2021-01-01",
                "2021-02-01",
                "2021-03-01",
                "2022-06-01",  # beyond the 365-day prior window
            ],
            "n_bidders": [1.0, 3.0, np.nan, 1.0],
            "bid_window_days": [5, 30, 20, 40],
            "procurement_method_details": ["opentender"] * 4,
        }
    )


def test_competition_prior_share_counts_strictly_earlier_procedures():
    out = competition_indicators(_comp_frame())
    assert out["buyer_prior_365d_count"].tolist() == [0.0, 1.0, 2.0, 0.0]
    # unknown n_bidders leaves the denominator unchanged (NaN != 0 bidders)
    assert np.isnan(out["buyer_prior_single_share"].iloc[0])
    assert out["buyer_prior_single_share"].iloc[1] == 1.0
    assert out["buyer_prior_single_share"].iloc[2] == 0.5
    assert np.isnan(out["buyer_prior_single_share"].iloc[3])


def test_competition_hit_only_in_competition_expecting_populations():
    df = _comp_frame()
    df.loc[len(df)] = {
        "buyer_id": "b9",
        "winner_id": "w9",
        "award_date": "2021-01-05",
        "n_bidders": 0.0,
        "bid_window_days": 3,
        "procurement_method_details": DIRECT_DETAILS,
    }
    out = competition_indicators(df)
    assert out["comp_a_hit"].tolist()[:4] == [1.0, 0.0, 0.0, 1.0]
    # direct award with no bids and a short window: structurally expected,
    # therefore module A does not fire (NaN = not applicable, not a clearance)
    assert np.isnan(out["comp_a_hit"].iloc[4])
    assert out["comp_single_bidder"].iloc[4] == 0.0
    assert out["comp_short_window"].iloc[4] == 1.0


def test_open_and_direct_populations_are_disjoint():
    assert DIRECT_DETAILS not in OPEN_DETAILS


# --------------------------------------------------------------------------- #
# Module D - value distribution
# --------------------------------------------------------------------------- #

def _value_frame() -> pd.DataFrame:
    varied = [45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100,
              105, 110, 115, 120, 125, 130, 135, 140, 145, 150, 155, 160]
    rows = {
        "cpv_primary": ["45000000-9"] * (len(varied) + 1)
        + ["30000000-2"] * 5
        + ["20000000-1"] * 25,
        "procurement_method_details": ["opentender"] * (len(varied) + 1 + 5 + 25),
        "award_total": [float(v) for v in varied] + [50000.0] + [100.0] * 5 + [900.0] * 25,
        "buyer_id": ["b"] * (len(varied) + 1 + 5 + 25),
        "winner_id": ["w"] * (len(varied) + 1 + 5 + 25),
        "award_date": ["2021-01-01"] * (len(varied) + 1 + 5 + 25),
    }
    return pd.DataFrame(rows)


def test_value_distribution_flags_tail_and_respects_min_group():
    df = _value_frame()
    out = value_distribution_indicators(df)
    # group 45/opentender: 25 priced rows (varied list + the outlier)
    assert out["val_group_n"].iloc[0] == 25
    assert out["val_group_n"].iloc[24] == 25
    # the 50 000 outlier sits in the far tail; ordinary rows do not
    assert out["val_robust_z"].iloc[24] >= 3.0
    assert out["val_d_hit"].iloc[24] == 1.0
    assert abs(out["val_robust_z"].iloc[1]) < 3.0
    assert out["val_d_hit"].iloc[1] == 0.0
    # 5-row group: too small for a distribution -> undetermined, not "normal"
    small = slice(25, 30)
    assert out["val_group_n"].iloc[small].eq(5).all()
    assert out["val_robust_z"].iloc[small].isna().all()
    assert out["val_d_hit"].iloc[small].isna().all()


def test_value_distribution_constant_group_has_no_z():
    df = _value_frame()
    out = value_distribution_indicators(df)
    constant = slice(30, 55)  # 25 identical values -> MAD == 0
    assert out["val_robust_z"].iloc[constant].isna().all()
    assert out["val_d_hit"].iloc[constant].isna().all()


def test_value_distribution_requires_a_price():
    df = pd.DataFrame(
        {
            "cpv_primary": ["45000000-9"],
            "procurement_method_details": ["opentender"],
            "award_total": [None],
            "buyer_id": ["b"],
            "winner_id": ["w"],
            "award_date": ["2021-01-01"],
        }
    )
    out = value_distribution_indicators(df)
    assert out["val_pctile"].isna().all()
    assert out["val_d_hit"].isna().all()


# --------------------------------------------------------------------------- #
# Evaluation-only forward outcomes
# --------------------------------------------------------------------------- #

def test_future_outcomes_are_strictly_later_and_windowed():
    df = pd.DataFrame(
        {
            "buyer_id": ["b1"] * 4,
            "winner_id": ["w1"] * 4,
            "cpv_primary": ["45000000-9"] * 4,
            "award_date": [
                "2021-01-01",
                "2021-01-01",
                "2021-03-01",
                "2022-06-01",
            ],
        }
    )
    out = future_confirmation_indicators(df)
    # same-day twin never confirms row 0/1; row 2 (59 days) does; row 3 too far
    assert out["future_repeat_same_winner_365d"].tolist() == [1.0, 1.0, 0.0, 0.0]
    assert out["future_same_buyer_cpv2_90d"].tolist() == [1.0, 1.0, 0.0, 0.0]


def test_future_outcomes_nan_when_inputs_missing():
    df = pd.DataFrame(
        {
            "buyer_id": ["b1", "b1"],
            "winner_id": [None, "w1"],
            "cpv_primary": ["45000000-9", "45000000-9"],
            "award_date": ["2021-01-01", "2021-02-01"],
        }
    )
    out = future_confirmation_indicators(df)
    assert np.isnan(out["future_repeat_same_winner_365d"].iloc[0])
    # CPV follow-up does not need the winner, so it is still determined
    assert out["future_same_buyer_cpv2_90d"].iloc[0] == 1.0


# --------------------------------------------------------------------------- #
# Composition, semantics, metadata
# --------------------------------------------------------------------------- #

def _full_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "buyer_id": ["b1", "b2", "b3", "b4"],
            "winner_id": ["w1", "w2", "w3", "w4"],
            "cpv_primary": ["45000000-9"] * 4,
            "procurement_method_details": [DIRECT_DETAILS] * 4,
            "award_date": ["2021-01-01", "2021-01-02", "2021-01-03", None],
            "award_total": [100.0, 200.0, 300.0, 400.0],
            "n_bidders": [0.0, 0.0, 0.0, 0.0],
            "bid_window_days": [10, 12, 14, 16],
        }
    )


def test_module_hits_distinguish_unknown_from_not_triggered():
    out = module_indicators(_full_frame())
    # rows 0-2: module B/C known (no cluster / no repeat) -> 0; D unknown
    # (group < MIN_GROUP_SIZE); A not applicable for direct awards.
    assert out["n_module_known"].tolist()[:3] == [2.0, 2.0, 2.0]
    assert out["n_module_hits"].tolist()[:3] == [0.0, 0.0, 0.0]
    # row 3 has no date: nothing can be determined -> 0 of 4 known
    assert out["n_module_known"].iloc[3] == 0.0
    assert out["n_module_hits"].iloc[3] == 0.0
    assert np.isnan(out["module_b_hit"].iloc[3])
    assert np.isnan(out["module_c_hit"].iloc[3])
    # module A undefined for the direct population on every row
    assert out["module_a_hit"].isna().all()


def test_module_indicators_normalise_foreign_index_and_restore_it():
    sub = _full_frame().iloc[[0, 3]]
    sub.index = ["rowA", "rowB"]
    out = module_indicators(sub)  # must not raise
    assert out.index.tolist() == ["rowA", "rowB"]


def test_metadata_disables_threshold_interpretation():
    meta = indicator_metadata()
    threshold = meta["modules"]["B_splitting"]["threshold_interpretation"]
    assert threshold["enabled"] is False
    assert "threshold" in threshold["reason"]
    assert "not evidence" in meta["disclaimer"]
    assert "equal representation" in meta["equal_alert_rates_are_not_a_goal"]
    assert "never prove collusion" in meta["modules"]["C_network"]["note"]
    assert "overpricing is NOT established" in meta["modules"]["D_value_distribution"]["note"]
    assert "evaluation-only" in meta["evaluation_only_outcomes"]["note"]
    assert "NaN" in meta["hit_semantics"]


def test_indicator_columns_exist_in_every_module_output():
    df = _full_frame()
    out = module_indicators(df)
    for col in (
        "comp_single_bidder",
        "buyer_prior_single_share",
        "split_cluster_n",
        "pair_prior_awards",
        "pair_buyer_share",
        "val_robust_z",
        "module_a_hit",
        "module_b_hit",
        "module_c_hit",
        "module_d_hit",
        "n_module_hits",
        "n_module_known",
    ):
        assert col in out.columns, col


# --------------------------------------------------------------------------- #
# scripts/34 - end-to-end smoke on a synthetic corpus
# --------------------------------------------------------------------------- #

_TINY_FEATURES = (
    "ocid,tender_id,title,status,procurement_method_details,"
    "buyer_id,buyer_name,winner_id,winner_name,cpv_primary,"
    "award_date,tender_start,published_date,award_total,award_value,"
    "n_bidders,bid_window_days\n"
)


def _tiny_features_csv(path: Path) -> int:
    """12 direct rows (3 form a splitting cluster) + 4 open tenders."""
    lines = []
    # cluster: same buyer B1, same CPV2 "45", same winner, within 90 days
    # (values 400/700/1000 so they land in quartiles 2-4, interleaved with
    # the control pool - matching needs candidates in the same stratum)
    for i, day in enumerate(("2024-01-01", "2024-02-01", "2024-03-15")):
        lines.append(
            f"ocid-{i},t{i},cluster {i},complete,directaward,"
            f"B1,Buyer One,W1,Supplier One,45000000-9,"
            f"{day},{day},{day},{(400, 700, 1000)[i]},{(400, 700, 1000)[i]},0,10"
        )
    # matched-control pool: distinct buyers, no repeat keys
    pool_money = (100, 200, 300, 500, 600, 800, 900, 1100, 1200)
    for i in range(9):
        lines.append(
            f"ocid-{10 + i},t{10 + i},solo {i},complete,directaward,"
            f"B{i + 2},Buyer {i + 2},W{i + 2},Supplier {i + 2},45000000-9,"
            f"2024-04-{i + 1:02d},2024-04-{i + 1:02d},2024-04-{i + 1:02d},"
            f"{pool_money[i]},{pool_money[i]},0,15"
        )
    # competition-expecting population for module A
    for i, nb in enumerate((1, 3, 0, 2)):
        lines.append(
            f"ocid-{30 + i},t{30 + i},open {i},complete,opentender,"
            f"B20,Buyer 20,W20,Supplier 20,30000000-2,"
            f"2024-05-{i + 1:02d},2024-05-{i + 1:02d},2024-05-{i + 1:02d},"
            f"{900 + i},{900 + i},{nb},{8 + i}"
        )
    path.write_text(_TINY_FEATURES + "\n".join(lines) + "\n", encoding="utf-8")
    return 16


def _load_script34():
    script = Path(__file__).resolve().parents[1] / "scripts" / "34_risk_modules.py"
    spec = importlib.util.spec_from_file_location("risk34", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script34_smoke_and_reproducibility(tmp_path):
    mod = _load_script34()
    features = tmp_path / "features.csv"
    n_rows = _tiny_features_csv(features)

    out_a = tmp_path / "out_a"
    common = [
        "--features", str(features),
        "--scores", str(tmp_path / "no_scores.csv"),  # v0-unavailable branch
        "--seed", "42",
        "--boot", "60",
        "--top", "10",
    ]
    assert mod.main(common + ["--outdir", str(out_a)]) == 0

    payload = json.loads(
        (out_a / "methodology" / "risk_modules.json").read_text(encoding="utf-8")
    )
    assert payload["corpus"]["rows"] == n_rows
    assert payload["corpus"]["event_date_provenance"]["missing"] == 0

    dt = payload["direct_track"]
    assert dt["n_direct"] == 12
    assert dt["n_selected_total"] == 3          # exactly the B1 cluster
    m = dt["matching"]
    assert m["n_matched_controls"] == 3
    assert m["n_selected_matched"] == 3
    assert m["controls_disjoint_from_selected"] is True
    assert m["n_selected_dropped_missing_year_or_quartile"] == 0

    # forward outcomes are computed but flagged evaluation-only
    assert "evaluation-only" in dt["outcome_note"]
    assert set(dt["outcomes"]) == {
        "future_repeat_same_winner_365d",
        "future_same_buyer_cpv2_90d",
        "v0_critical",
    }
    # scores table absent -> v0 reference honestly insufficient, not fabricated
    assert dt["outcomes"]["v0_critical"]["verdict"] == "insufficient_data"
    assert dt["outcomes"]["v0_critical"]["selected_rate"] is None

    # scientific guardrails travel with the artefact
    meta = payload["indicator_metadata"]
    assert meta["modules"]["B_splitting"]["threshold_interpretation"]["enabled"] is False
    assert "not evidence" in payload["disclaimer"]
    assert set(payload["populations"]) >= {"direct", "open_tender"}

    ind = pd.read_csv(out_a / "tables" / "risk_module_indicators.csv")
    assert len(ind) == n_rows
    cases = pd.read_csv(out_a / "tables" / "risk_module_cases.csv")
    assert 0 < len(cases) <= 10
    # the B1 cluster rows must be in the export; both hit-bearing groups are
    # present because open rows also trigger module A/B/C
    assert {"ocid-0", "ocid-1", "ocid-2"} <= set(cases["ocid"])
    assert set(cases["group"]) == {"direct", "open_tender"}

    # reproducibility: a second run with the same seed gives identical tables
    out_b = tmp_path / "out_b"
    assert mod.main(common + ["--outdir", str(out_b)]) == 0
    for name in ("risk_module_indicators.csv", "risk_module_cases.csv"):
        a = (out_a / "tables" / name).read_bytes()
        b = (out_b / "tables" / name).read_bytes()
        assert a == b, name
