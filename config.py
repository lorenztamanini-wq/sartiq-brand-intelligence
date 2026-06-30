"""Configuration, .env loading, and validated data loaders.

No third-party config dependency: `.env` is parsed by hand so the offline core
runs with only the libraries already present (pydantic, pyyaml). API keys and
heavy tools are read here but only *used* by the live path.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from models import Benchmarks, BrandTruth

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROMPTS_DIR = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"


def load_env(path: Path | None = None) -> None:
    """Minimal KEY=VALUE .env loader. Does not overwrite existing env vars."""
    path = path or (BASE_DIR / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


class Settings:
    """Runtime settings; reads env (call load_env() first for .env support)."""

    def __init__(self) -> None:
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.apollo_api_key = os.getenv("APOLLO_API_KEY", "")
        self.exa_api_key = os.getenv("EXA_API_KEY", "")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY", "")

        self.model = os.getenv("BRAND_BRIEF_MODEL", "claude-opus-4-8")
        # Vision can run on a cheaper tier at catalog scale; default to the
        # main model and let the operator downshift via env.
        self.vision_model = os.getenv("BRAND_BRIEF_VISION_MODEL", "claude-opus-4-8")
        # Basic web search (no server-side code execution / container state) is the
        # reliable default; the _20260209 variant adds dynamic filtering but runs
        # code execution under the hood, which complicates the manual tool loop.
        self.web_search_tool = os.getenv("BRAND_BRIEF_WEB_SEARCH_TOOL", "web_search_20250305")

        # Guardrails (non-negotiable for a real agent).
        self.max_tool_calls = int(os.getenv("BRAND_BRIEF_MAX_TOOL_CALLS", "25"))
        self.wall_clock_seconds = int(os.getenv("BRAND_BRIEF_WALL_CLOCK_S", "300"))
        self.pdp_sample_size = int(os.getenv("BRAND_BRIEF_PDP_SAMPLE", "30"))
        self.http_timeout = float(os.getenv("BRAND_BRIEF_HTTP_TIMEOUT", "20"))

    @property
    def has_live(self) -> bool:
        """Live digging is possible only with an Anthropic key present."""
        return bool(self.anthropic_api_key)


def get_settings() -> Settings:
    load_env()
    return Settings()


def load_benchmarks(path: Path | None = None) -> Benchmarks:
    path = path or (DATA_DIR / "benchmarks.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Benchmarks.model_validate(data)


def load_ground_truth(path: Path | None = None) -> dict[str, BrandTruth]:
    """Load and validate the pre-loaded brand intelligence, keyed by slug."""
    path = path or (DATA_DIR / "ground_truth.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, BrandTruth] = {}
    for slug, raw in (data.get("brands") or {}).items():
        out[slug] = BrandTruth.model_validate(raw)
    return out


def resolve_brand(name: str, truth: dict[str, BrandTruth]) -> str | None:
    """Map a free-text brand name, alias, or site domain to a slug, or None."""
    needle = name.strip().lower()
    for prefix in ("https://", "http://", "www."):
        if needle.startswith(prefix):
            needle = needle[len(prefix) :]
    needle = needle.rstrip("/")
    for slug, bt in truth.items():
        site = bt.site.lower().removeprefix("www.")
        candidates = {slug, bt.name.lower(), site} | {a.lower() for a in bt.aliases}
        if needle in candidates:
            return slug
    return None
