"""Cross-cutting invariants the briefs and economics promise.

Strengthens coverage of: the annual-images band, the top-down formula pinned
independently of the sanity gate, the partner-upside band endpoints, the §12b
"never blank" promise end-to-end, the offline negative path, and the Diesel
SPLIT read — plus a digit (not just a € sign) in the rendered output.
"""

from __future__ import annotations

import re
import unittest

import economics
from builder import assemble_offline
from config import load_benchmarks, load_ground_truth
from render import render_markdown
from sheet import rank_briefs, row_for

_SLUGS = ("ovs", "sandro", "diesel")
_TOL = 1.0  # euro tolerance for float identities


class TestEconomicInvariants(unittest.TestCase):
    def setUp(self) -> None:
        self.bm = load_benchmarks()
        self.truth = load_ground_truth()

    def test_annual_images_positive_and_ordered(self) -> None:
        for slug in _SLUGS:
            band = economics._annual_images(self.truth[slug].econ_inputs)
            with self.subTest(slug=slug):
                self.assertGreater(band.low, 0)
                self.assertLessEqual(band.low, band.high)

    def test_topdown_matches_formula(self) -> None:
        # Pin the cross-check formula so a silent break (e.g. dropped ecom
        # factor) is caught even though the sanity gate would just shift.
        inp = self.truth["sandro"].econ_inputs
        econ = economics.compute_opportunity(inp, self.bm)
        exp_low = (
            inp.revenue_eur
            * self.bm.visual_spend_pct_of_revenue.low
            * self.bm.ecom_imagery_subset_pct.low
        )
        exp_high = (
            inp.revenue_eur
            * self.bm.visual_spend_pct_of_revenue.high
            * self.bm.ecom_imagery_subset_pct.high
        )
        self.assertAlmostEqual(econ.topdown_range.low, exp_low, delta=_TOL)
        self.assertAlmostEqual(econ.topdown_range.high, exp_high, delta=_TOL)

    def test_partner_upside_band_endpoints(self) -> None:
        for slug in _SLUGS:
            inp = self.truth[slug].econ_inputs
            econ = economics.compute_opportunity(inp, self.bm)
            extra = inp.partner_multiplier - 1.0
            with self.subTest(slug=slug):
                self.assertAlmostEqual(
                    econ.partner_upside_range.low,
                    econ.annual_opportunity_range.low * extra,
                    delta=_TOL,
                )
                self.assertAlmostEqual(
                    econ.partner_upside_range.high,
                    econ.annual_opportunity_range.high * extra,
                    delta=_TOL,
                )


class TestBriefInvariants(unittest.TestCase):
    def setUp(self) -> None:
        self.briefs = {s: assemble_offline(s) for s in _SLUGS}

    def test_no_brief_field_is_blank(self) -> None:
        for slug, b in self.briefs.items():
            with self.subTest(slug=slug):
                for fv in b.all_fields():
                    self.assertTrue(fv.value.strip(), f"{slug}:{fv.name} blank")
                for attr in ("positioning", "markets", "parent_group", "confidence_note"):
                    self.assertTrue(getattr(b, attr).strip(), f"{slug}:{attr} blank")
                self.assertTrue(b.approach.hook.strip())
                self.assertTrue(b.approach.opening.strip())

    def test_unknown_slug_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            assemble_offline("gucci")

    def test_diesel_momentum_is_split(self) -> None:
        # The sharpest read in the set: brand vs parent diverge.
        self.assertIn("SPLIT", self.briefs["diesel"].q3_momentum.value)
        self.assertTrue(self.briefs["diesel"].q3_momentum.needs_human)

    def test_direction_is_evidenced_and_cites_a_snapshot(self) -> None:
        # P1.1: every DIRECTION states a call AND cites a historical snapshot.
        for slug, b in self.briefs.items():
            with self.subTest(slug=slug):
                d = b.q2_direction
                self.assertTrue(d.value.strip())
                self.assertTrue(d.sources, f"{slug} direction has no sources")
                urls = " ".join(s.url or "" for s in d.sources)
                self.assertIn("web.archive.org", urls, f"{slug} direction cites no snapshot")


class TestRenderAndSheetContent(unittest.TestCase):
    def setUp(self) -> None:
        self.briefs = [assemble_offline(s) for s in _SLUGS]

    def test_render_has_a_euro_figure_with_digits(self) -> None:
        md = render_markdown(self.briefs[0])
        self.assertRegex(md, r"€\s?\d[\d.,]*")  # a number, not just a € sign

    def test_sheet_row_carries_brand_euro_and_brief_link(self) -> None:
        ranked = rank_briefs(self.briefs)
        row = row_for(ranked[0])
        self.assertEqual(row["rank"], 1)
        self.assertTrue(row["brand"])
        self.assertRegex(row["opportunity_eur"], r"€\d")
        self.assertTrue(row["brief_file"].endswith(".md"))


if __name__ == "__main__":
    unittest.main()
