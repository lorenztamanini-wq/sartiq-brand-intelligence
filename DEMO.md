# DEMO — the 2-minute screen recording

A record-ready walkthrough, mapped to the spec's timestamps. **Run `make demo` once before recording** so `output/` is populated. Offline path, no key needed.

**The line to land:** *"A machine that finds and sizes opportunities, and a human who sharpens them — here's both."*

---

## 0:00–0:15 — Hook (the dashboard)

- On screen: **`output/index.html`** open in a browser.
- Say: *"You asked for a machine that finds and sizes opportunities, and a human who sharpens them. Here's both."*
- Point at the ranking: three brands, scored, each row a brand/+partner euro band, each linking to its brief.
  - `#1 Diesel · 3.5 · €3.9–19.5M / +€15.6–78.0M`
  - `#2 Sandro · 3.2 · €2.7–12.9M / +€8.2–38.8M`
  - `#3 OVS · 3.1 · €6.4–37.7M / +€7.7–45.3M`
- This is the "what lands on your desk" artifact — one ranked sheet, a click per brief.

## 0:15–0:45 — The machine digging

- Run it live in the terminal:
  ```bash
  make demo        # or: python3 cli.py --all --offline
  ```
- On screen: the `▶ digging:` lines, the **`MODE: OFFLINE`** banner, the ranked console summary, and the closing `desk: output/index.html` line.
- Say: *"One command digs all three, answers the seven questions, sizes the euro opportunity, and ranks them — deterministically, no key."*
- (Live note: with `ANTHROPIC_API_KEY` set, `python3 cli.py "Sandro" --live` runs the real Claude tool-use loop — web search, PDP audit, the vision classifier labelling on-model vs still-life. The banner flips to `MODE: LIVE`.)

## 0:45–1:15 — The brief

- Open **`output/sandro.md`** (or `sandro.html`).
- Walk the seven answers top to bottom: WHO · DIRECTION · MOMENTUM · ON THE PDPs · CONTENT NEED · DECISION-MAKER · CONTACT.
- Land on the economics block — the **€ range**, both bottom-up and the top-down cross-check, sanity gate `OK`:
  > **OPPORTUNITY (brand):** €2.7–12.9M/yr · **PARTNERS upside:** €8.2–38.8M/yr
- Say: *"The real number isn't the brand — it's the group. One relationship covers Sandro, Maje, Claudie Pierlot and Fursac: the **×4 SMCP partner upside**, €8.2–38.8M."*

## 1:15–1:45 — THE JUDGMENT (point the camera here)

The two on-camera "I overrode the AI" moments. Both render as a visible delta — read the `⟲ AI draft` → `░ human ░` lines straight off the brief.

**A. The OVS € reframe** (open `output/ovs.md`, CONTENT NEED block):
> ⟲ **AI draft —** €42.5–283.4M/yr (flat agency rate, tier-blind)
> ░ human ░ **reframed —** AI draft applied flat agency rates tier-blind (~€163M); reframed to the mass cost basis (€15–60/image).

- Say: *"The AI sized this on a flat agency rate — €42.5 to 283 million, tier-blind. But OVS is value retail with an in-house studio; the right per-image cost is €15–60. Reframed, it's €6.4–37.7M — and the wedge flips from 'cut your photo budget' to 'scale your studio.'"*

**B. The Diesel momentum SPLIT** (open `output/diesel.md`, MOMENTUM block):
> ⟲ **AI draft —** STRUGGLING — OTB group −4.8%, EBIT squeezed to ~€10m, wholesale −14.7%: the group is in decline.
> ░ human ░ **why I changed it —** … Diesel-the-brand posted its best profitability in 10 years — so the read is SPLIT, not struggling … they need OPPOSITE pitches (innovation to Diesel, efficiency to OTB).

- Say: *"The machine reads the group P&L and says 'struggling.' From the industry I know Diesel itself just had its best year in a decade — so it's a SPLIT: innovation to the brand, efficiency to the group. The sharpest single read in the set, and the machine wouldn't infer it."*

## 1:45–2:00 — The handoff

- Back to **`output/index.html`**.
- Say: *"What lands on your desk: one ranked sheet, a click per brief, AI draft in minutes, my judgment same day — and you can run the AI half yourself."*
- End on the command, on screen:
  ```bash
  python3 cli.py "Sandro"     # or: make demo
  ```

---

### Pre-flight checklist

- [ ] `make demo` run; `output/index.html`, `output/sandro.md`, `output/ovs.md`, `output/diesel.md` all present.
- [ ] Browser open on `output/index.html`; terminal cleared and ready.
- [ ] The two judgment deltas (OVS €, Diesel SPLIT) bookmarked so you can jump to them on camera.
