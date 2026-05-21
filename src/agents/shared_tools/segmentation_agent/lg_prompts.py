from __future__ import annotations

from agents.shared_tools.segmentation_agent.lg_text import (
    render_previous_chunk_summaries,
    render_segment_catalog,
    segment_records_from_state,
)
from agents.shared_tools.segmentation_agent.lg_types import ChunkSummary, SegmentationState, TextUnitSummary


def build_chunk_summary_prompt(state: SegmentationState) -> str:
    chunk_number = state["current_chunk_index"] + 1
    return (
        f"You are analyzing chunk {chunk_number} of {state['total_chunks']} from a long meeting transcript.\n"
        "Summarize the chunk, identify its topics, and decide if it is mixed-topic.\n"
        "Set mixed_topic=true only when the chunk clearly contains multiple materially different sections.\n\n"
        f"Chunk content:\n{state['current_chunk_text']}"
    )


def build_unit_summary_prompt(state: SegmentationState) -> str:
    chunk_number = state["current_chunk_index"] + 1
    unit_number = state["current_unit_index"] + 1
    total_units = len(state["current_chunk_units"])
    chunk_summary = ChunkSummary.model_validate(state["current_chunk_summary"] or {})
    return (
        f"You are summarizing unit {unit_number} of {total_units} inside chunk {chunk_number} of {state['total_chunks']}.\n"
        f"Chunk summary: {chunk_summary.summary}\n"
        f"Chunk topics: {', '.join(chunk_summary.topics)}\n\n"
        f"Unit content:\n{state['current_unit_text']}"
    )


def decision_system_prompt() -> str:
    return (
        "You are a segmentation agent for long meeting transcripts.\n"
        "You receive one text unit at a time. A unit may be a whole chunk or a subpart of a mixed chunk.\n"
        "Your job is to decide whether the current unit should:\n"
        "1. be appended to an existing segment, or\n"
        "2. start a new segment.\n\n"
        "You can inspect any chunk or existing segment using tools.\n"
        "Prefer append when the unit clearly continues the same discussion, case, project, or decision thread.\n"
        "Prefer new when the unit introduces a materially different topic, case, speaker agenda, or meeting section.\n"
        "If the unit corresponds to a different agenda item, contract, provider, project, case, or decision track, prefer new.\n"
        "Do not merge clearly different agenda items just because they happened in the same meeting."
    )


def chunk_routing_system_prompt() -> str:
    return (
        "You route large transcript chunks before fine-grained segmentation.\n"
        "Your first preference is to keep the whole chunk together when it mostly belongs to one discussion thread.\n"
        "Use split only when the chunk clearly combines multiple materially different topics that should become different segments.\n"
        "If the chunk spans multiple agenda items, contracts, projects, or decisions, prefer split.\n"
        "For long meetings, preserving context matters, but mixing unrelated agenda items is worse.\n"
        "If you are unsure whether the chunk continues an existing segment, use a tool before deciding.\n"
        "When you need evidence, return action='use_tool' with either read_chunk or read_segment."
    )


def build_route_agent_prompt(state: SegmentationState) -> str:
    chunk_summary = ChunkSummary.model_validate(state["current_chunk_summary"] or {})
    existing_segments = render_segment_catalog(segment_records_from_state(state))
    previous_chunks = render_previous_chunk_summaries(state)
    tool_context = state["route_tool_context"].strip() or "No tools used yet."
    used_tools = state["route_tool_calls"]
    tool_budget_note = (
        "You have already used tools in this route. Do not request another tool unless absolutely necessary."
        if used_tools >= 2
        else "Use a tool when you need direct evidence from a chunk or segment."
    )
    return (
        f"You are routing chunk {state['current_chunk_index'] + 1} of {state['total_chunks']} from a long meeting transcript.\n"
        "You must return one of these actions:\n"
        "- append\n"
        "- new\n"
        "- split\n"
        "- use_tool\n\n"
        "Use append when the whole chunk clearly continues an existing segment.\n"
        "Use new when the whole chunk clearly starts a distinct segment.\n"
        "Use split when the chunk contains multiple agenda items or materially different topics that should be assigned separately.\n"
        "Use use_tool when you need to inspect the full text of another chunk or an existing segment before deciding.\n"
        "You may use read_chunk and read_segment to inspect more detail before making a final routing decision.\n\n"
        f"{tool_budget_note}\n\n"
        f"Previous chunks:\n{previous_chunks}\n\n"
        f"Chunk title: {chunk_summary.short_title}\n"
        f"Chunk summary: {chunk_summary.summary}\n"
        f"Chunk topics: {', '.join(chunk_summary.topics)}\n"
        f"mixed_topic: {chunk_summary.mixed_topic}\n"
        f"transitions: {', '.join(chunk_summary.transition_notes) if chunk_summary.transition_notes else 'none'}\n\n"
        f"Existing segments:\n{existing_segments}\n\n"
        f"Tool observations so far:\n{tool_context}"
    )


def build_segment_agent_prompt(state: SegmentationState) -> str:
    chunk_summary = ChunkSummary.model_validate(state["current_chunk_summary"] or {})
    unit_summary = TextUnitSummary.model_validate(state["current_unit_summary"] or {})
    existing_segments = render_segment_catalog(segment_records_from_state(state))
    tool_context = state["segment_tool_context"].strip() or "No tools used yet."
    used_tools = state["segment_tool_calls"]
    tool_budget_note = (
        "You have already used tools in this placement decision. Do not request another tool unless absolutely necessary."
        if used_tools >= 2
        else "Use a tool when you need direct evidence from the full chunk or an existing segment."
    )
    return (
        f"You are evaluating chunk {state['current_chunk_index'] + 1} of {state['total_chunks']}.\n"
        f"This chunk was classified as mixed_topic={chunk_summary.mixed_topic}.\n"
        "You must return one of these actions:\n"
        "- append\n"
        "- new\n"
        "- use_tool\n\n"
        "Use append only when the current unit clearly continues an existing segment.\n"
        "Use new when the current unit starts a distinct agenda item, project, contract, provider discussion, or decision track.\n"
        "Use use_tool when you need to inspect a full chunk or an existing segment before deciding.\n\n"
        f"{tool_budget_note}\n\n"
        f"Chunk summary: {chunk_summary.summary}\n"
        f"Chunk transitions: {', '.join(chunk_summary.transition_notes) if chunk_summary.transition_notes else 'none'}\n"
        f"Current unit {state['current_unit_index'] + 1} of {len(state['current_chunk_units'])}:\n"
        f"- title: {unit_summary.short_title}\n"
        f"- summary: {unit_summary.summary}\n"
        f"- topics: {', '.join(unit_summary.topics)}\n\n"
        f"Existing segments:\n{existing_segments}\n\n"
        f"Tool observations so far:\n{tool_context}"
    )
