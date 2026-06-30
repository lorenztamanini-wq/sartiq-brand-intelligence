"""brand-brief — one command, a sourced one-page brief + structured JSON.

    python cli.py "Sandro"            # auto: live if ANTHROPIC_API_KEY set, else offline
    python cli.py "Sandro" --offline  # force the deterministic offline brief
    python cli.py "Sandro" --live     # force the Claude tool-use research loop
    python cli.py --all               # run OVS, Sandro, Diesel -> ranked sheet

Offline mode always works (no key, no network) and is the dual-mode fallback.
Live mode digs with Claude when keys are present; the human judgment layer
picks up from the `needs_human` / ░human░ flags.
"""

from __future__ import annotations

import argparse
import sys

import builder
import render
import sheet
from config import get_settings, load_ground_truth, resolve_brand
from models import Brief


def _load_all_briefs(out_dir: str) -> list[Brief]:
    """Every brief JSON on disk in out_dir, so digging one brand keeps the others
    on the ranked dashboard instead of wiping them."""
    import glob

    import review

    briefs: list[Brief] = []
    for path in sorted(glob.glob(f"{out_dir}/*.json")):
        try:
            briefs.append(review.load_brief(path))
        except Exception:  # noqa: BLE001 — skip a malformed/foreign json, never crash
            continue
    return briefs


def _resolve_mode(args, settings) -> str:
    if args.offline:
        return "offline"
    if args.live:
        return "live"
    return "live" if settings.has_live else "offline"


def _get_brief(brand: str, mode: str, settings, truth, progress=None) -> Brief:
    slug = resolve_brand(brand, truth)
    if mode == "offline":
        if slug is None:
            raise SystemExit(
                f"'{brand}' is not a seeded brand. Offline mode covers: "
                f"{', '.join(sorted(truth))}. Run with --live (needs ANTHROPIC_API_KEY)."
            )
        return builder.assemble_offline(slug, truth=truth)
    # Live path — import the agent lazily so offline never needs the heavy stack.
    from agent import run as run_agent

    return run_agent(brand, mode="live", settings=settings, progress=progress)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brand-brief", description=__doc__)
    parser.add_argument("brand", nargs="?", help='brand name, e.g. "Sandro"')
    parser.add_argument("--all", action="store_true", help="run all seeded brands (OVS, Sandro, Diesel)")
    parser.add_argument("--offline", action="store_true", help="force deterministic offline brief")
    parser.add_argument("--live", action="store_true", help="force the Claude research loop")
    parser.add_argument("--draft", action="store_true", help="(default) emit the AI draft brief")
    parser.add_argument("--out", default=None, help="output directory (default: ./output)")
    parser.add_argument("--no-pdf", action="store_true", help="skip PDF rendering")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a human-confirmed brief on re-dig (default: keep the confirmed one)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="don't open the dashboard in your browser when the run finishes",
    )
    args = parser.parse_args(argv)

    if not args.brand and not args.all:
        parser.error("provide a brand name or --all")

    settings = get_settings()
    truth = load_ground_truth()
    mode = _resolve_mode(args, settings)

    # Never silently downgrade an *explicit* --live: Luca must not believe the
    # agent dug live when it served the deterministic seed.
    if args.live and not settings.has_live:
        raise SystemExit(
            "--live requires ANTHROPIC_API_KEY (set it in .env). "
            "Drop --live for the deterministic offline brief instead."
        )

    def progress(msg: str) -> None:
        print(f"  … {msg}", file=sys.stderr)

    targets = sorted(truth) if args.all else [args.brand]
    briefs: list[Brief] = []
    for target in targets:
        print(f"▶ digging: {target}  (mode={mode})", file=sys.stderr)
        try:
            briefs.append(_get_brief(target, mode, settings, truth, progress))
        except SystemExit:
            raise  # already a clean, intentional message
        except Exception as err:  # noqa: BLE001 — a clean message beats a traceback
            raise SystemExit(
                f"\n✖ live dig of '{target}' failed: {err}\n"
                "  Transient web/API errors happen — try again. For the three "
                "seeded brands you can always use --offline."
            )

    out_dir = args.out or "output"

    # P3.1: a re-dig must not clobber a human-confirmed brief. Keep the confirmed
    # version (file + dashboard) unless --force; the fresh dig is discarded.
    if not args.force:
        guarded: list[Brief] = []
        for b in briefs:
            confirmed = render.load_confirmed(b, out_dir)
            if confirmed is not None:
                print(
                    f"  ⚠ {b.brand}: kept the human-confirmed brief — re-dig discarded "
                    "(pass --force to overwrite).",
                    file=sys.stderr,
                )
                guarded.append(confirmed)
            else:
                guarded.append(b)
        briefs = guarded

    # Write the freshly-dug brief(s) — these drive the auto-open + console banner.
    dug = sheet.rank_briefs(briefs)
    written: list[dict] = []
    for b in dug:
        written.append(render.write_outputs(b, out_dir, want_pdf=not args.no_pdf))

    # Dashboard + sheet reflect EVERY brief in the output dir (this dig merged with
    # previously-dug brands) — digging one brand never wipes the others off the desk.
    ranked = sheet.rank_briefs(_load_all_briefs(out_dir))
    sheet_paths = sheet.write_sheet(ranked, out_dir)
    index_path = render.write_index(ranked, out_dir)

    # Console summary — banner = the ACTUAL mode of THIS run; table = the full desk.
    actual_modes = sorted({b.generated_mode for b in dug})
    banner = "MODE: " + " / ".join(m.upper() for m in actual_modes)
    if all("offline" in m for m in actual_modes) and not settings.has_live:
        banner += "  (set ANTHROPIC_API_KEY for live digging)"
    print("\n" + banner)
    print("=" * 64)
    print(f"{'rank':>4}  {'score':>5}  {'brand':<10}  opportunity (brand / +partners)")
    print("-" * 64)
    for b in ranked:
        opp = b.economics.annual_opportunity_range
        par = b.economics.partner_upside_range
        print(
            f"{b.rank:>4}  {b.opportunity_score:>5}  {b.brand:<10}  "
            f"€{opp.low/1e6:.1f}–{opp.high/1e6:.1f}M  /  +€{par.low/1e6:.1f}–{par.high/1e6:.1f}M"
        )
    print("=" * 64)
    for w in written:
        print(f"  brief: {w.get('md')}")
    print(f"  sheet: {sheet_paths.get('csv')}  |  {sheet_paths.get('md')}")
    print(f"  desk:  {index_path}  (ranked dashboard, click a brief)")

    # Open the rendered brief(s) AND the dashboard in the browser. Suppress with
    # --no-open (CI/scripts). Never fatal: a headless box just prints the path.
    if not args.no_open:
        import webbrowser
        from pathlib import Path

        targets = [w["html"] for w in written if w.get("html")] + [index_path]
        opened_any = False
        for t in targets:
            try:
                if webbrowser.open(Path(t).resolve().as_uri()):
                    opened_any = True
            except Exception:
                pass
        print(
            "  → opened the brief(s) + dashboard in your browser"
            if opened_any
            else f"  (couldn't auto-open — run:  open {index_path})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
