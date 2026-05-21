from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class ChunkSummary(BaseModel):
    short_title: str = Field(description="Very short title for the chunk.")
    summary: str = Field(description="Short summary of what happens in the chunk.")
    topics: list[str] = Field(description="Main topics or themes detected in the chunk.")
    mixed_topic: bool = Field(
        description="Whether the chunk contains more than one materially different topic or section."
    )
    transition_notes: list[str] = Field(
        description="Detected topic changes or transitions inside the chunk. Empty when not mixed."
    )


class TextUnitSummary(BaseModel):
    short_title: str = Field(description="Very short title for this text unit.")
    summary: str = Field(description="Short summary of the unit.")
    topics: list[str] = Field(description="Main topics present in the unit.")


class SegmentPlacementDecision(BaseModel):
    action: Literal["append", "new"] = Field(
        description="Whether to append the current unit to an existing segment or create a new one."
    )
    target_segment_index: int | None = Field(
        default=None,
        description="Target segment index when action is append.",
    )
    rationale: str = Field(description="Short explanation for the decision.")
    segment_title: str | None = Field(
        default=None,
        description="Title for a new segment, or optional refined title for an existing one.",
    )


class ChunkRoutingDecision(BaseModel):
    action: Literal["append", "new", "split"] = Field(
        description="Whether to append the whole chunk, create a new segment from it, or split it internally first."
    )
    target_segment_index: int | None = Field(
        default=None,
        description="Target segment index when action is append.",
    )
    rationale: str = Field(description="Short explanation for the routing decision.")
    segment_title: str | None = Field(
        default=None,
        description="Title for a new segment or an optional refined title when appending.",
    )


class ChunkRoutingAgentStep(BaseModel):
    action: Literal["append", "new", "split", "use_tool"] = Field(
        description="Either finalize the route or ask to use a tool before deciding."
    )
    rationale: str = Field(description="Short explanation for the step.")
    target_segment_index: int | None = Field(
        default=None,
        description="Target segment index when action is append.",
    )
    segment_title: str | None = Field(
        default=None,
        description="Optional title for a new segment or refined title for append.",
    )
    tool_name: Literal["read_chunk", "read_segment"] | None = Field(
        default=None,
        description="Tool to use when action is use_tool.",
    )
    chunk_index: int | None = Field(
        default=None,
        description="Chunk index to read when tool_name is read_chunk.",
    )
    segment_index: int | None = Field(
        default=None,
        description="Segment index to read when tool_name is read_segment.",
    )


class SegmentPlacementAgentStep(BaseModel):
    action: Literal["append", "new", "use_tool"] = Field(
        description="Either finalize segment placement or ask to use a tool before deciding."
    )
    rationale: str = Field(description="Short explanation for the step.")
    target_segment_index: int | None = Field(
        default=None,
        description="Target segment index when action is append.",
    )
    segment_title: str | None = Field(
        default=None,
        description="Optional title for a new segment or refined title for append.",
    )
    tool_name: Literal["read_chunk", "read_segment"] | None = Field(
        default=None,
        description="Tool to use when action is use_tool.",
    )
    chunk_index: int | None = Field(
        default=None,
        description="Chunk index to read when tool_name is read_chunk.",
    )
    segment_index: int | None = Field(
        default=None,
        description="Segment index to read when tool_name is read_segment.",
    )


@dataclass
class SegmentRecord:
    index: int
    title: str
    summary: str
    text: str
    chunk_indices: list[int] = field(default_factory=list)
    unit_refs: list[dict[str, int]] = field(default_factory=list)
    chunk_summaries: list[str] = field(default_factory=list)
    unit_summaries: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SegmentationState(TypedDict):
    chunk_paths: list[str]
    current_chunk_index: int
    total_chunks: int
    current_chunk_text: str
    current_chunk_summary: dict[str, Any] | None
    processed_chunk_summaries: list[dict[str, Any]]
    chunk_routing_decision: dict[str, Any] | None
    route_agent_step: dict[str, Any] | None
    route_tool_context: str
    route_tool_calls: int
    current_chunk_units: list[str]
    current_unit_index: int
    current_unit_text: str
    current_unit_summary: dict[str, Any] | None
    segments: list[dict[str, Any]]
    last_decision: dict[str, Any] | None
    segment_agent_step: dict[str, Any] | None
    segment_tool_context: str
    segment_tool_calls: int
    done: bool
