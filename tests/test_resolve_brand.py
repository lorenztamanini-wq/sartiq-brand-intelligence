"""config.resolve_brand — free-text / alias / site-domain -> slug, or None.

The URL-normalization branch (strip scheme + www, trailing slash) is the most
error-prone part of a frozen-spine function the agent depends on.
"""

from __future__ import annotations

import unittest

from config import load_ground_truth, resolve_brand


class TestResolveBrand(unittest.TestCase):
    def setUp(self) -> None:
        self.truth = load_ground_truth()

    def test_exact_name_case_insensitive(self) -> None:
        self.assertEqual(resolve_brand("OVS", self.truth), "ovs")
        self.assertEqual(resolve_brand("sandro", self.truth), "sandro")

    def test_alias_resolves(self) -> None:
        # 'otb' is a seeded alias of Diesel; 'smcp' of Sandro.
        self.assertEqual(resolve_brand("otb", self.truth), "diesel")
        self.assertEqual(resolve_brand("SMCP", self.truth), "sandro")

    def test_site_domain_with_scheme_and_www(self) -> None:
        self.assertEqual(resolve_brand("https://www.diesel.com/", self.truth), "diesel")
        self.assertEqual(resolve_brand("ovs.it", self.truth), "ovs")

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(resolve_brand("Gucci", self.truth))
        self.assertIsNone(resolve_brand("", self.truth))


if __name__ == "__main__":
    unittest.main()
