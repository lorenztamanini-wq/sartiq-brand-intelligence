"""Hard Rule #1 — the offline path imports with the heavy libs absent.

A single stray top-level ``import weasyprint`` (or playwright/gspread/streamlit)
would break the whole offline path. This pins the invariant: every spine and
leaf module imports cleanly, and none of the optional heavy deps gets pulled in
transitively.
"""

from __future__ import annotations

import importlib
import sys
import unittest

_SPINE_AND_LEAVES = (
    "models",
    "economics",
    "config",
    "builder",
    "cli",
    "agent",
    "tools",
    "render",
    "sheet",
    # `app` is the standalone Streamlit entry script (it sys.exit()s when
    # streamlit is absent) — it is launched, never imported, so it is not part
    # of the import contract.
    "tool_impl.research",
    "tool_impl.catalog",
    "tool_impl.vision",
    "tool_impl.history",
    "tool_impl.people",
)

_HEAVY_OPTIONAL = ("playwright", "weasyprint", "gspread", "streamlit")


class TestLazyImportContract(unittest.TestCase):
    def test_all_modules_import_cleanly(self) -> None:
        for name in _SPINE_AND_LEAVES:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_heavy_libs_not_pulled_in_transitively(self) -> None:
        # Importing the live-path modules must not load any optional heavy lib.
        for name in ("agent", "tools", "render", "sheet", "cli"):
            importlib.import_module(name)
        for heavy in _HEAVY_OPTIONAL:
            with self.subTest(heavy=heavy):
                self.assertNotIn(
                    heavy,
                    sys.modules,
                    f"{heavy} was imported at module top level — it must be lazy",
                )


if __name__ == "__main__":
    unittest.main()
