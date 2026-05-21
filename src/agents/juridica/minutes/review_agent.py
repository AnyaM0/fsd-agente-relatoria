from __future__ import annotations

from agents.juridica.minutes.models import (
    ClarificationRequest,
    FinalValidation,
    MinutesFinalValidationModel,
    MinutesReviewModel,
    PPTContext,
    WriterAssignment,
    WriterDraft,
)
from agents.juridica.minutes.ppt_context import render_ppt_excerpt
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
    review_round: int,
) -> ClarificationRequest | None:
    review = model.invoke_structured(
        (
            f"Revisa esta sección del acta jurídica para la asignación {assignment.assignment_id}.\n"
            f"Título del tema: {assignment.theme_title}\n"
            f"Variante: {variant}\n"
            f"Instrucción de tarea: {assignment.task_instruction}\n"
            f"Chunks asignados a este writer: {assignment.chunk_refs}\n"
            f"Referencias PPT: {assignment.slide_refs}\n"
            f"{_FOUNDATION_NOTE}\n\n"
            f"Título actual de la sección: {draft.section_title}\n"
            f"Resumen actual de la sección: {draft.section_summary}\n"
            f"Markdown actual de la sección:\n{draft.body_markdown}\n\n"
            f"Resumen de otras secciones:\n{render_draft_catalog(all_drafts, exclude_assignment_id=assignment.assignment_id)}\n\n"
            f"Extracto relevante del PPT para revisión:\n{render_ppt_excerpt(ppt_context, assignment.slide_refs)}"
        ),
        MinutesReviewModel,
        system_prompt=(
            "Eres el revisor de un acta jurídica de reunión. "
            f"{_FOUNDATION_NOTE} "
            "Aprueba solo si la sección captura correctamente la discusión, las decisiones, las recomendaciones y los puntos no resueltos. Responde en español."
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


def validate_final_acta(markdown: str, ppt_context: PPTContext, model) -> FinalValidation:
    validation = model.invoke_structured(
        (
            "Valida esta acta jurídica de reunión como entregable final.\n"
            "Revisa cobertura de temas, exactitud de las decisiones, consistencia de las recomendaciones y si los puntos no resueltos quedaron explícitos.\n"
            f"{_FOUNDATION_NOTE}\n\n"
            f"Catálogo de diapositivas PPT:\n"
            + "\n".join(f"Slide {slide.slide_number}: {slide.title}" for slide in ppt_context.slides)
            + "\n\n"
            + f"Markdown del acta:\n{markdown}"
        ),
        MinutesFinalValidationModel,
        system_prompt=(
            "Eres el revisor final de un acta jurídica de reunión. "
            f"{_FOUNDATION_NOTE} "
            "Sé estricto con decisiones faltantes, afirmaciones no soportadas y recomendaciones omitidas. Responde en español."
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
