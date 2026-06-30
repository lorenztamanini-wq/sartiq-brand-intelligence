"""P3.1 — a re-dig must never clobber a human-confirmed brief."""

from __future__ import annotations

import tempfile
import unittest

import builder
import render
import review


class TestRedigGuard(unittest.TestCase):
    def test_load_confirmed_preserves_confirmed_values(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            confirmed = review.apply_field_edit(
                builder.assemble_offline("sandro"),
                "q6_decision_maker",
                "Jane Doe, CMO",
                confirmed=True,
            )
            render.write_outputs(confirmed, d, want_pdf=False)

            fresh = builder.assemble_offline("sandro")  # unconfirmed re-dig
            kept = render.load_confirmed(fresh, d)

            self.assertIsNotNone(kept)
            self.assertEqual(kept.q6_decision_maker.value, "Jane Doe, CMO")
            self.assertTrue(kept.q6_decision_maker.human_confirmed)

    def test_load_confirmed_is_none_for_unconfirmed_record(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            render.write_outputs(builder.assemble_offline("sandro"), d, want_pdf=False)
            self.assertIsNone(render.load_confirmed(builder.assemble_offline("sandro"), d))

    def test_load_confirmed_is_none_when_no_record_exists(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(render.load_confirmed(builder.assemble_offline("sandro"), d))


if __name__ == "__main__":
    unittest.main()
