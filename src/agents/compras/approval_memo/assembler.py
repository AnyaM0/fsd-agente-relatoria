from __future__ import annotations

from agents.compras.approval_memo.models import ApprovalTheme, WriterDraft
_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)


def write_executive_summary(
    drafts: list[WriterDraft],
    themes: list[ApprovalTheme],
    model,
) -> str:
    theme_catalog = "\n".join(f"- {theme.title}: {theme.description}" for theme in themes)
    section_catalog = "\n\n".join(
        f"{draft.section_title}\nSummary: {draft.section_summary}\n\n{draft.body_markdown}"
        for draft in drafts
    )
    return model.invoke_text(
        (
            "Escribe un resumen ejecutivo para un memo de aprobación.\n"
            "Debe ser conciso, orientado a decisiones y reflejar fielmente las secciones aprobadas de abajo.\n"
            f"{_FOUNDATION_NOTE}\n\n"
            f"Temas:\n{theme_catalog}\n\n"
            f"Secciones aprobadas:\n{section_catalog}"
        ),
        system_prompt=(
            "Escribes resúmenes ejecutivos breves para memos de aprobación. "
            f"{_FOUNDATION_NOTE} "
            "No agregues hechos que no estén presentes en las secciones aprobadas. Responde en español."
        ),
    ).strip()


def assemble_approval_memo(
    drafts: list[WriterDraft],
    themes: list[ApprovalTheme],
    executive_summary: str,
) -> str:
    ordered_drafts = _order_drafts_by_theme(drafts, themes)
    parts = ["# Approval Memo", ""]

    for draft in ordered_drafts:
        parts.append(f"## {draft.section_title}")
        parts.append("")
        parts.append(draft.body_markdown.strip())
        parts.append("")

    parts.append("## Executive Summary")
    parts.append("")
    parts.append(executive_summary.strip())
    return "\n".join(parts).strip() + "\n"


def _order_drafts_by_theme(drafts: list[WriterDraft], themes: list[ApprovalTheme]) -> list[WriterDraft]:
    priority_by_theme = {theme.theme_id: theme.priority for theme in themes}
    return sorted(
        drafts,
        key=lambda draft: (
            priority_by_theme.get(draft.theme_id, 999),
            draft.section_title.lower(),
        ),
    )
