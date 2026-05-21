from __future__ import annotations

from agents.juridica.minutes.models import ChunkContext, LegalTopic, PPTContext, TopicChunkPlanModel, WriterAssignment
from agents.juridica.minutes.ppt_context import render_ppt_excerpt
from agents.juridica.minutes.theme_discovery import render_chunk_summary_catalog


DEFAULT_EXPECTED_OUTPUT_SHAPE = (
    "Escribe una sección del acta en markdown con: "
    "1) qué se discutió, 2) decisiones tomadas si existen, 3) recomendaciones o siguientes pasos, "
    "4) puntos abiertos cuando la discusión no haya quedado cerrada. "
    "No incluyas párrafo ni subsección de resumen al final: el resumen ejecutivo global se genera por separado."
)
_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def plan_writer_assignments(
    themes: list[LegalTopic],
    ppt_context: PPTContext,
    chunks: list[ChunkContext],
    model,
    *,
    variant: str,
    max_chunks_per_theme: int = 6,
) -> list[WriterAssignment]:
    assignments: list[WriterAssignment] = []
    summary_catalog = render_chunk_summary_catalog(chunks)
    available_chunk_indices = {chunk.index for chunk in chunks}
    for index, theme in enumerate(sorted(themes, key=lambda item: (item.priority, item.title.lower())), start=1):
        plan = model.invoke_structured(
            (
                f"Planifica la asignación del writer para el tema jurídico '{theme.title}'.\n"
                f"Descripción del tema: {theme.description}\n"
                f"Origen del tema: {theme.source}\n"
                f"Prioridad del tema: {theme.priority}\n"
                f"Referencias iniciales de diapositivas PPT: {theme.slide_refs}\n"
                f"{_FOUNDATION_NOTE}\n"
                f"Devuelve como máximo {max_chunks_per_theme} índices de chunk.\n\n"
                f"Catálogo de resúmenes de chunks:\n{summary_catalog}\n\n"
                f"Catálogo de diapositivas PPT:\n"
                + "\n".join(f"Slide {slide.slide_number}: {slide.title}" for slide in ppt_context.slides)
            ),
            TopicChunkPlanModel,
            system_prompt=_planner_system_prompt(variant),
        )

        chunk_refs = sorted(set(ref for ref in plan.chunk_refs if ref in available_chunk_indices))
        if not chunk_refs:
            continue
        slide_refs = sorted(set(plan.slide_refs or theme.slide_refs))
        theme.chunk_refs = chunk_refs
        theme.slide_refs = slide_refs
        assignments.append(
            WriterAssignment(
                assignment_id=f"{theme.theme_id}-writer-{index:02d}",
                theme_id=theme.theme_id,
                writer_id=f"writer-{index:02d}",
                task_instruction=plan.task_instruction.strip(),
                chunk_refs=chunk_refs,
                ppt_context_excerpt=render_ppt_excerpt(ppt_context, slide_refs) if variant == "ppt_led" else None,
                slide_refs=slide_refs,
                expected_output_shape=DEFAULT_EXPECTED_OUTPUT_SHAPE,
                theme_title=theme.title,
            )
        )
    return assignments


def _planner_system_prompt(variant: str) -> str:
    if variant == "ppt_led":
        return (
            "Estás planificando trabajo para writers que redactan un acta jurídica de reunión. "
            "Elige los chunks que mejor soportan el tema y mantén la asignación alineada con el encuadre del PowerPoint. "
            f"{_FOUNDATION_NOTE} "
            "Responde en español."
        )
    return (
        "Estás planificando trabajo para writers que redactan un acta jurídica de reunión. "
        "Elige los chunks que mejor soportan el tema. En esta variante los writers solo recibirán chunks de transcripción. "
        f"{_FOUNDATION_NOTE} "
        "Responde en español."
    )
