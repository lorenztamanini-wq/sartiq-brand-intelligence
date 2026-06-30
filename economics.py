"""Deterministic economic-opportunity model and scoring.

Pure functions only. The agentic core may *supply inputs* to these functions
but can never write the € figure or the score directly — that boundary is what
turns "I pointed a model at the internet" into "an agent I can trust on a sales
call." Two runs of the same brand produce the same number.

Two independent estimates are triangulated:
  * bottom-up  — measured shots/SKU x SKU volume x channel variants x cost
  * top-down   — visual-content spend as a % of revenue (industry estimate)
If they diverge by more than an order of magnitude, the result is flagged
`needs_human` rather than silently picking one.
"""

from __future__ import annotations

import math

from models import Benchmarks, EconInputs, EconomicOpportunity, Range

# Bottom-up vs top-down must land within this factor to pass the sanity gate.
ORDER_OF_MAGNITUDE = 10.0

# Score weighting: economic opportunity is the PRIMARY driver of the rank (the
# spec ranks the sheet "by economic opportunity"); strategic fit is a documented
# secondary nudge — strong enough to break near-ties, not to invert a multi-x €
# gap. Winnability beyond that is the human layer's call, surfaced in the brief.
SIZE_WEIGHT = 0.75
FIT_WEIGHT = 0.25
# Opportunity (€/yr, brand + partner) mapped onto 0..5 on a log scale spanning
# the realistic brand+partner range so size differentiates without saturating.
# 10^SCORE_LOG_MIN € -> 0 ; 10^SCORE_LOG_MAX € -> 5.
SCORE_LOG_MIN = 6.0  # €1m  — floor of a meaningful brand opportunity
SCORE_LOG_MAX = 8.7  # ~€500m — top of the realistic brand + partner range


def _annual_images(inp: EconInputs) -> Range:
    """New-SKU shoots + a seasonal refresh on carryover, across channels.

    annual ~= (N x S x C) + (Rf x carryover x S x C)
    Returned as a band: the low end assumes refresh applies to fewer carryover
    SKUs than the high end.
    """
    base = inp.new_skus_per_year * inp.shots_per_sku * inp.channel_variants
    refresh_high = inp.refresh_factor * inp.carryover_skus * inp.shots_per_sku * inp.channel_variants
    refresh_low = 0.5 * refresh_high
    return Range(low=base + refresh_low, high=base + refresh_high)


def _opportunity(cost_today: Range, cost_sartiq: Range) -> Range:
    """Traditional spend displaced, as a band (never below zero)."""
    return Range(
        low=max(0.0, cost_today.low - cost_sartiq.high),
        high=max(0.0, cost_today.high - cost_sartiq.low),
    )


def compute_opportunity(inp: EconInputs, bm: Benchmarks) -> EconomicOpportunity:
    """Triangulate the annual € opportunity for a brand (+ its partners).

    The headline uses a **tier-aware** cost basis (the defensible number a
    fashion operator recognises). A naive **flat agency-rate** basis is computed
    alongside as the AI's draft, so the operator's reframe is visible — applying
    €80-450/image to a value retailer with an in-house studio overstates it.
    """
    images = _annual_images(inp)
    cost_sartiq = Range(
        low=images.low * bm.price_per_image_sartiq.low,
        high=images.high * bm.price_per_image_sartiq.high,
    )

    # Draft basis: flat quoted rate x effective multiplier, applied tier-blind.
    flat_low = bm.cost_per_image_traditional.low * bm.effective_multiplier.low
    flat_high = bm.cost_per_image_traditional.high * bm.effective_multiplier.high
    draft_cost_today = Range(low=images.low * flat_low, high=images.high * flat_high)
    draft_opportunity = _opportunity(draft_cost_today, cost_sartiq)

    # Headline basis: the tier-aware effective cost (falls back to flat).
    tier_band = bm.cost_per_image_by_tier.get(inp.tier) or Range(low=flat_low, high=flat_high)
    cost_today = Range(low=images.low * tier_band.low, high=images.high * tier_band.high)
    opportunity = _opportunity(cost_today, cost_sartiq)

    # Partner upside = the same wedge across the group + wholesale partners.
    extra = max(0.0, inp.partner_multiplier - 1.0)
    partner_upside = Range(low=opportunity.low * extra, high=opportunity.high * extra)

    # Top-down cross-check: visual spend as % of revenue, then the e-com subset.
    topdown = Range(
        low=inp.revenue_eur * bm.visual_spend_pct_of_revenue.low * bm.ecom_imagery_subset_pct.low,
        high=inp.revenue_eur * bm.visual_spend_pct_of_revenue.high * bm.ecom_imagery_subset_pct.high,
    )
    sanity_ok = _within_order_of_magnitude(opportunity, topdown)

    # A material draft-vs-headline gap is the operator's economics reframe.
    reframe_note: str | None = None
    if draft_opportunity.mid > 1.5 * max(opportunity.mid, 1.0):
        reframe_note = (
            f"{inp.tier}-tier production runs "
            f"€{tier_band.low:.0f}-{tier_band.high:.0f}/image, not the flat agency "
            f"rate — so the defensible opportunity is the tier-aware band above, "
            f"not the ~€{draft_opportunity.mid / 1e6:.0f}M draft."
        )

    return EconomicOpportunity(
        annual_images_range=images,
        cost_today_range=cost_today,
        cost_sartiq_range=cost_sartiq,
        annual_opportunity_range=opportunity,
        partner_upside_range=partner_upside,
        topdown_range=topdown,
        levers=[
            "speed (weeks -> hours)",
            "return-rate reduction (image accuracy)",
            "localization at near-zero marginal cost",
        ],
        assumptions=inp.assumptions,
        sanity_ok=sanity_ok,
        needs_human=not sanity_ok,
        draft_opportunity_range=draft_opportunity,
        reframe_note=reframe_note,
        tier=inp.tier,
    )


def _within_order_of_magnitude(a: Range, b: Range) -> bool:
    """True if the two bands' midpoints land within ORDER_OF_MAGNITUDE."""
    am, bm_ = a.mid, b.mid
    if am <= 0 or bm_ <= 0:
        return False
    ratio = max(am, bm_) / min(am, bm_)
    return ratio <= ORDER_OF_MAGNITUDE


def score(econ: EconomicOpportunity, fit_weight: float) -> float:
    """Map economic opportunity (+ fit) onto a 0..5 prioritization score.

    Deterministic: same inputs -> same score, always. The top-level ranked
    sheet is sorted by this. Size dominates; strategic fit nudges.
    """
    total_mid = econ.annual_opportunity_range.mid + econ.partner_upside_range.mid
    size_score = _log_scale(total_mid)
    fit = max(0.0, min(1.0, fit_weight)) * 5.0
    raw = SIZE_WEIGHT * size_score + FIT_WEIGHT * fit
    return round(max(0.0, min(5.0, raw)), 1)


def _log_scale(value_eur: float) -> float:
    if value_eur <= 0:
        return 0.0
    log_v = math.log10(value_eur)
    frac = (log_v - SCORE_LOG_MIN) / (SCORE_LOG_MAX - SCORE_LOG_MIN)
    return max(0.0, min(5.0, frac * 5.0))
