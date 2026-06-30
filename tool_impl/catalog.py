"""Catalog discovery and PDP auditing — live-mode network tools.

`list_catalog` finds likely product URLs and estimates catalog size by trying,
in order: ultimate-sitemap-parser (gzip/sitemap-index/robots.txt discovery), a
raw sitemap.xml fetch (and nested product sitemaps), the Shopify
`/products.json` endpoint, then a category-page link scrape. `audit_pdp` reads
one product page for imagery + JSON-LD, rendering with Playwright when present
(catches lazy-loaded srcset images) and falling back to httpx + bs4 otherwise.

Both degrade gracefully: a missing heavy dep or a network failure returns a
partial dict with an `error` note rather than raising into the agent loop.
Playwright is a missing dependency and is therefore lazy-imported inside the
function that needs it — never at module top level.
"""

from __future__ import annotations

import json
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# A path looks like a product detail page if it carries one of these markers.
_PRODUCT_HINTS = ("/products/", "/product/", "/p/", "/shop/", "/item/", "/dp/")
# Sitemaps whose URL suggests they enumerate products (Shopify-style and generic).
_PRODUCT_SITEMAP_HINTS = ("product", "products")
# Hard cap on the usp sitemap sweep: it probes many URLs with retries and can run
# for minutes on broken/hostile sitemaps (e.g. diesel.com), burning the dig budget.
_USP_TIMEOUT_S = 15

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SartiqBrandBot/1.0; +https://sartiq.example)"
    )
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _normalize_site(site: str) -> str:
    """Coerce a free-text site into a clean ``https://<host>`` origin."""
    raw = (site or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc or parsed.path.split("/")[0]
    return f"https://{host}".rstrip("/")


def _looks_like_product(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(hint in path for hint in _PRODUCT_HINTS)


def _same_host(url_a: str, url_b: str) -> bool:
    """Hosts match ignoring a leading ``www.`` — SSRF guard + www-mismatch fix.

    Child sitemaps and scraped links are only followed when they stay on the
    brand's own host, so a crafted sitemap pointing at an internal address
    (e.g. ``http://169.254.169.254/...``) is never fetched.
    """
    def host(u: str) -> str:
        return urlparse(u).netloc.lower().removeprefix("www.")

    return host(url_a) == host(url_b)


def _dedupe(urls: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
            if len(out) >= limit:
                break
    return out


def _parse_sitemap_locs(xml_bytes: bytes) -> list[str]:
    """Return every ``<loc>`` URL in a sitemap or sitemap index, via lxml."""
    from lxml import etree  # present offline; kept local for symmetry

    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return []
    # Namespace-agnostic: match any element whose local-name is "loc".
    return [
        (el.text or "").strip()
        for el in root.iter()
        if etree.QName(el).localname == "loc" and el.text
    ]


# --------------------------------------------------------------------------- #
# Catalog discovery
# --------------------------------------------------------------------------- #
def list_catalog(site: str, *, timeout: float = 20, max_items: int = 60) -> dict:
    """Discover product URLs and estimate catalog size for ``site``.

    Tries sitemap.xml (resolving nested product sitemaps), then the Shopify
    ``/products.json`` endpoint, then a category-page link scrape. Returns the
    first strategy that yields product URLs; on total failure returns an empty
    list with an ``error`` note. Never raises.
    """
    origin = _normalize_site(site)
    result: dict = {
        "catalog_size_estimate": None,
        "product_urls": [],
        "source": "none",
        "error": None,
    }
    if not origin:
        result["error"] = "no site provided"
        return result

    errors: list[str] = []
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            for strategy in (_via_usp, _via_sitemap, _via_shopify, _via_category_scrape):
                try:
                    found = strategy(client, origin, max_items)
                except Exception as exc:  # one strategy failing must not abort
                    errors.append(f"{strategy.__name__}: {exc}")
                    continue
                if found and found["product_urls"]:
                    return found
                if found and found.get("catalog_size_estimate") is not None:
                    # Sitemap existed but held no obvious PDPs — keep the count.
                    result["catalog_size_estimate"] = found["catalog_size_estimate"]
                    result["source"] = found["source"]
    except Exception as exc:  # client construction / unexpected failure
        errors.append(str(exc))

    if errors:
        result["error"] = "; ".join(errors)
    return result


def _via_usp(client: httpx.Client, origin: str, max_items: int) -> dict | None:
    """Primary sitemap path via ultimate-sitemap-parser.

    `usp` handles what the raw ``/sitemap.xml`` fetch misses: gzip ``.xml.gz``
    sitemaps, sitemap-index trees, robots.txt ``Sitemap:`` discovery, and
    per-region indexes — common on big retailers and Shopify. Lazy-imported
    (live-only, pulls `requests`); returns ``None`` on any failure so the legacy
    `_via_sitemap` / Shopify / category strategies still run. The ``client`` arg
    is unused (usp uses its own fetcher) but kept for a uniform strategy signature.
    """
    try:
        import logging

        from usp.tree import sitemap_tree_for_homepage  # lazy: missing/heavy dep

        # usp logs every candidate sitemap URL it probes (a flood on sites with
        # broken/non-standard sitemaps, e.g. diesel.com). Quiet it to errors only —
        # set the parent + any already-created child loggers.
        logging.getLogger("usp").setLevel(logging.ERROR)
        for _name in list(logging.root.manager.loggerDict):
            if _name == "usp" or _name.startswith("usp."):
                logging.getLogger(_name).setLevel(logging.ERROR)
    except Exception:
        return None

    # Run the sweep in a daemon thread with a hard timeout — usp does its own
    # multi-URL probing + retries and will not return quickly on a hostile site.
    # On timeout we abandon it (the daemon dies with the process) and fall back.
    import threading

    box: dict = {}

    def _fetch() -> None:
        try:
            box["pages"] = list(sitemap_tree_for_homepage(origin).all_pages())
        except Exception:  # noqa: BLE001
            box["error"] = True

    worker = threading.Thread(target=_fetch, daemon=True)
    worker.start()
    worker.join(_USP_TIMEOUT_S)
    pages = box.get("pages")
    if pages is None:  # timed out (still running) or errored -> fall back
        return None

    products: list[str] = []
    total = 0
    _CAP = 50_000  # runaway guard on enormous catalogs
    for page in pages:
        url = getattr(page, "url", None)
        # SSRF guard + relevance: only the brand's own host counts.
        if not url or not _same_host(url, origin):
            continue
        total += 1
        if _looks_like_product(url) and len(products) < max_items * 4:
            products.append(url)
        if total >= _CAP:
            break

    if not products:
        return None
    return {
        "catalog_size_estimate": total or None,
        "product_urls": _dedupe(products, max_items),
        "source": "sitemap_usp",
        "error": None,
    }


def _via_sitemap(client: httpx.Client, origin: str, max_items: int) -> dict | None:
    """Read /sitemap.xml, descend into product sitemaps, collect PDP URLs."""
    resp = client.get(f"{origin}/sitemap.xml")
    if resp.status_code >= 400 or not resp.content:
        return None

    locs = _parse_sitemap_locs(resp.content)
    if not locs:
        return None

    # Split direct page URLs from nested sitemap references.
    nested = [u for u in locs if u.lower().endswith(".xml")]
    direct = [u for u in locs if not u.lower().endswith(".xml")]

    all_urls: list[str] = list(direct)
    total_count = len(direct)

    # Prefer product-named child sitemaps; fall back to all nested sitemaps.
    product_sitemaps = [
        u for u in nested if any(h in u.lower() for h in _PRODUCT_SITEMAP_HINTS)
    ] or nested
    for sm_url in product_sitemaps:
        if len(all_urls) >= max_items * 3 and total_count > 0:
            break
        # SSRF guard: only descend into child sitemaps on the brand's own host.
        if not _same_host(sm_url, origin):
            continue
        try:
            child = client.get(sm_url)
        except Exception:
            continue
        if child.status_code >= 400 or not child.content:
            continue
        child_locs = [
            u for u in _parse_sitemap_locs(child.content)
            if not u.lower().endswith(".xml")
        ]
        all_urls.extend(child_locs)
        total_count += len(child_locs)

    products = [u for u in all_urls if _looks_like_product(u)]
    return {
        "catalog_size_estimate": (total_count or None),
        "product_urls": _dedupe(products, max_items),
        "source": "sitemap",
        "error": None,
    }


def _via_shopify(client: httpx.Client, origin: str, max_items: int) -> dict | None:
    """Page the Shopify ``/products.json`` endpoint for handles -> PDP URLs."""
    urls: list[str] = []
    total = 0
    page = 1
    while len(urls) < max_items and page <= 10:
        resp = client.get(
            f"{origin}/products.json", params={"limit": 250, "page": page}
        )
        if resp.status_code >= 400:
            break
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype.lower():
            break
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            break
        products = payload.get("products") if isinstance(payload, dict) else None
        if not products:
            break
        for prod in products:
            handle = prod.get("handle") if isinstance(prod, dict) else None
            if handle:
                urls.append(f"{origin}/products/{handle}")
        total += len(products)
        if len(products) < 250:  # last page reached
            break
        page += 1

    if not urls and total == 0:
        return None
    return {
        "catalog_size_estimate": (total or None),
        "product_urls": _dedupe(urls, max_items),
        "source": "shopify_products_json",
        "error": None,
    }


def _via_category_scrape(
    client: httpx.Client, origin: str, max_items: int
) -> dict | None:
    """Last resort: scrape the homepage for links that look like PDPs."""
    resp = client.get(origin)
    if resp.status_code >= 400 or not resp.text:
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        absolute = urljoin(origin + "/", a["href"])
        # Keep same-host product-looking links only (www-insensitive).
        if not _same_host(absolute, origin):
            continue
        if _looks_like_product(absolute):
            candidates.append(absolute.split("#")[0])
    if not candidates:
        return None
    return {
        "catalog_size_estimate": None,  # a scrape cannot estimate the full catalog
        "product_urls": _dedupe(candidates, max_items),
        "source": "category_scrape",
        "error": None,
    }


# --------------------------------------------------------------------------- #
# PDP audit
# --------------------------------------------------------------------------- #
def audit_pdp(url: str, *, timeout: float = 20) -> dict:
    """Collect image URLs + JSON-LD from one product page. Never raises.

    Renders with Playwright when it is installed (so lazy-loaded ``srcset``
    imagery is captured); otherwise falls back to a static httpx + bs4 fetch
    that still mines ``<img>`` tags and JSON-LD image arrays.
    """
    result: dict = {
        "url": url,
        "images": [],
        "json_ld": [],
        "rendered_with": "httpx",
        "error": None,
    }
    if not url:
        result["error"] = "no url provided"
        return result

    rendered = _audit_with_playwright(url, timeout)
    if rendered is not None:
        return rendered

    return _audit_with_httpx(url, timeout, result)


def _audit_with_playwright(url: str, timeout: float) -> dict | None:
    """Render with a headless Chromium if Playwright is available.

    Returns a populated result dict on success, or ``None`` if Playwright is
    not installed or the render failed — in which case the caller falls back to
    the static httpx path.
    """
    try:
        from playwright.sync_api import sync_playwright  # lazy: missing dep
    except Exception:
        return None

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                html = page.content()
                # Pull rendered <img> src + every srcset candidate directly.
                raw_images = page.eval_on_selector_all(
                    "img",
                    """els => els.flatMap(img => {
                        const out = [];
                        if (img.currentSrc) out.push(img.currentSrc);
                        if (img.src) out.push(img.src);
                        const ss = img.getAttribute('srcset');
                        if (ss) ss.split(',').forEach(p => {
                            const u = p.trim().split(/\\s+/)[0];
                            if (u) out.push(u);
                        });
                        return out;
                    })""",
                )
            finally:
                browser.close()
    except Exception as exc:
        return {
            "url": url,
            "images": [],
            "json_ld": [],
            "rendered_with": "httpx",
            "error": f"playwright render failed: {exc}",
        }

    soup = BeautifulSoup(html, "lxml")
    json_ld = _extract_json_ld(soup)
    images = _clean_images(url, raw_images + _json_ld_images(json_ld))
    return {
        "url": url,
        "images": images,
        "json_ld": json_ld,
        "rendered_with": "playwright",
        "error": None,
    }


def _audit_with_httpx(url: str, timeout: float, result: dict) -> dict:
    """Static fetch fallback: bs4 ``<img>`` + JSON-LD image arrays."""
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = client.get(url)
        resp.raise_for_status()
    except Exception as exc:
        result["error"] = str(exc)
        return result

    soup = BeautifulSoup(resp.text, "lxml")
    json_ld = _extract_json_ld(soup)
    raw: list[str] = []
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-srcset", "srcset"):
            val = img.get(attr)
            if not val:
                continue
            if attr.endswith("srcset"):
                raw.extend(part.strip().split(" ")[0] for part in val.split(","))
            else:
                raw.append(val)
    raw.extend(_json_ld_images(json_ld))
    result["images"] = _clean_images(url, raw)
    result["json_ld"] = json_ld
    return result


def _extract_json_ld(soup: BeautifulSoup) -> list:
    """Parse every ``<script type="application/ld+json">`` block."""
    blocks: list = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = tag.string or tag.get_text() or ""
        text = text.strip()
        if not text:
            continue
        try:
            blocks.append(json.loads(text))
        except (json.JSONDecodeError, ValueError):
            continue
    return blocks


def _json_ld_images(blocks: list) -> list[str]:
    """Pull ``image`` URLs out of JSON-LD product blocks (str | list | dict)."""
    out: list[str] = []

    def _collect(node: object) -> None:
        if isinstance(node, dict):
            img = node.get("image")
            if isinstance(img, str):
                out.append(img)
            elif isinstance(img, list):
                for item in img:
                    if isinstance(item, str):
                        out.append(item)
                    elif isinstance(item, dict) and isinstance(item.get("url"), str):
                        out.append(item["url"])
            elif isinstance(img, dict) and isinstance(img.get("url"), str):
                out.append(img["url"])
            for val in node.values():
                if isinstance(val, (list, dict)):
                    _collect(val)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    for block in blocks:
        _collect(block)
    return out


def _clean_images(base_url: str, images: list[str]) -> list[str]:
    """Absolutize, drop data URIs, and dedupe while preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for img in images:
        if not img or img.startswith("data:"):
            continue
        absolute = urljoin(base_url, img.strip())
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out
