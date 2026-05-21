from __future__ import annotations

from agents.compras.approval_memo.models import (
    ChunkContext,
    ClarificationRequest,
    WriterAssignment,
    WriterDraft,
    WriterDraftModel,
)
_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def write_assignment_draft(
    assignment: WriterAssignment,
    chunks: list[ChunkContext],
    model,
    *,
    variant: str,
) -> WriterDraft:
    chunk_payload = render_assignment_chunks(assignment, chunks)
    prompt_parts = [
        f"ID de asignación: {assignment.assignment_id}",
        f"ID del writer: {assignment.writer_id}",
        f"Tema de aprobación: {assignment.theme_title}",
        f"Instrucción de tarea: {assignment.task_instruction}",
        f"Formato esperado de salida: {assignment.expected_output_shape}",
        _FOUNDATION_NOTE,
    ]
    if variant == "ppt_led" and assignment.ppt_context_excerpt:
        prompt_parts.append(f"Extracto de contexto PPT:\n{assignment.ppt_context_excerpt}")
    prompt_parts.append(f"Chunks de transcripción asignados:\n{chunk_payload}")

    draft = model.invoke_structured(
        "\n\n".join(prompt_parts),
        WriterDraftModel,
        system_prompt=_writer_system_prompt(variant),
    )
    return WriterDraft(
        assignment_id=assignment.assignment_id,
        theme_id=assignment.theme_id,
        writer_id=assignment.writer_id,
        section_title=draft.section_title,
        body_markdown=draft.body_markdown,
        evidence_refs=sorted(set(ref for ref in draft.evidence_refs if ref in assignment.chunk_refs)),
        open_questions=draft.open_questions,
        confidence_notes=draft.confidence_notes,
        section_summary=draft.section_summary,
        revision_round=0,
    )


def revise_assignment_draft(
    assignment: WriterAssignment,
    current_draft: WriterDraft,
    clarification_request: ClarificationRequest,
    chunks: list[ChunkContext],
    model,
    *,
    variant: str,
) -> WriterDraft:
    chunk_payload = render_assignment_chunks(assignment, chunks)
    prompt_parts = [
        f"ID de asignación: {assignment.assignment_id}",
        f"ID del writer: {assignment.writer_id}",
        f"Tema de aprobación: {assignment.theme_title}",
        f"Instrucción de tarea: {assignment.task_instruction}",
        f"Título actual de la sección: {current_draft.section_title}",
        f"Resumen actual del borrador: {current_draft.section_summary}",
        f"Markdown actual del borrador:\n{current_draft.body_markdown}",
        f"Observaciones de aclaración: {clarification_request.issues}",
        f"Cambios solicitados: {clarification_request.requested_changes}",
        f"Chunks que debes abordar obligatoriamente: {clarification_request.must_address_refs}",
        _FOUNDATION_NOTE,
    ]
    if variant == "ppt_led" and assignment.ppt_context_excerpt:
        prompt_parts.append(f"Extracto de contexto PPT:\n{assignment.ppt_context_excerpt}")
    prompt_parts.append(f"Chunks de transcripción asignados:\n{chunk_payload}")

    draft = model.invoke_structured(
        "\n\n".join(prompt_parts),
        WriterDraftModel,
        system_prompt=(
            _writer_system_prompt(variant)
            + " Estás revisando una sección existente. Atiende explícitamente cada solicitud de aclaración."
        ),
    )
    return WriterDraft(
        assignment_id=assignment.assignment_id,
        theme_id=assignment.theme_id,
        writer_id=assignment.writer_id,
        section_title=draft.section_title,
        body_markdown=draft.body_markdown,
        evidence_refs=sorted(set(ref for ref in draft.evidence_refs if ref in assignment.chunk_refs)),
        open_questions=draft.open_questions,
        confidence_notes=draft.confidence_notes,
        section_summary=draft.section_summary,
        revision_round=current_draft.revision_round + 1,
    )


def render_assignment_chunks(assignment: WriterAssignment, chunks: list[ChunkContext]) -> str:
    parts: list[str] = []
    chunk_map = {chunk.index: chunk for chunk in chunks}
    for chunk_index in assignment.chunk_refs:
        chunk = chunk_map.get(chunk_index)
        if chunk is None:
            continue
        parts.append(
            f"Chunk {chunk.index}\n"
            f"Resumen: {chunk.summary.summary if chunk.summary is not None else ''}\n"
            f"Texto:\n{chunk.text}"
        )
    return "\n\n".join(parts).strip()


def _writer_system_prompt(variant: str) -> str:
    if variant == "ppt_led":
        return (
            "Eres un agente redactor que redacta una sección de un memo de aprobación. "
            "Usa el extracto del PPT para mantener el encuadre alineado, pero fundamenta todas las afirmaciones sustantivas en los chunks de transcripción asignados. "
            f"{_FOUNDATION_NOTE} "
            "No redactes secciones fuera del tema asignado. Responde en español."
        )

    return (
        "Eres un agente redactor que redacta una sección de un memo de aprobación usando solo los chunks de transcripción asignados. "
        "No asumas acceso al PowerPoint. "
        f"{_FOUNDATION_NOTE} "
        "Mantente dentro del tema asignado, no inventes hechos y responde en español."
    )
