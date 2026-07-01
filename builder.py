"""Offline brief assembler — deterministic, no Claude, no network.

Builds a fully-sourced `Brief` from the pre-loaded ground truth + the
deterministic economic model. This is the dual-mode fallback the spec calls
for: the demo always renders a correct, sourced brief even with no API key,
and the same economics / scoring / schema / render path is exercised that the
live agent feeds into.

Live mode (`agent.py`) replaces the *gathering* of these inputs with a Claude
tool-use loop; the assembly, economics, and scoring stay identical and
deterministic.
"""

from __future__ import annotations

from config import load_benchmarks, load_ground_truth
from economics import compute_opportunity, score
from models import (
    Approach,
    Benchmarks,
    Brief,
    BrandTruth,
    Confidence,
    EconomicOpportunity,
    FieldValue,
    Source,
)


def assemble_offline(
    slug: str,
    *,
    truth: dict[str, BrandTruth] | None = None,
    benchmarks: Benchmarks | None = None,
) -> Brief:
    """Assemble a `Brief` for a seeded brand slug from ground truth alone."""
    truth = truth if truth is not None else load_ground_truth()
    benchmarks = benchmarks if benchmarks is not None else load_benchmarks()
    if slug not in truth:
        raise KeyError(
            f"no ground truth for '{slug}'. Offline mode covers: "
            f"{', '.join(sorted(truth))}. Use --live for other brands."
        )

    bt = truth[slug]
    # Feed the partner names in so the per-brand group breakdown populates.
    econ_inputs = bt.econ_inputs.model_copy(update={"partners": list(bt.partners)})
    econ = compute_opportunity(econ_inputs, benchmarks)
    human = set(bt.human_fields)

    brief = Brief(
        brand=bt.name,
        parent_group=bt.parent_group,
        positioning=bt.positioning,
        markets=bt.markets,
        q1_who=_who(bt),
        q2_direction=_direction(bt),
        q3_momentum=_momentum(bt, human),
        q5_pdp=_pdp(bt),
        q4_content_need=_content_need(bt, econ, human),
        economics=econ,
        q6_decision_maker=_decision_maker(bt, human),
        q7_contact=_contact(bt, human),
        gap=_judgment("gap", bt.gap, human, bt),
        strategy=_judgment("strategy", bt.strategy, human, bt),
        approach=_approach(bt, human),
        confidence_note=_confidence_note(bt, econ),
        opportunity_score=score(econ, bt.fit_weight),
        partners=list(bt.partners),
        sources=[],  # aggregated below
        generated_mode="offline",
        trace=[
            {"step": "load_ground_truth", "note": f"seeded brand '{slug}'"},
            {"step": "compute_opportunity", "note": "deterministic economic model"},
            {"step": "score", "note": f"opportunity score {score(econ, bt.fit_weight)}/5"},
            {"step": "assemble", "note": "offline — no live tool calls"},
        ],
    )
    brief.sources = _aggregate_sources(brief)
    return brief


# --------------------------------------------------------------------------- #
# Per-question field builders
# --------------------------------------------------------------------------- #
def _who(bt: BrandTruth) -> FieldValue:
    return FieldValue(
        name="q1_who",
        value=(
            f"{bt.positioning}. Tier: {bt.tier}. {bt.channel_mix}. "
            f"Parent: {bt.parent_group}. Markets: {bt.markets}."
        ),
        confidence=Confidence.HIGH if bt.who_sources else Confidence.LOW,
        sources=list(bt.who_sources),
        is_estimate=not bt.who_sources,
        assumption=None if bt.who_sources else "positioning summarized from public profile",
    )


def _direction(bt: BrandTruth) -> FieldValue:
    return FieldValue(
        name="q2_direction",
        value=f"{bt.direction.verdict} — {bt.direction.detail}",
        confidence=Confidence.MED,
        sources=list(bt.direction.sources),
        is_estimate=not bt.direction.sources,
        assumption=None if bt.direction.sources else "trend inferred from public imagery",
    )


def _override(bt: BrandTruth, name: str) -> tuple[str | None, str | None]:
    """The seeded (ai_draft, rationale) for a field, or (None, None)."""
    ov = bt.overrides.get(name)
    return (ov.ai_draft, ov.rationale) if ov else (None, None)


def _momentum(bt: BrandTruth, human: set[str]) -> FieldValue:
    is_split = bt.momentum.verdict.value == "SPLIT"
    ai_draft, rationale = _override(bt, "q3_momentum")
    return FieldValue(
        name="q3_momentum",
        value=f"{bt.momentum.verdict.value}: {bt.momentum.detail}",
        confidence=Confidence.HIGH if bt.momentum.sources else Confidence.MED,
        sources=list(bt.momentum.sources),
        is_estimate=not bt.momentum.sources,
        assumption=None if bt.momentum.sources else "momentum read from reported figures",
        needs_human=is_split,
        human_sharpened=("q3_momentum" in human) or ai_draft is not None,
        ai_draft=ai_draft,
        sharpen_rationale=rationale,
    )


def _pdp(bt: BrandTruth) -> FieldValue:
    cp = bt.content_profile
    return FieldValue(
        name="q5_pdp",
        value=(
            f"~{cp.avg_shots_per_sku:g} shots/SKU · "
            f"{cp.pct_on_model:.0%} on-model / {cp.pct_still_life:.0%} still-life / "
            f"{cp.pct_video:.0%} video · consistency: {cp.consistency} · "
            f"cross-channel: {cp.cross_channel_note}"
        ),
        confidence=Confidence.LOW,
        sources=list(bt.content_sources),
        is_estimate=True,
        assumption=(
            "offline content profile is a tier-based estimate; live mode measures "
            "it via PDP audit (Playwright/JSON-LD) + the Claude vision classifier"
        ),
        needs_human=False,
    )


def _content_need(bt: BrandTruth, econ: EconomicOpportunity, human: set[str]) -> FieldValue:
    r = econ.annual_images_range
    return FieldValue(
        name="q4_content_need",
        value=(
            f"~{r.low:,.0f}–{r.high:,.0f} images/yr across own site + marketplace "
            f"+ market/localization variants (new SKUs + seasonal refresh)"
        ),
        confidence=Confidence.LOW,
        is_estimate=True,
        assumption="; ".join(econ.assumptions) or "volume estimated from catalog turnover",
        needs_human="q4_content_need" in human,
    )


def _decision_maker(bt: BrandTruth, human: set[str]) -> FieldValue:
    return FieldValue(
        name="q6_decision_maker",
        value=bt.decision_maker,
        confidence=Confidence.MED,
        sources=list(bt.decision_maker_sources),
        is_estimate=not bt.decision_maker_sources,
        assumption=None if bt.decision_maker_sources else "role mapped from org function",
        needs_human=True,  # always validate the named owner before outreach
        human_sharpened="q6_decision_maker" in human,
    )


def _contact(bt: BrandTruth, human: set[str]) -> FieldValue:
    return FieldValue(
        name="q7_contact",
        value=f"{bt.contact_angle}  Warm path: {bt.contact_warm_path}.",
        confidence=Confidence.LOW,
        sources=list(bt.decision_maker_sources),
        is_estimate=True,
        assumption=(
            "contact angle is judgment; named person + warm path require human "
            "validation (enrichment API, not LinkedIn scraping) — never assert a "
            "warm intro without evidence"
        ),
        needs_human=True,
        human_sharpened="q7_contact" in human,
    )


def _judgment(name: str, value: str, human: set[str], bt: BrandTruth) -> FieldValue:
    """gap / strategy — operator synthesis, the human's product."""
    ai_draft, rationale = _override(bt, name)
    return FieldValue(
        name=name,
        value=value,
        confidence=Confidence.MED,
        is_estimate=True,
        assumption="operator synthesis over the module outputs (the judgment layer)",
        needs_human=False,
        human_sharpened=(name in human) or ai_draft is not None,
        ai_draft=ai_draft,
        sharpen_rationale=rationale,
    )


def _approach(bt: BrandTruth, human: set[str]) -> Approach:
    return Approach(
        hook=bt.approach.hook,
        channel=bt.approach.channel,
        to_whom=bt.approach.to_whom,
        opening=bt.approach.opening,
        human_sharpened="approach" in human,
    )


def _confidence_note(bt: BrandTruth, econ: EconomicOpportunity) -> str:
    solid = "positioning, momentum and parent/partner structure are sourced"
    estimated = (
        "SKU volume, shots/SKU and therefore the € figure are estimates with "
        "stated assumptions (bands, not points)"
    )
    gate = "bottom-up and top-down agree within an order of magnitude" if econ.sanity_ok else (
        "bottom-up and top-down diverge by >1 order of magnitude — flagged for human review"
    )
    caveats = (
        "PDP/vision profile is a tier estimate offline (measured live); "
        "decision-maker and contact need human validation before any outreach"
    )
    from tool_impl.vision import confidence_line

    note = f"Solid: {solid}. Estimated: {estimated}. Economics: {gate}. Caveats: {caveats}."
    return f"{note} {confidence_line(None)}".strip()


def _aggregate_sources(brief: Brief) -> list[Source]:
    seen: set[tuple[str, str | None]] = set()
    out: list[Source] = []
    for fv in brief.all_fields():
        for s in fv.sources:
            key = (s.title, s.url)
            if key not in seen:
                seen.add(key)
                out.append(s)
    return out
