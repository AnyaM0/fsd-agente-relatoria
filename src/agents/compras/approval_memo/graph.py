from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.compras.approval_memo.assembler import assemble_approval_memo, write_executive_summary
from agents.compras.approval_memo.assignment_planner import plan_writer_assignments
from agents.compras.approval_memo.chunk_io import load_chunk_contexts_with_segmentation
from agents.compras.approval_memo.models import (
    ApprovalMemoRunResult,
    ApprovalTheme,
    ChunkContext,
    ClarificationRequest,
    FinalValidation,
    PPTContext,
    WriterAssignment,
    WriterDraft,
)
from agents.compras.approval_memo.ppt_context import convert_ppt_to_context, empty_ppt_context
from agents.compras.approval_memo.review_agent import review_writer_draft, validate_final_memo
from agents.compras.approval_memo.theme_discovery import (
    discover_chunk_led_themes,
    discover_ppt_led_themes,
)
from agents.compras.approval_memo.writer_agent import revise_assignment_draft, write_assignment_draft
from agents.compras.llm import build_compras_chat_model


class ApprovalMemoGraphState(TypedDict, total=False):
    ppt_path: str | None
    chunk_dir: str
    segmentation_result_path: str
    variant: Literal["ppt_led", "chunk_led"]
    max_themes: int
    max_revision_rounds: int
    markdown_output_path: str | None
    model: Any
    ppt_context: PPTContext
    chunks: list[ChunkContext]
    themes: list[ApprovalTheme]
    assignments: list[WriterAssignment]
    drafts_by_assignment: dict[str, WriterDraft]
    drafts: list[WriterDraft]
    clarification_requests: list[ClarificationRequest]
    current_review_requests: list[ClarificationRequest]
    current_review_round: int
    executive_summary: str
    approval_memo_markdown: str
    final_validation: FinalValidation
    status: Literal["approved", "needs_review"]


def create_approval_memo_graph():
    graph = StateGraph(ApprovalMemoGraphState)
    graph.add_node("load_context", load_context)
    graph.add_node("discover_themes", discover_themes)
    graph.add_node("plan_assignments", plan_assignments_node)
    graph.add_node("write_drafts", write_drafts_node)
    graph.add_node("review_drafts", review_drafts_node)
    graph.add_node("revise_drafts", revise_drafts_node)
    graph.add_node("assemble_memo", assemble_memo_node)
    graph.add_node("validate_memo", validate_memo_node)

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "discover_themes")
    graph.add_edge("discover_themes", "plan_assignments")
    graph.add_edge("plan_assignments", "write_drafts")
    graph.add_edge("write_drafts", "review_drafts")
    graph.add_conditional_edges(
        "review_drafts",
        route_after_review,
        {
            "revise_drafts": "revise_drafts",
            "assemble_memo": "assemble_memo",
        },
    )
    graph.add_edge("revise_drafts", "review_drafts")
    graph.add_edge("assemble_memo", "validate_memo")
    graph.add_edge("validate_memo", END)
    return graph.compile()


def run_approval_memo_graph(
    *,
    ppt_path: str | Path | None = None,
    chunk_dir: str | Path,
    segmentation_result_path: str | Path,
    variant: str = "ppt_led",
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    model=None,
    markdown_output_path: str | Path | None = None,
) -> ApprovalMemoRunResult:
    graph = create_approval_memo_graph()
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
    return ApprovalMemoRunResult(
        variant=final_state["variant"],
        status=final_state["status"],
        ppt_context=final_state["ppt_context"],
        chunks=final_state["chunks"],
        themes=final_state["themes"],
        assignments=final_state["assignments"],
        drafts=final_state["drafts"],
        clarification_requests=final_state["clarification_requests"],
        executive_summary=final_state["executive_summary"],
        approval_memo_markdown=final_state["approval_memo_markdown"],
        final_validation=final_state["final_validation"],
    )


def load_context(state: ApprovalMemoGraphState) -> dict[str, object]:
    llm = state.get("model") or build_compras_chat_model()
    markdown_output_path = state.get("markdown_output_path")
    if state.get("ppt_path"):
        ppt_context = convert_ppt_to_context(
            state["ppt_path"],
            markdown_output_path=markdown_output_path,
        )
    else:
        ppt_context = empty_ppt_context()
        if markdown_output_path is not None:
            Path(markdown_output_path).expanduser().resolve().write_text("", encoding="utf-8")
    chunks = load_chunk_contexts_with_segmentation(
        state["chunk_dir"],
        segmentation_result_path=state["segmentation_result_path"],
    )
    return {
        "model": llm,
        "ppt_context": ppt_context,
        "chunks": chunks,
        "clarification_requests": [],
        "current_review_requests": [],
        "current_review_round": 1,
    }


def discover_themes(state: ApprovalMemoGraphState) -> dict[str, object]:
    if state["variant"] == "ppt_led":
        themes = discover_ppt_led_themes(
            state["ppt_context"],
            state["chunks"],
            state["model"],
            max_themes=state["max_themes"],
        )
    else:
        themes = discover_chunk_led_themes(
            state["ppt_context"],
            state["chunks"],
            state["model"],
            max_themes=state["max_themes"],
        )
    return {"themes": themes}


def plan_assignments_node(state: ApprovalMemoGraphState) -> dict[str, object]:
    assignments = plan_writer_assignments(
        state["themes"],
        state["ppt_context"],
        state["chunks"],
        state["model"],
        variant=state["variant"],
    )
    if not assignments:
        raise ValueError("No writer assignments could be planned from the PPT and chunks.")
    return {"assignments": assignments}


def write_drafts_node(state: ApprovalMemoGraphState) -> dict[str, object]:
    drafts_by_assignment: dict[str, WriterDraft] = {}
    for assignment in state["assignments"]:
        drafts_by_assignment[assignment.assignment_id] = write_assignment_draft(
            assignment,
            state["chunks"],
            state["model"],
            variant=state["variant"],
        )
    return {
        "drafts_by_assignment": drafts_by_assignment,
        "current_review_requests": [],
    }


def review_drafts_node(state: ApprovalMemoGraphState) -> dict[str, object]:
    current_drafts = [state["drafts_by_assignment"][assignment.assignment_id] for assignment in state["assignments"]]
    round_requests: list[ClarificationRequest] = []
    for assignment in state["assignments"]:
        draft = state["drafts_by_assignment"][assignment.assignment_id]
        request = review_writer_draft(
            assignment,
            draft,
            current_drafts,
            state["ppt_context"],
            state["model"],
            variant=state["variant"],
            review_round=state["current_review_round"],
        )
        if request is not None:
            round_requests.append(request)
    return {
        "current_review_requests": round_requests,
        "clarification_requests": state["clarification_requests"] + round_requests,
    }


def route_after_review(state: ApprovalMemoGraphState) -> str:
    if not state["current_review_requests"]:
        return "assemble_memo"
    if state["current_review_round"] < state["max_revision_rounds"]:
        return "revise_drafts"
    return "assemble_memo"


def revise_drafts_node(state: ApprovalMemoGraphState) -> dict[str, object]:
    revised = dict(state["drafts_by_assignment"])
    request_by_assignment = {
        request.assignment_id: request for request in state["current_review_requests"]
    }
    for assignment in state["assignments"]:
        request = request_by_assignment.get(assignment.assignment_id)
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
    return {
        "drafts_by_assignment": revised,
        "current_review_round": state["current_review_round"] + 1,
    }


def assemble_memo_node(state: ApprovalMemoGraphState) -> dict[str, object]:
    unresolved_assignment_ids = {request.assignment_id for request in state["current_review_requests"]}
    drafts: list[WriterDraft] = []
    for assignment in state["assignments"]:
        draft = state["drafts_by_assignment"][assignment.assignment_id]
        draft.status = "needs_revision" if assignment.assignment_id in unresolved_assignment_ids else "approved"
        drafts.append(draft)

    executive_summary = write_executive_summary(drafts, state["themes"], state["model"])
    approval_memo_markdown = assemble_approval_memo(drafts, state["themes"], executive_summary)
    return {
        "drafts": drafts,
        "executive_summary": executive_summary,
        "approval_memo_markdown": approval_memo_markdown,
    }


def validate_memo_node(state: ApprovalMemoGraphState) -> dict[str, object]:
    final_validation = validate_final_memo(
        state["approval_memo_markdown"],
        state["ppt_context"],
        state["model"],
    )
    unresolved = bool(state["current_review_requests"])
    status: Literal["approved", "needs_review"] = (
        "approved" if final_validation.approved and not unresolved else "needs_review"
    )
    return {
        "final_validation": final_validation,
        "status": status,
    }


def _resolve_variant(variant: str, *, has_ppt: bool) -> Literal["ppt_led", "chunk_led"]:
    if variant == "auto":
        return "ppt_led" if has_ppt else "chunk_led"
    if variant == "ppt_led" and not has_ppt:
        return "chunk_led"
    return variant  # type: ignore[return-value]
