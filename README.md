# Brand Intelligence Agent

*Sartiq Founder-Associate challenge*

An AI agent that digs a fashion brand down to a sourced, one-page **opportunity brief**: it answers the seven qualifying questions, measures the brand's actual content footprint, and lands a **quantified, partner-inclusive euro opportunity** — what Sartiq can capture (~20% of the brand's estimated studio imagery spend) across the brand, its parent group, and its wholesale partners (each broken out, one line per brand). The agent gathers and sources the inputs; a **deterministic economics shell** turns those inputs into the number; and a **human judgment layer** picks the wedge, calls the strategy, and validates the named contact before anyone reaches out. Every field is either *sourced* or flagged as an *estimate with a stated assumption* — nothing is silently guessed, and nothing is fabricated.

> **Want to see the output first?** Three finished example briefs (OVS, Sandro, Diesel) plus the ranked dashboard are committed under [`samples/`](samples/) — open `samples/index.html`.

---

## Dual-mode by design

The system always works, with or without an API key.

- **Offline mode** — pure Python, no key, no network. Assembles a fully-sourced, deterministic brief for the three seeded brands from pre-loaded ground truth plus the economics model. This is the demo fallback and the path the tests exercise.
- **Live mode** — when `ANTHROPIC_API_KEY` is set, Claude runs a real tool-use research loop: web search, sitemap/catalog crawl, PDP audit, vision classification of product imagery, wayback history, and people enrichment. It *supplies the inputs*; the economics shell still computes the euro figure deterministically.

`cli.py "Sandro"` auto-selects: **live if a key is present, offline otherwise.** Force either with `--live` / `--offline`.

**The offline seed is never passed off as a live result.** `python3 cli.py "Sandro" --live` with no `ANTHROPIC_API_KEY` set **errors** — it refuses to silently serve the deterministic seed. A `MODE: OFFLINE` / `MODE: LIVE` banner prints to the console on every run, and if a live run fails mid-flight it falls back to offline but the brief is loudly stamped **`offline (live failed)`** — a failure is never dressed up as success.

---

## Use it — the review app (start here)

The product is a small web app: **dig a brand, review what the AI proposes, publish.** No terminal needed after the one-time setup.

```bash
make setup              # one-time: venv + dependencies + .env scaffold
source .venv/bin/activate
streamlit run app.py    # opens http://localhost:8501
```

Then, in the browser:

1. **Sidebar → type any brand name** (e.g. *Mango*, *COS*, *Ganni* — seeded or not), pick **live** (needs `ANTHROPIC_API_KEY` in `.env`) or **offline**, and click **Dig →**.
2. The agent researches the brand live and proposes the one-page brief (you watch the tool progress inline).
3. **Review queue** — each flagged field shows the **⟲ AI draft** and *why*; you **confirm or tweak** it, plus the outreach play (hook / channel / to-whom / opening).
4. **✓ Approve all & publish** — the brief is re-rendered with `✓ confirmed` marks and added to the ranked **prioritization dashboard**. Dig the next brand and it accumulates, ranked by opportunity.

That loop — **dig → review → publish** — *is* the product: the AI does the digging and proposes the judgment; the human confirms it before it counts. A live dig costs roughly **$1** in API credit and takes ~1–3 minutes; with no key, everything still runs in offline mode.

---

## CLI — the same engine, headless

Prefer the terminal, or running many brands at once? The CLI calls the exact same `agent.run()` core.

```bash
make setup    # venv + install deps + scaffold .env
make demo     # OVS/Sandro/Diesel briefs + ranked dashboard (offline, no key)
              # → open output/index.html
```

Or step through it by hand:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional — leave keys blank to run offline

# One brand (auto: live if ANTHROPIC_API_KEY is set, else offline)
python3 cli.py "Sandro"

# All three seeded brands -> ranked prioritization sheet + dashboard
python3 cli.py --all
```

Useful flags: `--offline` (force deterministic brief), `--live` (force the Claude loop), `--out <dir>`, `--no-pdf`.

A clear **`MODE: OFFLINE`** / **`MODE: LIVE`** banner prints to the console on every run, so it is never ambiguous which path produced a brief. Other Make targets: `make test`, `make live`, `make clean`.

The `anthropic` / `httpx` stack installs by default but is only *used* on the live path. The offline core needs only `pydantic`, `PyYAML`, and `Jinja2`; `streamlit` ships with the install (the review app). `playwright`, `weasyprint`, and `gspread` stay optional — absent, the system degrades gracefully (httpx PDP fallback, HTML-only output, local CSV/MD sheet).

**Optional extras, the fine print:**
- **PDF (`weasyprint`)** also needs native libraries — `brew install pango` on macOS, `apt install libpango-1.0-0` on Linux. Without them, Markdown + HTML still emit; only the `.pdf` is skipped.
- **The review app** (`streamlit run app.py`) is the primary UI and installs by default — see *Use it — the review app* above.

---

## Target brands

Three seeded brands, picked so each surfaces a different strategic angle:

| Brand | Parent group | Angle |
|-------|--------------|-------|
| **OVS** | OVS S.p.A. (standalone) | Mass/value scale — vast SKU turnover means the largest raw image volume and the clearest efficiency case. |
| **Sandro** | SMCP Group | Accessible-luxury, full-price — consistency across a multi-brand Parisian group (Maje, Claudie Pierlot, Fursac) is the wedge. |
| **Diesel** | OTB Group | Denim-led repositioning — momentum **SPLIT** (brand vs. group diverge), so Q3 is `needs_human` and strategy forks. |

Live mode runs for any brand name; offline mode covers these three.

---

## Where outputs land

Everything is written under `output/` (override with `--out`):

```
output/
  index.html      # the ranked DASHBOARD — what lands on your desk (open this first)
  <brand>.md      # the one-page brief (the deliverable)
  <brand>.json    # the structured Brief record (brief.model_dump_json)
  <brand>.html    # rendered HTML
  <brand>.pdf     # if weasyprint is installed (md + html always emit)
  prioritization_sheet.csv   # ranked, one row per brief, linked
  prioritization_sheet.md    # same, human-readable
```

**`output/index.html` is the "what lands on your desk" artifact** — open it and you get every brand ranked by opportunity score, with brand/+partner euro bands, each row linking straight to its one-page brief. The CLI prints its path last on every `--all` run.

`--all` ranks the briefs by opportunity score and prints a console summary (rank, score, brand, brand/+partner euro band) under the `MODE:` banner.

---

## Architecture

An **agentic core** feeds a **deterministic shell**, and the boundary between them is the whole point.

```
cli.py / app.py
      │
      ▼
 agent.py  ── live: Claude tool-use loop ────────────┐   (offline: builder.assemble_offline)
      │     web_search + tool_impl/{research,catalog, │
      │     vision,history,people}, dispatched via    │
      │     tools.py; guardrailed; full trace         │
      ▼                                               │
 EconInputs ──▶ economics.compute_opportunity ──▶ economics.score   ← deterministic, pure
      │                                               │
      ▼                                               ▼
 synthesis (Claude) ──▶ Brief ──▶ render.py / sheet.py
```

- **`agent.py`** runs the manual tool-use loop (`claude-opus-4-8`, adaptive thinking, high effort), follows the parent group and its partners, and loops until every required field is emitted to a confidence threshold — or a guardrail trips.
- **`economics.py`** is a pure deterministic model: it triangulates a **bottom-up** estimate (shots × SKUs × channels × cost) against a **top-down** cross-check (visual spend as a % of revenue) and flags `needs_human` if they diverge by more than an order of magnitude. The cost basis is now **tier-aware** (`data/benchmarks.yaml` → `cost_per_image_by_tier`: mass **€15–60**, accessible-luxury **€60–250**, luxury **€120–400**), so the headline € is a defensible per-tier number rather than a flat agency rate. The old flat agency rate is *kept* as the AI's draft so the reframe stays visible (see below). With the tier basis, bottom-up now agrees with the top-down cross-check — e.g. the OVS sanity ratio dropped from ~7.5× to ~1×. **The agent may only supply inputs — it never writes the euro number or the score.** Two runs of the same brand produce the same figure.
- **`render.py` / `sheet.py`** turn the `Brief` into the one-pager and the ranked sheet.

The hard contract every module codes against — exact signatures, the schema, the tool-use rules — lives in [`CONTRACT.md`](CONTRACT.md). Read it for internals.

---

## Guardrails

A real agent you can trust on a sales call needs limits and a paper trail:

- **Tool-call cap** — `BRAND_BRIEF_MAX_TOOL_CALLS` (default 25).
- **Wall-clock budget** — `BRAND_BRIEF_WALL_CLOCK_S` (default 300s), plus per-tool HTTP timeouts.
- **Full trace** — every step is recorded on `Brief.trace`, so you can see exactly how each number was reached.
- **Graceful degradation** — a missing heavy dependency or a network failure returns a partial dict with an `error`/`note` key; it never crashes the loop.
- **Schema-enforced provenance** — `FieldValue` *rejects* a value that is neither sourced nor an estimate-with-assumption. The "source or estimate, never blank" rule is enforced in code, not by convention.

---

## Where the human layer picks up

The agent produces a *draft*. The human judgment layer owns the calls the AI shouldn't make alone — and where the human overrides the machine, the brief now **shows the delta**, not just a tag. A human-owned field renders the AI's draft *and* the override side by side:

```
⟲ AI draft — X
░ human ░ why I changed it — Y
```

The two marquee overrides land on camera as the "I overrode the AI" moments:

- **The OVS € reframe.** AI draft: **€42.5–283.4M/yr** (a flat agency rate applied tier-blind). Human-reframed to **€6.4–37.7M/yr** on the correct value-retail, in-house-studio cost basis (€15–60/image) — and the wedge flips with it, from "cut your photo budget" to "scale your studio."
- **The Diesel momentum SPLIT.** AI reads the OTB group P&L and calls it **STRUGGLING**. The human splits it: **Diesel-the-brand is winning** (best profitability in a decade) while **OTB-the-group is pressured** (−4.8%, wholesale −14.7%) — so the two need opposite pitches (innovation to Diesel, efficiency to OTB). The sharpest single read in the set.

Other mechanics:

- **`needs_human` fields** are flagged visibly with a `⚑ needs human` marker — always the decision-maker and contact (validate the named owner and any warm path before outreach), Diesel's SPLIT momentum, and the economics whenever the sanity gate fails.
- **`human_sharpened` fields** carry a `░ human ░` tag — the wedge (the gap we fill), the strategy call, and the approach are operator synthesis on top of the module outputs.

The pre-loaded ground truth already marks which fields the human owns per brand. The contract is honest: contacts need validation, and the system never asserts a warm intro without evidence (people enrichment uses an API, **never** LinkedIn scraping).

---

## Tests

Stdlib `unittest` — no pytest dependency. **44 tests**, all green:

```bash
python3 -m unittest discover -s tests -v   # or: make test
```

Covers the economics ranges and tier-aware sanity gate, deterministic scoring (`score ∈ [0,5]`), the schema's provenance invariants, the offline brief for all three brands (all seven questions + gap/strategy, Diesel's SPLIT, JSON round-trip), rendering, and the prioritization sheet. The agentic core is covered too: **`tests/test_agent_loop.py`** drives the tool-use loop against a mocked Anthropic client — no key, no network — proving the control flow *and* the trust boundary: even when the model tries to smuggle in a euro figure, the agent **cannot** write the € number (it comes only from `economics.compute_opportunity`).

---

## Calls I made (and why)

Luca invited *"make a call yourself and tell me why."* Here are the six judgment calls baked into this build:

- **Sampled 20–40 PDPs per brand, not the full catalog.** A representative sample across categories gives meaningful content stats fast; boiling the whole catalog buys precision I don't need to size the opportunity. Speed beats completeness here.
- **Sized the € as *Sartiq's* opportunity, not the studio's spend.** Estimate what the brand spends on imagery — bottom-up (measured shots × SKUs × channels × tier cost) triangulated against top-down (visual spend as a % of revenue) — then take the **~20% Sartiq can capture** at its price (it prices ~80% below the studio). Always a band, never a point; the sanity gate catches divergence.
- **Contacts via an enrichment API plus human validation — never LinkedIn scraping.** ToS and accuracy both argue against scraping. The contact field stays `needs_human`, and the system never asserts a warm intro without evidence.
- **Defined "partners" as group sister-brands + wholesale/marketplace, broken out per brand.** That's where the real TAM lives. Sizing Sandro alone undersells it; sizing SMCP (×4 brands) reframes "a Sandro deal" into "an SMCP relationship" — and the brief lists each group brand's own estimated opportunity, flagged for the human.
- **Split Diesel into brand-vs-group strategies.** Diesel-the-brand wants innovation; OTB-the-group wants efficiency. The machine reads the group P&L and calls it "struggling" — the operator knows the brand is having its best year in a decade. This is the single sharpest read in the set, and the machine wouldn't infer it.
- **No hard Sartiq per-image price.** I model the *savings* as a range versus traditional cost, not a quoted unit price. Pricing isn't set, and a number I can't defend wouldn't survive scrutiny on a sales call.

---

## Why the agent loop is hand-rolled

The tool-use loop in `agent.py` is deliberately manual rather than built on the Claude Agent SDK. The reason is the **trust boundary**: the agent only ever *supplies inputs* to `compute_opportunity` — the deterministic shell (`economics.py`) owns the € figure and the opportunity score, and the agent can never write them. Keeping the loop explicit makes that boundary provable in code and pins it with a test (`tests/test_agent_loop.py::test_agent_cannot_write_the_euro_figure` feeds a bogus € and asserts it's ignored). The Agent SDK is the natural future migration once that boundary is encoded as an SDK hook; it wasn't adopted now to keep the boundary explicit and test-pinned for this submission.

## Dependencies, and why

Stdlib-first: every heavy library is lazy-imported and **live-mode only** — offline briefs never touch the network. Beyond the offline core (`pydantic`, `PyYAML`, `Jinja2`), live digging adds `anthropic`, `httpx`, `beautifulsoup4`, `lxml`, and `ultimate-sitemap-parser` (`usp`). `usp` is the primary catalog-enumeration path: it reads gzip `.xml.gz` sitemaps, sitemap-index trees, and robots.txt `Sitemap:` directives that a raw `/sitemap.xml` fetch misses, with the original sitemap / Shopify `/products.json` / category-scrape logic kept as fallback. `playwright`, `weasyprint`, `gspread`, and `streamlit` stay optional and degrade gracefully when absent.

## Honest limitations

- **PDP scraping is fragile.** JS-heavy product pages render best with Playwright; without it the agent falls back to httpx + JSON-LD, which can miss content.
- **SKU counts and the euro figure are estimates.** They are returned as **bands with stated assumptions**, never false-precision points, and the bottom-up/top-down sanity gate catches gross divergence.
- **Contacts need validation.** Decision-maker and contact fields are always `needs_human` — confirm the named owner and any warm path before outreach.
- **Wayback coverage varies.** archive.org history depends on what was actually crawled; sparse coverage is reported, not invented.
- **Offline content profiles are tier-based estimates.** Live mode measures the real profile via PDP audit + the Claude vision classifier.

---

*Internals and exact module signatures: [`CONTRACT.md`](CONTRACT.md).*

i found a problem, on the economic opportunity, if in a normal studio the expense is the one that it says, but sartiq pricing has 80% less than that so the opportunity is lower, but also, in the opportunity of money all the brands attached should be displayed, for example diesel opportunity is x and the other controlled brand is y
