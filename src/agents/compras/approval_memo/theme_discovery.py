from __future__ import annotations

import re

from agents.compras.approval_memo.models import (
    ApprovalTheme,
    ChunkContext,
    ChunkSummaryModel,
    ChunkSummaryRecord,
    PPTContext,
    ThemeDiscoveryModel,
)
from agents.compras.approval_memo.ppt_context import render_slide_catalog


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def summarize_chunks(chunks: list[ChunkContext], model) -> list[ChunkContext]:
    summarized: list[ChunkContext] = []
    for chunk in chunks:
        summary = model.invoke_structured(
            (
                "Resume este chunk de transcripción para la planeación posterior de un memo de aprobación.\n"
                "Enfócate en lo que ocurrió, decisiones, solicitudes, riesgos, aprobaciones, bloqueos y acciones concretas.\n"
                f"{_FOUNDATION_NOTE}\n\n"
                f"Índice del chunk: {chunk.index}\n"
                f"Texto del chunk:\n{chunk.text}"
            ),
            ChunkSummaryModel,
            system_prompt=(
                "Analizas chunks largos de transcripciones de reuniones y produces resúmenes concisos orientados a aprobación. "
                f"{_FOUNDATION_NOTE} "
                "No inventes hechos."
            ),
        )
        summarized.append(
            ChunkContext(
                index=chunk.index,
                path=chunk.path,
                text=chunk.text,
                token_count=chunk.token_count,
                start_token=chunk.start_token,
                end_token=chunk.end_token,
                summary=ChunkSummaryRecord(
                    short_title=summary.short_title,
                    summary=summary.summary,
                    notable_points=summary.notable_points,
                ),
            )
        )
    return summarized


def discover_ppt_led_themes(
    ppt_context: PPTContext,
    chunks: list[ChunkContext],
    model,
    *,
    max_themes: int = 6,
) -> list[ApprovalTheme]:
    result = model.invoke_structured(
        (
            "Extrae los temas principales de aprobación para un memo de aprobación.\n"
            "El PowerPoint es la fuente principal de estructura. Usa los resúmenes de chunks solo para confirmar qué temas importan.\n"
            f"{_FOUNDATION_NOTE}\n"
            f"Devuelve como máximo {max_themes} temas, ordenados por importancia.\n\n"
            f"Catálogo de diapositivas PPT:\n{render_slide_catalog(ppt_context)}\n\n"
            f"Catálogo de resúmenes de chunks:\n{render_chunk_summary_catalog(chunks)}\n\n"
            f"Markdown del PPT:\n{ppt_context.markdown[:20_000]}"
        ),
        ThemeDiscoveryModel,
        system_prompt=(
            "Diseñas estructuras de memos de aprobación a partir del contexto de un PowerPoint. "
            f"{_FOUNDATION_NOTE} "
            "Extrae los temas que deben convertirse en secciones del memo y prioriza los relacionados con aprobaciones, riesgos, decisiones, financiación, alcance y dependencias."
        ),
    )
    return _normalize_themes(result, source="ppt", max_themes=max_themes)


def discover_chunk_led_themes(
    ppt_context: PPTContext,
    chunks: list[ChunkContext],
    model,
    *,
    max_themes: int = 6,
) -> list[ApprovalTheme]:
    result = model.invoke_structured(
        (
            "Extrae los temas principales de aprobación para un memo de aprobación.\n"
            "Los chunks de transcripción son la fuente principal de estructura. El PPT solo sirve como apoyo de contexto, marco y vocabulario.\n"
            f"{_FOUNDATION_NOTE}\n"
            f"Devuelve como máximo {max_themes} temas, ordenados por importancia.\n\n"
            f"Catálogo de resúmenes de chunks:\n{render_chunk_summary_catalog(chunks)}\n\n"
            f"Catálogo de diapositivas PPT:\n{render_slide_catalog(ppt_context)}\n\n"
            f"Markdown del PPT:\n{ppt_context.markdown[:10_000]}"
        ),
        ThemeDiscoveryModel,
        system_prompt=(
            "Descubres temas para memos de aprobación a partir de chunks de transcripción de reuniones. "
            f"{_FOUNDATION_NOTE} "
            "Elige temas con suficiente entidad para convertirse en secciones del memo."
        ),
    )
    return _normalize_themes(result, source="chunks", max_themes=max_themes)


def render_chunk_summary_catalog(chunks: list[ChunkContext], *, max_chars: int = 8_000) -> str:
    parts: list[str] = []
    for chunk in chunks:
        if chunk.summary is None:
            continue
        notable_points = "; ".join(chunk.summary.notable_points[:3])
        parts.append(
            f"Chunk {chunk.index}: {chunk.summary.short_title}\n"
            f"Summary: {chunk.summary.summary}\n"
            f"Notable points: {notable_points}"
        )
    catalog = "\n\n".join(parts)
    return catalog[:max_chars].strip()


def _normalize_themes(result: ThemeDiscoveryModel, *, source: str, max_themes: int) -> list[ApprovalTheme]:
    themes: list[ApprovalTheme] = []
    used_ids: set[str] = set()
    for fallback_index, theme in enumerate(result.themes[:max_themes], start=1):
        base_id = _slugify(theme.title) or f"theme-{fallback_index}"
        theme_id = base_id
        suffix = 2
        while theme_id in used_ids:
            theme_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(theme_id)
        themes.append(
            ApprovalTheme(
                theme_id=theme_id,
                title=theme.title.strip(),
                description=theme.description.strip(),
                source=source,  # type: ignore[arg-type]
                priority=max(theme.priority, 1),
                slide_refs=sorted(set(theme.slide_refs)),
                selection_reason=theme.selection_reason.strip(),
            )
        )

    themes.sort(key=lambda item: (item.priority, item.title.lower()))
    return themes


def _slugify(text: str) -> str:
    lowered = text.strip().lower()
    normalized = _NON_ALNUM_RE.sub("-", lowered).strip("-")
    return normalized[:80]
