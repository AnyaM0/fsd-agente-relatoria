from __future__ import annotations

from agents.proyectos.minutes.models import (
    ChunkContext,
    ClarificationRequest,
    MinutesDraftModel,
    WriterAssignment,
    WriterDraft,
)

_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)
_CHRONOLOGICAL_NOTE = (
    "Presenta la información en el orden cronológico exacto en que aparecen los fragmentos numerados. "
    "No adelantes ni reordenes eventos: lo que ocurre en el Chunk 3 debe narrarse antes que lo del Chunk 7."
)
_NO_SUMMARY_NOTE = (
    "No agregues párrafo ni subsección de resumen, conclusión o síntesis al final de la sección: "
    "el resumen ejecutivo global se genera en una etapa separada."
)


def write_assignment_draft(
    assignment: WriterAssignment,
    chunks: list[ChunkContext],
    model,
    *,
    variant: str,
) -> WriterDraft:
    draft = model.invoke_structured(
        _build_prompt(assignment, chunks, variant=variant),
        MinutesDraftModel,
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
    prompt = _build_prompt(assignment, chunks, variant=variant) + (
        f"\n\nTítulo actual de la sección: {current_draft.section_title}"
        f"\nResumen actual de la sección: {current_draft.section_summary}"
        f"\nMarkdown actual de la sección:\n{current_draft.body_markdown}"
        f"\nProblemas identificados: {clarification_request.issues}"
        f"\nCambios solicitados: {clarification_request.requested_changes}"
        f"\nChunks que deben ser abordados: {clarification_request.must_address_refs}"
    )
    draft = model.invoke_structured(
        prompt,
        MinutesDraftModel,
        system_prompt=_writer_system_prompt(variant) + " Estás revisando una sección existente del acta.",
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


def _build_prompt(assignment: WriterAssignment, chunks: list[ChunkContext], *, variant: str) -> str:
    parts = [
        f"ID de asignación: {assignment.assignment_id}",
        f"ID del writer: {assignment.writer_id}",
        f"Tema del comité de proyectos: {assignment.theme_title}",
        f"Instrucción de tarea: {assignment.task_instruction}",
        f"Formato esperado de salida: {assignment.expected_output_shape}",
        _FOUNDATION_NOTE,
    ]
    if variant == "ppt_led" and assignment.ppt_context_excerpt:
        parts.append(f"Extracto de contexto PPT:\n{assignment.ppt_context_excerpt}")
    parts.append(f"Chunks de transcripción asignados:\n{render_assignment_chunks(assignment, chunks)}")
    return "\n\n".join(parts)


def render_assignment_chunks(assignment: WriterAssignment, chunks: list[ChunkContext]) -> str:
    chunk_map = {chunk.index: chunk for chunk in chunks}
    parts: list[str] = []
    for chunk_index in sorted(assignment.chunk_refs):
        chunk = chunk_map.get(chunk_index)
        if chunk is None:
            continue
        parts.append(
            f"Chunk {chunk.index}\n"
            f"Resumen: {chunk.summary.summary if chunk.summary else ''}\n"
            f"Texto:\n{chunk.text}"
        )
    return "\n\n".join(parts).strip()


def _writer_system_prompt(variant: str) -> str:
    if variant == "ppt_led":
        return (
            "Eres un agente redactor que redacta una sección del acta de un comité de proyectos. "
            "Captura el estado actual del proyecto, los avances reportados, los bloqueos o riesgos identificados, "
            "las decisiones del comité y los compromisos adquiridos con responsable y fecha, siempre sustentado en los chunks de transcripción. "
            f"{_CHRONOLOGICAL_NOTE} "
            f"{_NO_SUMMARY_NOTE} "
            f"{_FOUNDATION_NOTE} "
            "Responde en español."
        )
    return (
        "Eres un agente redactor que redacta una sección del acta de un comité de proyectos usando solo chunks de transcripción. "
        "Captura el estado del proyecto, avances, bloqueos, riesgos, decisiones del comité y compromisos con responsable y fecha. "
        f"{_CHRONOLOGICAL_NOTE} "
        f"{_NO_SUMMARY_NOTE} "
        f"{_FOUNDATION_NOTE} "
        "Responde en español."
    )
