"""Tests for the offline brief assembler (builder.assemble_offline).

Exercises the full deterministic path for the three seeded brands: every
question field is present and non-empty, gap/strategy are populated, at least
one field is human-sharpened, Diesel's q3 momentum is flagged needs_human
(SPLIT), economics pass the sanity gate, the score is in range, and the Brief
round-trips through JSON.
"""

from __future__ import annotations

import json
import unittest

from builder import assemble_offline
from models import Brief

_TARGET_SLUGS = ("ovs", "sandro", "diesel")


class TestOfflineBrief(unittest.TestCase):
    def setUp(self) -> None:
        self.briefs = {slug: assemble_offline(slug) for slug in _TARGET_SLUGS}

    def test_all_seven_questions_present_and_non_empty(self) -> None:
        question_attrs = (
            "q1_who",
            "q2_direction",
            "q3_momentum",
            "q5_pdp",
            "q4_content_need",
            "q6_decision_maker",
            "q7_contact",
        )
        for slug, brief in self.briefs.items():
            for attr in question_attrs:
                with self.subTest(slug=slug, field=attr):
                    fv = getattr(brief, attr)
                    self.assertTrue(fv.value.strip(), f"{attr} is empty")

    def test_gap_and_strategy_present(self) -> None:
        for slug, brief in self.briefs.items():
            with self.subTest(slug=slug):
                self.assertTrue(brief.gap.value.strip())
                self.assertTrue(brief.strategy.value.strip())

    def test_at_least_one_human_sharpened_field(self) -> None:
        for slug, brief in self.briefs.items():
            with self.subTest(slug=slug):
                sharpened = [fv for fv in brief.all_fields() if fv.human_sharpened]
                # The approach is not part of all_fields(); count it too.
                if brief.approach.human_sharpened:
                    sharpened.append(brief.approach)
                self.assertGreaterEqual(len(sharpened), 1)

    def test_diesel_q3_momentum_needs_human(self) -> None:
        self.assertTrue(self.briefs["diesel"].q3_momentum.needs_human)

    def test_economics_sanity_ok(self) -> None:
        for slug, brief in self.briefs.items():
            with self.subTest(slug=slug):
                self.assertTrue(brief.economics.sanity_ok)

    def test_score_in_zero_to_five(self) -> None:
        for slug, brief in self.briefs.items():
            with self.subTest(slug=slug):
                self.assertGreaterEqual(brief.opportunity_score, 0.0)
                self.assertLessEqual(brief.opportunity_score, 5.0)

    def test_json_round_trips(self) -> None:
        for slug, brief in self.briefs.items():
            with self.subTest(slug=slug):
                raw = brief.model_dump_json()
                data = json.loads(raw)
                self.assertEqual(data["brand"], brief.brand)
                # Re-validate the parsed payload back into the model.
                rebuilt = Brief.model_validate(data)
                self.assertEqual(rebuilt.brand, brief.brand)


if __name__ == "__main__":
    unittest.main()
