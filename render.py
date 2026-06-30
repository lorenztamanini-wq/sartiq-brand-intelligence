"""Brief rendering — Markdown, HTML, and PDF from a `Brief`.

Jinja2 drives the one-page layout (templates live in `config.TEMPLATES_DIR`).
Template logic is kept minimal: small filters here format euros and percents so
the templates stay declarative. Heavy deps are lazy-imported so this module
imports cleanly offline — `weasyprint` is only touched inside `render_pdf`.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import TEMPLATES_DIR
from models import Brief

# --------------------------------------------------------------------------- #
# Jinja filters — keep template logic minimal
# --------------------------------------------------------------------------- #
_MILLION = 1_000_000.0


def euro_m(value: float | None) -> str:
    """Format a euro amount as compact millions, e.g. 13500000 -> '13.5M'."""
    if value is None:
        return "—"
    return f"{value / _MILLION:.1f}M"


def euro_range(low: float | None, high: float | None) -> str:
    """Format a (low, high) euro band, e.g. '13.5-23.3M'."""
    if low is None or high is None:
        return "—"
    return f"{low / _MILLION:.1f}-{high / _MILLION:.1f}M"


def percent(value: float | None) -> str:
    """Format a 0..1 fraction as a whole-number percent, e.g. 0.45 -> '45%'."""
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


def _slug(brief: Brief) -> str:
    """Filesystem-safe slug — strips anything that could escape the output dir.

    Matches `sheet.brand_slug` so the sheet's brief link points at the file we
    actually write. A brand name like '../etc/passwd' collapses to a safe slug.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", brief.brand.strip().lower()).strip("-")
    return slug or "brand"


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        # Jinja matches the *final* extension, so '.html.j2' needs the compound
        # pattern; this enables HTML escaping for the HTML template while leaving
        # the Markdown template (.md.j2) unescaped.
        autoescape=select_autoescape(
            enabled_extensions=("html.j2", "html", "htm", "xml")
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["euro_m"] = euro_m
    env.filters["euro_range"] = euro_range
    env.filters["percent"] = percent
    return env


# --------------------------------------------------------------------------- #
# Render entrypoints
# --------------------------------------------------------------------------- #
def render_markdown(brief: Brief) -> str:
    """Render the one-page brief as Markdown (templates/brief.md.j2)."""
    env = _make_env()
    return env.get_template("brief.md.j2").render(brief=brief)


def render_html(brief: Brief) -> str:
    """Render the one-page brief as standalone HTML (templates/brief.html.j2)."""
    env = _make_env()
    css = (TEMPLATES_DIR / "brief.css").read_text(encoding="utf-8")
    return env.get_template("brief.html.j2").render(brief=brief, inline_css=css)


def render_pdf(brief: Brief, out_path) -> bool:
    """Render the brief to a PDF via weasyprint. Returns False if unavailable.

    weasyprint is missing in the base environment by design — degrade
    gracefully rather than raising into the caller.
    """
    try:
        from weasyprint import HTML  # lazy: not installed offline
    except Exception:
        return False
    try:
        html = render_html(brief)
        HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(str(out_path))
        return True
    except Exception:
        return False


def render_index(briefs: list[Brief]) -> str:
    """The ranked dashboard — the artefact that lands on the desk (links briefs)."""
    env = _make_env()
    rows = [
        {
            "rank": b.rank,
            "score": b.opportunity_score,
            "brand": b.brand,
            "slug": _slug(b),
            "positioning": b.positioning,
            "parent": b.parent_group,
            "momentum": b.q3_momentum.value.split(":", 1)[0].strip(),
            "gap": b.gap.value,
            "opp": euro_range(
                b.economics.annual_opportunity_range.low,
                b.economics.annual_opportunity_range.high,
            ),
            "partner": euro_range(
                b.economics.partner_upside_range.low,
                b.economics.partner_upside_range.high,
            ),
            "mode": b.generated_mode,
        }
        for b in briefs
    ]
    return env.get_template("index.html.j2").render(rows=rows)


def write_index(briefs: list[Brief], out_dir: str) -> str:
    """Write the ranked dashboard to <out_dir>/index.html; return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(render_index(briefs), encoding="utf-8")
    return str(path)


def load_confirmed(brief: Brief, out_dir: str) -> Brief | None:
    """If an existing <slug>.json already holds human-confirmed work, return it.

    Used to guard a re-dig from silently clobbering a confirmed brief (P3.1):
    callers substitute the confirmed brief (or pass --force to overwrite).
    """
    json_path = Path(out_dir) / f"{_slug(brief)}.json"
    if not json_path.exists():
        return None
    try:
        from review import has_confirmed_work, load_brief  # lazy: avoids import cycle

        existing = load_brief(json_path)
    except Exception:  # noqa: BLE001 — a bad/old record is not a confirmed one
        return None
    return existing if has_confirmed_work(existing) else None


def write_outputs(brief: Brief, out_dir: str, *, want_pdf: bool = True) -> dict:
    """Write <slug>.md/.json/.html (and .pdf when possible) into `out_dir`.

    Returns a dict of output paths (strings) keyed md/json/html/pdf; any output
    that could not be produced (e.g. PDF without weasyprint) is `None`.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = _slug(brief)

    md_path = out / f"{slug}.md"
    json_path = out / f"{slug}.json"
    html_path = out / f"{slug}.html"
    pdf_path = out / f"{slug}.pdf"

    md_path.write_text(render_markdown(brief), encoding="utf-8")
    json_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    html_path.write_text(render_html(brief), encoding="utf-8")

    pdf_ok = bool(want_pdf and render_pdf(brief, pdf_path))

    return {
        "md": str(md_path),
        "json": str(json_path),
        "html": str(html_path),
        "pdf": str(pdf_path) if pdf_ok else None,
    }
