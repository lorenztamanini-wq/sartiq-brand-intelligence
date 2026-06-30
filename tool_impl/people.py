"""Decision-maker enrichment — Apollo if configured, an honest stub otherwise.

The Q6 decision-maker is a human-owned field: we surface candidate titles and,
where a paid data source is wired up, candidate names — but we NEVER scrape
LinkedIn, and we ALWAYS set `needs_human=True` so the operator verifies the
person before any outreach. No fabricated names ever leave this module.
"""

from __future__ import annotations

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"

# Cap on people returned, to keep the tool_result payload small.
MAX_PEOPLE = 10


def _stub(titles: list[str], company_domain: str, error: str | None) -> dict:
    """No-source result: hand the human the titles to chase, name no one."""
    note = (
        "no people-data provider configured (set APOLLO_API_KEY to enable Apollo "
        "lookups); returning target titles only — names need a human"
    )
    return {
        "people": [
            {
                "name": "",
                "title": title,
                "linkedin": "",
                "email_status": "unknown",
            }
            for title in titles
        ],
        "needs_human": True,
        "error": error or note,
    }


def enrich_people(titles: list[str], company_domain: str, *, settings) -> dict:
    """Find decision-maker candidates at `company_domain` for the given titles.

    With `settings.apollo_api_key` set, queries Apollo's people search for people
    matching `titles` at the company domain. Without it (or on any failure),
    returns a stub that lists the target titles but names no one. Either way the
    result is flagged `needs_human=True` — this field is never auto-trusted, and
    LinkedIn is never scraped.

    Returns a dict: {"people": [{"name", "title", "linkedin", "email_status"}],
                     "needs_human": True, "error": str | None}.
    """
    api_key = getattr(settings, "apollo_api_key", "") or ""
    if not api_key:
        return _stub(titles, company_domain, error=None)

    import httpx

    payload = {
        "person_titles": titles,
        "q_organization_domains": company_domain,
        "page": 1,
        "per_page": MAX_PEOPLE,
    }
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
    }

    try:
        resp = httpx.post(
            APOLLO_SEARCH_URL, json=payload, headers=headers, timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # network/HTTP/JSON failure — fall back to the stub.
        return _stub(titles, company_domain, error=f"apollo lookup failed: {exc}")

    raw_people = data.get("people") or []
    people: list[dict] = []
    for person in raw_people[:MAX_PEOPLE]:
        if not isinstance(person, dict):
            continue
        name = person.get("name") or " ".join(
            p for p in (person.get("first_name"), person.get("last_name")) if p
        )
        people.append(
            {
                "name": name or "",
                "title": person.get("title") or "",
                "linkedin": person.get("linkedin_url") or "",
                "email_status": person.get("email_status") or "unknown",
            }
        )

    error = None if people else "apollo returned no matches for these titles"
    return {"people": people, "needs_human": True, "error": error}
