from __future__ import annotations

import json
import os
import re
from pathlib import Path

from agents.shared_tools.segmentation_agent.lg_types import (
    ChunkRoutingDecision,
    ChunkSummary,
    SegmentPlacementDecision,
    SegmentRecord,
    SegmentationState,
    TextUnitSummary,
)


_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")
DEFAULT_PARAGRAPH_UNIT_CHARS = 20000
DEFAULT_SENTENCE_UNIT_CHARS = 20000
DEFAULT_MAX_SPLIT_UNITS = 4
DEFAULT_FORCE_SPLIT_MIN_TRANSITIONS = 2


def segment_records_from_state(state: SegmentationState) -> list[SegmentRecord]:
    return [
        SegmentRecord(
            index=item["index"],
            title=item["title"],
            summary=item["summary"],
            text=item.get("text", ""),
            chunk_indices=list(item.get("chunk_indices", [])),
            unit_refs=list(item.get("unit_refs", [])),
            chunk_summaries=list(item.get("chunk_summaries", [])),
            unit_summaries=list(item.get("unit_summaries", [])),
        )
        for item in state["segments"]
    ]


def render_segment_catalog(segments: list[SegmentRecord]) -> str:
    if not segments:
        return "No existing segments yet."

    lines = []
    for segment in segments:
        lines.append(
            f"- Segment {segment.index}: title={segment.title!r}, chunks={segment.chunk_indices}, "
            f"unit_refs={segment.unit_refs}, summary={segment.summary}"
        )
    return "\n".join(lines)


def render_previous_chunk_summaries(state: SegmentationState) -> str:
    items = state["processed_chunk_summaries"]
    if not items:
        return "No previous chunks have been processed yet."

    lines = []
    for item in items:
        lines.append(
            f"- Chunk {item['chunk_index'] + 1}: title={item['short_title']!r}, summary={item['summary']}"
        )
    return "\n".join(lines)


def coalesce_units(units: list[str], *, max_units: int) -> list[str]:
    if len(units) <= max_units:
        return units

    merged: list[str] = []
    group_size = (len(units) + max_units - 1) // max_units
    for start in range(0, len(units), group_size):
        merged.append("\n\n".join(unit.strip() for unit in units[start : start + group_size] if unit.strip()))
    return [unit for unit in merged if unit.strip()]


def split_chunk_into_units(text: str) -> list[str]:
    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT_RE.split(text) if part.strip()]
    if len(paragraphs) > 1:
        units: list[str] = []
        current = ""
        max_chars = int(os.getenv("SEGMENTATION_MAX_UNIT_CHARS", str(DEFAULT_PARAGRAPH_UNIT_CHARS)))

        for paragraph in paragraphs:
            if not current:
                current = paragraph
                continue

            candidate = f"{current}\n\n{paragraph}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                units.append(current)
                current = paragraph

        if current:
            units.append(current)

        max_units = int(os.getenv("SEGMENTATION_MAX_SPLIT_UNITS", str(DEFAULT_MAX_SPLIT_UNITS)))
        return coalesce_units(units or [text.strip()], max_units=max_units)

    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]
    if len(sentences) <= 1:
        return [text.strip()]

    units: list[str] = []
    current = ""
    max_chars = int(os.getenv("SEGMENTATION_SENTENCE_UNIT_CHARS", str(DEFAULT_SENTENCE_UNIT_CHARS)))
    for sentence in sentences:
        if not current:
            current = sentence
            continue

        candidate = f"{current} {sentence}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            units.append(current)
            current = sentence

    if current:
        units.append(current)

    max_units = int(os.getenv("SEGMENTATION_MAX_SPLIT_UNITS", str(DEFAULT_MAX_SPLIT_UNITS)))
    return coalesce_units(units or [text.strip()], max_units=max_units)


def tool_log(stage: str, tool_name: str, *, arguments: dict[str, object]) -> None:
    print(f"[segmentation_agent:{stage}] tool={tool_name} args={json.dumps(arguments, ensure_ascii=True)}")


def truncate_tool_output(text: str, *, max_chars: int = 12000) -> str:
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars]}\n\n[truncated: {len(normalized) - max_chars} chars omitted]"


def read_chunk_text(state: SegmentationState, chunk_index: int, *, stage: str) -> str:
    chunk_paths = state["chunk_paths"]
    tool_log(stage, "read_chunk", arguments={"chunk_index": chunk_index})
    if chunk_index < 0 or chunk_index >= len(chunk_paths):
        return f"Invalid chunk_index={chunk_index}. Valid chunk indices are 0 through {len(chunk_paths) - 1}."
    return Path(chunk_paths[chunk_index]).read_text(encoding="utf-8")


def read_segment_text(state: SegmentationState, segment_index: int, *, stage: str) -> str:
    segments = segment_records_from_state(state)
    tool_log(stage, "read_segment", arguments={"segment_index": segment_index})
    if segment_index < 0 or segment_index >= len(segments):
        return f"Invalid segment_index={segment_index}. Valid segment indices are 0 through {len(segments) - 1}."
    segment = next((item for item in segments if item.index == segment_index), None)
    if segment is None:
        return f"Unknown segment index: {segment_index}"
    return segment.text


def append_tool_context(existing: str, *, tool_name: str, arguments: dict[str, object], output: str) -> str:
    observation = (
        f"Tool used: {tool_name}\n"
        f"Arguments: {json.dumps(arguments, ensure_ascii=True)}\n"
        f"Output:\n{truncate_tool_output(output)}"
    )
    if not existing.strip():
        return observation
    return f"{existing.rstrip()}\n\n---\n\n{observation}"


def merge_segment_summary(segment: SegmentRecord) -> str:
    parts = [segment.summary, *segment.unit_summaries[-2:]]
    merged = " ".join(part.strip() for part in parts if part.strip())
    return " ".join(merged.split())


def append_text(existing_text: str, new_text: str) -> str:
    if not existing_text.strip():
        return new_text.strip()
    return f"{existing_text.rstrip()}\n\n{new_text.strip()}"


def apply_segment_decision(state: SegmentationState, decision: SegmentPlacementDecision) -> list[dict[str, object]]:
    segments = segment_records_from_state(state)
    chunk_summary = ChunkSummary.model_validate(state["current_chunk_summary"] or {})
    unit_summary = TextUnitSummary.model_validate(state["current_unit_summary"] or {})
    chunk_index = state["current_chunk_index"]
    unit_index = state["current_unit_index"]
    unit_text = state["current_unit_text"].strip()

    if not segments:
        decision = SegmentPlacementDecision(
            action="new",
            target_segment_index=None,
            rationale="The first unit always starts the first segment.",
            segment_title=unit_summary.short_title,
        )

    if decision.action == "append":
        if decision.target_segment_index is None:
            raise ValueError("append decision requires target_segment_index")
        segment = next((item for item in segments if item.index == decision.target_segment_index), None)
        if segment is None:
            raise ValueError(f"Unknown segment index: {decision.target_segment_index}")

        if chunk_index not in segment.chunk_indices:
            segment.chunk_indices.append(chunk_index)
        segment.unit_refs.append({"chunk_index": chunk_index, "unit_index": unit_index})
        segment.chunk_summaries.append(chunk_summary.summary)
        segment.unit_summaries.append(unit_summary.summary)
        segment.text = append_text(segment.text, unit_text)
        segment.summary = merge_segment_summary(segment)
        if decision.segment_title:
            segment.title = decision.segment_title
    else:
        new_segment = SegmentRecord(
            index=len(segments),
            title=decision.segment_title or unit_summary.short_title,
            summary=unit_summary.summary,
            text=unit_text,
            chunk_indices=[chunk_index],
            unit_refs=[{"chunk_index": chunk_index, "unit_index": unit_index}],
            chunk_summaries=[chunk_summary.summary],
            unit_summaries=[unit_summary.summary],
        )
        segments.append(new_segment)

    return [segment.as_dict() for segment in segments]


def route_rule_gate(state: SegmentationState) -> dict[str, object]:
    chunk_summary = ChunkSummary.model_validate(state["current_chunk_summary"] or {})
    force_split_min_transitions = int(
        os.getenv(
            "SEGMENTATION_FORCE_SPLIT_MIN_TRANSITIONS",
            str(DEFAULT_FORCE_SPLIT_MIN_TRANSITIONS),
        )
    )
    force_split_char_threshold = int(os.getenv("SEGMENTATION_FORCE_SPLIT_MIN_CHARS", "8000"))

    if (
        chunk_summary.mixed_topic
        and len(chunk_summary.transition_notes) >= force_split_min_transitions
        and len(state["current_chunk_text"].strip()) >= force_split_char_threshold
    ):
        decision = ChunkRoutingDecision(
            action="split",
            target_segment_index=None,
            rationale=(
                "The chunk is long, mixed-topic, and contains multiple explicit transitions, "
                "so it should be segmented internally before assignment."
            ),
            segment_title=chunk_summary.short_title,
        )
        return {"chunk_routing_decision": decision.model_dump()}

    if not state["segments"] and not chunk_summary.mixed_topic:
        decision = ChunkRoutingDecision(
            action="new",
            target_segment_index=None,
            rationale="The first non-mixed chunk should seed the first segment.",
            segment_title=chunk_summary.short_title,
        )
        return {"chunk_routing_decision": decision.model_dump()}

    return {"chunk_routing_decision": None}
