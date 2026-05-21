from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agents.shared_tools.segmentation_agent import (
    render_segments_markdown,
    run_iterative_segmentation,
)

DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.azure.local"
DEFAULT_CHUNK_DIR = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_chunks_16k"
DEFAULT_JSON_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_segments.json"
DEFAULT_MD_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_segments.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the iterative LangGraph segmentation agent over chunk files.")
    parser.add_argument("--chunk-dir", type=Path, default=DEFAULT_CHUNK_DIR, help="Directory containing chunk_*.txt files.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="Optional env file for model credentials.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT, help="Path to write the raw segmentation result JSON.")
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MD_OUTPUT, help="Path to write a human-readable markdown summary.")
    return parser


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1].strip()
        if key and key not in os.environ:
            os.environ[key] = value


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    load_env_file(args.env_file)

    result = run_iterative_segmentation(args.chunk_dir)

    ensure_parent(args.json_output)
    args.json_output.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")

    ensure_parent(args.markdown_output)
    args.markdown_output.write_text(render_segments_markdown(result), encoding="utf-8")

    print(f"Wrote JSON result to {args.json_output}")
    print(f"Wrote markdown summary to {args.markdown_output}")
    print(f"Segments: {len(result.get('segments', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
