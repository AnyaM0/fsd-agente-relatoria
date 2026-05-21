from __future__ import annotations

import argparse
import os
from pathlib import Path

from agents.compras.approval_memo.pipeline import run_approval_memo_pipeline, write_approval_memo_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an approval memo from a PowerPoint and transcript chunk directory."
    )
    parser.add_argument("--ppt", type=Path, required=True, help="Path to the source PowerPoint file.")
    parser.add_argument("--chunk-dir", type=Path, required=True, help="Directory containing chunk_*.txt files.")
    parser.add_argument(
        "--segmentation-result",
        type=Path,
        required=True,
        help="JSON output from the segmentation agent containing processed_chunk_summaries.",
    )
    parser.add_argument(
        "--variant",
        choices=["ppt_led", "chunk_led"],
        default="ppt_led",
        help="Planning variant to use for the orchestrator and writers.",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for all generated outputs.")
    parser.add_argument("--env-file", type=Path, default=None, help="Optional env file for model credentials.")
    parser.add_argument("--max-themes", type=int, default=6, help="Maximum number of approval themes to keep.")
    parser.add_argument(
        "--max-revision-rounds",
        type=int,
        default=2,
        help="Maximum number of targeted clarification rounds before final validation.",
    )
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

    output_dir = args.output_dir.expanduser().resolve()
    result = run_approval_memo_pipeline(
        ppt_path=args.ppt,
        chunk_dir=args.chunk_dir,
        segmentation_result_path=args.segmentation_result,
        variant=args.variant,
        max_themes=args.max_themes,
        max_revision_rounds=args.max_revision_rounds,
        markdown_output_path=output_dir / "ppt_context.md",
    )
    paths = write_approval_memo_outputs(result, output_dir=output_dir)

    print(f"Variant: {result.variant}")
    print(f"Status: {result.status}")
    print(f"Themes: {len(result.themes)}")
    print(f"Assignments: {len(result.assignments)}")
    print(f"Drafts: {len(result.drafts)}")
    print(f"Clarification requests: {len(result.clarification_requests)}")
    print(f"Approval memo: {paths['approval_memo_markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
