from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agents.compras.acta_graph import create_compras_acta_graph


DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "compras_acta_graph.png"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the compras root acta LangGraph as a PNG.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--xray", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    graph = create_compras_acta_graph()
    png = graph.get_graph(xray=1 if args.xray else 0).draw_mermaid_png()

    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png)

    print(f"Wrote graph PNG to {output_path}")
    print(f"xray={args.xray}")
    print(f"bytes={len(png)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
