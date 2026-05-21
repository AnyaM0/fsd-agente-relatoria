from __future__ import annotations

from agents.proyectos.minutes.models import ProjectTopic, WriterDraft
from agents.shared_tools.meeting_minutes.models import WriterAssignment

_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def write_executive_summary(drafts: list[WriterDraft], themes: list[ProjectTopic], model) -> str:
    theme_catalog = "\n".join(f"- {theme.title}: {theme.description}" for theme in themes)
    section_catalog = "\n\n".join(
        f"{draft.section_title}\nSummary: {draft.section_summary}\n\n{draft.body_markdown}"
        for draft in drafts
    )
    return model.invoke_text(
        (
            "Escribe un resumen ejecutivo conciso para un acta de comité de proyectos.\n"
            "Debe capturar los proyectos tratados, los avances más relevantes, las decisiones del comité, "
            "los principales riesgos o bloqueos y los compromisos adquiridos con responsable y fecha.\n"
            f"{_FOUNDATION_NOTE}\n\n"
            f"Temas:\n{theme_catalog}\n\n"
            f"Secciones aprobadas:\n{section_catalog}"
        ),
        system_prompt=(
            "Escribes resúmenes concisos para actas de comités de proyectos. "
            f"{_FOUNDATION_NOTE} "
            "No inventes hechos y responde en español."
        ),
    ).strip()


def assemble_acta(
    drafts: list[WriterDraft],
    themes: list[ProjectTopic],
    executive_summary: str,
    assignments: list[WriterAssignment] | None = None,
) -> str:
    min_chunk_by_assignment: dict[str, int] = {}
    if assignments:
        for a in assignments:
            if a.chunk_refs:
                min_chunk_by_assignment[a.assignment_id] = min(a.chunk_refs)

    def _sort_key(draft: WriterDraft) -> tuple[int, int]:
        chronological = min_chunk_by_assignment.get(draft.assignment_id, 999)
        priority = next((t.priority for t in themes if t.theme_id == draft.theme_id), 999)
        return (chronological, priority)

    ordered = sorted(drafts, key=_sort_key)
    parts = ["# Acta de Comité de Proyectos", ""]
    for draft in ordered:
        parts.append(f"## {draft.section_title}")
        parts.append("")
        parts.append(draft.body_markdown.strip())
        parts.append("")
    parts.append("## Resumen Ejecutivo")
    parts.append("")
    parts.append(executive_summary.strip())
    return "\n".join(parts).strip() + "\n"
