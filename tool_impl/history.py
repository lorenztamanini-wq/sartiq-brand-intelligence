"""Wayback Machine history sampling via the archive.org CDX API.

Answers "how has this brand's visual presence evolved?" by sampling roughly one
snapshot per year for the most recent N years. Uses only `httpx` (already
present); never raises to the agent loop — a network or parse failure returns a
partial dict with an `error` note and an honest `coverage` string.
"""

from __future__ import annotations

from datetime import datetime, timezone

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"


def _playback_url(timestamp: str, original: str) -> str:
    """Build a Wayback playback URL for a captured snapshot."""
    return f"https://web.archive.org/web/{timestamp}/{original}"


def _year_of(timestamp: str) -> int | None:
    """Parse the 4-digit year prefix of a CDX timestamp (YYYYMMDDhhmmss)."""
    if len(timestamp) < 4 or not timestamp[:4].isdigit():
        return None
    return int(timestamp[:4])


def wayback_snapshots(url: str, *, years: int = 5, timeout: float = 20) -> dict:
    """Sample ~one Wayback snapshot per year for the most recent N years.

    Queries the archive.org CDX API for all captures of `url`, collapsed to one
    row per (timestamp, day) bucket, then keeps the earliest capture in each of
    the last `years` calendar years. Returns playback URLs the agent can cite or
    pass to vision. Coverage is reported honestly — thin histories say so.

    Returns a dict: {"snapshots": [{"year", "timestamp", "url"}],
                     "coverage": str, "error": str | None}.
    """
    import httpx

    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,original",
        "collapse": "timestamp:4",  # collapse to ~one row per calendar year (YYYY prefix)
    }

    try:
        resp = httpx.get(CDX_ENDPOINT, params=params, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:  # network, HTTP, or JSON failure — degrade.
        return {
            "snapshots": [],
            "coverage": "no archive data retrieved",
            "error": f"wayback query failed: {exc}",
        }

    # CDX json returns a header row first; tolerate an empty result.
    if not isinstance(rows, list) or len(rows) <= 1:
        return {
            "snapshots": [],
            "coverage": "no snapshots found for this URL in the archive",
            "error": None,
        }

    data_rows = rows[1:]
    current_year = datetime.now(timezone.utc).year
    earliest_year = current_year - years + 1

    # Keep the earliest capture seen for each year within the window.
    per_year: dict[int, tuple[str, str]] = {}
    for row in data_rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        timestamp, original = str(row[0]), str(row[1])
        year = _year_of(timestamp)
        if year is None or year < earliest_year or year > current_year:
            continue
        existing = per_year.get(year)
        if existing is None or timestamp < existing[0]:
            per_year[year] = (timestamp, original)

    snapshots = [
        {
            "year": year,
            "timestamp": timestamp,
            "url": _playback_url(timestamp, original),
        }
        for year, (timestamp, original) in sorted(per_year.items())
    ]

    covered = len(snapshots)
    if covered == 0:
        coverage = f"no snapshots in the last {years} years"
    elif covered < years:
        coverage = (
            f"thin coverage: {covered} of {years} years sampled "
            f"({snapshots[0]['year']}–{snapshots[-1]['year']})"
        )
    else:
        coverage = (
            f"{covered} yearly snapshots "
            f"({snapshots[0]['year']}–{snapshots[-1]['year']})"
        )

    return {"snapshots": snapshots, "coverage": coverage, "error": None}
