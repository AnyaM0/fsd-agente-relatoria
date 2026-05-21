from __future__ import annotations

import argparse
from pathlib import Path

from agents.juridica.acta_graph import run_juridica_acta_graph
from agents.shared_tools.cli_utils import load_env_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the juridica end-to-end graph.")
    parser.add_argument("--audio", type=Path, default=None)
    parser.add_argument("--transcript", type=Path, default=None)
    parser.add_argument("--ppt", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chunk-dir", type=Path, default=None)
    parser.add_argument("--segmentation-result", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--variant", choices=["auto", "ppt_led", "chunk_led"], default="auto")
    parser.add_argument("--chunk-max-tokens", type=int, default=16_000)
    parser.add_argument("--max-themes", type=int, default=6)
    parser.add_argument("--max-revision-rounds", type=int, default=2)
    return parser
def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    load_env_file(args.env_file)
    result = run_juridica_acta_graph(
        audio_path=args.audio,
        transcript_path=args.transcript,
        ppt_path=args.ppt,
        output_dir=args.output_dir,
        chunk_dir=args.chunk_dir,
        segmentation_result_path=args.segmentation_result,
        variant=args.variant,
        max_themes=args.max_themes,
        max_revision_rounds=args.max_revision_rounds,
        chunk_max_tokens=args.chunk_max_tokens,
    )
    print(f"Status: {result.status}")
    if result.transcript_path:
        print(f"Transcript path: {result.transcript_path}")
    print(f"Acta final markdown: {result.acta_markdown_path}")
    print(f"Acta final json: {result.acta_json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
