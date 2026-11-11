"""Comparison helpers stay defined when flags or scores are degenerate."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.mta_compare import (
    exact_top_fraction_flag,
    jaccard,
    spearman,
    top_ocids,
    topk_overlap,
)
from src.mtender.mta_protocol import fit_sample


def test_jaccard_of_two_empty_flags_is_one():
    assert jaccard(np.zeros(4), np.zeros(4)) == 1.0


def test_jaccard_and_topk_use_the_same_population():
    left = np.array([1, 1, 0, 0])
    right = np.array([1, 0, 1, 0])
    assert jaccard(left, right) == 1 / 3
    scores_a = np.array([0.9, 0.8, 0.1, 0.0])
    scores_b = np.array([0.2, 0.95, 0.9, 0.1])
    ocids = np.array(["a", "b", "c", "d"])
    overlap = topk_overlap(scores_a, scores_b, ocids, 2)
    assert overlap["intersection"] == 1
    assert top_ocids(scores_a, ocids, 2) == ["a", "b"]


def test_tied_scores_break_by_ocid():
    scores = np.array([1.0, 1.0, 0.0])
    ocids = np.array(["c", "a", "b"])
    assert top_ocids(scores, ocids, 2) == ["a", "c"]


def test_spearman_is_absent_when_a_score_is_constant():
    assert spearman(np.ones(5), np.arange(5)) is None
    assert spearman(np.arange(5, dtype=float), np.arange(5, dtype=float)) == pytest.approx(1.0)


def test_exact_top_fraction_flags_the_requested_count():
    scores = np.arange(10, dtype=float)
    ocids = np.array([f"{i:02d}" for i in range(10)])
    flag, k = exact_top_fraction_flag(scores, ocids, 0.2)
    assert k == 2
    assert int(flag.sum()) == 2
    assert list(flag) == [0, 0, 0, 0, 0, 0, 0, 0, 1, 1]


def test_fit_sample_is_seeded_and_is_not_a_prefix():
    drawn = fit_sample(1000, 50, 42)
    assert len(drawn) == 50
    assert list(drawn) == list(fit_sample(1000, 50, 42))
    assert list(drawn) != list(range(50))
    assert list(fit_sample(10, 50, 42)) == list(range(10))
