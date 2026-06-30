"""Agentic core — the live Claude tool-use loop, with an offline fallback.

`run()` is the single entry point the CLI and the Streamlit demo call. It has
two branches:

  * **offline** — deterministic, no Claude, no network: delegate straight to
    `builder.assemble_offline`. Also taken automatically when live is requested
    but no Anthropic key is present.
  * **live** — a manual tool-use loop against `claude-opus-4-8`. Claude digs the
    web (server `web_search` tool) and our custom tools (`tools.CUSTOM_TOOLS`),
    supplies inputs to the deterministic economic model (never the € number),
    and emits the Brief fields. We then run a synthesis pass for the judgment
    text, assemble a `Brief`, and score it.

Hard rules honoured here:
  * `anthropic`, `tools`, and `builder`'s live use are imported INSIDE the live
    branch only — this module imports cleanly offline.
  * On ANY failure in the live loop, if the brand is seeded we fall back to the
    offline brief (with a trace note) rather than raising.
  * The economic € figure and the 0..5 score come only from `economics.*`; the
    agent supplies inputs, never the result.
"""

from __future__ import annotations

import json
import time
from typing import Callable, Optional

import builder
import config
import economics
from config import PROMPTS_DIR
from models import (
    Approach,
    Brief,
    Confidence,
    EconInputs,
    EconomicOpportunity,
    FieldValue,
    Source,
)

# Required Brief field names the agent is expected to emit (via emit_field).
_REQUIRED_FIELDS = (
    "q1_who",
    "q2_direction",
    "q3_momentum",
    "q5_pdp",
    "q4_content_need",
    "q6_decision_maker",
    "q7_contact",
)

_MAX_TOKENS = 8000

# USD per 1M tokens (input / output). Cache reads bill ~0.1x input, writes ~1.25x.
_PRICES = {
    "claude-opus-4-8": {"in": 5.0, "out": 25.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0},
}


def _cache_system(text: str) -> list:
    """Wrap the system prompt so its (large, stable) prefix is prompt-cached.

    The system prompt + seeded ground truth is re-sent on every loop turn; caching
    it bills the repeats at ~0.1x instead of full price — same model, same output.
    """
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _accumulate_usage(ctx, response) -> None:
    """Add one response's token usage to ctx.usage (no-op for the stub client)."""
    u = getattr(response, "usage", None)
    if u is None:
        return
    ctx.usage["input"] += getattr(u, "input_tokens", 0) or 0
    ctx.usage["output"] += getattr(u, "output_tokens", 0) or 0
    ctx.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
    ctx.usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0


def _estimate_cost(usage: dict, model: str) -> float:
    p = _PRICES.get(model, _PRICES["claude-opus-4-8"])
    return (
        usage["input"] * p["in"]
        + usage["output"] * p["out"]
        + usage["cache_read"] * p["in"] * 0.1
        + usage["cache_write"] * p["in"] * 1.25
    ) / 1_000_000


def run(
    brand: str,
    *,
    mode: str = "live",
    settings=None,
    progress: Optional[Callable[[str], None]] = None,
) -> Brief:
    """Produce a `Brief` for `brand`, live (Claude loop) or offline.

    `progress` is an optional UI callback taking a short status string.
    """
    settings = settings or config.get_settings()
    truth = config.load_ground_truth()
    slug = config.resolve_brand(brand, truth)

    def _say(msg: str) -> None:
        if progress is not None:
            progress(msg)

    # Offline branch: explicit, or live requested without a key.
    if mode == "offline" or not settings.has_live:
        if slug is None:
            raise ValueError(
                f"'{brand}' is not a seeded brand and live mode is unavailable "
                f"(no Anthropic key). Offline mode covers: {', '.join(sorted(truth))}."
            )
        _say(f"offline brief for {slug}")
        return builder.assemble_offline(slug, truth=truth)

    # Live branch — wrapped so any failure falls back to offline when possible.
    try:
        return _run_live(brand, slug, settings, truth, _say)
    except Exception as err:  # noqa: BLE001 — degrade gracefully, never raise to caller
        if slug is not None:
            _say(f"live failed ({err}); falling back to offline")
            brief = builder.assemble_offline(slug, truth=truth)
            # Loud signal: a failed live run must never read as a successful one.
            brief.generated_mode = "offline (live failed)"
            brief.confidence_note = (
                f"⚠ LIVE RUN FAILED ({err}) — served the deterministic offline "
                f"brief from seeded ground truth, NOT freshly dug data. " + brief.confidence_note
            )
            brief.trace = list(brief.trace) + [
                {"step": "fallback", "note": f"live failed: {err}; fell back to offline"}
            ]
            return brief
        raise


# --------------------------------------------------------------------------- #
# Live loop
# --------------------------------------------------------------------------- #
def _run_live(
    brand: str,
    slug: Optional[str],
    settings,
    truth: dict,
    say: Callable[[str], None],
) -> Brief:
    """The manual Claude tool-use loop. Imports the heavy stack lazily."""
    import anthropic

    import tools

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    benchmarks = config.load_benchmarks()

    system = _build_system_prompt(slug, truth)
    tool_defs = [
        {"type": settings.web_search_tool, "name": "web_search"}
    ] + tools.CUSTOM_TOOLS

    ctx = tools.ToolContext(
        settings=settings,
        slug=slug,
        truth=truth,
        benchmarks=benchmarks,
    )

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Build the brand intelligence brief for: {brand}. "
                "Dig with the tools, supply economic inputs to compute_opportunity, "
                "and emit every required Brief field with sources or a flagged estimate."
            ),
        }
    ]

    deadline = time.monotonic() + settings.wall_clock_seconds
    tool_calls = 0
    container_id: Optional[str] = None

    while True:
        if time.monotonic() >= deadline:
            say("wall-clock guardrail reached — wrapping up")
            ctx.trace.append({"step": "guardrail", "note": "wall_clock_seconds reached"})
            break
        if tool_calls >= settings.max_tool_calls:
            say("tool-call budget reached — wrapping up")
            ctx.trace.append({"step": "guardrail", "note": "max_tool_calls reached"})
            break

        create_kwargs = dict(
            model=settings.model,
            max_tokens=_MAX_TOKENS,
            system=_cache_system(system),
            tools=tool_defs,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            # Cache the stable system+tools prefix AND the growing message history
            # (auto-placed on the last cacheable block) — re-read at ~0.1x each turn.
            cache_control={"type": "ephemeral"},
        )
        # web_search_20260209 runs code execution server-side; its container must
        # be carried across turns or the API 400s ("container_id is required when
        # there are pending tool uses generated by code execution") on continuation.
        if container_id is not None:
            create_kwargs["container"] = container_id
        response = client.messages.create(**create_kwargs)
        _accumulate_usage(ctx, response)

        container = getattr(response, "container", None)
        if container is not None and getattr(container, "id", None):
            container_id = container.id

        stop = response.stop_reason

        if stop == "end_turn":
            messages.append({"role": "assistant", "content": response.content})
            break

        if stop == "pause_turn":
            # Server-side pause (e.g. long web_search) — re-send the turn.
            messages.append({"role": "assistant", "content": response.content})
            say("pausing — continuing the turn")
            continue

        if stop == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                # web_search is a server tool: its result arrives inline, so we
                # must not dispatch it (and must not echo a tool_result for it).
                if block.name == "web_search":
                    continue
                tool_calls += 1
                tool_input = block.input if isinstance(block.input, dict) else {}
                output = _safe_dispatch(tools, block.name, tool_input, ctx)
                say(f"tool: {block.name}")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    }
                )
                if tool_calls >= settings.max_tool_calls:
                    break
            saw_web_search = any(
                getattr(b, "type", None) == "tool_use"
                and getattr(b, "name", None) == "web_search"
                for b in response.content
            )
            if results:
                # Custom tools dispatched — return all results in one user turn.
                messages.append({"role": "user", "content": results})
            elif not saw_web_search:
                # tool_use with nothing actionable and no server tool to resume:
                # stop rather than re-send an unanswerable turn.
                ctx.trace.append({"step": "stop", "note": "tool_use with no actionable tools"})
                break
            else:
                # Only web_search this turn (server tool, result inline). Count the
                # round against the tool-call budget so the "hard cap" guardrail
                # bounds web-heavy runs too, then re-send to let the model continue
                # (an assistant turn ending in server-tool use is a valid message).
                tool_calls += 1
                ctx.trace.append({"step": "web_search", "note": "server-tool round (counted)"})
            continue

        # Unknown stop reason — record and stop rather than loop forever.
        ctx.trace.append({"step": "stop", "note": f"unhandled stop_reason: {stop}"})
        messages.append({"role": "assistant", "content": response.content})
        break

    brief = _assemble_from_ctx(client, ctx, slug, truth, benchmarks, settings, say, brand)
    u = ctx.usage
    if u["input"] or u["cache_read"] or u["output"]:
        say(
            f"cost: {u['input']:,} in + {u['cache_read']:,} cached-read / "
            f"{u['output']:,} out ≈ ${_estimate_cost(u, settings.model):.2f} "
            f"(loop+synthesis on {settings.model}; vision billed separately)"
        )
    return brief


def _safe_dispatch(tools, name: str, tool_input: dict, ctx) -> str:
    """Dispatch a custom tool; never raise into the loop."""
    try:
        return tools.dispatch(name, tool_input, ctx)
    except Exception as err:  # noqa: BLE001 — tools degrade, loop continues
        ctx.trace.append({"step": "tool_error", "note": f"{name}: {err}"})
        return json.dumps({"error": f"{name} failed: {err}"})


# --------------------------------------------------------------------------- #
# Assembly: economics + synthesis -> Brief
# --------------------------------------------------------------------------- #
def _proposed(value, label: str) -> str:
    """A proposed field value for an unseeded brand, always flagged for the human."""
    v = value.strip() if isinstance(value, str) else ""
    return f"{v} (proposed — needs human validation)" if v else f"{label} not established — needs human"


def _assemble_from_ctx(
    client,
    ctx,
    slug: Optional[str],
    truth: dict,
    benchmarks,
    settings,
    say: Callable[[str], None],
    brand: str = "",
) -> Brief:
    """Turn the collected context into a scored `Brief`."""
    bt = truth.get(slug) if slug is not None else None

    econ = _resolve_economics(ctx, bt, benchmarks)
    say("synthesizing judgment")
    synthesis = _run_synthesis(client, ctx, econ, settings, say)

    human = set(bt.human_fields) if bt is not None else set()

    fields = {
        name: _field_from_ctx(ctx, name, bt, human) for name in _REQUIRED_FIELDS
    }

    gap = _judgment_field("gap", synthesis.get("gap"), bt.gap if bt else None, human)
    strategy = _judgment_field(
        "strategy", synthesis.get("strategy"), bt.strategy if bt else None, human
    )
    approach = _resolve_approach(synthesis.get("approach"), bt, human)
    confidence_note = synthesis.get("confidence_note") or _default_confidence_note(econ, bt)
    from tool_impl.vision import confidence_line

    _vline = confidence_line(settings, images=getattr(ctx, "images", None))
    if _vline:
        confidence_note = f"{confidence_note} {_vline}".strip()

    # Seeded brand -> its canonical name; otherwise the user's own input
    # (NOT the agent's verbose "who" answer, which made an ugly name + filename).
    brand_name = bt.name if bt is not None else (brand.strip() or _ctx_brand(ctx))
    # Unseeded brand: never leave a field blank/"unknown". Use the agent's own
    # proposal from synthesis, flagged for human validation. (Luca may run this
    # on a brand of his choosing — the "run it yourself" bonus.)
    parent = bt.parent_group if bt is not None else _proposed(synthesis.get("proposed_parent"), "parent group")
    positioning = bt.positioning if bt is not None else fields["q1_who"].value
    markets = bt.markets if bt is not None else _proposed(synthesis.get("proposed_markets"), "key markets")
    partners = list(bt.partners) if bt is not None else []
    fit_weight = bt.fit_weight if bt is not None else 0.5

    brief = Brief(
        brand=brand_name,
        parent_group=parent,
        positioning=positioning,
        markets=markets,
        q1_who=fields["q1_who"],
        q2_direction=fields["q2_direction"],
        q3_momentum=fields["q3_momentum"],
        q5_pdp=fields["q5_pdp"],
        q4_content_need=fields["q4_content_need"],
        economics=econ,
        q6_decision_maker=fields["q6_decision_maker"],
        q7_contact=fields["q7_contact"],
        gap=gap,
        strategy=strategy,
        approach=approach,
        confidence_note=confidence_note,
        opportunity_score=economics.score(econ, fit_weight),
        partners=partners,
        sources=[],
        generated_mode="live",
        trace=list(ctx.trace),
    )
    brief.sources = _aggregate_sources(brief)
    return brief


def _resolve_economics(ctx, bt, benchmarks) -> EconomicOpportunity:
    """Use the economics object the dispatcher stashed, else compute from inputs."""
    existing = getattr(ctx, "economics", None)
    if isinstance(existing, EconomicOpportunity):
        return existing

    inputs = getattr(ctx, "econ_inputs", None) or {}
    if not inputs and bt is not None:
        # Agent supplied no inputs — fall back to seeded ground-truth inputs.
        return economics.compute_opportunity(bt.econ_inputs, benchmarks)
    try:
        econ_inputs = EconInputs.model_validate(inputs)
    except Exception:
        if bt is not None:
            return economics.compute_opportunity(bt.econ_inputs, benchmarks)
        raise
    return economics.compute_opportunity(econ_inputs, benchmarks)


def _field_from_ctx(ctx, name: str, bt, human: set[str]) -> FieldValue:
    """Build a FieldValue from what the agent emitted, else the ground truth.

    Any required field the agent did not emit falls back to the seeded value
    (when the brand is known) and is flagged `needs_human`.
    """
    raw = (getattr(ctx, "fields", None) or {}).get(name)

    # Non-human-owned field with an agent answer: trust the agent's sourced value.
    if raw and name not in human:
        return _coerce_field(name, raw, human)

    if bt is not None:
        fv = _ground_truth_field(name, bt, human)
        if fv is not None:
            if raw is not None and name in human:
                # The agent drafted a human-owned field, then the operator layer
                # sharpened it: keep the agent's draft beside the final so the
                # "AI digs, human decides" split is visible, not just asserted.
                fv.ai_draft = fv.ai_draft or str(raw.get("value", ""))[:400]
                fv.sharpen_rationale = (
                    fv.sharpen_rationale
                    or "operator sharpened the AI draft with industry judgment"
                )
                fv.human_sharpened = True
            else:
                fv.needs_human = True
            return fv

    if raw:
        return _coerce_field(name, raw, human)

    # No agent value and no ground truth: an honest, flagged placeholder.
    return FieldValue(
        name=name,
        value="not established by the live run",
        confidence=Confidence.LOW,
        is_estimate=True,
        assumption="agent did not emit this field and no ground truth was available",
        needs_human=True,
        human_sharpened=name in human,
    )


def _coerce_field(name: str, raw: dict, human: set[str]) -> FieldValue:
    """Coerce an emitted field dict into a validated FieldValue.

    The schema enforces source-or-estimate; if the agent's payload satisfies
    neither, we mark it an estimate with an explicit assumption so we never
    fabricate certainty.
    """
    sources = _coerce_sources(raw.get("sources"))
    is_estimate = bool(raw.get("is_estimate", False))
    assumption = raw.get("assumption")

    if not sources and not is_estimate:
        is_estimate = True
        assumption = assumption or "emitted without a source — treated as an estimate"
    if is_estimate and not assumption:
        assumption = "estimate; assumption not stated by the agent"

    return FieldValue(
        name=name,
        value=str(raw.get("value", "")),
        confidence=_coerce_confidence(raw.get("confidence")),
        sources=sources,
        is_estimate=is_estimate,
        assumption=assumption,
        needs_human=bool(raw.get("needs_human", False)),
        human_sharpened=raw.get("human_sharpened", name in human),
    )


def _coerce_sources(raw) -> list[Source]:
    out: list[Source] = []
    for s in raw or []:
        if isinstance(s, dict) and s.get("title"):
            out.append(Source(title=str(s["title"]), url=s.get("url"), note=s.get("note")))
    return out


def _coerce_confidence(value) -> Confidence:
    try:
        return Confidence(str(value).lower())
    except (ValueError, TypeError):
        return Confidence.LOW


def _ground_truth_field(name: str, bt, human: set[str]) -> Optional[FieldValue]:
    """Reuse the offline builder's per-field logic for ground-truth fallback."""
    econ_for_fields = economics.compute_opportunity(bt.econ_inputs, config.load_benchmarks())
    table = {
        "q1_who": lambda: builder._who(bt),
        "q2_direction": lambda: builder._direction(bt),
        "q3_momentum": lambda: builder._momentum(bt, human),
        "q5_pdp": lambda: builder._pdp(bt),
        "q4_content_need": lambda: builder._content_need(bt, econ_for_fields, human),
        "q6_decision_maker": lambda: builder._decision_maker(bt, human),
        "q7_contact": lambda: builder._contact(bt, human),
    }
    maker = table.get(name)
    return maker() if maker else None


def _judgment_field(
    name: str, agent_value, fallback_value, human: set[str]
) -> FieldValue:
    """gap / strategy text from synthesis, falling back to ground truth."""
    value = agent_value or fallback_value
    needs_human = not agent_value and fallback_value is None
    if not value:
        value = "not established by the live run"
        needs_human = True
    return FieldValue(
        name=name,
        value=str(value),
        confidence=Confidence.MED,
        is_estimate=True,
        assumption="operator synthesis over the live module outputs (the judgment layer)",
        needs_human=needs_human,
        human_sharpened=name in human,
    )


def _resolve_approach(agent_approach, bt, human: set[str]) -> Approach:
    """Build the Approach from synthesis output, falling back to ground truth."""
    sharpened = "approach" in human
    if isinstance(agent_approach, dict) and agent_approach.get("hook"):
        return Approach(
            hook=str(agent_approach.get("hook", "")),
            channel=str(agent_approach.get("channel", "")),
            to_whom=str(agent_approach.get("to_whom", "")),
            opening=str(agent_approach.get("opening", "")),
            human_sharpened=sharpened,
        )
    if bt is not None:
        return Approach(
            hook=bt.approach.hook,
            channel=bt.approach.channel,
            to_whom=bt.approach.to_whom,
            opening=bt.approach.opening,
            human_sharpened=sharpened,
        )
    return Approach(
        hook="needs human",
        channel="needs human",
        to_whom="needs human",
        opening="needs human",
        human_sharpened=sharpened,
    )


# --------------------------------------------------------------------------- #
# Synthesis call
# --------------------------------------------------------------------------- #
def _run_synthesis(client, ctx, econ: EconomicOpportunity, settings, say) -> dict:
    """One Claude pass over the filled schema -> gap/strategy/approach/confidence.

    Returns a dict (possibly empty). Never raises: synthesis is best-effort and
    the assembler has ground-truth fallbacks for everything it produces.
    """
    system = _read_prompt("synthesis.md")
    if not system:
        return {}

    payload = {
        "fields": getattr(ctx, "fields", {}) or {},
        "economics": {
            "annual_opportunity_eur": [
                econ.annual_opportunity_range.low,
                econ.annual_opportunity_range.high,
            ],
            "partner_upside_eur": [
                econ.partner_upside_range.low,
                econ.partner_upside_range.high,
            ],
            "sanity_ok": econ.sanity_ok,
            "levers": econ.levers,
        },
    }
    user = (
        "Synthesize the one-pager judgment over this filled schema. Return ONLY a "
        "JSON object with keys: gap, strategy, approach "
        "(object: hook, channel, to_whom, opening), confidence_note, "
        "proposed_parent (the brand's parent group from your research, or null if "
        "you genuinely could not find it), proposed_markets (its key markets, or "
        "null). Do not invent numbers, people, or citations.\n\n"
        + json.dumps(payload, default=str)
    )
    try:
        response = client.messages.create(
            model=settings.model,
            max_tokens=_MAX_TOKENS,
            system=_cache_system(system),
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            cache_control={"type": "ephemeral"},
        )
        _accumulate_usage(ctx, response)
    except Exception as err:  # noqa: BLE001 — best-effort, fall back to ground truth
        ctx.trace.append({"step": "synthesis_error", "note": str(err)})
        return {}

    text = _text_of(response)
    parsed = _extract_json(text)
    return parsed if isinstance(parsed, dict) else {}


# --------------------------------------------------------------------------- #
# Prompt + parsing helpers
# --------------------------------------------------------------------------- #
def _build_system_prompt(slug: Optional[str], truth: dict) -> str:
    base = _read_prompt("agent_system.md") or (
        "You are a brand-intelligence research agent. Fill the brief schema with "
        "sourced evidence using the available tools. Never assert a field without "
        "a source — flag needs_human instead. You supply inputs to "
        "compute_opportunity; you never write the € number yourself."
    )
    if slug is not None and slug in truth:
        try:
            seed = truth[slug].model_dump(mode="json")
        except Exception:
            seed = None
        if seed is not None:
            base = (
                base
                + "\n\n## Seeded ground truth (verify and extend; do not fabricate beyond it)\n"
                + json.dumps(seed, default=str)
            )
    return base


def _read_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _text_of(response) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


def _extract_json(text: str):
    """Best-effort: parse a JSON object from model text (raw or fenced)."""
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
        candidate = candidate.strip()
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        pass
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(candidate[start : end + 1])
        except (ValueError, TypeError):
            return None
    return None


def _ctx_brand(ctx) -> str:
    raw = (getattr(ctx, "fields", None) or {}).get("q1_who")
    if isinstance(raw, dict) and raw.get("value"):
        return str(raw["value"])[:60]
    return "unknown brand"


def _default_confidence_note(econ: EconomicOpportunity, bt) -> str:
    gate = (
        "bottom-up and top-down agree within an order of magnitude"
        if econ.sanity_ok
        else "bottom-up and top-down diverge by >1 order of magnitude — flagged for human review"
    )
    return (
        f"Live run. Economics: {gate}. Decision-maker and contact need human "
        "validation before any outreach; estimated fields carry stated assumptions."
    )


def _aggregate_sources(brief: Brief) -> list[Source]:
    seen: set[tuple] = set()
    out: list[Source] = []
    for fv in brief.all_fields():
        for s in fv.sources:
            key = (s.title, s.url)
            if key not in seen:
                seen.add(key)
                out.append(s)
    return out
