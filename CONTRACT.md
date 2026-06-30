# Frozen Interface Contract — Brand Intelligence Agent

This is the authoritative interface every module codes against. The spine
(`models.py`, `economics.py`, `config.py`, `builder.py`, `cli.py`, plus
`data/*.yaml`) **already exists as real files** — Read them. Implement your
module to these signatures exactly. Do not change the spine.

## Hard rules (all modules)

1. **Import cleanly with only these libs present**: `pydantic, yaml, jinja2,
   httpx, bs4, lxml, anthropic`. **Missing & must be lazy-imported inside the
   function that needs them**: `playwright, weasyprint, gspread, streamlit`.
   A top-level `import weasyprint` (etc.) is a bug — it breaks offline import.
   Verify with: `python3 -c "import <yourmodule>"` (must succeed offline).
2. **Degrade gracefully.** If a heavy dep or network is unavailable, return a
   partial/typed result with an `error`/`note` field — never raise to the agent
   loop. Tools return JSON-serializable `dict`s.
3. **Never fabricate.** No invented numbers, people, or citations. Unknowns are
   flagged `needs_human`, returned empty, or labelled estimates with assumptions.
4. **Anthropic SDK**: model `claude-opus-4-8`. Manual tool-use loop: call
   `client.messages.create(...)`, check `response.stop_reason`; on `"tool_use"`
   append `response.content` to messages, run tools, send one user message of
   `tool_result` blocks (each with matching `tool_use_id`); on `"pause_turn"`
   append assistant content and re-send; stop on `"end_turn"`. Web search is the
   server tool `{"type": "web_search_20260209", "name": "web_search"}` (results
   arrive inline — do NOT dispatch it client-side). Vision: image blocks
   `{"type":"image","source":{"type":"url","url":...}}`. Use
   `thinking={"type":"adaptive"}` + `output_config={"effort":"high"}` for the
   loop and synthesis. Read keys from `config.Settings`.

## Spine types you consume (see models.py)

`Brief, FieldValue, Confidence, Source, Range, Benchmarks, EconInputs,
EconomicOpportunity, Approach, ContentProfile, BrandTruth, Momentum`.
`economics.compute_opportunity(EconInputs, Benchmarks) -> EconomicOpportunity`,
`economics.score(EconomicOpportunity, fit_weight: float) -> float`.
`builder.assemble_offline(slug, *, truth=None, benchmarks=None) -> Brief`.
`config.get_settings() -> Settings`, `config.load_ground_truth()`,
`config.load_benchmarks()`, `config.resolve_brand(name, truth) -> slug|None`.

---

## Modules to implement

### tool_impl/research.py
```python
def fetch_page(url: str, *, timeout: float = 20) -> dict
# -> {"url","status":int|None,"title":str,"text":str(truncated ~8k),"json_ld":list,"error":str|None}
# httpx GET; parse with bs4/lxml; extract <script type="application/ld+json"> blocks.
```

### tool_impl/catalog.py
```python
def list_catalog(site: str, *, timeout: float = 20, max_items: int = 60) -> dict
# Try sitemap.xml / product sitemaps / Shopify /products.json / category pages.
# -> {"catalog_size_estimate":int|None,"product_urls":list[str],"source":str,"error":str|None}

def audit_pdp(url: str, *, timeout: float = 20) -> dict
# Render with Playwright if installed; else httpx + JSON-LD fallback.
# -> {"url","images":list[str],"json_ld":list,"rendered_with":"playwright"|"httpx","error":str|None}
```

### tool_impl/vision.py
```python
def classify_images(image_urls: list[str], *, settings) -> dict
# Claude vision (settings.vision_model). Label each: on_model|still_life|flat_lay|
# ghost_mannequin|video|detail; note model_present, background, garment worn.
# Offline / no key -> {"classifications":[],"summary":{},"note":"vision unavailable offline"}.
# -> {"classifications":list[dict],"summary":{"avg_shots":..,"pct_on_model":..,
#     "pct_still_life":..,"pct_video":..,"consistency":str},"error":str|None}
```

### tool_impl/history.py
```python
def wayback_snapshots(url: str, *, years: int = 5, timeout: float = 20) -> dict
# archive.org CDX: http://web.archive.org/cdx/search/cdx?url=<url>&output=json
# Pick ~yearly snapshots. -> {"snapshots":[{"year","timestamp","url"}],"coverage":str,"error":str|None}
```

### tool_impl/people.py
```python
def enrich_people(titles: list[str], company_domain: str, *, settings) -> dict
# Apollo (settings.apollo_api_key) if present, else stub. Never LinkedIn scraping.
# -> {"people":[{"name","title","linkedin","email_status"}],"needs_human":True,"error":str|None}
```

### tools.py  (registry + dispatch for the live loop)
```python
@dataclass
class ToolContext:
    settings: any; slug: str|None; truth: dict; benchmarks: any
    catalog: dict = {}; images: list = []; econ_inputs: dict = {}
    fields: dict[str, dict] = {}; trace: list[dict] = []

CUSTOM_TOOLS: list[dict]   # Anthropic tool defs for: fetch_page, list_catalog,
#   audit_pdp, classify_images, wayback_snapshots, enrich_people,
#   compute_opportunity, emit_field. (web_search is added by agent, not here.)

def dispatch(name: str, tool_input: dict, ctx: ToolContext) -> str
# Route to tool_impl.*; record results into ctx and ctx.trace; return a string
# (JSON) for the tool_result. compute_opportunity: validate inputs into EconInputs,
# call economics.compute_opportunity, stash on ctx, return the ranges as JSON —
# the agent may ONLY supply inputs, never the € result. emit_field: store a
# FieldValue dict in ctx.fields keyed by field name.
```

### agent.py  (the agentic core)
```python
def run(brand: str, *, mode: str = "live", settings=None, progress=None) -> Brief
# mode=="offline" -> return builder.assemble_offline(resolve_brand(...)).
# mode=="live": run the manual tool-use loop with guardrails
#   (settings.max_tool_calls, settings.wall_clock_seconds, per-tool timeouts).
#   System prompt = prompts/agent_system.md, seeded with ground truth if the
#   brand is known. Tools = web_search server tool + tools.CUSTOM_TOOLS.
#   Loop until every required field is emitted (to a confidence threshold) OR a
#   guardrail trips. Then: economics from ctx.econ_inputs, synthesis (Claude over
#   prompts/synthesis.md) -> gap/strategy/approach, assemble Brief (mode="live",
#   trace=ctx.trace). progress(str) is an optional UI callback.
# Lazy-import tools/tool_impl/anthropic INSIDE the live branch only.
```

### render.py  (+ templates/brief.md.j2, templates/brief.html.j2, templates/brief.css)
```python
def render_markdown(brief: Brief) -> str          # the one-page brief (template)
def render_html(brief: Brief) -> str              # jinja2 HTML (no `markdown` dep)
def render_pdf(brief: Brief, out_path) -> bool     # weasyprint if available, else False
def write_outputs(brief: Brief, out_dir: str, *, want_pdf: bool = True) -> dict
# writes <brand>.md, <brand>.json (brief.model_dump_json), <brand>.html, and
# <brand>.pdf if weasyprint present. -> {"md","json","html","pdf"} (paths or None).
```
Template must render the §6 layout: header (brand, score/rank, positioning,
parent, markets), the 7 answers, CONTENT NEED + OPPORTUNITY (brand) + PARTNERS
ranges + levers, DECISION-MAKER, CONTACT, THE GAP WE FILL, STRATEGY, APPROACH
(hook/channel/to-whom/opening), CONFIDENCE, sources. Mark `human_sharpened`
fields with a ░ human ░ tag and `needs_human` visibly. One page; keep it tight.

### sheet.py
```python
def rank_briefs(briefs: list[Brief]) -> list[Brief]   # sort desc by opportunity_score, set .rank (1-based)
def row_for(brief: Brief) -> dict                       # flat row for the sheet
def write_sheet(briefs: list[Brief], out_dir: str) -> dict
# Always writes prioritization_sheet.csv + .md (ranked, each row links its brief).
# gspread push only if installed AND creds present. -> {"csv","md","gsheet":None|url}
```

### app.py  (optional Streamlit demo)
```python
# `streamlit run app.py`. Lazy `import streamlit`. Text box -> brand name ->
# run agent (live if key else offline) -> show brief markdown + download buttons.
# Must not break `python3 -c "import app"`? It's a script; guard streamlit import.
```

### prompts/agent_system.md, prompts/vision_classifier.md, prompts/synthesis.md
- **agent_system**: goal = fill the Brief schema with sourced evidence; the tool
  list; the rule "follow the parent group and its partners, enumerate sister
  brands + wholesale"; the stopping condition; "never assert a field without a
  source — flag needs_human instead"; "you supply inputs to compute_opportunity,
  you never write the € number." Seeded ground truth appended when known.
- **vision_classifier**: classify one product image as on_model/still_life/
  flat_lay/ghost_mannequin/video/detail; note model present? background? worn?
  Return JSON.
- **synthesis**: over the filled schema, write the one-pager, name the single
  gap, recommend strategy (growing->innovation; pressured->efficiency;
  premium->consistency; brand-vs-group split when they disagree), set confidence,
  flag needs_human. Encode the §7b judgment playbook as guidance.

### tests/  (stdlib unittest — NO pytest)
- `test_economics.py`: ranges ordered; `_annual_images` positive; sanity gate
  true/false cases; partner upside = opportunity×(mult−1); topdown formula.
- `test_scoring.py`: `score` ∈ [0,5]; deterministic; higher opportunity → higher
  score; fit nudges.
- `test_schema.py`: `FieldValue` raises when neither sourced nor estimate; raises
  on estimate-without-assumption; accepts sourced; `Range` reorders low/high.
- `test_offline_brief.py`: `assemble_offline` for ovs/sandro/diesel — all 7
  questions + gap/strategy present and valid; ≥1 human_sharpened field; Diesel
  q3 is needs_human (SPLIT); economics.sanity_ok; score ∈ [0,5]; JSON round-trips.
- `test_render.py`: `render_markdown`/`render_html` non-empty, contain the brand,
  a € figure, "THE GAP", and a ░ human ░ mark; `write_outputs` writes md+json+html
  to a temp dir.
- `test_sheet.py`: `rank_briefs` sorts desc and sets rank 1..N; `write_sheet`
  writes csv+md.
Run all: `python3 -m unittest discover -s tests -v` from the project root.

### README.md
Env setup, the single command, the 3 target brands, where the human layer picks
up, dual-mode note (offline always works; live needs keys), milestone map.
