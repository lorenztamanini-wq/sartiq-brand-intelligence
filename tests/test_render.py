"""Tests for brief rendering (render.py).

Exercises Markdown + HTML rendering of an offline brief (non-empty, contains
the brand, a euro figure, "THE GAP", and the ░ human ░ marker) and that
write_outputs lands the .md/.json/.html files in a temp directory.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from builder import assemble_offline
from render import render_html, render_markdown, write_outputs

_HUMAN_MARK = "░ human ░"  # "░ human ░"


class TestRender(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = assemble_offline("diesel")

    def _assert_contains_brief_tokens(self, text: str) -> None:
        self.assertTrue(text.strip(), "render output is empty")
        self.assertIn(self.brief.brand, text)
        self.assertIn("€", text)  # euro sign
        # The "gap" heading is GAP in Markdown and uppercased via CSS in HTML;
        # match case-insensitively so the assertion tracks rendered intent, not
        # the template's casing choice.
        self.assertIn("gap", text.lower())
        self.assertIn(_HUMAN_MARK, text)

    def test_render_markdown_contains_tokens(self) -> None:
        self._assert_contains_brief_tokens(render_markdown(self.brief))

    def test_render_html_contains_tokens(self) -> None:
        self._assert_contains_brief_tokens(render_html(self.brief))

    def test_write_outputs_writes_md_json_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = write_outputs(self.brief, tmp, want_pdf=False)

            for key in ("md", "json", "html"):
                with self.subTest(output=key):
                    path = result.get(key)
                    self.assertIsNotNone(path, f"{key} path missing")
                    self.assertTrue(Path(path).is_file(), f"{key} not written")

            # The JSON output must be parseable and carry the brand.
            data = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
            self.assertEqual(data["brand"], self.brief.brand)


if __name__ == "__main__":
    unittest.main()
