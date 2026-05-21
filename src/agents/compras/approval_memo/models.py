from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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
from pydantic import BaseModel, Field

ApprovalTheme = MeetingTheme


@dataclass
class ApprovalMemoRunResult:
    variant: Literal["ppt_led", "chunk_led"]
    status: Literal["approved", "needs_review"]
    ppt_context: PPTContext
    chunks: list[ChunkContext]
    themes: list[ApprovalTheme]
    assignments: list[WriterAssignment]
    drafts: list[WriterDraft]
    clarification_requests: list[ClarificationRequest]
    executive_summary: str
    approval_memo_markdown: str
    final_validation: FinalValidation

    def as_dict(self) -> dict[str, Any]:
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
            "approval_memo_markdown": self.approval_memo_markdown,
            "final_validation": self.final_validation.as_dict(),
        }


class ChunkSummaryModel(BaseModel):
    short_title: str = Field(description="Short title for the transcript chunk.")
    summary: str = Field(description="Concise summary of the chunk.")
    notable_points: list[str] = Field(
        default_factory=list,
        description="Important points, decisions, or findings from the chunk.",
    )


class ThemeCandidateModel(BaseModel):
    title: str = Field(description="Theme title.")
    description: str = Field(description="Short explanation of the approval theme.")
    priority: int = Field(description="Relative importance, where 1 is highest priority.")
    slide_refs: list[int] = Field(
        default_factory=list,
        description="Slide numbers that strongly support this theme.",
    )
    selection_reason: str = Field(description="Why this theme matters for the approval memo.")


class ThemeDiscoveryModel(BaseModel):
    themes: list[ThemeCandidateModel] = Field(description="Discovered approval themes ordered by priority.")


class ThemeChunkPlanModel(BaseModel):
    chunk_refs: list[int] = Field(description="Chunk indices that support the theme.")
    slide_refs: list[int] = Field(default_factory=list, description="Relevant slide numbers for the theme.")
    task_instruction: str = Field(description="Writer-specific instruction for drafting the section.")


class WriterDraftModel(BaseModel):
    section_title: str = Field(description="Title of the drafted memo section.")
    section_summary: str = Field(description="Short summary of the drafted section.")
    body_markdown: str = Field(description="Markdown body of the drafted section.")
    evidence_refs: list[int] = Field(description="Chunk indices used as evidence.")
    open_questions: list[str] = Field(default_factory=list, description="Open questions or ambiguities.")
    confidence_notes: str = Field(description="Concise note about confidence or uncertainty.")


class DraftReviewModel(BaseModel):
    approved: bool = Field(description="Whether the section is approved as-is.")
    issues: list[str] = Field(default_factory=list, description="Issues found in the section.")
    requested_changes: list[str] = Field(
        default_factory=list,
        description="Concrete revision requests when the section is not approved.",
    )
    must_address_refs: list[int] = Field(
        default_factory=list,
        description="Chunk indices that the writer must address in the revision.",
    )


class FinalValidationModel(BaseModel):
    approved: bool = Field(description="Whether the memo is approved as final.")
    issues: list[str] = Field(default_factory=list, description="Remaining issues in the final memo.")
    recommendations: list[str] = Field(
        default_factory=list,
        description="Recommended follow-up actions before publication or approval.",
    )
    summary: str = Field(description="Short summary of the final validation result.")
