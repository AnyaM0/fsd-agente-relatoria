from __future__ import annotations

from agents.proyectos.minutes.acta_metadata_models import ActaMetadata
from agents.proyectos.minutes.models import ProjectTopic, WriterDraft
from agents.shared_tools.meeting_minutes.models import WriterAssignment
from typing import Any

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
    assignments: list[WriterAssignment] | None = None,
    acta_metadata: ActaMetadata | None = None,
    model: Any = None,
) -> str:
    if acta_metadata is None:
        return _assemble_acta_simple(drafts, themes, assignments)
    return _assemble_acta_with_template(drafts, themes, assignments, acta_metadata, model)


def _assemble_acta_simple(
    drafts: list[WriterDraft],
    themes: list[ProjectTopic],
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
        parts.append(f"**{draft.section_title}**")
        parts.append("")
        parts.append(draft.body_markdown.strip())
        parts.append("")
        parts.append("---")
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def _assemble_acta_with_template(
    drafts: list[WriterDraft],
    themes: list[ProjectTopic],
    assignments: list[WriterAssignment] | None = None,
    acta_metadata: ActaMetadata | None = None,
    model: Any = None,
) -> str:
    parts = []
    
    # =========================================================================
    # ENCABEZADO CON METADATOS
    # =========================================================================
    parts.append(f"**Reunión No.** {acta_metadata.meeting_number}")
    parts.append("")
    
    # Tabla de info básica
    parts.append("| Fecha | Hora | Lugar |")
    parts.append("|---|---|---|")
    parts.append(f"| {acta_metadata.date} | {acta_metadata.start_time} – {acta_metadata.end_time} | {acta_metadata.location} |")
    parts.append("")
    
    # =========================================================================
    # TABLA MIEMBROS DEL COMITÉ/PRECOMITÉ
    # =========================================================================
    header_text = "Miembros del Precomité" if acta_metadata.variant == "precomite" else "Miembros del Comité"
    parts.append(f"| **{header_text}** | | | |")
    parts.append("|---|---|---|---|")
    parts.append("| **Nombre** | **Cargo** | **Nombre** | **Cargo** |")
    
    # Rellenar tabla de asistentes (en pares)
    members = acta_metadata.committee_members
    for i in range(0, len(members), 2):
        name1 = members[i].name if i < len(members) else ""
        pos1 = members[i].position if i < len(members) else ""
        name2 = members[i + 1].name if i + 1 < len(members) else ""
        pos2 = members[i + 1].position if i + 1 < len(members) else ""
        parts.append(f"| {name1} | {pos1} | {name2} | {pos2} |")
    
    parts.append("")
    
    # =========================================================================
    # TABLA SOLICITANTES
    # =========================================================================
    parts.append("| **Solicitantes** | | | |")
    parts.append("|---|---|---|---|")
    parts.append("| **Nombre** | **Cargo** | **Nombre** | **Cargo** |")
    
    requesters = acta_metadata.requesters
    for i in range(0, len(requesters), 2):
        name1 = requesters[i].name if i < len(requesters) else ""
        pos1 = requesters[i].position if i < len(requesters) else ""
        name2 = requesters[i + 1].name if i + 1 < len(requesters) else ""
        pos2 = requesters[i + 1].position if i + 1 < len(requesters) else ""
        parts.append(f"| {name1} | {pos1} | {name2} | {pos2} |")
    
    parts.append("")
    
    # =========================================================================
    # ORDEN DEL DÍA
    # =========================================================================
    parts.append("**Orden del día**")
    if acta_metadata.variant == "precomite":
        parts.append("1. Preaprobación de iniciativas")
    else:
        parts.append("1. Aprobación de iniciativas")
    
    if acta_metadata.has_refrendations:
        if acta_metadata.variant == "precomite":
            parts.append("2. Preaprobación de refrendaciones")
        else:
            parts.append("2. Aprobación de refrendaciones")
    
    parts.append("")
    parts.append("---")
    parts.append("")
    
    # =========================================================================
    # DESARROLLO DE LA REUNIÓN
    # =========================================================================
    parts.append("### Desarrollo de la reunión")
    parts.append("")

    if acta_metadata.variant == "precomite":
        parts.append("**1. Preaprobación de iniciativas**")
    else:
        parts.append("**1. Aprobación de iniciativas**")

    parts.append("")

    # Incluir drafts como subsecciones numeradas
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

    iniciativas_drafts = []
    refrendaciones_drafts = []
    
    for draft in ordered:
        theme = next((t for t in themes if t.theme_id == draft.theme_id), None)
        if theme and theme.topic_type == "refrendacion":
            refrendaciones_drafts.append(draft)
        else:
            iniciativas_drafts.append(draft)

    for idx, draft in enumerate(iniciativas_drafts, start=1):
        parts.append(f"**1.{idx} {draft.section_title}**")
        parts.append("")
        parts.append(draft.body_markdown.strip())
        parts.append("")
        parts.append("---")
        parts.append("")

    # Sección de refrendaciones (si aplica)
    if acta_metadata.has_refrendations or refrendaciones_drafts:
        if acta_metadata.variant == "precomite":
            parts.append("**2. Preaprobación de refrendaciones**")
        else:
            parts.append("**2. Aprobación de refrendaciones**")
        parts.append("")
        
        if refrendaciones_drafts:
            for idx, draft in enumerate(refrendaciones_drafts, start=1):
                parts.append(f"**2.{idx} {draft.section_title}**")
                parts.append("")
                parts.append(draft.body_markdown.strip())
                parts.append("")
                parts.append("---")
                parts.append("")
        else:
            parts.append("*[Contenido de refrendaciones]*")
            parts.append("")
            parts.append("---")
            parts.append("")

    # =========================================================================
    # TABLA DE COMPROMISOS
    # =========================================================================
    parts.append("**Compromisos a la fecha**")
    parts.append("")
    
    if model is not None:
        commitments_table = generate_commitments_table(drafts, model)
        parts.append(commitments_table.strip())
    else:
        parts.append("| Proyecto | Descripción | Responsable | Fecha |")
        parts.append("|---|---|---|---|")

        for commitment in acta_metadata.commitments:
            responsible = commitment.responsible if isinstance(commitment.responsible, str) else " / ".join(commitment.responsible)
            parts.append(f"| {commitment.project_name} | {commitment.description} | {responsible} | {commitment.due_date} |")

        if not acta_metadata.commitments:
            parts.append("| — | Sin compromisos registrados | — | — |")

    parts.append("")

    return "\n".join(parts).strip() + "\n"

def generate_commitments_table(drafts: list[WriterDraft], model: Any) -> str:
    sections = "\n\n".join(f"Proyecto: {d.section_title}\nSección completa:\n{d.body_markdown}" for d in drafts)
    prompt = (
        "Extrae los compromisos de las secciones de proyectos y organízalos en una tabla Markdown. Reglas estrictas:\n"
        "Columnas EXACTAS: | Proyecto | Descripción | Responsable | Fecha |\n"
        "- Una fila por proyecto; si un proyecto no tiene compromisos, NO lo incluyas en la tabla.\n"
        "- PROHIBIDO inventar compromisos. Solo incluye compromisos explícitamente mencionados en el texto de la sección.\n"
        "- Descripción: extrae los compromisos de forma literal o muy cercana al texto original. Siempre comienza la celda con 'Se acuerda '.\n"
        "  - Un solo compromiso: 'Se acuerda [compromiso].'\n"
        "  - Varios compromisos del mismo proyecto:\n"
        "    Se acuerda:\n"
        "    - [Compromiso 1]\n"
        "    - [Compromiso 2]\n"
        "- Responsable: nombre propio de la persona responsable. Si no se menciona un nombre propio, escribe 'Por definir'. NO uses áreas, departamentos ni cargos genéricos.\n"
        "- Fecha: fecha o plazo mencionado en el texto. Si no se especifica, escribe 'Por definir'.\n"
        "- Las refrendaciones sin compromisos propios NO aparecen en esta tabla.\n"
        "- Si no existe ningún compromiso en ningún proyecto, devuelve exactamente:\n"
        "| Proyecto | Descripción | Responsable | Fecha |\n|---|---|---|---|\n| — | Sin compromisos registrados | — | — |\n\n"
        "Secciones de proyectos:\n\n"
        f"{sections}"
    )
    return model.invoke_text(
        prompt,
        system_prompt="Eres un asistente experto extrayendo y consolidando compromisos de actas en tablas Markdown estrictamente formateadas."
    )

