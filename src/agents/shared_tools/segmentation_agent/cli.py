from __future__ import annotations

import argparse
import os
from pathlib import Path

from agents.shared_tools.segmentation_agent.pipeline import (
    run_segmentation_pipeline_from_file,
    write_segmentation_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chunk a transcript text file and then run the LangGraph segmentation pipeline."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to the input text file.")
    parser.add_argument("--chunks-output-dir", type=Path, required=True, help="Directory for chunk_*.txt files and chunks.json.")
    parser.add_argument("--json-output", type=Path, required=True, help="Path to write the segmentation JSON.")
    parser.add_argument("--markdown-output", type=Path, required=True, help="Path to write the segmentation markdown summary.")
    parser.add_argument("--env-file", type=Path, default=None, help="Optional env file for model credentials.")
    parser.add_argument("--chunk-max-tokens", type=int, default=16_000, help="Maximum tokens per chunk using o200k_base.")
    return parser


def load_env_file(path: Path | None) -> None:
    if path is None or not path.exists():
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    load_env_file(args.env_file)

    pipeline_result = run_segmentation_pipeline_from_file(
        args.input,
        chunks_output_dir=args.chunks_output_dir,
        max_tokens=args.chunk_max_tokens,
    )
    write_segmentation_outputs(
        pipeline_result,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )

    print(f"Chunk directory: {pipeline_result.chunk_dir}")
    print(f"Chunks metadata: {pipeline_result.chunks_metadata_path}")
    print(f"JSON output: {args.json_output.expanduser().resolve()}")
    print(f"Markdown output: {args.markdown_output.expanduser().resolve()}")
    print(f"Segments: {len(pipeline_result.result.get('segments', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
