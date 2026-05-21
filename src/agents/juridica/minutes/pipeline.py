from __future__ import annotations

import json
from pathlib import Path

from agents.juridica.minutes.graph import run_juridica_minutes_graph
from agents.juridica.minutes.models import JuridicaMinutesRunResult


def run_juridica_minutes_pipeline(
    *,
    ppt_path: str | Path | None = None,
    chunk_dir: str | Path,
    segmentation_result_path: str | Path,
    variant: str = "auto",
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    model=None,
    markdown_output_path: str | Path | None = None,
) -> JuridicaMinutesRunResult:
    return run_juridica_minutes_graph(
        ppt_path=ppt_path,
        chunk_dir=chunk_dir,
        segmentation_result_path=segmentation_result_path,
        variant=variant,
        max_themes=max_themes,
        max_revision_rounds=max_revision_rounds,
        model=model,
        markdown_output_path=markdown_output_path,
    )


def write_juridica_minutes_outputs(
    result: JuridicaMinutesRunResult,
    *,
    output_dir: str | Path,
    encoding: str = "utf-8",
) -> dict[str, str]:
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "ppt_markdown": output_dir / "ppt_context.md",
        "themes": output_dir / "themes.json",
        "assignments": output_dir / "writer_assignments.json",
        "drafts": output_dir / "writer_drafts.json",
        "review_log": output_dir / "review_log.json",
        "acta_json": output_dir / "acta_juridica.json",
        "acta_markdown": output_dir / "acta_juridica.md",
    }
    paths["ppt_markdown"].write_text(result.ppt_context.markdown, encoding=encoding)
    paths["themes"].write_text(json.dumps([item.as_dict() for item in result.themes], ensure_ascii=True, indent=2), encoding=encoding)
    paths["assignments"].write_text(json.dumps([item.as_dict() for item in result.assignments], ensure_ascii=True, indent=2), encoding=encoding)
    paths["drafts"].write_text(json.dumps([item.as_dict() for item in result.drafts], ensure_ascii=True, indent=2), encoding=encoding)
    paths["review_log"].write_text(json.dumps([item.as_dict() for item in result.clarification_requests], ensure_ascii=True, indent=2), encoding=encoding)
    paths["acta_json"].write_text(json.dumps(result.as_dict(), ensure_ascii=True, indent=2), encoding=encoding)
    paths["acta_markdown"].write_text(result.acta_markdown, encoding=encoding)
    return {key: str(value) for key, value in paths.items()}
