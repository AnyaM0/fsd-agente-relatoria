from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agents.shared_tools.segmentation_agent import create_iterative_segmentation_graph

DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.azure.local"
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_segmentation_graph_xray.png"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export the segmentation agent LangGraph as a Mermaid PNG.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="Optional env file for model credentials.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to write the PNG.")
    parser.add_argument("--xray", action="store_true", default=True, help="Expand subgraphs in the rendered graph.")
    parser.add_argument("--no-xray", dest="xray", action="store_false", help="Render the collapsed graph.")
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

    graph = create_iterative_segmentation_graph()
    png = graph.get_graph(xray=args.xray).draw_mermaid_png()

    ensure_parent(args.output)
    args.output.write_bytes(png)

    print(f"Wrote graph PNG to {args.output}")
    print(f"xray={args.xray}")
    print(f"bytes={len(png)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
