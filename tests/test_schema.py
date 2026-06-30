"""Tests for the schema quality gate (models.FieldValue, models.Range).

The §12b "source or estimate, never blank" invariant is enforced in code:
construction must raise when a field is neither sourced nor a stated estimate.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from models import FieldValue, Range, Source


class TestFieldValueGate(unittest.TestCase):
    def test_no_sources_and_not_estimate_raises(self) -> None:
        with self.assertRaises(ValidationError):
            FieldValue(name="q1_who", value="something", is_estimate=False)

    def test_estimate_without_assumption_raises(self) -> None:
        with self.assertRaises(ValidationError):
            FieldValue(
                name="q4_content_need",
                value="~10k images/yr",
                is_estimate=True,
                assumption=None,
            )

    def test_sourced_field_constructs(self) -> None:
        fv = FieldValue(
            name="q1_who",
            value="Italy's leading value retailer",
            sources=[Source(title="Corporate site", url="https://example.com")],
        )
        self.assertEqual(fv.name, "q1_who")
        self.assertFalse(fv.is_estimate)

    def test_estimate_with_assumption_constructs(self) -> None:
        fv = FieldValue(
            name="q4_content_need",
            value="~10k images/yr",
            is_estimate=True,
            assumption="volume estimated from catalog turnover",
        )
        self.assertTrue(fv.is_estimate)
        self.assertEqual(fv.assumption, "volume estimated from catalog turnover")


class TestRangeReorder(unittest.TestCase):
    def test_reorders_low_high(self) -> None:
        self.assertEqual(Range(low=10, high=1).low, 1)


if __name__ == "__main__":
    unittest.main()
