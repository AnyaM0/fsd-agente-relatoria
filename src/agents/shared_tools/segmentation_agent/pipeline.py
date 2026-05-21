from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agents.shared_tools.segmentation_agent.chunking import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TOKEN_ENCODING,
    TokenChunker,
    write_chunks_to_directory,
)
from agents.shared_tools.segmentation_agent.langgraph_agent import (
    render_segments_markdown,
    run_iterative_segmentation,
)


@dataclass(frozen=True)
class SegmentationPipelineResult:
    chunk_dir: str
    chunks_metadata_path: str
    result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SegmentationPipeline:
    def __init__(
        self,
        *,
        encoding_name: str = DEFAULT_TOKEN_ENCODING,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model=None,
    ) -> None:
        self.chunker = TokenChunker(
            encoding_name=encoding_name,
            max_tokens=max_tokens,
        )
        self.model = model

    def chunk_text(self, text: str, output_dir: str | Path) -> list[dict[str, Any]]:
        return write_chunks_to_directory(
            text,
            output_dir,
            encoding_name=self.chunker.encoding_name,
            max_tokens=self.chunker.max_tokens,
        )

    def run_text(self, text: str, *, chunks_output_dir: str | Path) -> SegmentationPipelineResult:
        chunk_dir = Path(chunks_output_dir).expanduser().resolve()
        metadata = self.chunk_text(text, chunk_dir)
        result = run_iterative_segmentation(chunk_dir, model=self.model)
        return SegmentationPipelineResult(
            chunk_dir=str(chunk_dir),
            chunks_metadata_path=str(chunk_dir / "chunks.json"),
            result=result,
        )

    def run_file(
        self,
        input_path: str | Path,
        *,
        chunks_output_dir: str | Path,
        encoding: str = "utf-8",
    ) -> SegmentationPipelineResult:
        path = Path(input_path).expanduser().resolve()
        text = path.read_text(encoding=encoding)
        return self.run_text(text, chunks_output_dir=chunks_output_dir)


def write_segmentation_outputs(
    pipeline_result: SegmentationPipelineResult,
    *,
    json_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
    encoding: str = "utf-8",
) -> None:
    if json_output is not None:
        json_path = Path(json_output).expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(pipeline_result.result, ensure_ascii=True, indent=2),
            encoding=encoding,
        )

    if markdown_output is not None:
        markdown_path = Path(markdown_output).expanduser().resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_segments_markdown(pipeline_result.result),
            encoding=encoding,
        )


def run_segmentation_pipeline_from_text(
    text: str,
    *,
    chunks_output_dir: str | Path,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model=None,
) -> SegmentationPipelineResult:
    pipeline = SegmentationPipeline(
        encoding_name=encoding_name,
        max_tokens=max_tokens,
        model=model,
    )
    return pipeline.run_text(text, chunks_output_dir=chunks_output_dir)


def run_segmentation_pipeline_from_file(
    input_path: str | Path,
    *,
    chunks_output_dir: str | Path,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model=None,
    encoding: str = "utf-8",
) -> SegmentationPipelineResult:
    pipeline = SegmentationPipeline(
        encoding_name=encoding_name,
        max_tokens=max_tokens,
        model=model,
    )
    return pipeline.run_file(
        input_path,
        chunks_output_dir=chunks_output_dir,
        encoding=encoding,
    )
