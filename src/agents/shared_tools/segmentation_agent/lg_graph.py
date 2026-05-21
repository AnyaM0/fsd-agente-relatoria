from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from agents.shared_tools.segmentation_agent.lg_llm import build_default_chat_model
from agents.shared_tools.segmentation_agent.lg_prompts import (
    build_chunk_summary_prompt,
    build_route_agent_prompt,
    build_segment_agent_prompt,
    build_unit_summary_prompt,
    chunk_routing_system_prompt,
    decision_system_prompt,
)
from agents.shared_tools.segmentation_agent.lg_text import (
    append_tool_context,
    apply_segment_decision,
    read_chunk_text,
    read_segment_text,
    render_segment_catalog,
    route_rule_gate,
    segment_records_from_state,
    split_chunk_into_units,
)
from agents.shared_tools.segmentation_agent.lg_types import (
    ChunkRoutingAgentStep,
    ChunkRoutingDecision,
    ChunkSummary,
    SegmentPlacementAgentStep,
    SegmentPlacementDecision,
    SegmentationState,
    TextUnitSummary,
)


def list_chunk_files(chunk_dir: str | Path) -> list[Path]:
    path = Path(chunk_dir).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Chunk directory not found: {path}")

    chunk_paths = sorted(
        candidate
        for candidate in path.iterdir()
        if candidate.is_file() and candidate.name.startswith("chunk_") and candidate.suffix == ".txt"
    )
    if not chunk_paths:
        raise ValueError(f"No chunk_*.txt files found in {path}")
    return chunk_paths


def load_current_chunk(state: SegmentationState) -> dict[str, object]:
    current_path = Path(state["chunk_paths"][state["current_chunk_index"]])
    return {
        "current_chunk_text": current_path.read_text(encoding="utf-8"),
        "current_chunk_summary": None,
        "chunk_routing_decision": None,
        "route_agent_step": None,
        "route_tool_context": "",
        "route_tool_calls": 0,
        "current_chunk_units": [],
        "current_unit_index": 0,
        "current_unit_text": "",
        "current_unit_summary": None,
        "last_decision": None,
        "segment_agent_step": None,
        "segment_tool_context": "",
        "segment_tool_calls": 0,
    }


def summarize_current_chunk(state: SegmentationState, model) -> dict[str, object]:
    summary = model.invoke_structured(
        build_chunk_summary_prompt(state),
        ChunkSummary,
        system_prompt="You analyze long meeting transcripts and return concise structured summaries for chunk routing.",
    )
    return {"current_chunk_summary": summary.model_dump()}


def route_after_rule_gate(state: SegmentationState) -> str:
    return "route_finalize" if state["chunk_routing_decision"] is not None else "route_llm"


def route_llm_step(state: SegmentationState, model) -> dict[str, object]:
    step = model.invoke_structured(
        build_route_agent_prompt(state),
        ChunkRoutingAgentStep,
        system_prompt=chunk_routing_system_prompt(),
    )
    return {"route_agent_step": step.model_dump()}


def route_after_llm_step(state: SegmentationState) -> str:
    step = ChunkRoutingAgentStep.model_validate(state["route_agent_step"] or {})
    return "route_dispatch_tool" if step.action == "use_tool" else "route_finalize"


def route_dispatch_tool(state: SegmentationState) -> dict[str, object]:
    return {}


def route_after_tool_dispatch(state: SegmentationState) -> str:
    step = ChunkRoutingAgentStep.model_validate(state["route_agent_step"] or {})
    if step.tool_name == "read_chunk":
        return "route_read_chunk"
    if step.tool_name == "read_segment":
        return "route_read_segment"
    raise ValueError("route_dispatch_tool requires tool_name to be read_chunk or read_segment")


def route_read_chunk_node(state: SegmentationState) -> dict[str, object]:
    step = ChunkRoutingAgentStep.model_validate(state["route_agent_step"] or {})
    chunk_index = step.chunk_index if step.chunk_index is not None else state["current_chunk_index"]
    output = read_chunk_text(state, chunk_index, stage="route_chunk")
    return {
        "route_tool_context": append_tool_context(
            state["route_tool_context"],
            tool_name="read_chunk",
            arguments={"chunk_index": chunk_index},
            output=output,
        ),
        "route_tool_calls": state["route_tool_calls"] + 1,
        "route_agent_step": None,
    }


def route_read_segment_node(state: SegmentationState) -> dict[str, object]:
    step = ChunkRoutingAgentStep.model_validate(state["route_agent_step"] or {})
    if step.segment_index is None:
        raise ValueError("read_segment requires segment_index")
    output = read_segment_text(state, step.segment_index, stage="route_chunk")
    return {
        "route_tool_context": append_tool_context(
            state["route_tool_context"],
            tool_name="read_segment",
            arguments={"segment_index": step.segment_index},
            output=output,
        ),
        "route_tool_calls": state["route_tool_calls"] + 1,
        "route_agent_step": None,
    }


def route_finalize(state: SegmentationState) -> dict[str, object]:
    if state["chunk_routing_decision"] is not None:
        return {}

    step = ChunkRoutingAgentStep.model_validate(state["route_agent_step"] or {})
    decision = ChunkRoutingDecision(
        action=step.action,
        target_segment_index=step.target_segment_index,
        rationale=step.rationale,
        segment_title=step.segment_title,
    )
    return {"chunk_routing_decision": decision.model_dump(), "route_agent_step": None}


def create_route_chunk_subgraph(model):
    graph = StateGraph(SegmentationState)
    graph.add_node("route_rule_gate", route_rule_gate)
    graph.add_node("route_llm", lambda state: route_llm_step(state, model))
    graph.add_node("route_dispatch_tool", route_dispatch_tool)
    graph.add_node("route_read_chunk", route_read_chunk_node)
    graph.add_node("route_read_segment", route_read_segment_node)
    graph.add_node("route_finalize", route_finalize)

    graph.add_edge(START, "route_rule_gate")
    graph.add_conditional_edges(
        "route_rule_gate",
        route_after_rule_gate,
        {
            "route_llm": "route_llm",
            "route_finalize": "route_finalize",
        },
    )
    graph.add_conditional_edges(
        "route_llm",
        route_after_llm_step,
        {
            "route_dispatch_tool": "route_dispatch_tool",
            "route_finalize": "route_finalize",
        },
    )
    graph.add_conditional_edges(
        "route_dispatch_tool",
        route_after_tool_dispatch,
        {
            "route_read_chunk": "route_read_chunk",
            "route_read_segment": "route_read_segment",
        },
    )
    graph.add_edge("route_read_chunk", "route_llm")
    graph.add_edge("route_read_segment", "route_llm")
    graph.add_edge("route_finalize", END)
    return graph.compile()


def route_after_chunk_routing(state: SegmentationState) -> str:
    decision = ChunkRoutingDecision.model_validate(state["chunk_routing_decision"] or {})
    return "prepare_split_units" if decision.action == "split" else "prepare_whole_chunk"


def prepare_whole_chunk(state: SegmentationState) -> dict[str, object]:
    chunk_summary = ChunkSummary.model_validate(state["current_chunk_summary"] or {})
    routing = ChunkRoutingDecision.model_validate(state["chunk_routing_decision"] or {})
    segment_title = routing.segment_title or chunk_summary.short_title
    unit_summary = TextUnitSummary(
        short_title=segment_title,
        summary=chunk_summary.summary,
        topics=chunk_summary.topics,
    )
    decision = SegmentPlacementDecision(
        action="append" if routing.action == "append" else "new",
        target_segment_index=routing.target_segment_index,
        rationale=routing.rationale,
        segment_title=segment_title,
    )
    whole_text = state["current_chunk_text"].strip()
    return {
        "current_chunk_units": [whole_text],
        "current_unit_index": 0,
        "current_unit_text": whole_text,
        "current_unit_summary": unit_summary.model_dump(),
        "last_decision": decision.model_dump(),
        "segment_agent_step": None,
        "segment_tool_context": "",
        "segment_tool_calls": 0,
    }


def prepare_split_units(state: SegmentationState) -> dict[str, object]:
    chunk_summary = ChunkSummary.model_validate(state["current_chunk_summary"] or {})
    units = split_chunk_into_units(state["current_chunk_text"]) if chunk_summary.mixed_topic else [state["current_chunk_text"].strip()]
    first_unit = units[0].strip()

    initial_unit_summary: dict[str, object] | None = None
    if len(units) == 1:
        initial_unit_summary = TextUnitSummary(
            short_title=chunk_summary.short_title,
            summary=chunk_summary.summary,
            topics=chunk_summary.topics,
        ).model_dump()

    return {
        "current_chunk_units": units,
        "current_unit_index": 0,
        "current_unit_text": first_unit,
        "current_unit_summary": initial_unit_summary,
        "last_decision": None,
        "segment_agent_step": None,
        "segment_tool_context": "",
        "segment_tool_calls": 0,
    }


def summarize_current_unit(state: SegmentationState, model) -> dict[str, object]:
    if state["current_unit_summary"] is not None:
        return {}

    summary = model.invoke_structured(
        build_unit_summary_prompt(state),
        TextUnitSummary,
        system_prompt="You summarize one unit from a long meeting transcript for later semantic segmentation.",
    )
    return {"current_unit_summary": summary.model_dump()}


def route_after_unit_summary(state: SegmentationState) -> str:
    return "seed_first_segment" if not state["segments"] else "decide_segment"


def seed_first_segment(state: SegmentationState) -> dict[str, object]:
    unit_summary = TextUnitSummary.model_validate(state["current_unit_summary"] or {})
    decision = SegmentPlacementDecision(
        action="new",
        target_segment_index=None,
        rationale="The first unit seeds the first segment.",
        segment_title=unit_summary.short_title,
    )
    return {"last_decision": decision.model_dump()}


def segment_llm_step(state: SegmentationState, model) -> dict[str, object]:
    step = model.invoke_structured(
        build_segment_agent_prompt(state),
        SegmentPlacementAgentStep,
        system_prompt=decision_system_prompt(),
    )
    return {"segment_agent_step": step.model_dump()}


def segment_after_llm_step(state: SegmentationState) -> str:
    step = SegmentPlacementAgentStep.model_validate(state["segment_agent_step"] or {})
    return "segment_dispatch_tool" if step.action == "use_tool" else "segment_finalize"


def segment_dispatch_tool(state: SegmentationState) -> dict[str, object]:
    return {}


def segment_after_tool_dispatch(state: SegmentationState) -> str:
    step = SegmentPlacementAgentStep.model_validate(state["segment_agent_step"] or {})
    if step.tool_name == "read_chunk":
        return "segment_read_chunk"
    if step.tool_name == "read_segment":
        return "segment_read_segment"
    raise ValueError("segment_dispatch_tool requires tool_name to be read_chunk or read_segment")


def segment_read_chunk_node(state: SegmentationState) -> dict[str, object]:
    step = SegmentPlacementAgentStep.model_validate(state["segment_agent_step"] or {})
    chunk_index = step.chunk_index if step.chunk_index is not None else state["current_chunk_index"]
    output = read_chunk_text(state, chunk_index, stage="decide_segment")
    return {
        "segment_tool_context": append_tool_context(
            state["segment_tool_context"],
            tool_name="read_chunk",
            arguments={"chunk_index": chunk_index},
            output=output,
        ),
        "segment_tool_calls": state["segment_tool_calls"] + 1,
        "segment_agent_step": None,
    }


def segment_read_segment_node(state: SegmentationState) -> dict[str, object]:
    step = SegmentPlacementAgentStep.model_validate(state["segment_agent_step"] or {})
    if step.segment_index is None:
        raise ValueError("read_segment requires segment_index")
    output = read_segment_text(state, step.segment_index, stage="decide_segment")
    return {
        "segment_tool_context": append_tool_context(
            state["segment_tool_context"],
            tool_name="read_segment",
            arguments={"segment_index": step.segment_index},
            output=output,
        ),
        "segment_tool_calls": state["segment_tool_calls"] + 1,
        "segment_agent_step": None,
    }


def segment_finalize(state: SegmentationState) -> dict[str, object]:
    step = SegmentPlacementAgentStep.model_validate(state["segment_agent_step"] or {})
    decision = SegmentPlacementDecision(
        action=step.action,
        target_segment_index=step.target_segment_index,
        rationale=step.rationale,
        segment_title=step.segment_title,
    )
    return {"last_decision": decision.model_dump(), "segment_agent_step": None}


def create_segment_decision_subgraph(model):
    graph = StateGraph(SegmentationState)
    graph.add_node("segment_llm", lambda state: segment_llm_step(state, model))
    graph.add_node("segment_dispatch_tool", segment_dispatch_tool)
    graph.add_node("segment_read_chunk", segment_read_chunk_node)
    graph.add_node("segment_read_segment", segment_read_segment_node)
    graph.add_node("segment_finalize", segment_finalize)

    graph.add_edge(START, "segment_llm")
    graph.add_conditional_edges(
        "segment_llm",
        segment_after_llm_step,
        {
            "segment_dispatch_tool": "segment_dispatch_tool",
            "segment_finalize": "segment_finalize",
        },
    )
    graph.add_conditional_edges(
        "segment_dispatch_tool",
        segment_after_tool_dispatch,
        {
            "segment_read_chunk": "segment_read_chunk",
            "segment_read_segment": "segment_read_segment",
        },
    )
    graph.add_edge("segment_read_chunk", "segment_llm")
    graph.add_edge("segment_read_segment", "segment_llm")
    graph.add_edge("segment_finalize", END)
    return graph.compile()


def apply_decision_node(state: SegmentationState) -> dict[str, object]:
    decision = SegmentPlacementDecision.model_validate(state["last_decision"] or {})
    segments = apply_segment_decision(state, decision)
    return {"segments": segments}


def advance_cursor(state: SegmentationState) -> dict[str, object]:
    processed_chunk_summaries = list(state["processed_chunk_summaries"])
    if state["current_chunk_summary"] is not None:
        current_summary = ChunkSummary.model_validate(state["current_chunk_summary"])
        current_chunk_index = state["current_chunk_index"]
        if not any(item["chunk_index"] == current_chunk_index for item in processed_chunk_summaries):
            processed_chunk_summaries.append(
                {
                    "chunk_index": current_chunk_index,
                    "short_title": current_summary.short_title,
                    "summary": current_summary.summary,
                }
            )

    next_unit_index = state["current_unit_index"] + 1
    if next_unit_index < len(state["current_chunk_units"]):
        return {
            "current_unit_index": next_unit_index,
            "current_unit_text": state["current_chunk_units"][next_unit_index],
            "current_unit_summary": None,
            "last_decision": None,
            "segment_agent_step": None,
            "segment_tool_context": "",
            "segment_tool_calls": 0,
            "processed_chunk_summaries": processed_chunk_summaries,
        }

    next_chunk_index = state["current_chunk_index"] + 1
    done = next_chunk_index >= state["total_chunks"]
    return {
        "current_chunk_index": next_chunk_index,
        "current_chunk_units": [],
        "current_unit_index": 0,
        "current_unit_text": "",
        "current_unit_summary": None,
        "last_decision": None,
        "processed_chunk_summaries": processed_chunk_summaries,
        "route_agent_step": None,
        "route_tool_context": "",
        "route_tool_calls": 0,
        "segment_agent_step": None,
        "segment_tool_context": "",
        "segment_tool_calls": 0,
        "done": done,
    }


def route_after_advance(state: SegmentationState) -> str:
    if state["done"]:
        return END

    if state["current_chunk_units"] and state["current_unit_index"] < len(state["current_chunk_units"]):
        return "summarize_unit"

    return "load_chunk"


def create_iterative_segmentation_graph(model=None):
    model = model or build_default_chat_model()
    route_chunk_graph = create_route_chunk_subgraph(model)
    segment_decision_graph = create_segment_decision_subgraph(model)
    graph = StateGraph(SegmentationState)
    graph.add_node("load_chunk", load_current_chunk)
    graph.add_node("summarize_chunk", lambda state: summarize_current_chunk(state, model))
    graph.add_node("route_chunk", route_chunk_graph)
    graph.add_node("prepare_whole_chunk", prepare_whole_chunk)
    graph.add_node("prepare_split_units", prepare_split_units)
    graph.add_node("summarize_unit", lambda state: summarize_current_unit(state, model))
    graph.add_node("seed_first_segment", seed_first_segment)
    graph.add_node("decide_segment", segment_decision_graph)
    graph.add_node("apply_decision", apply_decision_node)
    graph.add_node("advance_cursor", advance_cursor)

    graph.add_edge(START, "load_chunk")
    graph.add_edge("load_chunk", "summarize_chunk")
    graph.add_edge("summarize_chunk", "route_chunk")
    graph.add_conditional_edges(
        "route_chunk",
        route_after_chunk_routing,
        {
            "prepare_whole_chunk": "prepare_whole_chunk",
            "prepare_split_units": "prepare_split_units",
        },
    )
    graph.add_edge("prepare_whole_chunk", "apply_decision")
    graph.add_edge("prepare_split_units", "summarize_unit")
    graph.add_conditional_edges(
        "summarize_unit",
        route_after_unit_summary,
        {
            "seed_first_segment": "seed_first_segment",
            "decide_segment": "decide_segment",
        },
    )
    graph.add_edge("seed_first_segment", "apply_decision")
    graph.add_edge("decide_segment", "apply_decision")
    graph.add_edge("apply_decision", "advance_cursor")
    graph.add_conditional_edges(
        "advance_cursor",
        route_after_advance,
        {
            "summarize_unit": "summarize_unit",
            "load_chunk": "load_chunk",
            END: END,
        },
    )

    return graph.compile()


def run_iterative_segmentation(
    chunk_dir: str | Path,
    *,
    model=None,
) -> dict[str, object]:
    chunk_paths = [str(path) for path in list_chunk_files(chunk_dir)]
    graph = create_iterative_segmentation_graph(model=model)
    initial_state: SegmentationState = {
        "chunk_paths": chunk_paths,
        "current_chunk_index": 0,
        "total_chunks": len(chunk_paths),
        "current_chunk_text": "",
        "current_chunk_summary": None,
        "processed_chunk_summaries": [],
        "chunk_routing_decision": None,
        "route_agent_step": None,
        "route_tool_context": "",
        "route_tool_calls": 0,
        "current_chunk_units": [],
        "current_unit_index": 0,
        "current_unit_text": "",
        "current_unit_summary": None,
        "segments": [],
        "last_decision": None,
        "segment_agent_step": None,
        "segment_tool_context": "",
        "segment_tool_calls": 0,
        "done": False,
    }
    return graph.invoke(initial_state)


def render_segments_markdown(result: dict[str, object]) -> str:
    segments = result.get("segments", [])
    lines = []
    for segment in segments:
        lines.append(f"## Segment {segment['index']}: {segment['title']}")
        lines.append(f"- chunks: {segment['chunk_indices']}")
        lines.append(f"- unit_refs: {segment.get('unit_refs', [])}")
        lines.append(f"- summary: {segment['summary']}")
        lines.append("")
        lines.append(segment.get("text", "").strip())
        lines.append("")
    return "\n".join(lines).strip()
