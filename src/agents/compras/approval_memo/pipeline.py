from __future__ import annotations

import json
from pathlib import Path

from agents.compras.approval_memo.chunk_io import load_chunk_contexts
from agents.compras.approval_memo.graph import run_approval_memo_graph
from agents.compras.approval_memo.models import ApprovalMemoRunResult


def run_approval_memo_pipeline(
    *,
    ppt_path: str | Path | None = None,
    chunk_dir: str | Path,
    segmentation_result_path: str | Path,
    variant: str = "auto",
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    model=None,
    markdown_output_path: str | Path | None = None,
) -> ApprovalMemoRunResult:
    return run_approval_memo_graph(
        ppt_path=ppt_path,
        chunk_dir=chunk_dir,
        segmentation_result_path=segmentation_result_path,
        variant=variant,
        max_themes=max_themes,
        max_revision_rounds=max_revision_rounds,
        model=model,
        markdown_output_path=markdown_output_path,
    )


def run_ppt_led_approval_memo(
    *,
    ppt_path: str | Path,
    chunk_dir: str | Path,
    segmentation_result_path: str | Path,
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    model=None,
    markdown_output_path: str | Path | None = None,
) -> ApprovalMemoRunResult:
    return run_approval_memo_pipeline(
        ppt_path=ppt_path,
        chunk_dir=chunk_dir,
        segmentation_result_path=segmentation_result_path,
        variant="ppt_led",
        max_themes=max_themes,
        max_revision_rounds=max_revision_rounds,
        model=model,
        markdown_output_path=markdown_output_path,
    )


def run_chunk_led_approval_memo(
    *,
    ppt_path: str | Path | None = None,
    chunk_dir: str | Path,
    segmentation_result_path: str | Path,
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    model=None,
    markdown_output_path: str | Path | None = None,
) -> ApprovalMemoRunResult:
    return run_approval_memo_pipeline(
        ppt_path=ppt_path,
        chunk_dir=chunk_dir,
        segmentation_result_path=segmentation_result_path,
        variant="chunk_led",
        max_themes=max_themes,
        max_revision_rounds=max_revision_rounds,
        model=model,
        markdown_output_path=markdown_output_path,
    )


def write_approval_memo_outputs(
    result: ApprovalMemoRunResult,
    *,
    output_dir: str | Path,
    encoding: str = "utf-8",
) -> dict[str, str]:
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "ppt_markdown": resolved_output_dir / "ppt_context.md",
        "chunk_summaries": resolved_output_dir / "chunk_summaries.json",
        "themes": resolved_output_dir / "themes.json",
        "assignments": resolved_output_dir / "writer_assignments.json",
        "drafts": resolved_output_dir / "writer_drafts.json",
        "review_log": resolved_output_dir / "review_log.json",
        "approval_memo_json": resolved_output_dir / "approval_memo.json",
        "approval_memo_markdown": resolved_output_dir / "approval_memo.md",
    }

    paths["ppt_markdown"].write_text(result.ppt_context.markdown, encoding=encoding)
    paths["chunk_summaries"].write_text(
        json.dumps([chunk.as_dict() for chunk in result.chunks], ensure_ascii=True, indent=2),
        encoding=encoding,
    )
    paths["themes"].write_text(
        json.dumps([theme.as_dict() for theme in result.themes], ensure_ascii=True, indent=2),
        encoding=encoding,
    )
    paths["assignments"].write_text(
        json.dumps([assignment.as_dict() for assignment in result.assignments], ensure_ascii=True, indent=2),
        encoding=encoding,
    )
    paths["drafts"].write_text(
        json.dumps([draft.as_dict() for draft in result.drafts], ensure_ascii=True, indent=2),
        encoding=encoding,
    )
    paths["review_log"].write_text(
        json.dumps([request.as_dict() for request in result.clarification_requests], ensure_ascii=True, indent=2),
        encoding=encoding,
    )
    paths["approval_memo_json"].write_text(
        json.dumps(result.as_dict(), ensure_ascii=True, indent=2),
        encoding=encoding,
    )
    paths["approval_memo_markdown"].write_text(
        result.approval_memo_markdown,
        encoding=encoding,
    )
    return {key: str(value) for key, value in paths.items()}


__all__ = [
    "load_chunk_contexts",
    "run_approval_memo_pipeline",
    "run_chunk_led_approval_memo",
    "run_ppt_led_approval_memo",
    "write_approval_memo_outputs",
]
