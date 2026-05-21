from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

from agents.shared_tools.markitdown_tool import convert_powerpoint_to_markdown


class MarkItDownPowerPointTests(unittest.TestCase):
    def test_convert_powerpoint_to_markdown_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "demo.pptx"
            output_path = tmp_path / "demo.md"
            input_path.write_bytes(b"fake-pptx")

            fake_module = types.ModuleType("markitdown")

            class FakeResult:
                text_content = "# Slide 1\n\nHello world"

            class FakeMarkItDown:
                def __init__(self, **kwargs) -> None:
                    self.kwargs = kwargs

                def convert(self, path: str) -> FakeResult:
                    self.path = path
                    return FakeResult()

            fake_module.MarkItDown = FakeMarkItDown
            previous = sys.modules.get("markitdown")
            sys.modules["markitdown"] = fake_module
            try:
                result = convert_powerpoint_to_markdown(input_path, output_path=output_path)
            finally:
                if previous is None:
                    sys.modules.pop("markitdown", None)
                else:
                    sys.modules["markitdown"] = previous

            self.assertEqual(result.source_path, str(input_path.resolve()))
            self.assertEqual(result.output_path, str(output_path.resolve()))
            self.assertIn("Hello world", result.markdown)
            self.assertEqual(output_path.read_text(encoding="utf-8"), result.markdown)

    def test_convert_powerpoint_to_markdown_rejects_non_powerpoint_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "demo.txt"
            input_path.write_text("not a powerpoint", encoding="utf-8")

            with self.assertRaises(ValueError):
                convert_powerpoint_to_markdown(input_path)


if __name__ == "__main__":
    unittest.main()
