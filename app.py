"""Streamlit review form — the human becomes part of the system.

    streamlit run app.py

The model digs and *proposes* the sharpening; you confirm or tweak each flagged
field, then publish. Publishing re-renders the brief (with `✓ confirmed` marks)
and refreshes the ranked dashboard. All logic lives in `review.py`; this file is
a thin UI shell, lazily importing streamlit so the rest of the project stays
importable without it.
"""

from __future__ import annotations

import sys

try:
    import streamlit as st
except ImportError:  # keep the project importable without streamlit
    print(
        "Streamlit isn't installed. Install it with:\n"
        "  pip install streamlit\n"
        "then run:\n"
        "  streamlit run app.py"
    )
    sys.exit(0)

import config
import render
import review
from agent import run as run_agent

OUT = str(config.OUTPUT_DIR)
settings = config.get_settings()

st.set_page_config(page_title="Sartiq — Brand Intelligence", layout="wide")
st.title("Sartiq — Brand Intelligence")
st.caption("AI digs and proposes the sharpening. You confirm or tweak. Then publish.")

# --------------------------------------------------------------------------- #
# Sidebar — dig a brand into a draft
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Dig a brand")
    brand = st.text_input("Brand name", placeholder="e.g. Sandro")
    mode = st.radio(
        "Mode", ["auto", "offline", "live"], horizontal=True,
        help="auto/live = real dig when ANTHROPIC_API_KEY is set, else offline seed",
    )
    if st.button("Dig →", disabled=not brand.strip()):
        run_mode = "offline" if mode == "offline" else "live"
        with st.status(f"Digging {brand}…", expanded=True) as status:
            try:
                brief = run_agent(
                    brand, mode=run_mode, settings=settings,
                    progress=lambda m: status.write(m),
                )
                review.publish(brief, OUT)  # write draft + refresh dashboard
                status.update(label=f"Draft ready — {brief.brand}", state="complete")
                st.session_state["selected"] = render._slug(brief)
            except Exception as exc:  # noqa: BLE001 — show the reason, don't crash the app
                status.update(label=f"Dig failed: {exc}", state="error")
    if not settings.has_live:
        st.info("No API key → digs run offline. Add ANTHROPIC_API_KEY to .env for live.")

# --------------------------------------------------------------------------- #
# Main — review queue + publish
# --------------------------------------------------------------------------- #
drafts = review.list_drafts(OUT)
if not drafts:
    st.info("No briefs yet — dig a brand from the sidebar (offline works with no key).")
    st.stop()

slugs = [p.stem for p in drafts]
default = st.session_state.get("selected")
idx = slugs.index(default) if default in slugs else 0
choice = st.selectbox("Brief to review", slugs, index=idx)
brief = review.load_brief(f"{OUT}/{choice}.json")

head_l, head_r = st.columns([4, 1])
head_l.subheader(brief.brand)
head_l.caption(f"{brief.positioning} · {brief.parent_group}")
head_r.metric("Score", f"{brief.opportunity_score}/5")
st.markdown(
    f"**Mode:** `{brief.generated_mode}` · "
    f"**Opportunity:** €{brief.economics.annual_opportunity_range.low / 1e6:.1f}"
    f"–{brief.economics.annual_opportunity_range.high / 1e6:.1f}M/yr"
)

items = review.reviewable_fields(brief)
if not items and not review.approach_pending(brief):
    st.success("✓ Every field is operator-confirmed — this brief is publish-ready.")

st.markdown("### Review queue — confirm or tweak each proposal, then publish")
edits: dict[str, str] = {}
with st.form("review_form"):
    for it in items:
        st.markdown(f"**{it['label']}** · confidence `{it['confidence']}`")
        if it.get("ai_draft"):
            st.caption(f"⟲ AI draft — {it['ai_draft']}")
        if it.get("rationale"):
            st.caption(f"░ human ░ why — {it['rationale']}")
        edits[it["name"]] = st.text_area(
            it["label"], value=it["value"], key=f"v_{it['name']}",
            label_visibility="collapsed",
        )
        st.divider()

    ap = brief.approach
    st.markdown("**Approach — the play to get in**")
    a_hook = st.text_input("Hook", ap.hook, key="ap_hook")
    a_channel = st.text_input("Channel", ap.channel, key="ap_channel")
    a_to = st.text_input("To whom", ap.to_whom, key="ap_to")
    a_open = st.text_area("Opening message", ap.opening, key="ap_open")

    submitted = st.form_submit_button("✓ Approve all & publish", type="primary")

if submitted:
    updated = brief
    for name, value in edits.items():
        updated = review.apply_field_edit(updated, name, value, confirmed=True)
    updated = review.apply_approach_edit(
        updated, hook=a_hook, channel=a_channel, to_whom=a_to, opening=a_open,
        confirmed=True,
    )
    paths = review.publish(updated, OUT)
    st.success(f"Published — {updated.brand} is operator-confirmed and the dashboard is refreshed.")
    st.markdown(f"- Brief: `{paths.get('md')}`\n- Dashboard: `{paths.get('index')}`")
    st.balloons()
