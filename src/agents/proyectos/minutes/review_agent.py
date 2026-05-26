from __future__ import annotations

from agents.proyectos.minutes.models import (
    ClarificationRequest,
    FinalValidation,
    MinutesFinalValidationModel,
    MinutesReviewModel,
    PPTContext,
    WriterAssignment,
    WriterDraft,
)
from agents.proyectos.minutes.ppt_context import render_ppt_excerpt

_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def review_writer_draft(
    assignment: WriterAssignment,
    draft: WriterDraft,
    all_drafts: list[WriterDraft],
    ppt_context: PPTContext,
    model,
    *,
    variant: str,
    meeting_type: str = "comite",
    review_round: int,
) -> ClarificationRequest | None:
    if meeting_type == "precomite":
        required_sections = (
            "bullets de identificación (Unidad, Línea, Programa), "
            "**Descripción:** en párrafos corridos (sin subtítulos, sin bullets, sin tablas), "
            "**Estado:** con sub-bullets por área (Comunicaciones, Jurídica, Talento Humano), "
            "**Decisión del Precomité:** con una oración declarativa y lista de items."
        )
        forbidden_sections = (
            "resumen ejecutivo, características generales del proyecto, componentes, indicadores, "
            "bloqueos o riesgos, próximas acciones, emojis, subtítulos dentro de la descripción, tablas dentro de la descripción."
        )
    else:
        required_sections = (
            "código del proyecto si se conoce, bullets de identificación (Unidad, Línea, Programa), "
            "**Descripción:** en párrafos corridos (sin subtítulos, sin bullets, sin tablas), "
            "**Decisión del Comité:** con una oración declarativa y lista de compromisos. "
            "NO debe tener sección Estado."
        )
        forbidden_sections = (
            "resumen ejecutivo, sección Estado por áreas, características generales, componentes, indicadores, "
            "bloqueos o riesgos, próximas acciones, emojis, subtítulos dentro de la descripción, tablas dentro de la descripción."
        )
    review = model.invoke_structured(
        (
            f"Revisa esta sección del acta para la asignación {assignment.assignment_id}.\n"
            f"Iniciativa: {assignment.theme_title}\n"
            f"Tipo de reunión: {meeting_type}\n"
            f"Chunks asignados: {assignment.chunk_refs}\n"
            f"{_FOUNDATION_NOTE}\n\n"
            f"Título de la sección: {draft.section_title}\n"
            f"Markdown de la sección:\n{draft.body_markdown}\n\n"
            f"Extracto relevante del PPT:\n{render_ppt_excerpt(ppt_context, assignment.slide_refs)}"
        ),
        MinutesReviewModel,
        system_prompt=(
            f"Eres el revisor de un acta de {'Precomité' if meeting_type == 'precomite' else 'Comité'} de Proyectos. "
            f"{_FOUNDATION_NOTE} "
            f"Aprueba SOLO si la sección contiene exactamente: {required_sections} "
            f"Rechaza si contiene contenido prohibido: {forbidden_sections} "
            "La Descripción debe constar exactamente de 2 a 3 párrafos en total (el Párrafo 1 de Objetivo y los párrafos de aportes financieros). "
            "RECHAZA INMEDIATAMENTE si la Descripción incluye párrafos adicionales descriptivos u operativos que mencionen componentes del proyecto, duración, territorios de ejecución, rol de ejecutor de la Fundación, o desgloses presupuestales operativos. "
            "Responde en español."
        ),
    )
    if review.approved:
        return None
    return ClarificationRequest(
        assignment_id=assignment.assignment_id,
        writer_id=assignment.writer_id,
        issues=review.issues,
        requested_changes=review.requested_changes,
        must_address_refs=review.must_address_refs,
        review_round=review_round,
    )


def validate_final_acta(markdown: str, ppt_context: PPTContext, model, meeting_type: str = "comite") -> FinalValidation:
    decision_label = "Decisión del Precomité" if meeting_type == "precomite" else "Decisión del Comité"
    approval_word = "preaprobada" if meeting_type == "precomite" else "aprobada"
    validation = model.invoke_structured(
        (
            f"Valida esta acta de {'Precomité' if meeting_type == 'precomite' else 'Comité'} de Proyectos como entregable final.\n"
            "Verifica que cada iniciativa contenga:\n"
            "1. Bullets de identificación (Unidad, Línea, Programa)\n"
            "2. **Descripción:** con al menos 2 párrafos corridos\n"
            + ("3. **Estado:** por área (Comunicaciones, Jurídica, Talento Humano)\n" if meeting_type == "precomite" else "")
            + f"{'4' if meeting_type == 'precomite' else '3'}. **{decision_label}:** con 'Iniciativa {approval_word}' y lista de items\n"
            "Verifica que NO exista: resumen ejecutivo, sección Estado (solo comité), bloqueos/riesgos, próximas acciones, emojis.\n"
            "Verifica que la tabla de Compromisos a la fecha esté presente.\n"
            f"{_FOUNDATION_NOTE}\n\n"
            f"Catálogo de diapositivas PPT:\n"
            + "\n".join(f"Slide {slide.slide_number}: {slide.title}" for slide in ppt_context.slides)
            + "\n\n"
            + f"Markdown del acta:\n{markdown}"
        ),
        MinutesFinalValidationModel,
        system_prompt=(
            f"Eres el revisor final de un acta de {'Precomité' if meeting_type == 'precomite' else 'Comité'} de Proyectos. "
            f"{_FOUNDATION_NOTE} "
            "Verifica estructura y completitud de la Descripción: debe tener estrictamente 2 o 3 párrafos (Párrafo 1 de Objetivo + aportes financieros). "
            "RECHAZA INMEDIATAMENTE si la Descripción incluye información operativa o de contexto sobre componentes del proyecto, duración, territorios de ejecución, rol ejecutor o desgloses operativos. "
            "Verifica que la Decisión esté presente con al menos un item. Responde en español."
        ),
    )
    return FinalValidation(
        approved=validation.approved,
        issues=validation.issues,
        recommendations=validation.recommendations,
        summary=validation.summary,
    )


def render_draft_catalog(drafts: list[WriterDraft], *, exclude_assignment_id: str | None = None) -> str:
    parts: list[str] = []
    for draft in drafts:
        if exclude_assignment_id is not None and draft.assignment_id == exclude_assignment_id:
            continue
        parts.append(f"{draft.assignment_id}: {draft.section_title}\nSummary: {draft.section_summary}")
    return "\n\n".join(parts).strip() or "No other sections yet."
