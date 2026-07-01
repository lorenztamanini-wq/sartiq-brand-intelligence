"""Cross-brand prioritization sheet — the ranked top-level view.

Takes the per-brand `Brief`s and produces the comparison artefact a human
opens first: who to call, in what order, and why. Sorted by the deterministic
`opportunity_score` (size + fit, from `economics.score`), never re-judged here.

Always writes a CSV and a Markdown table offline. A Google Sheet is pushed only
when `gspread` is installed *and* a service-account credentials env var is set —
otherwise that step is skipped cleanly (the contract's degrade-gracefully rule).
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from models import Brief

# Env vars any of which, if set to a readable path, enables the gspread push.
GSPREAD_CREDS_ENV_VARS = (
    "GSPREAD_SERVICE_ACCOUNT",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_SHEETS_CREDENTIALS",
)


def brand_slug(brand: str) -> str:
    """Filesystem-safe slug for a brand name (matches render's `<brand>.md`)."""
    slug = re.sub(r"[^a-z0-9]+", "-", brand.strip().lower()).strip("-")
    return slug or "brand"


def rank_briefs(briefs: list[Brief]) -> list[Brief]:
    """Sort briefs by `opportunity_score` desc (stable) and set 1-based `rank`.

    Only *grounded* briefs are ranked. A brief whose brand the live run could
    not establish (blocked site, no ground truth) is left unranked
    (`rank = None`) and pushed to the end, so a default-derived number can
    never occupy a slot on the priority list. Ties keep their original relative
    order so the ranking is deterministic for equal scores.
    """
    grounded = [b for b in briefs if b.is_grounded]
    ungrounded = [b for b in briefs if not b.is_grounded]
    ranked = sorted(grounded, key=lambda b: b.opportunity_score, reverse=True)
    for i, brief in enumerate(ranked, start=1):
        brief.rank = i
    for brief in ungrounded:
        brief.rank = None
    return ranked + ungrounded


def _eur_range(low: float, high: float) -> str:
    """Format a € band in compact millions, matching the briefs (e.g. €42.5–283.4M)."""
    return f"€{low / 1_000_000:.1f}–{high / 1_000_000:.1f}M"


def _first_line(text: str) -> str:
    """First non-empty line of a (possibly multi-line) field value."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return text.strip()


def _shorten(text: str, limit: int = 140) -> str:
    """Collapse whitespace and truncate a long judgment field for a cell."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def row_for(brief: Brief) -> dict:
    """Flatten one `Brief` into a sheet row (JSON-serializable, all strings)."""
    econ = brief.economics
    opp = econ.annual_opportunity_range
    partner = econ.partner_upside_range
    return {
        "rank": brief.rank if brief.rank is not None else "",
        "score": brief.opportunity_score,
        "brand": brief.brand,
        "parent_group": brief.parent_group,
        "momentum": _first_line(brief.q3_momentum.value),
        "positioning": brief.positioning,
        "opportunity_eur": _eur_range(opp.low, opp.high),
        "partner_eur": _eur_range(partner.low, partner.high),
        "gap": _shorten(brief.gap.value),
        "strategy": _shorten(brief.strategy.value),
        "decision_maker": _first_line(brief.q6_decision_maker.value),
        "contact": _shorten(brief.q7_contact.value),
        "mode": brief.generated_mode,
        "brief_file": f"{brand_slug(brief.brand)}.md",
    }


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #
def _write_csv(rows: list[dict], path: Path) -> None:
    header = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _md_escape(text: str) -> str:
    """Escape pipes/newlines so a value stays inside one Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _write_md(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("# Prioritization Sheet\n\n_No briefs._\n", encoding="utf-8")
        return

    columns = list(rows[0].keys())
    lines = ["# Prioritization Sheet", "", "Ranked by opportunity score (size + fit).", ""]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        cells = []
        for col in columns:
            if col == "brand":
                # Link the brand cell to its one-page brief.
                cells.append(f"[{_md_escape(row['brand'])}]({row['brief_file']})")
            else:
                cells.append(_md_escape(row[col]))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _gspread_creds_path() -> str | None:
    """Return the first credentials path set in env and present on disk."""
    for var in GSPREAD_CREDS_ENV_VARS:
        val = os.getenv(var)
        if val and Path(val).expanduser().is_file():
            return str(Path(val).expanduser())
    return None


def _push_gsheet(rows: list[dict]) -> str | None:
    """Push the ranked rows to a Google Sheet — only if usable; else None.

    gspread is a *missing* dependency: import it lazily, and never raise to the
    caller — a failed push degrades to a skipped step.
    """
    creds_path = _gspread_creds_path()
    if not creds_path or not rows:
        return None
    try:
        import gspread  # lazy: missing offline

        client = gspread.service_account(filename=creds_path)
        sheet = client.create("Sartiq — Brand Prioritization")
        worksheet = sheet.sheet1
        header = list(rows[0].keys())
        values = [header] + [[str(r[c]) for c in header] for r in rows]
        worksheet.update("A1", values)
        return sheet.url
    except Exception:
        # Network/auth/permission failure must not break the offline artefacts.
        return None


def write_sheet(briefs: list[Brief], out_dir: str) -> dict:
    """Write the ranked CSV + Markdown sheet; push a Google Sheet if possible.

    Returns `{"csv", "md", "gsheet"}` — `gsheet` is the sheet URL or `None`.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    ranked = rank_briefs(list(briefs))
    rows = [row_for(b) for b in ranked]

    csv_path = out_path / "prioritization_sheet.csv"
    md_path = out_path / "prioritization_sheet.md"
    _write_csv(rows, csv_path)
    _write_md(rows, md_path)

    gsheet_url = _push_gsheet(rows)

    return {
        "csv": str(csv_path),
        "md": str(md_path),
        "gsheet": gsheet_url,
    }
