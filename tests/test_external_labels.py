"""The external label join must never silently widen.

Regression tests for the bug this cycle actually hit: joining blacklist entry
numbers onto winners with ``";".join(sorted([]))`` produced an empty string,
which is *not* missing, so every procedure with a winner name was labelled
positive (77% of the corpus) and every "precision" computed from it was
meaningless.
"""

from __future__ import annotations

import pandas as pd

from src.mtender.external_labels import _nrs_for, build_label_table, parse_decision_date


def test_empty_membership_is_none_not_empty_string():
    assert _nrs_for("some supplier", {}) is None
    assert _nrs_for(None, {"k": [1]}) is None
    assert _nrs_for("k", {"k": [7, 3]}) == "3;7"
    assert _nrs_for("k", {"k": [7, 7]}) == "7"


def test_decision_date_is_parsed_from_the_din_format():
    assert parse_decision_date("13/23 din 07.12.2023") == "2023-12-07"
    assert parse_decision_date("not a date") is None
    assert parse_decision_date(None) is None


def test_label_base_rate_is_small_and_matches_the_summary():
    table, summary = build_label_table()
    positives = int(table["is_aap_positive"].sum())
    assert positives == summary["n_positive_procedures"]
    # 22 suppliers cannot own a fifth of a 152k-procedure corpus.
    assert positives < 0.05 * len(table)
    assert positives > 0, "the AAP snapshot must match something, or step 2 is vacuous"
    # a procedure is positive only through an exact name match
    labelled = table[table["is_aap_positive"] == 1]
    assert labelled["winner_key"].notna().all()
    assert labelled["blacklist_nrs"].notna().all()
    assert (labelled["match_level"] == "exact_normalised").all()


def test_unmatched_rows_carry_no_membership_string():
    table, _ = build_label_table()
    unmatched = table[table["is_aap_positive"] == 0]
    assert unmatched["blacklist_nrs"].isna().all()
    # rows without any winner name are never positive
    assert table[table["winner_name"].isna()]["is_aap_positive"].sum() == 0


def test_known_entry_has_its_documented_procedure_count():
    """Rodital-Lux (entry 1) is the largest match in the corpus (259 awards)."""
    _, summary = build_label_table()
    by_nr = {r["blacklist_nr"]: r for r in summary["per_entry"]}
    assert by_nr[1]["match_level"] == "exact_normalised"
    assert by_nr[1]["n_procedures"] == 259
    # 18 exact / 4 ambiguous on the 2026-09-25 snapshot, as script 09 reports
    assert summary["n_exact_normalised_matches"] == 18
    assert summary["n_ambiguous_candidates"] == 4


def test_scored_corpus_is_aligned_by_ocid_not_position():
    """Regression for the positional-join bug in scripts/16.

    ``tender_anomaly_scores.csv`` is sorted by ``n_models_flagging`` and
    ``features.csv`` by ``ocid``, so a positional alignment pairs the label of
    one procedure with the score of another. The join helper must produce a
    table where ``consensus == (n_models_flagging >= 3)`` row by row and where
    the row order follows the score export.
    """
    from src.mtender.external_labels import load_scored_corpus

    corpus = load_scored_corpus()
    assert len(corpus) == len(corpus["ocid"].unique())
    assert (corpus["consensus"].astype(int) >= 0).all()
    # the identity must hold for every row: consensus is votes >= 3
    assert (corpus["consensus"].astype(int)
            == (corpus["n_models_flagging"].astype(int) >= 3).astype(int)).all()
    # positives survive the join
    assert corpus["is_aap_positive"].sum() == 633
    # and the score export really is NOT in ocid order, or the test is vacuous
    assert not corpus["ocid"].is_monotonic_increasing
