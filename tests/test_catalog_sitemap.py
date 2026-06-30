"""Catalog sitemap enumeration (P3) — deterministic, no network.

Covers the new `usp`-primary path (`_via_usp`) by stubbing the sitemap tree, plus
the legacy lxml sitemap filter. No live fetch happens in these tests.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tool_impl import catalog


class _StubPage:
    def __init__(self, url: str) -> None:
        self.url = url


class _StubTree:
    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    def all_pages(self):
        return [_StubPage(u) for u in self._urls]


_USP = "usp.tree.sitemap_tree_for_homepage"


class TestViaUsp(unittest.TestCase):
    def test_filters_host_and_products_and_dedupes(self) -> None:
        urls = [
            "https://brand.com/products/red-dress",
            "https://brand.com/products/blue-coat",
            "https://brand.com/products/red-dress",  # duplicate
            "https://brand.com/about",               # same host, not a product
            "https://www.brand.com/p/shoe-123",      # www == brand.com host
            "https://evil.com/products/x",           # cross-host -> dropped (SSRF)
        ]
        with patch(_USP, return_value=_StubTree(urls)):
            out = catalog._via_usp(None, "https://brand.com", 60)

        self.assertEqual(out["source"], "sitemap_usp")
        self.assertEqual(
            set(out["product_urls"]),
            {
                "https://brand.com/products/red-dress",
                "https://brand.com/products/blue-coat",
                "https://www.brand.com/p/shoe-123",
            },
        )
        # total counts every SAME-HOST page (incl. the dup + the non-product), not evil.com
        self.assertEqual(out["catalog_size_estimate"], 5)

    def test_returns_none_when_no_products(self) -> None:
        with patch(_USP, return_value=_StubTree(["https://brand.com/about"])):
            self.assertIsNone(catalog._via_usp(None, "https://brand.com", 60))

    def test_returns_none_on_failure(self) -> None:
        with patch(_USP, side_effect=Exception("boom")):
            self.assertIsNone(catalog._via_usp(None, "https://brand.com", 60))


class TestLegacySitemapFilter(unittest.TestCase):
    SITEMAP_XML = (
        b'<?xml version="1.0"?>'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://brand.com/products/a</loc></url>"
        b"<url><loc>https://brand.com/products/b</loc></url>"
        b"<url><loc>https://brand.com/about-us</loc></url>"
        b"</urlset>"
    )

    def test_parses_locs_and_filters_products(self) -> None:
        locs = catalog._parse_sitemap_locs(self.SITEMAP_XML)
        self.assertEqual(len(locs), 3)
        products = [u for u in locs if catalog._looks_like_product(u)]
        self.assertEqual(
            products,
            ["https://brand.com/products/a", "https://brand.com/products/b"],
        )


if __name__ == "__main__":
    unittest.main()
