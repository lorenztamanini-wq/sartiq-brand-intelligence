# Sartiq — Brand Intelligence Agent

Type a fashion brand → a sourced, one-page **opportunity brief**: the 7 qualifying
questions, a quantified **Sartiq** opportunity (brand + its group, per-brand), the
wedge, the strategy call, and a sendable outreach play. The AI digs and *proposes*;
**you confirm the judgment** before it counts.

> **New here?** Open **[`GUIDE.html`](GUIDE.html)** (download it and open in a browser) —
> a visual walkthrough of what it does and how to use it. This README is just setup + run.

---

## Requirements
- **Python 3.11+**
- *(Optional)* an **Anthropic API key** for live digging. Without any key it runs in
  **offline mode** and still produces complete, sourced briefs for the three seeded
  brands (OVS, Sandro, Diesel).

## 1. Setup (one command)
```bash
make setup      # creates a .venv, installs deps, and scaffolds .env from .env.example
```
<sub>Prefer manual? `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && cp .env.example .env`</sub>

## 2. Try it with no key (offline)
```bash
make demo       # builds OVS / Sandro / Diesel briefs + a ranked dashboard
open output/index.html
```

## 3. Run it for real (the product)
```bash
source .venv/bin/activate
streamlit run app.py      # → http://localhost:8501
```
In the sidebar: type **any** brand → pick **live** → **Dig →** → review/confirm each
flagged field → **Publish**. Each brand you dig accumulates on the ranked dashboard.

## 4. Add your API key (for live digs)
`make setup` created a `.env`. Open it and set your key — **that's the only change needed**
(no folders to rename, nothing else to configure):
```dotenv
ANTHROPIC_API_KEY=sk-ant-...
```
That's it. A live dig costs roughly **$1** in API credit and takes ~1–3 min.
`APOLLO_API_KEY` is optional (named-contact enrichment for Q7).

## Command-line alternative
```bash
python cli.py "Mango"          # auto: live if a key is set, else offline
python cli.py "Sandro" --live  # force a live dig
python cli.py --all --offline  # the three seeded brands, no key
python cli.py "OVS" --out mydir --no-open
```

## Where the output lands
Everything is written to **`output/`**: each brief as `.md` / `.html` / `.json`,
plus **`index.html`** (the ranked "prioritization dashboard") and a CSV/MD sheet.
Run `make demo` to generate a set for OVS / Sandro / Diesel.

## Configuration (optional, via `.env`)
| Variable | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | enables live mode |
| `APOLLO_API_KEY` | — | named-contact enrichment (Q7) |
| `BRAND_BRIEF_MODEL` | `claude-opus-4-8` | the reasoning model |
| `BRAND_BRIEF_VISION_MODEL` | `claude-opus-4-8` | image classifier (`claude-haiku-4-5` is cheaper) |
| `BRAND_BRIEF_MAX_TOOL_CALLS` | `25` | agent guardrail |
| `BRAND_BRIEF_WALL_CLOCK_S` | `300` | agent time budget |
| `BRAND_BRIEF_PDP_SAMPLE` | `30` | product pages sampled per brand |

---
*Offline mode always works (no key, no network). Live mode digs with Claude when a key
is present. The euro figure and score are computed by a deterministic model — the agent
supplies inputs but can never write the number.*
