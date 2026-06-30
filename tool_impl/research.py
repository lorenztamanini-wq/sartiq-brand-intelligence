"""Page fetch + parse tool.

A single, well-behaved HTTP GET that degrades gracefully: it never raises to
the agent loop. On any failure (network down, bad status, parse error) it
returns the same dict shape with `error` set and sensible empties, so the
tool-use loop always gets a JSON-serializable result.

Only the always-present libs are used (`httpx`, `bs4`, `lxml`). Nothing heavy
or optional is imported here.
"""

from __future__ import annotations

import json

import httpx
from bs4 import BeautifulSoup

# Truncate extracted body text so a tool_result stays bounded for the loop.
MAX_TEXT_CHARS = 8000

# A desktop UA so sites serve the full (non-mobile, non-bot) page.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _empty(url: str, *, status: int | None = None, error: str | None = None) -> dict:
    """The canonical result shape, with empties for the partial/error path."""
    return {
        "url": url,
        "status": status,
        "title": "",
        "text": "",
        "json_ld": [],
        "error": error,
    }


def _extract_json_ld(soup: BeautifulSoup) -> list:
    """Parse every <script type="application/ld+json"> block, skipping bad ones."""
    blocks: list = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except (ValueError, TypeError):
            # Malformed JSON-LD is common in the wild — skip silently.
            continue
    return blocks


def _visible_text(soup: BeautifulSoup) -> str:
    """Collapse the document's visible text, dropping script/style noise."""
    for noise in soup(["script", "style", "noscript", "template"]):
        noise.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text[:MAX_TEXT_CHARS]


def fetch_page(url: str, *, timeout: float = 20) -> dict:
    """GET a URL and extract title, visible text, and JSON-LD blocks.

    Returns a dict with keys: ``url``, ``status`` (int|None), ``title``,
    ``text`` (truncated to ~8k chars), ``json_ld`` (list), ``error`` (str|None).
    Never raises: on any exception the dict is returned with ``error`` set and
    sensible empties.
    """
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never raise.
        return _empty(url, error=f"{type(exc).__name__}: {exc}")

    status = response.status_code
    try:
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        json_ld = _extract_json_ld(soup)
        text = _visible_text(soup)
    except Exception as exc:  # noqa: BLE001 — parse failures degrade too.
        return _empty(url, status=status, error=f"parse: {type(exc).__name__}: {exc}")

    return {
        "url": str(response.url),
        "status": status,
        "title": title,
        "text": text,
        "json_ld": json_ld,
        "error": None,
    }
