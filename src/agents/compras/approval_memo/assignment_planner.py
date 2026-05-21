from __future__ import annotations

from agents.compras.approval_memo.models import (
    ApprovalTheme,
    ChunkContext,
    PPTContext,
    ThemeChunkPlanModel,
    WriterAssignment,
)
from agents.compras.approval_memo.ppt_context import render_ppt_excerpt
from agents.compras.approval_memo.theme_discovery import render_chunk_summary_catalog


DEFAULT_EXPECTED_OUTPUT_SHAPE = (
    "Escribe una sección del memo de aprobación en markdown con: "
    "1) un título preciso, 2) una narrativa clara, 3) evidencia ligada a los chunks entregados, "
    "4) riesgos, decisiones, aprobaciones o acciones solicitadas cuando existan."
)
_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def plan_writer_assignments(
    themes: list[ApprovalTheme],
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
                f"Planifica la asignación para el writer del tema de aprobación '{theme.title}'.\n"
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
            ThemeChunkPlanModel,
            system_prompt=_planner_system_prompt(variant),
        )

        chunk_refs = sorted(set(ref for ref in plan.chunk_refs if ref in available_chunk_indices))
        if not chunk_refs:
            continue

        slide_refs = sorted(set(plan.slide_refs or theme.slide_refs))
        theme.chunk_refs = chunk_refs
        theme.slide_refs = slide_refs

        assignment = WriterAssignment(
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
        assignments.append(assignment)

    return assignments


def _planner_system_prompt(variant: str) -> str:
    if variant == "ppt_led":
        return (
            "Estás planificando trabajo para agentes redactores. "
            "Elige los chunks de transcripción que mejor soportan el tema de aprobación. "
            "El PowerPoint es el ancla estructural, así que mantén la asignación alineada con el encuadre de las diapositivas. "
            f"{_FOUNDATION_NOTE} "
            "Devuelve siempre índices de chunk que soporten materialmente el tema."
        )

    return (
        "Estás planificando trabajo para agentes redactores. "
        "Elige los chunks de transcripción que mejor soportan el tema de aprobación. "
        "En esta variante los writers solo recibirán chunks de transcripción, así que la instrucción debe ser autosuficiente. "
        f"{_FOUNDATION_NOTE} "
        "Usa las referencias de diapositivas solo para trazabilidad del orquestador, no como entrada del writer."
    )
