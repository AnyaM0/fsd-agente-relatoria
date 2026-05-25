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

_EXPECTED_OUTPUT_SHAPE_PRECOMITE = (
    "Redacta el cuerpo de UNA iniciativa de Precomité. "
    "El body_markdown debe contener (en este orden): "
    "1) bullets de identificación (Unidad, Línea, Programa), "
    "2) **Descripción:** en párrafos corridos (sin subtítulos, sin bullets, sin tablas), "
    "3) **Estado:** con sub-bullets por área (Comunicaciones, Jurídica, Talento Humano), "
    "4) **Decisión del Precomité:** SIEMPRE empieza con 'Iniciativa preaprobada' seguido de la lista de compromisos. Cada compromiso DEBE iniciar con un verbo en infinitivo (Coordinar, Definir, Dar inicio, etc.) y seguir la estructura: '[Verbo infinitivo] [qué] [con quién / para qué / considerando qué]'. "
    "PROHIBIDO: resumen ejecutivo, características generales, componentes, indicadores, bloqueos/riesgos, próximas acciones, emojis."
)

_EXPECTED_OUTPUT_SHAPE_COMITE = (
    "Redacta el cuerpo de UNA iniciativa de Comité. "
    "El body_markdown debe contener (en este orden): "
    "1) código del proyecto si se conoce (ej. [Código: DT-DUI-260007]), "
    "2) bullets de identificación (Unidad, Línea, Programa), "
    "3) **Descripción:** en párrafos corridos (sin subtítulos, sin bullets, sin tablas), "
    "4) **Decisión del Comité:** SIEMPRE empieza con 'Iniciativa aprobada' seguido de la lista de compromisos. Cada compromiso DEBE iniciar con un verbo en infinitivo (Coordinar, Definir, Dar inicio, etc.) y seguir la estructura: '[Verbo infinitivo] [qué] [con quién / para qué / considerando qué]'. "
    "NO hay sección Estado en el Comité. "
    "PROHIBIDO: resumen ejecutivo, características generales, componentes, indicadores, bloqueos/riesgos, próximas acciones, emojis."
)

_EXPECTED_OUTPUT_SHAPE_REFRENDACION_PRECOMITE = (
    "Redacta el cuerpo de UNA refrendación de Precomité. "
    "El body_markdown debe contener (en este orden EXACTO):\n"
    "1) Código del proyecto si se conoce (ej. DT-DUI-230009)\n"
    "2) Bullets de identificación (Unidad, Línea, Programa)\n"
    "3) Título: **Solicitud de refrendación:**\n"
    "4) Párrafos de la solicitud (ver LÓGICA DE PÁRRAFOS PARA REFRENDACIÓN)\n"
    "5) Tabla financiera en markdown (Columnas: [vacío] | Aprobado | Solicitud | Refrendación)\n"
    "6) **Decisión del Precomité:**\n"
    "Refrendación preaprobada\n"
    "(Sin punto final y sin lista de compromisos, salvo que haya compromisos concretos derivados explícitamente de la refrendación)\n"
    "PROHIBIDO: sección Estado, descripción de objetivos del proyecto original, resumen ejecutivo, componentes, indicadores o bloqueos."
)

_EXPECTED_OUTPUT_SHAPE_REFRENDACION_COMITE = (
    "Redacta el cuerpo de UNA refrendación de Comité. "
    "El body_markdown debe contener (en este orden EXACTO):\n"
    "1) Código del proyecto si se conoce (ej. DT-DUI-230009)\n"
    "2) Bullets de identificación (Unidad, Línea, Programa)\n"
    "3) Título: **Solicitud de refrendación:**\n"
    "4) Párrafos de la solicitud (ver LÓGICA DE PÁRRAFOS PARA REFRENDACIÓN)\n"
    "5) Tabla financiera en markdown (Columnas: [vacío] | Aprobado | Solicitud | Refrendación)\n"
    "6) **Decisión del Comité:**\n"
    "Refrendación aprobada.\n"
    "(Con punto final y sin lista de compromisos, salvo que haya compromisos concretos derivados explícitamente de la refrendación)\n"
    "PROHIBIDO: sección Estado, descripción de objetivos del proyecto original, resumen ejecutivo, componentes, indicadores o bloqueos."
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
    meeting_type: str = "comite",
    max_chunks_per_theme: int = 6,
) -> list[WriterAssignment]:
    assignments: list[WriterAssignment] = []
    summary_catalog = render_chunk_summary_catalog(chunks)
    available_chunk_indices = {chunk.index for chunk in chunks}
    for index, theme in enumerate(sorted(themes, key=lambda item: (item.priority, item.title.lower())), start=1):
        if theme.topic_type == "refrendacion":
            expected_shape = _EXPECTED_OUTPUT_SHAPE_REFRENDACION_PRECOMITE if meeting_type == "precomite" else _EXPECTED_OUTPUT_SHAPE_REFRENDACION_COMITE
        else:
            expected_shape = _EXPECTED_OUTPUT_SHAPE_PRECOMITE if meeting_type == "precomite" else _EXPECTED_OUTPUT_SHAPE_COMITE
        
        plan = model.invoke_structured(
            (
                f"Planifica la asignación de chunks para la iniciativa: '{theme.title}'.\n"
                f"Descripción: {theme.description}\n"
                f"Razón de selección: {theme.selection_reason}\n"
                f"{_FOUNDATION_NOTE}\n\n"
                f"Catálogo de resúmenes de chunks disponibles:\n{summary_catalog}\n\n"
                f"Extracto PPT relevante:\n{render_ppt_excerpt(ppt_context, theme.slide_refs)}\n\n"
                f"Selecciona como máximo {max_chunks_per_theme} chunks que mejor soporten esta iniciativa. "
                f"Prioriza chunks con: objetivo de la iniciativa, información financiera (valor total, aportes FSD, aliados), "
                f"estado por área (Comunicaciones, Jurídica, Talento Humano) si es precomité, "
                f"y decisión del comité con compromisos concretos (responsable + acción). "
                f"Índices disponibles: {sorted(available_chunk_indices)}"
            ),
            TopicChunkPlanModel,
            system_prompt=(
                "Estás planificando chunks para writers que redactan actas de comité de proyectos. "
                "Elige los chunks que contienen: objetivo de la iniciativa, información financiera (valor total, aporte FSD, apalancamiento), "
                "estado por área si aplica, y decisión del comité con compromisos concretos. "
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
                expected_output_shape=expected_shape,
                ppt_context_excerpt=render_ppt_excerpt(ppt_context, valid_slide_refs) if variant == "ppt_led" else "",
            )
        )
    return assignments
