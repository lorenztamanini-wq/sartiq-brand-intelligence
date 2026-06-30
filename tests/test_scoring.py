"""Tests for economics.score — the 0..5 prioritization score.

Exercises: bounded range, determinism, monotonicity in opportunity size at
equal fit, and that raising fit_weight raises the score.
"""

from __future__ import annotations

import unittest

from config import load_benchmarks, load_ground_truth
from economics import compute_opportunity, score


class TestScore(unittest.TestCase):
    def setUp(self) -> None:
        self.benchmarks = load_benchmarks()
        truth = load_ground_truth()
        # OVS has the largest opportunity; Sandro the smallest of the three.
        self.big = compute_opportunity(truth["ovs"].econ_inputs, self.benchmarks)
        self.small = compute_opportunity(
            truth["sandro"].econ_inputs, self.benchmarks
        )

    def test_score_within_zero_to_five(self) -> None:
        for econ in (self.big, self.small):
            s = score(econ, 0.5)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 5.0)

    def test_score_is_deterministic(self) -> None:
        first = score(self.big, 0.5)
        second = score(self.big, 0.5)
        self.assertEqual(first, second)

    def test_larger_opportunity_scores_at_least_as_high_at_equal_fit(self) -> None:
        fit = 0.5
        self.assertGreaterEqual(score(self.big, fit), score(self.small, fit))

    def test_raising_fit_weight_raises_score(self) -> None:
        low_fit = score(self.small, 0.1)
        high_fit = score(self.small, 0.9)
        self.assertGreater(high_fit, low_fit)


if __name__ == "__main__":
    unittest.main()
