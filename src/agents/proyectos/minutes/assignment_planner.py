from __future__ import annotations

from agents.proyectos.minutes.models import (
    ChunkContext,
    PPTContext,
    ProjectTopic,
    TopicChunkPlanModel,
)
from agents.proyectos.minutes.ppt_context import render_ppt_excerpt
from agents.proyectos.minutes.theme_discovery import render_chunk_summary_catalog
from agents.shared_tools.meeting_minutes.models import WriterAssignment

DEFAULT_EXPECTED_OUTPUT_SHAPE = (
    "Escribe una sección del acta en markdown con: "
    "1) estado actual del proyecto o tema y avances reportados, "
    "2) bloqueos o riesgos identificados, "
    "3) decisiones tomadas por el comité, "
    "4) compromisos adquiridos con responsable y fecha cuando se hayan mencionado, "
    "5) próximas acciones o puntos pendientes. "
    "No incluyas párrafo ni subsección de resumen al final: el resumen ejecutivo global se genera por separado."
)

_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def plan_writer_assignments(
    themes: list[ProjectTopic],
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
                f"Planifica la asignación de chunks para el tema del comité de proyectos: '{theme.title}'.\n"
                f"Descripción del tema: {theme.description}\n"
                f"Razón de selección: {theme.selection_reason}\n"
                f"{_FOUNDATION_NOTE}\n\n"
                f"Catálogo de resúmenes de chunks disponibles:\n{summary_catalog}\n\n"
                f"Extracto PPT relevante:\n{render_ppt_excerpt(ppt_context, theme.slide_refs)}\n\n"
                f"Selecciona como máximo {max_chunks_per_theme} chunks que mejor soporten el tema. "
                f"Elige chunks con información sobre estado, avances, riesgos, decisiones o compromisos. "
                f"Índices disponibles: {sorted(available_chunk_indices)}"
            ),
            TopicChunkPlanModel,
            system_prompt=(
                "Estás planificando trabajo para writers que redactan un acta de comité de proyectos. "
                "Elige los chunks que mejor soportan el tema, priorizando los que contienen "
                "estado de proyecto, decisiones del comité y compromisos con responsable y fecha. "
                f"{_FOUNDATION_NOTE} "
                "Responde en español."
            ),
        )
        valid_chunk_refs = sorted(set(plan.chunk_refs) & available_chunk_indices)[:max_chunks_per_theme]
        valid_slide_refs = sorted(set(plan.slide_refs) & {slide.slide_number for slide in ppt_context.slides})
        assignments.append(
            WriterAssignment(
                assignment_id=f"w{index:02d}",
                writer_id=f"writer-{index:02d}",
                theme_id=theme.theme_id,
                theme_title=theme.title,
                chunk_refs=valid_chunk_refs,
                slide_refs=valid_slide_refs,
                task_instruction=plan.task_instruction,
                expected_output_shape=DEFAULT_EXPECTED_OUTPUT_SHAPE,
                ppt_context_excerpt=render_ppt_excerpt(ppt_context, valid_slide_refs) if variant == "ppt_led" else "",
            )
        )
    return assignments
