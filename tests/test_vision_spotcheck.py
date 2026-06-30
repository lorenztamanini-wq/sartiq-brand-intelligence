"""Vision spot-check (§12b) — agreement math, baseline, and brief integration."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import config
from builder import assemble_offline
from tool_impl import vision


class TestVisionSpotcheck(unittest.TestCase):
    def test_agreement_math(self) -> None:
        self.assertEqual(vision.agreement(["a", "b", "c"], ["a", "b", "c"]), 1.0)
        self.assertEqual(vision.agreement(["a", "x"], ["a", "b"]), 0.5)
        self.assertEqual(vision.agreement([None, "a"], ["a", "a"]), 1.0)  # None skipped
        self.assertEqual(vision.agreement([], []), 0.0)

    def test_spotcheck_baseline_offline(self) -> None:
        sc = vision.spotcheck(settings=None)
        self.assertEqual(sc["mode"], "baseline")
        self.assertGreaterEqual(sc["n"], 10)
        self.assertTrue(0.0 <= sc["agreement"] <= 1.0)
        # the fixtures have one deliberate miss (flat_lay read as still_life)
        self.assertAlmostEqual(sc["agreement"], 11 / 12, places=2)

    def test_confidence_line_is_rendered(self) -> None:
        line = vision.confidence_line(None)
        self.assertIn("Vision spot-check", line)
        self.assertRegex(line, r"\d+% classifier agreement on \d+ labelled samples")

    def test_every_brief_shows_the_vision_figure(self) -> None:
        for slug in ("ovs", "sandro", "diesel"):
            with self.subTest(slug=slug):
                self.assertIn("Vision spot-check", assemble_offline(slug).confidence_note)

    def test_live_with_no_resolved_images_falls_back_to_baseline(self) -> None:
        # Regression: fixture URLs that 404 must NOT print a misleading "0% (this run)".
        s = config.Settings()
        s.anthropic_api_key = "sk-test-not-real"
        with patch.object(vision, "classify_images", return_value={"classifications": []}):
            sc = vision.spotcheck(s)
        self.assertEqual(sc["mode"], "baseline")
        self.assertGreater(sc["agreement"], 0.0)  # the credible baseline, not 0%

    def test_live_with_valid_predictions_reports_this_run(self) -> None:
        s = config.Settings()
        s.anthropic_api_key = "sk-test-not-real"
        samples = vision._load_fixtures()
        perfect = {"classifications": [{"label": x["label"]} for x in samples]}
        with patch.object(vision, "classify_images", return_value=perfect):
            sc = vision.spotcheck(s)
        self.assertEqual(sc["mode"], "live")
        self.assertEqual(sc["agreement"], 1.0)
        self.assertEqual(sc["n"], len(samples))


def _cls(pairs):
    return {"classifications": [{"url": u, "label": l} for u, l in pairs]}


class TestVisionSelfConsistency(unittest.TestCase):
    def _live(self):
        s = config.Settings()
        s.anthropic_api_key = "sk-test-not-real"
        return s

    def test_offline_returns_none(self) -> None:
        self.assertIsNone(vision.self_consistency(["u1", "u2", "u3"], settings=None))

    def test_too_few_images_returns_none(self) -> None:
        self.assertIsNone(vision.self_consistency(["u1", "u2"], self._live()))

    def test_agreeing_passes_score_1(self) -> None:
        urls = ["u1", "u2", "u3", "u4"]
        p = _cls([("u1", "on_model"), ("u2", "still_life"), ("u3", "on_model"), ("u4", "video")])
        with patch.object(vision, "classify_images", side_effect=[p, p]):
            sc = vision.self_consistency(urls, self._live())
        self.assertEqual(sc["mode"], "self_consistency")
        self.assertEqual(sc["agreement"], 1.0)
        self.assertEqual(sc["n"], 4)

    def test_partial_disagreement(self) -> None:
        urls = ["u1", "u2", "u3", "u4"]
        a = _cls([("u1", "on_model"), ("u2", "still_life"), ("u3", "on_model"), ("u4", "video")])
        b = _cls([("u1", "on_model"), ("u2", "flat_lay"), ("u3", "on_model"), ("u4", "video")])
        with patch.object(vision, "classify_images", side_effect=[a, b]):
            sc = vision.self_consistency(urls, self._live())
        self.assertEqual(sc["agreement"], 0.75)
        self.assertEqual(sc["n"], 4)

    def test_confidence_line_prefers_self_consistency_live(self) -> None:
        urls = ["u1", "u2", "u3"]
        p = _cls([("u1", "on_model"), ("u2", "still_life"), ("u3", "on_model")])
        with patch.object(vision, "classify_images", side_effect=[p, p]):
            line = vision.confidence_line(self._live(), images=urls)
        self.assertIn("Vision self-consistency", line)
        self.assertIn("from this run", line)

    def test_confidence_line_offline_still_baseline(self) -> None:
        # No images / no key -> the existing held-out baseline wording is preserved.
        self.assertIn("held-out baseline", vision.confidence_line(None))


if __name__ == "__main__":
    unittest.main()
