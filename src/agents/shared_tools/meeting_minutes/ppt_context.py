from __future__ import annotations

import re
from pathlib import Path

from agents.shared_tools.markitdown_tool import convert_powerpoint_to_markdown
from agents.shared_tools.meeting_minutes.models import PPTContext, PPTSlideContext


_SLIDE_SPLIT_RE = re.compile(
    r"<!--\s*Slide number:\s*(\d+)\s*-->\s*",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$", re.MULTILINE)


def convert_ppt_to_context(
    ppt_path: str | Path,
    *,
    markdown_output_path: str | Path | None = None,
) -> PPTContext:
    result = convert_powerpoint_to_markdown(
        ppt_path,
        output_path=markdown_output_path,
    )
    slides = parse_markdown_slides(result.markdown)
    return PPTContext(
        source_path=result.source_path,
        markdown=result.markdown,
        slides=slides,
    )


def empty_ppt_context(*, source_path: str = "") -> PPTContext:
    return PPTContext(
        source_path=source_path,
        markdown="",
        slides=[],
    )


def parse_markdown_slides(markdown: str) -> list[PPTSlideContext]:
    slides: list[PPTSlideContext] = []
    matches = list(_SLIDE_SPLIT_RE.finditer(markdown))

    if not matches:
        title = _extract_slide_title(markdown, default_title="Slide 1")
        return [PPTSlideContext(slide_number=1, title=title, markdown=markdown.strip())]

    for index, match in enumerate(matches):
        slide_number = int(match.group(1))
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        content = markdown[content_start:content_end].strip()
        title = _extract_slide_title(content, default_title=f"Slide {slide_number}")
        slides.append(
            PPTSlideContext(
                slide_number=slide_number,
                title=title,
                markdown=content,
            )
        )
    return slides


def render_ppt_excerpt(context: PPTContext | None, slide_refs: list[int], *, max_slides: int = 4) -> str:
    if context is None or (not context.slides and not context.markdown.strip()):
        return "No PowerPoint context provided."

    if not slide_refs:
        excerpt = context.markdown[:5_000].strip()
        return excerpt or "No PowerPoint context provided."

    selected_refs = set(slide_refs[:max_slides])
    parts: list[str] = []
    for slide in context.slides:
        if slide.slide_number not in selected_refs:
            continue
        parts.append(f"Slide {slide.slide_number}: {slide.title}\n{slide.markdown.strip()}")
    rendered = "\n\n".join(parts).strip()
    return rendered or "No PowerPoint context provided."


def render_slide_catalog(context: PPTContext | None, *, max_chars: int = 6_000) -> str:
    if context is None or not context.slides:
        return "No PowerPoint context provided."
    parts = [f"Slide {slide.slide_number}: {slide.title}" for slide in context.slides]
    catalog = "\n".join(parts)
    return catalog[:max_chars].strip()


def _extract_slide_title(markdown: str, *, default_title: str) -> str:
    heading_match = _HEADING_RE.search(markdown)
    if heading_match:
        title = heading_match.group(1).strip()
        if title:
            return title

    for line in markdown.splitlines():
        stripped = line.strip(" -*\t")
        if stripped:
            return stripped[:120]
    return default_title
