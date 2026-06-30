"""The agentic core, proven with a stubbed Anthropic client (no key, no network).

The deterministic shell is covered elsewhere; this exercises the part Luca is
actually grading — the live tool-use loop — and pins the trust boundary: the
agent supplies inputs to compute_opportunity, it never writes the € figure.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import agent
import config
import economics
from models import EconInputs

# Sandro-shaped economic inputs, PLUS a bogus euro field the model tries to smuggle
# in — it must be ignored (the € comes only from economics.compute_opportunity).
_ECON_INPUTS = {
    "new_skus_per_year": 3000,
    "shots_per_sku": 5,
    "channel_variants": 3,
    "refresh_factor": 0.3,
    "carryover_skus": 1500,
    "revenue_eur": 609_000_000,
    "partner_multiplier": 4.0,
    "tier": "accessible-luxury",
    "assumptions": ["test inputs"],
    "annual_opportunity_eur": 999_999_999,  # <-- bogus; must be ignored
}

_REQUIRED = (
    "q1_who", "q2_direction", "q3_momentum", "q5_pdp",
    "q4_content_need", "q6_decision_maker", "q7_contact",
)


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class _StubMessages:
    """Returns scripted responses in order; repeats the last one if over-called."""

    def __init__(self, scripts):
        self._scripts = scripts
        self._i = 0

    def create(self, **_kwargs):
        resp = self._scripts[min(self._i, len(self._scripts) - 1)]
        self._i += 1
        return resp


class _StubClient:
    def __init__(self, scripts):
        self.messages = _StubMessages(scripts)


def _tool_use(name, inp, _id):
    return _Block(type="tool_use", name=name, input=inp, id=_id)


def _text(t):
    return _Block(type="text", text=t)


def _scripts():
    # Turn 1: compute_opportunity + emit all 7 fields (with a web_search too).
    blocks = [
        _Block(type="tool_use", name="web_search", input={"query": "Sandro"}, id="ws0"),
        _tool_use("compute_opportunity", dict(_ECON_INPUTS), "t0"),
    ]
    for i, name in enumerate(_REQUIRED):
        blocks.append(
            _tool_use("emit_field", {
                "name": name, "value": f"agent-drafted {name}",
                "is_estimate": True, "assumption": "agent estimate",
            }, f"e{i}")
        )
    return [
        _Resp("tool_use", blocks),
        _Resp("end_turn", [_text("done digging")]),
        # The synthesis call:
        _Resp("end_turn", [_text(
            '{"gap":"agent gap","strategy":"agent strategy",'
            '"approach":{"hook":"h","channel":"c","to_whom":"w","opening":"o"},'
            '"confidence_note":"agent confidence"}'
        )]),
    ]


class TestLiveLoop(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = config.Settings()
        self.settings.anthropic_api_key = "sk-test-not-real"  # forces the live branch
        self.benchmarks = config.load_benchmarks()

    def _run(self):
        stub = _StubClient(_scripts())
        with patch("anthropic.Anthropic", return_value=stub):
            return agent.run("Sandro", mode="live", settings=self.settings)

    def test_loop_runs_and_populates_all_fields(self) -> None:
        brief = self._run()
        self.assertEqual(brief.generated_mode, "live")
        for fv in brief.all_fields():
            self.assertTrue(fv.value.strip(), f"{fv.name} blank")

    def test_agent_cannot_write_the_euro_figure(self) -> None:
        # The € must equal the deterministic model on the supplied inputs —
        # NOT the bogus 999,999,999 the model tried to inject.
        brief = self._run()
        expected = economics.compute_opportunity(
            EconInputs.model_validate(_ECON_INPUTS), self.benchmarks
        )
        self.assertAlmostEqual(
            brief.economics.annual_opportunity_range.high,
            expected.annual_opportunity_range.high,
            delta=1.0,
        )
        self.assertNotEqual(brief.economics.annual_opportunity_range.high, 999_999_999)

    def test_non_human_field_uses_agent_value(self) -> None:
        # q1_who is not human-owned for Sandro -> the agent's sourced value stands.
        brief = self._run()
        self.assertIn("agent-drafted q1_who", brief.q1_who.value)

    def test_human_field_keeps_agent_draft_as_delta(self) -> None:
        # q6 is human-owned for Sandro -> final is the operator value, and the
        # agent's draft is retained as ai_draft (the visible split).
        brief = self._run()
        self.assertIsNotNone(brief.q6_decision_maker.ai_draft)
        self.assertIn("agent-drafted q6", brief.q6_decision_maker.ai_draft)
        self.assertTrue(brief.q6_decision_maker.human_sharpened)


def _scripts_unseeded():
    """Same dig, but synthesis proposes parent + markets (unseeded brand path)."""
    scripts = _scripts()
    scripts[-1] = _Resp("end_turn", [_text(
        '{"gap":"agent gap","strategy":"agent strategy",'
        '"approach":{"hook":"h","channel":"c","to_whom":"w","opening":"o"},'
        '"confidence_note":"agent confidence",'
        '"proposed_parent":"Independent — no parent group found",'
        '"proposed_markets":"EU + US e-commerce"}'
    )])
    return scripts


class TestCostAccounting(unittest.TestCase):
    def test_estimate_cost_opus_per_million(self) -> None:
        usage = {"input": 1_000_000, "output": 1_000_000, "cache_read": 0, "cache_write": 0}
        self.assertAlmostEqual(agent._estimate_cost(usage, "claude-opus-4-8"), 30.0, places=4)

    def test_cache_read_bills_one_tenth(self) -> None:
        usage = {"input": 0, "output": 0, "cache_read": 1_000_000, "cache_write": 0}
        self.assertAlmostEqual(agent._estimate_cost(usage, "claude-opus-4-8"), 0.5, places=4)

    def test_accumulate_usage_is_noop_without_usage(self) -> None:
        import tools

        ctx = tools.ToolContext(settings=None, slug=None, truth={}, benchmarks=None)
        agent._accumulate_usage(ctx, object())  # stub response: no .usage attribute
        self.assertEqual(ctx.usage["input"], 0)

    def test_accumulate_usage_sums_fields(self) -> None:
        import tools

        class _U:
            input_tokens, output_tokens = 10, 20
            cache_read_input_tokens, cache_creation_input_tokens = 5, 3

        class _R:
            usage = _U()

        ctx = tools.ToolContext(settings=None, slug=None, truth={}, benchmarks=None)
        agent._accumulate_usage(ctx, _R())
        self.assertEqual(
            ctx.usage, {"input": 10, "output": 20, "cache_read": 5, "cache_write": 3}
        )


class TestComputeOpportunitySchema(unittest.TestCase):
    """Regression: the agent MUST supply `tier` (it silently defaulted to
    accessible-luxury, inflating mass-tier brands like OVS ~4x)."""

    def test_tier_is_a_required_input(self) -> None:
        import tools

        spec = next(t for t in tools.CUSTOM_TOOLS if t["name"] == "compute_opportunity")
        schema = spec["input_schema"]
        self.assertIn("tier", schema["properties"])
        self.assertIn("tier", schema["required"])
        self.assertEqual(
            schema["properties"]["tier"]["enum"], ["mass", "accessible-luxury", "luxury"]
        )


class TestUnseededBrand(unittest.TestCase):
    """P1.2: a brand NOT in ground truth still yields a near-complete brief."""

    def setUp(self) -> None:
        self.settings = config.Settings()
        self.settings.anthropic_api_key = "sk-test-not-real"

    def _run(self):
        stub = _StubClient(_scripts_unseeded())
        with patch("anthropic.Anthropic", return_value=stub):
            return agent.run("Mango", mode="live", settings=self.settings)

    def test_no_required_field_is_blank(self) -> None:
        brief = self._run()
        self.assertEqual(brief.brand, "Mango")  # user input, not a seeded slug
        for fv in brief.all_fields():
            self.assertTrue(fv.value.strip(), f"{fv.name} blank")
        for attr in ("parent_group", "positioning", "markets", "confidence_note"):
            self.assertTrue(getattr(brief, attr).strip(), f"{attr} blank")
        self.assertTrue(brief.approach.hook.strip())

    def test_parent_and_markets_are_proposed_and_flagged(self) -> None:
        brief = self._run()
        self.assertIn("proposed", brief.parent_group.lower())
        self.assertIn("needs human", brief.parent_group.lower())
        self.assertIn("proposed", brief.markets.lower())


if __name__ == "__main__":
    unittest.main()
