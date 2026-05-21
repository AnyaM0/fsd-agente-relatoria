from __future__ import annotations

import argparse
from pathlib import Path

from agents.shared_tools.markitdown_tool import convert_powerpoint_to_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a PowerPoint file to Markdown using MarkItDown.")
    parser.add_argument("--input", type=Path, required=True, help="Path to the PowerPoint file.")
    parser.add_argument("--output", type=Path, required=True, help="Path to write the Markdown output.")
    parser.add_argument("--enable-plugins", action="store_true", help="Enable MarkItDown plugins.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    result = convert_powerpoint_to_markdown(
        args.input,
        output_path=args.output,
        enable_plugins=args.enable_plugins,
    )
    print(f"Source: {result.source_path}")
    print(f"Markdown output: {result.output_path}")
    print(f"Chars: {len(result.markdown)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
