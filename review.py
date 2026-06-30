"""Human review/approve layer — turn a flagged draft into a confirmed brief.

The model digs and *proposes* the sharpening; the operator confirms or edits.
This is the logic behind the Streamlit review form (`app.py`) — pure functions,
fully testable offline, so the form stays a thin shell.

Flow: a draft brief lands with proposed values + `⚑ needs human` flags. The
operator reviews only the flagged fields (each pre-filled with the proposal,
its AI draft, the rationale, and a confidence). On approve/edit the field is
marked `human_confirmed`; on publish, every artifact (brief + dashboard + sheet)
is re-rendered so the report is signed-off and shareable.
"""

from __future__ import annotations

from pathlib import Path

import render
import sheet
from models import Brief

# Friendly labels for the review queue.
FIELD_LABELS: dict[str, str] = {
    "q1_who": "1 · Who they are",
    "q2_direction": "2 · Direction of travel",
    "q3_momentum": "3 · Momentum",
    "q5_pdp": "5 · On the PDPs",
    "q4_content_need": "4 · Content need + opportunity",
    "q6_decision_maker": "6 · Decision-maker",
    "q7_contact": "7 · Contact + warm path",
    "gap": "The gap we fill",
    "strategy": "Strategy",
}


def load_brief(path: str | Path) -> Brief:
    """Load a draft brief from its JSON record."""
    return Brief.model_validate_json(Path(path).read_text(encoding="utf-8"))


def list_drafts(out_dir: str | Path) -> list[Path]:
    """All brief JSON records in an output dir (newest first)."""
    paths = [p for p in Path(out_dir).glob("*.json")]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def reviewable_fields(brief: Brief) -> list[dict]:
    """The fields awaiting operator sign-off — proposal + draft + why + confidence.

    A field is reviewable if it's human-owned or flagged, and not yet confirmed.
    """
    out: list[dict] = []
    for fv in brief.all_fields():
        if (fv.needs_human or fv.human_sharpened) and not fv.human_confirmed:
            out.append(
                {
                    "name": fv.name,
                    "label": FIELD_LABELS.get(fv.name, fv.name),
                    "value": fv.value,
                    "ai_draft": fv.ai_draft,
                    "rationale": fv.sharpen_rationale,
                    "confidence": fv.confidence.value,
                }
            )
    return out


def approach_pending(brief: Brief) -> bool:
    """True if the outreach play still needs operator sign-off."""
    return not brief.approach.human_confirmed


def apply_field_edit(brief: Brief, name: str, new_value: str, *, confirmed: bool = True) -> Brief:
    """Return a new Brief with one field's value updated and (optionally) confirmed.

    Immutable: never mutates the input. Confirming clears `needs_human` and sets
    `human_confirmed` (so the brief renders `✓ confirmed`).
    """
    fv = getattr(brief, name)
    updates = {"value": new_value, "human_sharpened": True}
    if confirmed:
        updates["human_confirmed"] = True
        updates["needs_human"] = False
    return brief.model_copy(update={name: fv.model_copy(update=updates)})


def apply_approach_edit(
    brief: Brief,
    *,
    hook: str,
    channel: str,
    to_whom: str,
    opening: str,
    confirmed: bool = True,
) -> Brief:
    """Return a new Brief with the outreach play updated and (optionally) confirmed."""
    ap = brief.approach.model_copy(
        update={
            "hook": hook,
            "channel": channel,
            "to_whom": to_whom,
            "opening": opening,
            "human_sharpened": True,
            "human_confirmed": confirmed,
        }
    )
    return brief.model_copy(update={"approach": ap})


def is_fully_confirmed(brief: Brief) -> bool:
    """True when nothing is left flagged for the human."""
    return not reviewable_fields(brief) and not approach_pending(brief)


def has_confirmed_work(brief: Brief) -> bool:
    """True if a human has confirmed any field or the outreach play (P3.1)."""
    if brief.approach.human_confirmed:
        return True
    return any(fv.human_confirmed for fv in brief.all_fields())


def publish(brief: Brief, out_dir: str | Path) -> dict:
    """Write the (re)confirmed brief, then refresh the dashboard + sheet.

    Re-ranks across every brief in the dir so the dashboard stays consistent.
    Returns the written paths (brief outputs + index).
    """
    out_dir = str(out_dir)
    written = render.write_outputs(brief, out_dir)

    briefs = [load_brief(p) for p in sorted(Path(out_dir).glob("*.json"))]
    ranked = sheet.rank_briefs(briefs)
    sheet.write_sheet(ranked, out_dir)
    index_path = render.write_index(ranked, out_dir)

    written["index"] = index_path
    return written
