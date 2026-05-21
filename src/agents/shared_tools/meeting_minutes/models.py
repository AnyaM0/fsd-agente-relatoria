from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class PPTSlideContext:
    slide_number: int
    title: str
    markdown: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PPTContext:
    source_path: str
    markdown: str
    slides: list[PPTSlideContext]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChunkSummaryRecord:
    short_title: str
    summary: str
    notable_points: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChunkContext:
    index: int
    path: str
    text: str
    token_count: int | None = None
    start_token: int | None = None
    end_token: int | None = None
    summary: ChunkSummaryRecord | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "path": self.path,
            "text": self.text,
            "token_count": self.token_count,
            "start_token": self.start_token,
            "end_token": self.end_token,
            "summary": None if self.summary is None else self.summary.as_dict(),
        }


@dataclass
class MeetingTheme:
    theme_id: str
    title: str
    description: str
    source: Literal["ppt", "chunks"]
    priority: int
    slide_refs: list[int] = field(default_factory=list)
    chunk_refs: list[int] = field(default_factory=list)
    selection_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WriterAssignment:
    assignment_id: str
    theme_id: str
    writer_id: str
    task_instruction: str
    chunk_refs: list[int]
    ppt_context_excerpt: str | None = None
    slide_refs: list[int] = field(default_factory=list)
    expected_output_shape: str = ""
    theme_title: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WriterDraft:
    assignment_id: str
    theme_id: str
    writer_id: str
    section_title: str
    body_markdown: str
    evidence_refs: list[int] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    confidence_notes: str = ""
    section_summary: str = ""
    revision_round: int = 0
    status: Literal["pending_review", "approved", "needs_revision"] = "pending_review"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClarificationRequest:
    assignment_id: str
    writer_id: str
    issues: list[str]
    requested_changes: list[str]
    must_address_refs: list[int] = field(default_factory=list)
    review_round: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinalValidation:
    approved: bool
    issues: list[str]
    recommendations: list[str]
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
