# HANDOFF — Brand Intelligence Agent (Sartiq Founder-Associate challenge)

> **Purpose of this file:** a complete, self-contained handoff so anyone (you, a
> teammate, or a fresh AI chat) can pick this up cold. If you start a new chat,
> point it at this repo and this file first.

---

## 1. What this is

A **Brand Intelligence Agent** for the Sartiq Founder-Associate challenge
(evaluator: **Luca**). You give it a fashion brand name; it returns a **sourced
one-page opportunity brief** answering Luca's 7 questions, with a **quantified,
partner-inclusive € opportunity**, a single sharp **wedge**, a **strategy call**,
and a **sendable outreach play** — plus a **ranked prioritization dashboard**
across brands.

The thing that makes it more than "point an LLM at the web": **the AI digs and
*proposes* the sharpening; a human reviews/approves it in a form.** The judgment
is *shown* (AI draft → human override + rationale), not just asserted.

**Location:** `~/Projects/sartiq`

---

## 2. Architecture (the one-liner for Luca)

**Agentic core + deterministic shell.**
- **Agentic core** (`agent.py`): a real Claude (`claude-opus-4-8`) tool-use loop
  that decides its own research path — find the parent group, enumerate sister
  brands + wholesale, audit product pages, classify imagery, until the brief is
  filled. With guardrails (max tool calls, wall-clock, a full trace log).
- **Deterministic shell** (`economics.py`, `score()`, `render.py`): pure
  functions. **The agent feeds inputs to the economic model; it never writes the
  € figure or the 0–5 score.** Two runs of the same brand → the same brief.

**Dual-mode:**
- **Offline** — deterministic, no API key, no network. Drives the demo + all
  tests. Uses pre-loaded ground truth (`data/ground_truth.yaml`).
- **Live** — the real Claude dig (web search, page fetch, PDP audit + Claude
  vision, people enrichment). Needs `ANTHROPIC_API_KEY` + credits.

---

## 3. Repo map (key files)

```
sartiq/
  models.py            # Pydantic schema = the contract. FieldValue (value, ai_draft,
                       #   sharpen_rationale, needs_human, human_sharpened, human_confirmed),
                       #   EconomicOpportunity (tier-aware + draft_opportunity_range + reframe_note),
                       #   EconInputs (incl. tier), Benchmarks, BrandTruth, Override, Approach, Brief.
  economics.py         # compute_opportunity() (TIER-AWARE) + score(). Pure, deterministic.
  config.py            # Settings, .env loader (no dep), benchmarks/ground-truth loaders,
                       #   resolve_brand(), web_search_tool setting.
  builder.py           # assemble_offline() — deterministic brief from ground truth.
  agent.py             # run() — the LIVE tool-use loop + offline dispatch + assembly + synthesis.
  tools.py             # ToolContext + CUSTOM_TOOLS (Anthropic tool defs) + dispatch().
  tool_impl/
    research.py        #   fetch_page()
    catalog.py         #   list_catalog(), audit_pdp()  (Playwright optional, httpx fallback)
    vision.py          #   classify_images()  (Claude vision; lazy)
    history.py         #   wayback_snapshots()  (archive.org CDX)
    people.py          #   enrich_people()  (Apollo; never LinkedIn scraping)
  review.py            # HUMAN REVIEW ENGINE: load_brief, reviewable_fields, apply_field_edit,
                       #   apply_approach_edit, is_fully_confirmed, publish (+ refresh dashboard).
  app.py               # Streamlit REVIEW FORM (thin shell over review.py). `streamlit run app.py`.
  render.py            # render_markdown/html/pdf, write_outputs, render_index/write_index (dashboard).
  sheet.py             # rank_briefs, row_for, write_sheet (ranked CSV + MD).
  cli.py               # `python3 cli.py "<brand>" [--live|--offline] [--all]`.
  data/
    benchmarks.yaml    # editable cost benchmarks + cost_per_image_by_tier (the tier lever).
    ground_truth.yaml  # §10 seeded brand intelligence: OVS, Sandro, Diesel (+ AI-draft overrides).
  prompts/             # agent_system.md, vision_classifier.md, synthesis.md (readable, tweakable).
  templates/           # brief.md.j2, brief.html.j2, brief.css, index.html.j2 (editorial design).
  tests/               # 50 tests (see §6).
  README.md            # full user guide + "Calls I made (and why)".
  DEMO.md              # the 2-minute video shot-list (mapped to spec §11).
  CONTRACT.md          # frozen interface spec (how the modules fit).
  Makefile             # `make setup`, `make demo`, `make test`, `make live`.
  .env.example         # copy to .env; all keys optional (blank = offline).
```

---

## 4. How to run

```bash
cd ~/Projects/sartiq

# one-time setup
make setup                       # venv + deps + .env   (or: python3 -m venv .venv && pip install -r requirements.txt)

# OFFLINE (free, instant, no key) — this is what you demo
python3 cli.py --all --offline   # OVS, Sandro, Diesel → ranked dashboard
python3 cli.py "Sandro"          # one brand (auto: live if key set, else offline)
open output/index.html           # the ranked dashboard — click any brief

# LIVE (real dig — needs ANTHROPIC_API_KEY in .env + credits)
python3 cli.py "Sandro" --live
#   cheaper: set BRAND_BRIEF_VISION_MODEL=claude-haiku-4-5 in .env (vision is the cost driver)

# HUMAN REVIEW FORM (the "make the human part of the system" piece)
pip install streamlit
streamlit run app.py             # → http://localhost:8501 ; pick a brief, review proposals, "Approve all & publish"

# TESTS
python3 -m unittest discover -s tests   # 50 pass
```

**Outputs land in `output/`:** `<brand>.md` / `.json` / `.html`, `index.html`
(dashboard), `prioritization_sheet.csv` / `.md`.

---

## 5. The 7 questions (method → source)

1. **Who they are / what they sell** — web search + page fetch over About/IR/Wikipedia → positioning, tier, channels, parent + sister brands.
2. **Direction (innovate vs copy)** — *(shallowest live question)* Wayback then-vs-now imagery trend is wired (`history.py`) but not deeply used yet.
3. **Growing or struggling** — latest FY results → GROWING / RECOVERING / PRESSURED / **SPLIT** (Diesel: brand wins, group pressured).
4. **Content need + € opportunity** — measured PDP profile → the deterministic economic model (§ below).
5. **What's on the PDPs** — enumerate catalog (sitemap/JSON-LD/Shopify), sample 20–40 PDPs, Claude vision classifies on-model/still-life/etc., cross-channel consistency check.
6. **Likely decision-maker** — map the function that owns e-com content/creative.
7. **Right contact + warm path** — enrichment API (Apollo) + human validation; never assert a warm intro without evidence.

**Economics (`economics.py`):** triangulated two ways — bottom-up (images × tier-aware cost) vs top-down (% of revenue). The headline uses a **tier-aware** cost basis (mass €15–60/img, accessible-luxury €60–250, luxury €120–400); the naive flat agency rate (€80–450) is kept as the **AI draft** so the human reframe is visible. Sanity gate flags if the two diverge >1 order of magnitude.

---

## 6. What's built & verified

- **73 tests pass** (`tests/`): economics + sanity gate, scoring, the FieldValue source-or-estimate gate, offline briefs for all 3 brands, render, sheet, the lazy-import contract, resolve_brand, invariants, **the mocked agent-loop (proves the agent can't write the €)**, the **review engine**, the **vision spot-check + self-consistency**, the **catalog sitemap enumeration**, the **unseeded-brand path**, and the **re-dig guard**.
- **Live mode works** — verified this build with real **OVS + Sandro** digs (`generated_mode: live`), tier set correctly per brand.
- **Q2 (direction) is evidenced** — every brief states an innovate-vs-copy call AND cites a historical Wayback snapshot (offline uses seeded snapshots; the live agent runs `wayback_snapshots` then reads then-vs-now — exercised live on OVS/Sandro, which cited dated 2023/2022 captures).
- **Vision confidence (§12b)** — every brief's CONFIDENCE line carries a figure. **Live** reports real per-run **self-consistency** (two independent classifier passes on the dig's own images); **offline** shows the labelled held-out baseline (`data/vision_fixtures.json`).
- **Catalog enumeration hardened** — `list_catalog` uses `ultimate-sitemap-parser` as the primary path (gzip `.xml.gz`, sitemap-index, robots.txt `Sitemap:` discovery), with the original sitemap/Shopify/category logic as fallback. Improves the SKU-count *input* the agent feeds economics (the € itself is still computed only by `economics.py`).
- **Unseeded brands arrive near-final** — a brand with no ground truth (e.g. Mango) gets parent/markets *proposed and flagged* `needs human`, never blank.
- **Re-dig never clobbers confirmed work** — re-running a human-confirmed brand keeps the confirmed version (file + dashboard); `--force` to overwrite.
- **The judgment is shown** — every brief renders `⟲ AI draft → ░ human ░ override + why` on momentum, gap, strategy, and the € (the OVS reframe: €42.5–283.4M draft → €6.4–37.7M tier-aware).
- **Human-in-the-loop review form** — proposes sharpened values; you confirm/edit; publish flips `⚑ needs human` → `✓ confirmed` and refreshes the dashboard.
- **Safety** — `--live` without a key errors (no silent offline); failed live runs are stamped `offline (live failed)`; the `MODE:` banner reflects the *actual* mode used; clean error messages, never tracebacks.
- **Current ranking** (live OVS/Sandro, offline Diesel): **Diesel 3.5 > OVS 3.2 = Sandro 3.2** — Diesel's SPLIT read leads; OVS and Sandro tie (OVS the big scale play, Sandro the best-fit consistency play).

---

## 7. Key decisions made (and why)

- **Dual-mode** — the dev sandbox had no API key / no network, so offline carries verification and de-risks the demo; live enriches when keys exist.
- **Agent feeds inputs, never writes the €/score** — the trust boundary; pinned by a mocked-client test.
- **Economic-opportunity-primary scoring**, strategic fit as a documented nudge.
- **Tier-aware economics** — applying agency rates to a value retailer overstated OVS ~7.5×; the tier basis fixes it AND the flat draft becomes the visible reframe (kills two birds).
- **Basic web search (`web_search_20250305`)** — the enhanced `_20260209` variant runs server-side code execution that broke the manual loop with a `container_id` error; basic search avoids it. Configurable via `BRAND_BRIEF_WEB_SEARCH_TOOL`.
- **Contacts via enrichment API + human validation**, never LinkedIn scraping (ToS + accuracy).
- **Vision model configurable** (`BRAND_BRIEF_VISION_MODEL`) — Haiku makes live runs much cheaper (vision is the cost driver); kept on Opus by default to protect classification + the visible self-consistency figure.
- **Prompt caching + cost logging** — the loop caches the stable system+tools prefix and the growing message history (`cache_control: ephemeral`), so the ~20 re-sent turns bill at ~0.1×; zero quality change. Each live run now prints actual token usage + an estimated € (loop+synthesis; vision billed separately).

---

## 8. What's still MISSING / next steps

**To finish the submission (mostly yours):**
- [ ] **The 2-minute video** — not recorded. `DEMO.md` is the shot list. *(yours)*
- [ ] **Delivery vehicle** — this is a local folder, **not yet a git repo**. Needs to become a GitHub repo / zip / link for Luca. *(can be automated)*
- [ ] **A cover note to Luca** — the one-paragraph "what this is + how to run." *(can be drafted)*

**Done in the finish-to-spec + research-plumbing passes (was deferred, now built):**
- [x] **Vision confidence (§12b)** — real per-run **self-consistency** live (two passes on the dig's own images); held-out baseline offline.
- [x] **Unseeded-brand thinness** — synthesis now *proposes* parent/markets, flagged `needs human`; no blanks.
- [x] **Q2 (direction)** — evidenced innovate-vs-copy call citing a Wayback snapshot, offline + **exercised live** on OVS/Sandro.
- [x] **Catalog enumeration** — `usp` primary path (gzip/sitemap-index/robots.txt) with the old logic as fallback.
- [x] **Re-dig guard** — confirmed briefs are preserved (`--force` to overwrite).
- [x] **MODE banner** — reflects the actual mode used.
- [x] **Tier honesty (live)** — the agent now supplies `tier` to `compute_opportunity` (was silently defaulting to accessible-luxury and inflating mass-tier brands ~4×).

**Open:**
- [ ] **Diesel live dig** — never completed; the live run hit a credit limit and fell back to offline. Re-run `python3 cli.py "Diesel" --live` once credit is topped up.
- [ ] **Economics polish** — `returns` and `localization` levers are named but not quantified in the €; partner multipliers are hand-set, not derived from a rule.
- [ ] **Deliberately NOT done** (judged low-value vs risk — see `plans/rosy-honking-manatee.md`): `waybackpy`/`extruct` swaps for Q2/Q5 (current `history.py`/`audit_pdp` already robust and already parse JSON-LD), and the Agent-SDK migration.

**Polish / robustness:**
- [ ] **Streamlit form not click-tested** (the `review.py` engine is fully tested; the UI shell wasn't runtime-clicked).
- [ ] **LinkedIn-as-source citation** — decision-maker/contact cite a LinkedIn *company-page* URL (with an "enrich via Apollo" note); reads as LinkedIn sourcing. Relabel to "function mapping (enrich via Apollo)" for cleanliness.

---

## 9. Honest limitations (put these in front of Luca, not hidden)

- PDP scraping is fragile (anti-bot, layout) — mitigated by sitemap/JSON-LD + sampling.
- SKU/turnover and therefore the € are **estimates with stated bands**, not points.
- Decision-maker / contact data needs human validation before any outreach.
- Wayback coverage varies by brand.
- Live runs cost a little API credit and can hit transient errors (handled by a clean message + offline fallback for seeded brands).

---

## 10. Picking this up in a new chat

Say something like: *"Read `~/Projects/sartiq/HANDOFF.md` and `CONTRACT.md`, then
[your task]."* The handoff + the tests + the README give a fresh session full
context. Start any change by running `python3 -m unittest discover -s tests` to
confirm a green baseline, and `python3 cli.py --all --offline` to see live output.
