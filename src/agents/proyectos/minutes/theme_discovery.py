from __future__ import annotations

import re

from agents.proyectos.minutes.models import ChunkContext, PPTContext, ProjectTopic, TopicDiscoveryModel
from agents.proyectos.minutes.ppt_context import render_slide_catalog


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def discover_ppt_led_topics(
    ppt_context: PPTContext,
    chunks: list[ChunkContext],
    model,
    *,
    max_themes: int = 6,
) -> list[ProjectTopic]:
    result = model.invoke_structured(
        (
            "Extrae los principales temas del comité de proyectos para un acta formal.\n"
            "Enfócate en: proyectos discutidos, avances reportados, bloqueos o riesgos identificados, "
            "decisiones del comité, compromisos adquiridos con responsables y fechas, y próximas acciones.\n"
            "El PowerPoint es la fuente principal de estructura.\n"
            f"{_FOUNDATION_NOTE}\n"
            f"Devuelve como máximo {max_themes} temas.\n\n"
            f"Catálogo de diapositivas PPT:\n{render_slide_catalog(ppt_context)}\n\n"
            f"Catálogo de resúmenes de chunks:\n{render_chunk_summary_catalog(chunks)}\n\n"
            f"Markdown del PPT:\n{ppt_context.markdown[:20_000]}"
        ),
        TopicDiscoveryModel,
        system_prompt=(
            "Diseñas actas de comités de proyectos a partir del contexto de un PowerPoint. "
            f"{_FOUNDATION_NOTE} "
            "Prefiere temas que capturen el estado de cada proyecto, las decisiones tomadas por el comité "
            "y los compromisos con responsable y fecha que surgieron en la reunión."
        ),
    )
    return _normalize_topics(result, source="ppt", max_themes=max_themes)


def discover_chunk_led_topics(
    ppt_context: PPTContext,
    chunks: list[ChunkContext],
    model,
    *,
    max_themes: int = 6,
) -> list[ProjectTopic]:
    result = model.invoke_structured(
        (
            "Extrae los principales temas del comité de proyectos para un acta formal.\n"
            "Enfócate en: proyectos discutidos, avances reportados, bloqueos o riesgos identificados, "
            "decisiones del comité, compromisos adquiridos con responsables y fechas, y próximas acciones.\n"
            "Los chunks de transcripción son la fuente principal de estructura.\n"
            f"{_FOUNDATION_NOTE}\n"
            f"Devuelve como máximo {max_themes} temas.\n\n"
            f"Catálogo de resúmenes de chunks:\n{render_chunk_summary_catalog(chunks)}\n\n"
            f"Catálogo de diapositivas PPT:\n{render_slide_catalog(ppt_context)}\n\n"
            f"Markdown del PPT:\n{ppt_context.markdown[:10_000]}"
        ),
        TopicDiscoveryModel,
        system_prompt=(
            "Diseñas actas de comités de proyectos a partir de chunks de transcripción. "
            f"{_FOUNDATION_NOTE} "
            "Agrupa la conversación en temas coherentes por proyecto o área, preservando decisiones, "
            "compromisos con responsable y fecha, y riesgos identificados. Responde en español."
        ),
    )
    return _normalize_topics(result, source="chunks", max_themes=max_themes)


def render_chunk_summary_catalog(chunks: list[ChunkContext], *, max_chars: int = 8_000) -> str:
    parts: list[str] = []
    for chunk in chunks:
        if chunk.summary is None:
            continue
        parts.append(
            f"Chunk {chunk.index}: {chunk.summary.short_title}\n"
            f"Summary: {chunk.summary.summary}\n"
            f"Notable points: {'; '.join(chunk.summary.notable_points[:3])}"
        )
    return "\n\n".join(parts)[:max_chars].strip()


def _normalize_topics(result: TopicDiscoveryModel, *, source: str, max_themes: int) -> list[ProjectTopic]:
    topics: list[ProjectTopic] = []
    used_ids: set[str] = set()
    for fallback_index, theme in enumerate(result.themes[:max_themes], start=1):
        base_id = _slugify(theme.title) or f"topic-{fallback_index}"
        topic_id = base_id
        suffix = 2
        while topic_id in used_ids:
            topic_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(topic_id)
        topics.append(
            ProjectTopic(
                theme_id=topic_id,
                title=theme.title.strip(),
                description=theme.description.strip(),
                source=source,  # type: ignore[arg-type]
                priority=max(theme.priority, 1),
                slide_refs=sorted(set(theme.slide_refs)),
                selection_reason=theme.selection_reason.strip(),
            )
        )
    topics.sort(key=lambda item: (item.priority, item.title.lower()))
    return topics


def _slugify(text: str) -> str:
    lowered = text.strip().lower()
    normalized = _NON_ALNUM_RE.sub("-", lowered).strip("-")
    return normalized[:80]
