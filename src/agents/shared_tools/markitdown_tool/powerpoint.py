from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_POWERPOINT_EXTENSIONS = {".pptx", ".pptm", ".ppt", ".potx", ".potm"}


@dataclass(frozen=True)
class PowerPointMarkdownResult:
    source_path: str
    markdown: str
    output_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_markitdown():
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise ImportError(
            "markitdown is not installed. Install it with the pptx extras, for example: "
            "\"markitdown[pptx]\"."
        ) from exc
    return MarkItDown


def convert_powerpoint_to_markdown(
    input_path: str | Path,
    *,
    output_path: str | Path | None = None,
    enable_plugins: bool = False,
    llm_client: Any | None = None,
    llm_model: str | None = None,
    llm_prompt: str | None = None,
) -> PowerPointMarkdownResult:
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PowerPoint file not found: {path}")
    if path.suffix.lower() not in _POWERPOINT_EXTENSIONS:
        raise ValueError(f"Unsupported PowerPoint file extension: {path.suffix}")

    MarkItDown = _load_markitdown()
    converter = MarkItDown(
        enable_plugins=enable_plugins,
        llm_client=llm_client,
        llm_model=llm_model,
        llm_prompt=llm_prompt,
    )
    result = converter.convert(str(path))
    markdown = result.text_content

    resolved_output_path: str | None = None
    if output_path is not None:
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        resolved_output_path = str(target)

    return PowerPointMarkdownResult(
        source_path=str(path),
        markdown=markdown,
        output_path=resolved_output_path,
    )


def powerpoint_to_markdown(
    input_path: str | Path,
    *,
    output_path: str | Path | None = None,
    enable_plugins: bool = False,
    llm_client: Any | None = None,
    llm_model: str | None = None,
    llm_prompt: str | None = None,
) -> str:
    return convert_powerpoint_to_markdown(
        input_path,
        output_path=output_path,
        enable_plugins=enable_plugins,
        llm_client=llm_client,
        llm_model=llm_model,
        llm_prompt=llm_prompt,
    ).markdown
