"""Tests for the deterministic economic model (economics.py).

Exercises: Range reordering, the opportunity/partner-upside ranges over the
three ground-truth brands, the partner-upside identity, the sanity gate on
agreeing inputs, and the divergent-inputs failure case.
"""

from __future__ import annotations

import unittest

from config import load_benchmarks, load_ground_truth
from economics import compute_opportunity
from models import EconInputs, Range

# Relative tolerance for the partner-upside identity check.
_REL_TOL = 1e-6
_TARGET_SLUGS = ("ovs", "sandro", "diesel")


class TestRange(unittest.TestCase):
    def test_reorders_low_and_high(self) -> None:
        # Arrange / Act
        r = Range(low=10.0, high=1.0)

        # Assert
        self.assertEqual(r.low, 1.0)
        self.assertEqual(r.high, 10.0)


class TestComputeOpportunity(unittest.TestCase):
    def setUp(self) -> None:
        self.truth = load_ground_truth()
        self.benchmarks = load_benchmarks()

    def test_ranges_ordered_and_non_negative(self) -> None:
        for slug in _TARGET_SLUGS:
            with self.subTest(slug=slug):
                econ = compute_opportunity(
                    self.truth[slug].econ_inputs, self.benchmarks
                )
                opp = econ.annual_opportunity_range
                partner = econ.partner_upside_range

                self.assertLessEqual(opp.low, opp.high)
                self.assertLessEqual(partner.low, partner.high)
                self.assertGreaterEqual(opp.low, 0.0)
                self.assertGreaterEqual(partner.low, 0.0)

    def test_partner_upside_mid_equals_opportunity_times_mult_minus_one(self) -> None:
        for slug in _TARGET_SLUGS:
            with self.subTest(slug=slug):
                inp = self.truth[slug].econ_inputs
                econ = compute_opportunity(inp, self.benchmarks)

                expected = econ.annual_opportunity_range.mid * (
                    inp.partner_multiplier - 1.0
                )
                self.assertAlmostEqual(
                    econ.partner_upside_range.mid,
                    expected,
                    delta=abs(expected) * _REL_TOL + 1e-6,
                )

    def test_headline_is_capture_of_studio_spend(self) -> None:
        # The headline € is Sartiq's capture (~20%) of the brand's studio spend,
        # NOT the studio spend itself.
        cap = self.benchmarks.sartiq_capture_pct
        for slug in _TARGET_SLUGS:
            with self.subTest(slug=slug):
                econ = compute_opportunity(self.truth[slug].econ_inputs, self.benchmarks)
                self.assertAlmostEqual(
                    econ.annual_opportunity_range.low, econ.cost_today_range.low * cap, delta=1.0
                )
                self.assertAlmostEqual(
                    econ.annual_opportunity_range.high, econ.cost_today_range.high * cap, delta=1.0
                )

    def test_partner_breakdown_splits_the_group_upside(self) -> None:
        inp = self.truth["diesel"].econ_inputs.model_copy(
            update={"partners": ["A", "B", "C", "D"]}
        )
        econ = compute_opportunity(inp, self.benchmarks)
        self.assertEqual([p.name for p in econ.partner_breakdown], ["A", "B", "C", "D"])
        # even split → the lines sum to the combined partner upside
        self.assertAlmostEqual(
            sum(p.opportunity.low for p in econ.partner_breakdown),
            econ.partner_upside_range.low,
            delta=1.0,
        )
        self.assertAlmostEqual(
            sum(p.opportunity.high for p in econ.partner_breakdown),
            econ.partner_upside_range.high,
            delta=1.0,
        )

    def test_no_partners_means_no_breakdown(self) -> None:
        econ = compute_opportunity(self.truth["diesel"].econ_inputs, self.benchmarks)
        self.assertEqual(econ.partner_breakdown, [])

    def test_sanity_ok_for_all_three_targets(self) -> None:
        for slug in _TARGET_SLUGS:
            with self.subTest(slug=slug):
                econ = compute_opportunity(
                    self.truth[slug].econ_inputs, self.benchmarks
                )
                self.assertTrue(econ.sanity_ok)
                self.assertFalse(econ.needs_human)

    def test_divergent_inputs_fail_sanity_gate(self) -> None:
        # Arrange: a huge bottom-up volume against a tiny revenue makes the
        # bottom-up and top-down estimates diverge by >1 order of magnitude.
        divergent = EconInputs(
            new_skus_per_year=5_000_000,
            shots_per_sku=8.0,
            channel_variants=5.0,
            refresh_factor=1.0,
            carryover_skus=2_000_000,
            revenue_eur=50_000.0,
            partner_multiplier=2.0,
            assumptions=["deliberately divergent: huge catalog, tiny revenue"],
        )

        # Act
        econ = compute_opportunity(divergent, self.benchmarks)

        # Assert
        self.assertFalse(econ.sanity_ok)
        self.assertTrue(econ.needs_human)


if __name__ == "__main__":
    unittest.main()
