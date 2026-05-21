from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.proyectos.llm import build_proyectos_chat_model
from agents.proyectos.minutes.assembler import assemble_acta, write_executive_summary
from agents.proyectos.minutes.assignment_planner import plan_writer_assignments
from agents.proyectos.minutes.chunk_io import load_chunk_contexts_with_segmentation
from agents.proyectos.minutes.models import (
    ClarificationRequest,
    FinalValidation,
    ProyectosMinutesRunResult,
    ProjectTopic,
    PPTContext,
    WriterAssignment,
    WriterDraft,
)
from agents.proyectos.minutes.ppt_context import convert_ppt_to_context, empty_ppt_context
from agents.proyectos.minutes.review_agent import review_writer_draft, validate_final_acta
from agents.proyectos.minutes.theme_discovery import discover_chunk_led_topics, discover_ppt_led_topics


class ProyectosMinutesGraphState(TypedDict, total=False):
    ppt_path: str | None
    chunk_dir: str
    segmentation_result_path: str
    variant: Literal["ppt_led", "chunk_led"]
    max_themes: int
    max_revision_rounds: int
    markdown_output_path: str | None
    model: Any
    ppt_context: PPTContext
    chunks: list[Any]
    themes: list[ProjectTopic]
    assignments: list[WriterAssignment]
    drafts_by_assignment: dict[str, WriterDraft]
    drafts: list[WriterDraft]
    clarification_requests: list[ClarificationRequest]
    current_review_requests: list[ClarificationRequest]
    current_review_round: int
    executive_summary: str
    acta_markdown: str
    final_validation: FinalValidation
    status: Literal["approved", "needs_review"]


def create_proyectos_minutes_graph():
    graph = StateGraph(ProyectosMinutesGraphState)
    graph.add_node("load_context", load_context)
    graph.add_node("discover_topics", discover_topics)
    graph.add_node("plan_assignments", plan_assignments_node)
    graph.add_node("write_drafts", write_drafts_node)
    graph.add_node("review_drafts", review_drafts_node)
    graph.add_node("revise_drafts", revise_drafts_node)
    graph.add_node("assemble_acta", assemble_acta_node)
    graph.add_node("validate_acta", validate_acta_node)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "discover_topics")
    graph.add_edge("discover_topics", "plan_assignments")
    graph.add_edge("plan_assignments", "write_drafts")
    graph.add_edge("write_drafts", "review_drafts")
    graph.add_conditional_edges(
        "review_drafts",
        route_after_review,
        {"revise_drafts": "revise_drafts", "assemble_acta": "assemble_acta"},
    )
    graph.add_edge("revise_drafts", "review_drafts")
    graph.add_edge("assemble_acta", "validate_acta")
    graph.add_edge("validate_acta", END)
    return graph.compile()


def run_proyectos_minutes_graph(
    *,
    ppt_path: str | Path | None = None,
    chunk_dir: str | Path,
    segmentation_result_path: str | Path,
    variant: str = "ppt_led",
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    model=None,
    markdown_output_path: str | Path | None = None,
) -> ProyectosMinutesRunResult:
    graph = create_proyectos_minutes_graph()
    resolved_ppt_path = None if ppt_path is None else str(Path(ppt_path).expanduser().resolve())
    resolved_variant = _resolve_variant(variant, has_ppt=resolved_ppt_path is not None)
    final_state = graph.invoke(
        {
            "ppt_path": resolved_ppt_path,
            "chunk_dir": str(Path(chunk_dir).expanduser().resolve()),
            "segmentation_result_path": str(Path(segmentation_result_path).expanduser().resolve()),
            "variant": resolved_variant,
            "max_themes": max_themes,
            "max_revision_rounds": max_revision_rounds,
            "model": model,
            "markdown_output_path": None if markdown_output_path is None else str(Path(markdown_output_path).expanduser().resolve()),
        }
    )
    return ProyectosMinutesRunResult(
        variant=final_state["variant"],
        status=final_state["status"],
        ppt_context=final_state["ppt_context"],
        chunks=final_state["chunks"],
        themes=final_state["themes"],
        assignments=final_state["assignments"],
        drafts=final_state["drafts"],
        clarification_requests=final_state["clarification_requests"],
        executive_summary=final_state["executive_summary"],
        acta_markdown=final_state["acta_markdown"],
        final_validation=final_state["final_validation"],
    )


def load_context(state: ProyectosMinutesGraphState) -> dict[str, object]:
    model = state.get("model") or build_proyectos_chat_model()
    if state.get("ppt_path"):
        ppt_context = convert_ppt_to_context(state["ppt_path"], markdown_output_path=state.get("markdown_output_path"))
    else:
        ppt_context = empty_ppt_context()
        if state.get("markdown_output_path") is not None:
            Path(state["markdown_output_path"]).expanduser().resolve().write_text("", encoding="utf-8")
    chunks = load_chunk_contexts_with_segmentation(
        state["chunk_dir"],
        segmentation_result_path=state["segmentation_result_path"],
    )
    return {
        "model": model,
        "ppt_context": ppt_context,
        "chunks": chunks,
        "clarification_requests": [],
        "current_review_requests": [],
        "current_review_round": 1,
    }


def discover_topics(state: ProyectosMinutesGraphState) -> dict[str, object]:
    if state["variant"] == "ppt_led":
        themes = discover_ppt_led_topics(state["ppt_context"], state["chunks"], state["model"], max_themes=state["max_themes"])
    else:
        themes = discover_chunk_led_topics(state["ppt_context"], state["chunks"], state["model"], max_themes=state["max_themes"])
    return {"themes": themes}


def plan_assignments_node(state: ProyectosMinutesGraphState) -> dict[str, object]:
    assignments = plan_writer_assignments(state["themes"], state["ppt_context"], state["chunks"], state["model"], variant=state["variant"])
    if not assignments:
        raise ValueError("No writer assignments could be planned for proyectos minutes.")
    return {"assignments": assignments}


def write_drafts_node(state: ProyectosMinutesGraphState) -> dict[str, object]:
    drafts_by_assignment: dict[str, WriterDraft] = {}
    from agents.proyectos.minutes.writer_agent import write_assignment_draft
    for assignment in state["assignments"]:
        drafts_by_assignment[assignment.assignment_id] = write_assignment_draft(
            assignment,
            state["chunks"],
            state["model"],
            variant=state["variant"],
        )
    return {"drafts_by_assignment": drafts_by_assignment, "current_review_requests": []}


def review_drafts_node(state: ProyectosMinutesGraphState) -> dict[str, object]:
    current_drafts = [state["drafts_by_assignment"][assignment.assignment_id] for assignment in state["assignments"]]
    requests: list[ClarificationRequest] = []
    for assignment in state["assignments"]:
        request = review_writer_draft(
            assignment,
            state["drafts_by_assignment"][assignment.assignment_id],
            current_drafts,
            state["ppt_context"],
            state["model"],
            variant=state["variant"],
            review_round=state["current_review_round"],
        )
        if request is not None:
            requests.append(request)
    return {
        "current_review_requests": requests,
        "clarification_requests": state["clarification_requests"] + requests,
    }


def route_after_review(state: ProyectosMinutesGraphState) -> str:
    if not state["current_review_requests"]:
        return "assemble_acta"
    if state["current_review_round"] < state["max_revision_rounds"]:
        return "revise_drafts"
    return "assemble_acta"


def revise_drafts_node(state: ProyectosMinutesGraphState) -> dict[str, object]:
    revised = dict(state["drafts_by_assignment"])
    from agents.proyectos.minutes.writer_agent import revise_assignment_draft
    request_map = {request.assignment_id: request for request in state["current_review_requests"]}
    for assignment in state["assignments"]:
        request = request_map.get(assignment.assignment_id)
        if request is None:
            continue
        revised[assignment.assignment_id] = revise_assignment_draft(
            assignment,
            revised[assignment.assignment_id],
            request,
            state["chunks"],
            state["model"],
            variant=state["variant"],
        )
    return {"drafts_by_assignment": revised, "current_review_round": state["current_review_round"] + 1}


def assemble_acta_node(state: ProyectosMinutesGraphState) -> dict[str, object]:
    unresolved = {request.assignment_id for request in state["current_review_requests"]}
    drafts: list[WriterDraft] = []
    for assignment in state["assignments"]:
        draft = state["drafts_by_assignment"][assignment.assignment_id]
        draft.status = "needs_revision" if assignment.assignment_id in unresolved else "approved"
        drafts.append(draft)
    executive_summary = write_executive_summary(drafts, state["themes"], state["model"])
    acta_markdown = assemble_acta(drafts, state["themes"], executive_summary, state["assignments"])
    return {"drafts": drafts, "executive_summary": executive_summary, "acta_markdown": acta_markdown}


def validate_acta_node(state: ProyectosMinutesGraphState) -> dict[str, object]:
    final_validation = validate_final_acta(state["acta_markdown"], state["ppt_context"], state["model"])
    unresolved = bool(state["current_review_requests"])
    status: Literal["approved", "needs_review"] = "approved" if final_validation.approved and not unresolved else "needs_review"
    return {"final_validation": final_validation, "status": status}


def _resolve_variant(variant: str, *, has_ppt: bool) -> Literal["ppt_led", "chunk_led"]:
    if variant == "auto":
        return "ppt_led" if has_ppt else "chunk_led"
    if variant == "ppt_led" and not has_ppt:
        return "chunk_led"
    return variant  # type: ignore[return-value]
