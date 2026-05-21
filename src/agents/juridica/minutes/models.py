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


LegalTopic = MeetingTheme


@dataclass
class JuridicaMinutesRunResult:
    variant: Literal["ppt_led", "chunk_led"]
    status: Literal["approved", "needs_review"]
    ppt_context: PPTContext
    chunks: list[ChunkContext]
    themes: list[LegalTopic]
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
    title: str = Field(description="Theme title.")
    description: str = Field(description="Short explanation of what was discussed under this topic.")
    priority: int = Field(description="Relative importance, where 1 is highest priority.")
    slide_refs: list[int] = Field(default_factory=list, description="Relevant slide numbers.")
    selection_reason: str = Field(description="Why this topic matters for the legal meeting minutes.")


class TopicDiscoveryModel(BaseModel):
    themes: list[TopicCandidateModel] = Field(description="Topics discussed in the meeting, ordered by importance.")


class TopicChunkPlanModel(BaseModel):
    chunk_refs: list[int] = Field(description="Chunk indices that support the topic.")
    slide_refs: list[int] = Field(default_factory=list, description="Relevant slide numbers for the topic.")
    task_instruction: str = Field(description="Writer-specific instruction for drafting the acta section.")


class MinutesDraftModel(BaseModel):
    section_title: str = Field(description="Title of the drafted acta section.")
    section_summary: str = Field(description="Short summary of the drafted section.")
    body_markdown: str = Field(description="Markdown body of the acta section.")
    evidence_refs: list[int] = Field(description="Chunk indices used as evidence.")
    open_questions: list[str] = Field(default_factory=list, description="Open questions or unresolved points.")
    confidence_notes: str = Field(description="Concise note about confidence or uncertainty.")


class MinutesReviewModel(BaseModel):
    approved: bool = Field(description="Whether the section is approved as-is.")
    issues: list[str] = Field(default_factory=list, description="Issues found in the section.")
    requested_changes: list[str] = Field(default_factory=list, description="Concrete revision requests.")
    must_address_refs: list[int] = Field(default_factory=list, description="Chunk indices that must be addressed.")


class MinutesFinalValidationModel(BaseModel):
    approved: bool = Field(description="Whether the acta is approved as final.")
    issues: list[str] = Field(default_factory=list, description="Remaining issues in the acta.")
    recommendations: list[str] = Field(default_factory=list, description="Recommended corrections or follow-up.")
    summary: str = Field(description="Short summary of the final validation result.")
