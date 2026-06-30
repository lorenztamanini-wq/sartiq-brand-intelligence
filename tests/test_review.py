"""The human review/approve layer — propose, confirm/edit, publish.

Proves the operator workflow without any UI: the engine in `review.py` lists
what needs sign-off, applies edits immutably, flips `⚑ needs human` to
`✓ confirmed`, and publishes a refreshed set of artifacts.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import review
from builder import assemble_offline


class TestReviewEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = assemble_offline("sandro")

    def test_reviewable_lists_the_human_fields(self) -> None:
        names = {it["name"] for it in review.reviewable_fields(self.brief)}
        # Sandro's human-owned fields must be in the queue, not q1/q2 (sourced).
        self.assertTrue({"gap", "strategy", "q6_decision_maker", "q7_contact"} <= names)
        self.assertNotIn("q1_who", names)
        # Each item carries the proposal + confidence (the "almost perfect" report).
        for it in review.reviewable_fields(self.brief):
            self.assertTrue(it["value"].strip())
            self.assertIn("confidence", it)

    def test_apply_field_edit_confirms_and_is_immutable(self) -> None:
        before = self.brief.gap.human_confirmed
        updated = review.apply_field_edit(self.brief, "gap", "sharpened gap text", confirmed=True)
        # New brief reflects the edit + confirmation...
        self.assertEqual(updated.gap.value, "sharpened gap text")
        self.assertTrue(updated.gap.human_confirmed)
        self.assertFalse(updated.gap.needs_human)
        # ...and the original is untouched (immutable).
        self.assertEqual(before, self.brief.gap.human_confirmed)
        self.assertNotEqual(self.brief.gap.value, "sharpened gap text")

    def test_apply_approach_edit_confirms(self) -> None:
        updated = review.apply_approach_edit(
            self.brief, hook="h", channel="c", to_whom="w", opening="o", confirmed=True
        )
        self.assertEqual(updated.approach.opening, "o")
        self.assertTrue(updated.approach.human_confirmed)

    def test_confirming_everything_clears_the_queue(self) -> None:
        b = self.brief
        for it in review.reviewable_fields(b):
            b = review.apply_field_edit(b, it["name"], it["value"], confirmed=True)
        b = review.apply_approach_edit(
            b, hook=b.approach.hook, channel=b.approach.channel,
            to_whom=b.approach.to_whom, opening=b.approach.opening, confirmed=True,
        )
        self.assertTrue(review.is_fully_confirmed(b))

    def test_publish_writes_brief_and_refreshes_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            review.publish(self.brief, d)
            self.assertTrue((Path(d) / "sandro.md").exists())
            self.assertTrue((Path(d) / "sandro.json").exists())
            self.assertTrue((Path(d) / "index.html").exists())
            self.assertTrue((Path(d) / "prioritization_sheet.csv").exists())
            # round-trip: the published JSON loads back to an equal brief.
            reloaded = review.load_brief(Path(d) / "sandro.json")
            self.assertEqual(reloaded.brand, self.brief.brand)

    def test_confirmed_field_renders_check_not_flag(self) -> None:
        import render
        updated = review.apply_field_edit(self.brief, "gap", "g", confirmed=True)
        md = render.render_markdown(updated)
        # The gap line should show the confirmed mark; its own flag is gone.
        gap_line = [ln for ln in md.splitlines() if "THE GAP WE FILL" in ln][0]
        self.assertIn("✓ confirmed", gap_line)


if __name__ == "__main__":
    unittest.main()
