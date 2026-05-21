from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agents.compras.approval_memo import create_approval_memo_graph


DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "compras_approval_memo_graph.png"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the compras approval memo LangGraph as a PNG.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the PNG graph.")
    parser.add_argument("--xray", action="store_true", help="Render the expanded graph with xray=1.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    graph = create_approval_memo_graph()
    rendered = graph.get_graph(xray=1 if args.xray else 0).draw_mermaid_png()

    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rendered)

    print(f"Wrote graph PNG to {output_path}")
    print(f"xray={args.xray}")
    print(f"bytes={len(rendered)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
