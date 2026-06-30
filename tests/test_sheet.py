"""Tests for the prioritization sheet (sheet.py).

Exercises ranking (sorted by score desc with distinct, contiguous 1..N ranks)
and that write_sheet lands the CSV + Markdown artefacts in a temp directory.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from builder import assemble_offline
from sheet import rank_briefs, write_sheet

_TARGET_SLUGS = ("ovs", "sandro", "diesel")


class TestSheet(unittest.TestCase):
    def setUp(self) -> None:
        self.briefs = [assemble_offline(slug) for slug in _TARGET_SLUGS]

    def test_rank_briefs_sorts_desc_and_sets_contiguous_ranks(self) -> None:
        ranked = rank_briefs(self.briefs)

        # Scores are non-increasing down the ranked list.
        scores = [b.opportunity_score for b in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

        # Ranks are exactly 1..N, distinct and contiguous.
        ranks = [b.rank for b in ranked]
        self.assertEqual(ranks, list(range(1, len(self.briefs) + 1)))
        self.assertEqual(len(set(ranks)), len(self.briefs))

    def test_write_sheet_creates_csv_and_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = write_sheet(self.briefs, tmp)

            csv_path = Path(result["csv"])
            md_path = Path(result["md"])
            self.assertEqual(csv_path.name, "prioritization_sheet.csv")
            self.assertEqual(md_path.name, "prioritization_sheet.md")
            self.assertTrue(csv_path.is_file())
            self.assertTrue(md_path.is_file())
            self.assertTrue(csv_path.read_text(encoding="utf-8").strip())
            self.assertTrue(md_path.read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    unittest.main()
