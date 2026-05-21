from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from agents.shared_tools.meeting_minutes.models import (
    ChunkContext,
    ChunkSummaryRecord,
    ClarificationRequest,
    FinalValidation,
    MeetingTheme,
    PPTContext,
    PPTSlideContext,
    WriterAssignment,
    WriterDraft,
)


ProjectTopic = MeetingTheme


@dataclass
class ProyectosMinutesRunResult:
    variant: Literal["ppt_led", "chunk_led"]
    status: Literal["approved", "needs_review"]
    ppt_context: PPTContext
    chunks: list[ChunkContext]
    themes: list[ProjectTopic]
    assignments: list[WriterAssignment]
    drafts: list[WriterDraft]
    clarification_requests: list[ClarificationRequest]
    executive_summary: str
    acta_markdown: str
    final_validation: FinalValidation

    def as_dict(self) -> dict[str, object]:
        return {
            "variant": self.variant,
            "status": self.status,
            "ppt_context": self.ppt_context.as_dict(),
            "chunks": [chunk.as_dict() for chunk in self.chunks],
            "themes": [theme.as_dict() for theme in self.themes],
            "assignments": [assignment.as_dict() for assignment in self.assignments],
            "drafts": [draft.as_dict() for draft in self.drafts],
            "clarification_requests": [request.as_dict() for request in self.clarification_requests],
            "executive_summary": self.executive_summary,
            "acta_markdown": self.acta_markdown,
            "final_validation": self.final_validation.as_dict(),
        }


class TopicCandidateModel(BaseModel):
    title: str = Field(description="Título del tema o proyecto tratado.")
    description: str = Field(description="Breve descripción de lo que se discutió sobre este tema o proyecto.")
    priority: int = Field(description="Importancia relativa, donde 1 es la más alta.")
    slide_refs: list[int] = Field(default_factory=list, description="Números de diapositiva relevantes.")
    selection_reason: str = Field(description="Por qué este tema es relevante para el acta del comité de proyectos.")


class TopicDiscoveryModel(BaseModel):
    themes: list[TopicCandidateModel] = Field(description="Temas o proyectos tratados en el comité, ordenados por importancia.")


class TopicChunkPlanModel(BaseModel):
    chunk_refs: list[int] = Field(description="Índices de chunks que soportan el tema.")
    slide_refs: list[int] = Field(default_factory=list, description="Diapositivas relevantes para el tema.")
    task_instruction: str = Field(description="Instrucción específica para el writer que redactará esta sección del acta.")


class MinutesDraftModel(BaseModel):
    section_title: str = Field(description="Título de la sección del acta.")
    section_summary: str = Field(description="Resumen breve de la sección redactada.")
    body_markdown: str = Field(description="Cuerpo en markdown de la sección del acta.")
    evidence_refs: list[int] = Field(description="Índices de chunks usados como evidencia.")
    open_questions: list[str] = Field(default_factory=list, description="Puntos abiertos o sin resolver.")
    confidence_notes: str = Field(description="Nota breve sobre confianza o incertidumbre en el contenido.")


class MinutesReviewModel(BaseModel):
    approved: bool = Field(description="Si la sección está aprobada tal como está.")
    issues: list[str] = Field(default_factory=list, description="Problemas encontrados en la sección.")
    requested_changes: list[str] = Field(default_factory=list, description="Cambios concretos solicitados.")
    must_address_refs: list[int] = Field(default_factory=list, description="Chunks que deben ser abordados.")


class MinutesFinalValidationModel(BaseModel):
    approved: bool = Field(description="Si el acta está aprobada como entregable final.")
    issues: list[str] = Field(default_factory=list, description="Problemas pendientes en el acta.")
    recommendations: list[str] = Field(default_factory=list, description="Correcciones o seguimiento recomendado.")
    summary: str = Field(description="Resumen breve del resultado de la validación final.")
