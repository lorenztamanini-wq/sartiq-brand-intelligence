"""Pydantic schema — the deterministic contract for the whole system.

Every answered field carries provenance: it is either *sourced* or explicitly
flagged an *estimate* with a stated assumption. The schema rejects silent
guesses (see `FieldValue` validator) — this is the §12b "source or estimate,
never blank" quality gate, enforced in code rather than by convention.

This file is the frozen interface. `economics.py`, `builder.py`, `agent.py`,
`render.py`, `sheet.py` and the tests all depend on these types.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------- #
# Provenance primitives
# --------------------------------------------------------------------------- #
class Confidence(str, Enum):
    HIGH = "high"
    MED = "med"
    LOW = "low"


class Momentum(str, Enum):
    """Q3 read — drives the innovation-vs-cost-cutting strategy call."""

    GROWING = "GROWING"
    RECOVERING = "RECOVERING"
    PRESSURED = "PRESSURED"
    SPLIT = "SPLIT"  # brand vs parent diverge (e.g. Diesel inside OTB)


class Source(BaseModel):
    title: str
    url: Optional[str] = None
    note: Optional[str] = None


class FieldValue(BaseModel):
    """One answered field: the value plus where it came from.

    Invariant: a field must be sourced OR flagged an estimate-with-assumption.
    Construction raises if neither holds. This is enforced, not advisory.
    """

    name: str
    value: str
    confidence: Confidence = Confidence.LOW
    sources: list[Source] = Field(default_factory=list)
    is_estimate: bool = False
    assumption: Optional[str] = None
    needs_human: bool = False
    human_sharpened: bool = False
    # Set True once the operator has reviewed & approved (or edited) the proposed
    # value in the review form — turns `⚑ needs human` into `✓ confirmed`.
    human_confirmed: bool = False
    # The draft→override delta — what the AI produced before the operator
    # sharpened it, and why. This is what makes the judgment *visible* (§11 /
    # §12b-4) rather than merely asserted by the `human_sharpened` flag.
    ai_draft: Optional[str] = None
    sharpen_rationale: Optional[str] = None

    @model_validator(mode="after")
    def _source_or_estimate(self) -> "FieldValue":
        if not self.sources and not self.is_estimate:
            raise ValueError(
                f"field '{self.name}': neither sourced nor flagged an estimate "
                "(quality gate: source or estimate, never blank)"
            )
        if self.is_estimate and not self.assumption:
            raise ValueError(
                f"field '{self.name}': estimate without a stated assumption"
            )
        return self


# --------------------------------------------------------------------------- #
# Economic model types
# --------------------------------------------------------------------------- #
class Range(BaseModel):
    """A defensible band — never false precision."""

    low: float
    high: float

    @model_validator(mode="after")
    def _ordered(self) -> "Range":
        if self.high < self.low:
            self.low, self.high = self.high, self.low
        return self

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0


class Benchmarks(BaseModel):
    """Editable cost benchmarks (data/benchmarks.yaml). All € unless noted."""

    cost_per_image_traditional: Range
    effective_multiplier: Range
    # Tier-aware effective cost per final image — the defensible basis. Falls
    # back to cost_per_image_traditional × effective_multiplier (the naive flat
    # "draft" basis) when a tier is missing.
    cost_per_image_by_tier: dict[str, Range] = Field(default_factory=dict)
    on_model_per_sku: Range
    price_per_image_sartiq: Range
    # Sartiq's addressable revenue as a share of the brand's (tier-aware) studio
    # imagery spend — the headline opportunity is this fraction of that spend.
    sartiq_capture_pct: float = 0.20
    images_per_pdp: Range
    return_rate: Range
    localization_multiplier: Range
    visual_spend_pct_of_revenue: Range
    ecom_imagery_subset_pct: Range


class EconInputs(BaseModel):
    """Inputs the agent/builder feeds into the deterministic model.

    The agent may only *supply* these; it never computes the € result.
    """

    new_skus_per_year: int
    shots_per_sku: float
    channel_variants: float
    refresh_factor: float
    carryover_skus: int
    revenue_eur: float
    partner_multiplier: float
    # Tier drives the traditional cost basis (a value retailer's in-house
    # studio costs a fraction of a luxury maison's on-model shoot). Without it
    # the model overstates value retail by applying agency rates.
    tier: str = "accessible-luxury"  # mass | accessible-luxury | luxury
    # Group / wholesale brands the partner upside is split across (per-brand
    # breakdown). Names only — sizing is an even split, flagged as an estimate.
    partners: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class PartnerLine(BaseModel):
    """One group/partner brand's estimated Sartiq opportunity (rough even split)."""

    name: str
    opportunity: Range


class EconomicOpportunity(BaseModel):
    annual_images_range: Range  # headline = tier-aware (the human-reframed basis)
    cost_today_range: Range  # the brand's own studio imagery spend (tier-aware)
    cost_sartiq_range: Range
    annual_opportunity_range: Range  # SARTIQ's capture — the headline
    partner_upside_range: Range  # the group's other brands + wholesale (combined)
    # Per-brand split of the group upside — one line per attached brand (estimate).
    partner_breakdown: list[PartnerLine] = Field(default_factory=list)
    topdown_range: Range
    levers: list[str]
    assumptions: list[str]
    sanity_ok: bool
    needs_human: bool
    # The AI's naive draft € — flat agency-rate benchmark applied tier-blind —
    # kept beside the tier-aware headline so the operator's reframe is visible.
    draft_opportunity_range: Optional[Range] = None
    reframe_note: Optional[str] = None
    tier: str = "accessible-luxury"


# --------------------------------------------------------------------------- #
# Brief structure
# --------------------------------------------------------------------------- #
class Approach(BaseModel):
    """The play to get in — Luca's 'strategy to get to each one'. Not a footnote."""

    hook: str
    channel: str
    to_whom: str
    opening: str
    human_sharpened: bool = False
    human_confirmed: bool = False


class ContentProfile(BaseModel):
    """Q5 measured content profile (offline: plausible per-tier estimates)."""

    avg_shots_per_sku: float
    pct_on_model: float
    pct_still_life: float
    pct_video: float
    consistency: str
    cross_channel_note: str


# --------------------------------------------------------------------------- #
# Pre-loaded ground truth (data/ground_truth.yaml) — validated on load
# --------------------------------------------------------------------------- #
class MomentumTruth(BaseModel):
    verdict: Momentum
    detail: str
    sources: list[Source] = Field(default_factory=list)


class DirectionTruth(BaseModel):
    verdict: str  # e.g. "ahead / copy what works" | "behind / propose innovation"
    detail: str
    sources: list[Source] = Field(default_factory=list)


class Override(BaseModel):
    """A seeded AI-draft → human-sharpened delta for a named brief field."""

    ai_draft: str
    rationale: str


class BrandTruth(BaseModel):
    name: str
    aliases: list[str]
    site: str
    parent_group: str
    positioning: str
    tier: str  # mass | accessible-luxury | luxury
    markets: str
    channel_mix: str
    who_sources: list[Source] = Field(default_factory=list)
    momentum: MomentumTruth
    direction: DirectionTruth
    content_profile: ContentProfile
    content_sources: list[Source] = Field(default_factory=list)
    econ_inputs: EconInputs
    decision_maker: str
    decision_maker_sources: list[Source] = Field(default_factory=list)
    contact_angle: str
    contact_warm_path: str  # honest: "cold entry" unless evidence exists
    partners: list[str]
    gap: str
    strategy: str
    approach: Approach
    fit_weight: float  # 0..1, how well Sartiq's core wedge fits this brand
    human_fields: list[str]  # field names the human layer owns -> marked ░human░
    # Visible AI-draft -> human-override deltas, keyed by brief field name
    # (q3_momentum, gap, strategy, ...). This is the §11 / §12b-4 judgment proof.
    overrides: dict[str, Override] = Field(default_factory=dict)


class Brief(BaseModel):
    """The one-page brief + structured record. Render and sheet consume this."""

    brand: str
    parent_group: str
    positioning: str
    markets: str

    q1_who: FieldValue
    q2_direction: FieldValue
    q3_momentum: FieldValue
    q5_pdp: FieldValue
    q4_content_need: FieldValue
    economics: EconomicOpportunity
    q6_decision_maker: FieldValue
    q7_contact: FieldValue

    gap: FieldValue
    strategy: FieldValue
    approach: Approach
    confidence_note: str

    opportunity_score: float  # 0..5
    rank: Optional[int] = None
    partners: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)

    generated_mode: str = "offline"  # "offline" | "live"
    trace: list[dict] = Field(default_factory=list)

    def all_fields(self) -> list[FieldValue]:
        return [
            self.q1_who,
            self.q2_direction,
            self.q3_momentum,
            self.q5_pdp,
            self.q4_content_need,
            self.q6_decision_maker,
            self.q7_contact,
            self.gap,
            self.strategy,
        ]

    @property
    def is_grounded(self) -> bool:
        """True when the run actually established the brand's identity.

        A bot-blocked or unenumerable site with no ground-truth fallback leaves
        the identity fields as "not established" placeholders (see agent.py).
        Such a brief must not present a confident score or hold a rank — the €
        would be a default/estimate over an *unread* brand, not a real
        prioritization signal. The display surfaces flag it and unrank it.
        """
        marker = "not established"
        return (
            marker not in self.positioning.lower()
            and marker not in self.q1_who.value.lower()
        )
