"""Claude-vision classification of product imagery (Q5 content profile).

Each product image is labelled with a shot type plus a few structural notes
(model present? background? garment worn?). The per-image calls are independent
and failure-tolerant: a single bad URL or malformed response is skipped, never
fatal. Offline or without an Anthropic key the function degrades to an empty,
typed result rather than raising — the offline path supplies estimates instead.

Lazy-imports `anthropic` inside `classify_images` so the module imports cleanly
with no key and no network.
"""

from __future__ import annotations

import json
from pathlib import Path

# Allowed shot labels (single source of truth for validation + aggregation).
LABELS = ("on_model", "still_life", "flat_lay", "ghost_mannequin", "video", "detail")

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "vision_classifier.md"

_INLINE_INSTRUCTION = (
    "You are a fashion e-commerce imagery analyst. Classify the single product "
    "image into exactly one shot type and note its structure.\n\n"
    "Return STRICT JSON only — no prose, no markdown fence — with these fields:\n"
    '  "label": one of '
    "on_model | still_life | flat_lay | ghost_mannequin | video | detail\n"
    '  "model_present": true|false  (is a human model visible?)\n'
    '  "background": short phrase (e.g. "studio white", "editorial street")\n'
    '  "worn": true|false  (is the garment worn on a body/mannequin?)\n\n'
    "Label guide: on_model = worn by a human; still_life = product on a surface "
    "with no body; flat_lay = laid flat top-down; ghost_mannequin = hollow-man "
    "invisible mannequin; video = a video frame/clip; detail = close crop of "
    "fabric/stitch/hardware. Output JSON and nothing else."
)


_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "data" / "vision_fixtures.json"


def agreement(predicted: list, truth: list) -> float:
    """Fraction of non-missing predictions that match the labelled truth (0..1)."""
    pairs = [(p, t) for p, t in zip(predicted, truth) if p]
    return round(sum(1 for p, t in pairs if p == t) / len(pairs), 3) if pairs else 0.0


def _load_fixtures(path=None) -> list[dict]:
    p = Path(path) if path else _FIXTURES_PATH
    try:
        return (json.loads(p.read_text(encoding="utf-8")) or {}).get("samples", [])
    except Exception:  # noqa: BLE001 — missing/bad fixtures degrade, never raise
        return []


def spotcheck(settings=None, *, fixtures_path=None) -> dict:
    """How often does the classifier agree with held-out labels? (§12b gate.)

    Offline / no key: a recorded baseline derived from representative predictions
    shipped in the fixture set. Live: re-run `classify_images` on the sample URLs
    and compare to the labels. -> {"agreement": 0..1, "n": int, "mode": str}.
    """
    samples = _load_fixtures(fixtures_path)
    if not samples:
        return {"agreement": 0.0, "n": 0, "mode": "unavailable"}
    truth = [s.get("label") for s in samples]
    key = getattr(settings, "anthropic_api_key", "") if settings else ""
    if key:
        try:
            res = classify_images([s["url"] for s in samples], settings=settings)
            predicted = [c.get("label") for c in (res.get("classifications") or [])]
            predicted = (predicted + [None] * len(samples))[: len(samples)]
            n_valid = sum(1 for p in predicted if p)
            # Only report a live figure when images actually classified. If none
            # resolved (e.g. fixture URLs unreachable), fall through to the
            # labelled baseline — never surface a misleading 0% "this run".
            if n_valid:
                return {"agreement": agreement(predicted, truth), "n": n_valid, "mode": "live"}
        except Exception:  # noqa: BLE001 — fall back to the recorded baseline
            pass
    predicted = [s.get("predicted") for s in samples]
    return {"agreement": agreement(predicted, truth), "n": len(samples), "mode": "baseline"}


def self_consistency(image_urls, settings=None, *, sample: int = 6) -> dict | None:
    """Per-run vision confidence: re-classify a small sample of the dig's OWN
    images and measure how often two independent passes agree (§12b).

    This is the honest "is the classifier right THIS run?" answer — it runs on
    images that actually resolved during the dig, not on external fixtures. Live
    only; returns None offline, on too few images, or on any failure (caller then
    falls back to the labelled baseline). -> {"agreement", "n", "mode"} | None.
    """
    key = getattr(settings, "anthropic_api_key", "") if settings else ""
    urls = [u for u in (image_urls or []) if isinstance(u, str) and u][:sample]
    if not key or len(urls) < 3:
        return None
    try:
        first = classify_images(urls, settings=settings)
        second = classify_images(urls, settings=settings)
    except Exception:  # noqa: BLE001 — fall back to the baseline
        return None
    a = {c.get("url"): c.get("label") for c in (first.get("classifications") or [])}
    b = {c.get("url"): c.get("label") for c in (second.get("classifications") or [])}
    shared = [u for u in a if u in b and a[u] and b[u]]
    if len(shared) < 3:
        return None
    agree = round(sum(1 for u in shared if a[u] == b[u]) / len(shared), 3)
    return {"agreement": agree, "n": len(shared), "mode": "self_consistency"}


def confidence_line(settings=None, *, images=None) -> str:
    """One-line vision-confidence summary for the brief's CONFIDENCE block.

    Prefers a real per-run self-consistency figure (live, on the dig's own
    images); falls back to the labelled held-out baseline otherwise.
    """
    sc = self_consistency(images, settings)
    if sc:
        return (
            f"Vision self-consistency: {round(sc['agreement'] * 100)}% label agreement "
            f"across two independent passes on {sc['n']} images from this run."
        )
    sc = spotcheck(settings)
    if sc["mode"] == "unavailable" or not sc["n"]:
        return ""
    tag = "this run" if sc["mode"] == "live" else "held-out baseline"
    return f"Vision spot-check: {round(sc['agreement'] * 100)}% classifier agreement on {sc['n']} labelled samples ({tag})."


def _load_instruction() -> str:
    """Prefer the prompt file if present; fall back to the inline instruction."""
    try:
        if _PROMPT_PATH.exists():
            text = _PROMPT_PATH.read_text(encoding="utf-8").strip()
            if text:
                return text
    except OSError:
        pass
    return _INLINE_INSTRUCTION


def _extract_json(text: str) -> dict | None:
    """Best-effort parse of strict-JSON-ish model output. None on failure."""
    text = text.strip()
    if text.startswith("```"):
        # Strip a ```json ... ``` fence if the model added one anyway.
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalise(parsed: dict, url: str) -> dict | None:
    """Coerce a parsed model dict into a validated classification record."""
    label = str(parsed.get("label", "")).strip().lower()
    if label not in LABELS:
        return None
    return {
        "url": url,
        "label": label,
        "model_present": bool(parsed.get("model_present", False)),
        "background": str(parsed.get("background", "")).strip(),
        "worn": bool(parsed.get("worn", False)),
    }


def _summarise(classifications: list[dict], sampled: int) -> dict:
    """Aggregate per-image labels into the content-profile summary."""
    n = len(classifications)
    if n == 0:
        return {
            "avg_shots": 0.0,
            "pct_on_model": 0.0,
            "pct_still_life": 0.0,
            "pct_video": 0.0,
            "consistency": "unknown",
        }

    def pct(label: str) -> float:
        return round(100.0 * sum(c["label"] == label for c in classifications) / n, 1)

    pct_on_model = pct("on_model")
    pct_still_life = pct("still_life")
    pct_video = pct("video")

    # Consistency: how dominant is the most common shot type across the sample.
    counts: dict[str, int] = {}
    for c in classifications:
        counts[c["label"]] = counts.get(c["label"], 0) + 1
    dominant_share = max(counts.values()) / n
    if dominant_share >= 0.75:
        consistency = "high"
    elif dominant_share >= 0.5:
        consistency = "medium"
    else:
        consistency = "low"

    # avg_shots = classified images per sampled PDP-ish unit; without per-PDP
    # grouping we report the average classified-images per attempted image as a
    # coverage-aware figure (1.0 == every sampled image classified cleanly).
    avg_shots = round(n / sampled, 2) if sampled else 0.0

    return {
        "avg_shots": avg_shots,
        "pct_on_model": pct_on_model,
        "pct_still_life": pct_still_life,
        "pct_video": pct_video,
        "consistency": consistency,
    }


def classify_images(image_urls: list[str], *, settings) -> dict:
    """Classify product images with Claude vision into a content profile.

    Args:
        image_urls: candidate product-image URLs (capped at settings.pdp_sample_size).
        settings: a config.Settings — reads anthropic_api_key, vision_model,
            pdp_sample_size.

    Returns a JSON-serializable dict:
        {"classifications": list[dict], "summary": dict, "error": str|None}
    Offline / no key adds "note" and returns empties — never raises.
    """
    if not getattr(settings, "anthropic_api_key", ""):
        return {
            "classifications": [],
            "summary": {},
            "note": "vision unavailable offline",
            "error": None,
        }

    try:
        import anthropic  # lazy: missing/offline-safe and only needed live
    except ImportError as exc:  # pragma: no cover - anthropic is a present lib
        return {
            "classifications": [],
            "summary": {},
            "note": "vision unavailable offline",
            "error": f"anthropic import failed: {exc}",
        }

    cap = max(0, int(getattr(settings, "pdp_sample_size", 30)))
    urls = [u for u in (image_urls or []) if isinstance(u, str) and u][:cap]
    if not urls:
        return {"classifications": [], "summary": _summarise([], 0), "error": None}

    instruction = _load_instruction()
    model = getattr(settings, "vision_model", None) or getattr(
        settings, "model", "claude-opus-4-8"
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    except Exception as exc:  # noqa: BLE001 - construction must not crash the loop
        return {
            "classifications": [],
            "summary": {},
            "error": f"anthropic client init failed: {exc}",
        }

    classifications: list[dict] = []
    last_error: str | None = None

    for url in urls:
        try:
            # Classification is a fast labelling task: no extended thinking
            # (which would also force max_tokens >= 1024), low effort to keep
            # cost sane across a 20-40 image sample.
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                output_config={"effort": "low"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {"type": "url", "url": url},
                            },
                            {"type": "text", "text": instruction},
                        ],
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001 - per-image tolerance: skip & continue
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        parsed = _extract_json(text)
        if parsed is None:
            continue
        record = _normalise(parsed, url)
        if record is not None:
            classifications.append(record)

    summary = _summarise(classifications, len(urls))
    error = last_error if not classifications else None
    return {"classifications": classifications, "summary": summary, "error": error}
