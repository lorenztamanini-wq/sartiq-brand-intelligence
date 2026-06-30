"""Tool registry + dispatch for the live agentic loop.

`CUSTOM_TOOLS` are the Anthropic tool definitions the agent advertises (the
`web_search` server tool is added by `agent.py`, not here). `dispatch` routes a
tool-use block to the matching `tool_impl.*` implementation, records the raw
result plus a trace entry onto the shared `ToolContext`, and returns a JSON
string for the `tool_result` block.

Two boundaries are enforced here, not by convention:
  * `compute_opportunity` — the agent supplies *inputs* only. We validate them
    into `EconInputs`, run the deterministic `economics.compute_opportunity`
    over the loaded benchmarks, stash the `EconomicOpportunity` on the context,
    and return only the ranges. The agent never writes the € figure.
  * `emit_field` — the agent's answers land in `ctx.fields` keyed by name; the
    `FieldValue` schema (source-or-estimate gate) is enforced downstream.

`dispatch` never raises: a failing tool returns a JSON dict with an `error`
key so the loop keeps moving.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import models


# --------------------------------------------------------------------------- #
# Shared mutable context threaded through the loop
# --------------------------------------------------------------------------- #
@dataclass
class ToolContext:
    """State the tools read from and write into across the agentic loop."""

    settings: Any
    slug: str | None
    truth: dict
    benchmarks: Any
    catalog: dict = field(default_factory=dict)
    images: list = field(default_factory=list)
    econ_inputs: dict = field(default_factory=dict)
    fields: dict[str, dict] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    # Token usage accumulated across the loop + synthesis (for the cost summary).
    usage: dict = field(
        default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    )
    # Set by compute_opportunity; the assembler reads it back (the deterministic
    # € result, computed once, never written by the agent).
    economics: Any = None


# --------------------------------------------------------------------------- #
# Anthropic tool definitions (web_search is added by the agent, not here)
# --------------------------------------------------------------------------- #
CUSTOM_TOOLS: list[dict] = [
    {
        "name": "fetch_page",
        "description": (
            "Fetch a single web page over HTTP and return its title, truncated "
            "visible text (~8k chars), and any JSON-LD structured-data blocks. "
            "Use for brand 'about' pages, press releases, parent-group sites."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute URL of the page to fetch.",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "list_catalog",
        "description": (
            "Estimate a brand's catalog size and enumerate product URLs by "
            "probing sitemap.xml / product sitemaps / Shopify /products.json / "
            "category pages. Use to size SKU volume for the content-need model."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "site": {
                    "type": "string",
                    "description": "Brand site root or domain (e.g. https://www.example.com).",
                }
            },
            "required": ["site"],
        },
    },
    {
        "name": "audit_pdp",
        "description": (
            "Audit one product-detail page: extract its product images and "
            "JSON-LD. Renders with Playwright when available, else falls back to "
            "HTTP + JSON-LD. Use to measure shots/SKU and image style per PDP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute URL of a product-detail page.",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "classify_images",
        "description": (
            "Classify product images with Claude vision: each is labelled "
            "on_model / still_life / flat_lay / ghost_mannequin / video / detail, "
            "noting model presence, background, and whether the garment is worn. "
            "Returns per-image labels plus a summary (avg shots, % on-model, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute URLs of product images to classify.",
                }
            },
            "required": ["image_urls"],
        },
    },
    {
        "name": "wayback_snapshots",
        "description": (
            "Query the Internet Archive (archive.org CDX) for ~yearly snapshots "
            "of a URL over the last few years. Use to read a brand's trajectory "
            "(visual refresh cadence, repositioning) over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to look up in the Wayback Machine.",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "enrich_people",
        "description": (
            "Find decision-makers at a company by title using a contact-enrichment "
            "API (never LinkedIn scraping). Returns candidate people with title, "
            "LinkedIn URL, and email status; results always need human validation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target role titles (e.g. 'Head of E-commerce').",
                },
                "company_domain": {
                    "type": "string",
                    "description": "Company domain to scope the search (e.g. example.com).",
                },
            },
            "required": ["titles", "company_domain"],
        },
    },
    {
        "name": "compute_opportunity",
        "description": (
            "Compute the deterministic annual € opportunity for the brand (and its "
            "partners). You supply ONLY the inputs — never a euro figure. The "
            "model triangulates bottom-up volume against a top-down revenue check "
            "and returns defensible ranges. Call once you have grounded inputs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "new_skus_per_year": {
                    "type": "integer",
                    "description": "New SKUs launched per year.",
                },
                "shots_per_sku": {
                    "type": "number",
                    "description": "Average product images shot per SKU.",
                },
                "channel_variants": {
                    "type": "number",
                    "description": "Multiplier for channel/market/localization variants per image.",
                },
                "refresh_factor": {
                    "type": "number",
                    "description": "Fraction of carryover SKUs reshot each season (0..1+).",
                },
                "carryover_skus": {
                    "type": "integer",
                    "description": "Existing catalog SKUs eligible for seasonal refresh.",
                },
                "revenue_eur": {
                    "type": "number",
                    "description": "Annual revenue in EUR (for the top-down cross-check).",
                },
                "partner_multiplier": {
                    "type": "number",
                    "description": "Group + wholesale reach multiplier (>=1; 1 = brand only).",
                },
                "tier": {
                    "type": "string",
                    "enum": ["mass", "accessible-luxury", "luxury"],
                    "description": (
                        "Production tier — MUST match the brand's actual price "
                        "positioning from q1_who; it sets the per-image cost basis "
                        "(mass €15-60, accessible-luxury €60-250, luxury €120-400). "
                        "Value / mass-market / fast-fashion retailers (e.g. OVS, "
                        "Primark, H&M) are 'mass' — a higher tier overstates the €. "
                        "Contemporary/premium brands are 'accessible-luxury'; "
                        "designer houses are 'luxury'."
                    ),
                },
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Stated assumptions behind these inputs (required for honesty).",
                },
            },
            "required": [
                "new_skus_per_year",
                "shots_per_sku",
                "channel_variants",
                "refresh_factor",
                "carryover_skus",
                "revenue_eur",
                "partner_multiplier",
                "tier",
            ],
        },
    },
    {
        "name": "emit_field",
        "description": (
            "Record one answered brief field. Every field must be either sourced "
            "or flagged as an estimate with a stated assumption — never assert a "
            "value without a source; flag needs_human instead. Field names match "
            "the schema (e.g. q1_who, q2_direction, q3_momentum, q5_pdp, "
            "q4_content_need, q6_decision_maker, q7_contact, gap, strategy)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Schema field name this value answers.",
                },
                "value": {
                    "type": "string",
                    "description": "The answer text.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "med", "low"],
                    "description": "Confidence in the value.",
                },
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "note": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                    "description": "Citations backing the value (title + url).",
                },
                "is_estimate": {
                    "type": "boolean",
                    "description": "True if the value is an estimate rather than sourced.",
                },
                "assumption": {
                    "type": "string",
                    "description": "Required when is_estimate is true: the stated assumption.",
                },
                "needs_human": {
                    "type": "boolean",
                    "description": "True if a human must validate before this is acted on.",
                },
            },
            "required": ["name", "value"],
        },
    },
]


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def dispatch(name: str, tool_input: dict, ctx: ToolContext) -> str:
    """Route a tool-use call to its implementation; never raise.

    Records the raw result and a trace entry onto `ctx`, then returns the
    result as a JSON string for the `tool_result` block.
    """
    tool_input = tool_input or {}
    try:
        result = _route(name, tool_input, ctx)
    except Exception as exc:  # degrade gracefully — never break the loop
        result = {"error": f"{name} failed: {exc}"}

    ctx.trace.append({"step": name, "input": tool_input, "result": result})
    return json.dumps(result, default=str)


def _route(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    """Dispatch by tool name. Lazy-imports `tool_impl` so import stays offline."""
    if name == "fetch_page":
        from tool_impl import research

        return research.fetch_page(
            tool_input["url"], timeout=ctx.settings.http_timeout
        )

    if name == "list_catalog":
        from tool_impl import catalog

        result = catalog.list_catalog(
            tool_input["site"], timeout=ctx.settings.http_timeout
        )
        ctx.catalog = result
        return result

    if name == "audit_pdp":
        from tool_impl import catalog

        result = catalog.audit_pdp(
            tool_input["url"], timeout=ctx.settings.http_timeout
        )
        for img in result.get("images", []) or []:
            if img not in ctx.images:
                ctx.images.append(img)
        return result

    if name == "classify_images":
        from tool_impl import vision

        return vision.classify_images(
            tool_input["image_urls"], settings=ctx.settings
        )

    if name == "wayback_snapshots":
        from tool_impl import history

        return history.wayback_snapshots(
            tool_input["url"], timeout=ctx.settings.http_timeout
        )

    if name == "enrich_people":
        from tool_impl import people

        return people.enrich_people(
            tool_input["titles"],
            tool_input["company_domain"],
            settings=ctx.settings,
        )

    if name == "compute_opportunity":
        return _compute_opportunity(tool_input, ctx)

    if name == "emit_field":
        return _emit_field(tool_input, ctx)

    return {"error": "unknown tool " + name}


def _compute_opportunity(tool_input: dict, ctx: ToolContext) -> dict:
    """Validate agent inputs into EconInputs, run the model, return ranges only.

    The agent supplies inputs; the deterministic € result is computed here and
    stashed on the context. The agent never sees or writes the euro figure
    except as the returned ranges.
    """
    import economics

    econ_in = models.EconInputs.model_validate(tool_input)
    ctx.econ_inputs = econ_in.model_dump()

    opportunity = economics.compute_opportunity(econ_in, ctx.benchmarks)
    # Stash the computed object where the assembler reads it (ctx.economics),
    # so the deterministic result is reused, not recomputed.
    ctx.economics = opportunity

    return {
        "annual_images_range": _range(opportunity.annual_images_range),
        "cost_today_range": _range(opportunity.cost_today_range),
        "cost_sartiq_range": _range(opportunity.cost_sartiq_range),
        "annual_opportunity_range": _range(opportunity.annual_opportunity_range),
        "partner_upside_range": _range(opportunity.partner_upside_range),
        "topdown_range": _range(opportunity.topdown_range),
        "levers": opportunity.levers,
        "assumptions": opportunity.assumptions,
        "sanity_ok": opportunity.sanity_ok,
        "needs_human": opportunity.needs_human,
    }


def _emit_field(tool_input: dict, ctx: ToolContext) -> dict:
    """Store the agent's answer for a field, keyed by name, in ctx.fields."""
    name = tool_input.get("name")
    if not name:
        return {"error": "emit_field requires a 'name'"}
    ctx.fields[name] = dict(tool_input)
    return {"stored": name, "fields_emitted": sorted(ctx.fields)}


def _range(rng: models.Range) -> dict:
    """A Range as a plain JSON-serializable dict (low/high/mid)."""
    return {"low": rng.low, "high": rng.high, "mid": rng.mid}
