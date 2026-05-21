from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.compras.approval_memo import create_approval_memo_graph, write_approval_memo_outputs
from agents.compras.llm import build_compras_chat_model
from agents.shared_tools.meeting_minutes import transcribe_media_file
from agents.shared_tools.segmentation_agent.pipeline import (
    run_segmentation_pipeline_from_file,
    write_segmentation_outputs,
)


@dataclass(frozen=True)
class ComprasActaResult:
    variant: Literal["ppt_led", "chunk_led"]
    status: str
    audio_path: str | None
    transcript_path: str | None
    transcript_json_path: str | None
    ppt_path: str | None
    output_dir: str
    chunk_dir: str
    segmentation_result_path: str
    segmentation_markdown_path: str
    acta_markdown_path: str
    acta_json_path: str
    approval_result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComprasActaGraphState(TypedDict, total=False):
    audio_path: str
    transcript_path: str
    transcript_json_path: str
    ppt_path: str
    output_dir: str
    input_chunk_dir: str
    input_segmentation_result_path: str
    variant: Literal["ppt_led", "chunk_led"]
    max_themes: int
    max_revision_rounds: int
    chunk_max_tokens: int
    model: Any
    markdown_output_path: str
    transcript_output_path: str
    transcript_json_output_path: str
    chunk_dir: str
    segmentation_result_path: str
    segmentation_markdown_path: str
    segmentation_result: dict[str, Any]
    ppt_context: Any
    chunks: list[Any]
    themes: list[Any]
    assignments: list[Any]
    drafts_by_assignment: dict[str, Any]
    drafts: list[Any]
    clarification_requests: list[Any]
    current_review_requests: list[Any]
    current_review_round: int
    executive_summary: str
    approval_memo_markdown: str
    final_validation: Any
    approval_result: dict[str, Any]
    output_paths: dict[str, str]
    status: str


def create_compras_acta_graph():
    graph = StateGraph(ComprasActaGraphState)
    graph.add_node("prepare_run", prepare_run)
    graph.add_node("transcribe_media", transcribe_media_node)
    graph.add_node("segmentation", create_segmentation_subgraph())
    graph.add_node("approval_memo", create_approval_memo_graph())
    graph.add_node("capture_approval_result", capture_approval_result)
    graph.add_node("persist_result", persist_result)

    graph.add_edge(START, "prepare_run")
    graph.add_conditional_edges(
        "prepare_run",
        route_after_prepare,
        {
            "transcribe_media": "transcribe_media",
            "segmentation": "segmentation",
            "approval_memo": "approval_memo",
        },
    )
    graph.add_edge("transcribe_media", "segmentation")
    graph.add_edge("segmentation", "approval_memo")
    graph.add_edge("approval_memo", "capture_approval_result")
    graph.add_edge("capture_approval_result", "persist_result")
    graph.add_edge("persist_result", END)
    return graph.compile()


def run_compras_acta_graph(
    *,
    audio_path: str | Path | None = None,
    transcript_path: str | Path | None = None,
    ppt_path: str | Path | None = None,
    output_dir: str | Path,
    chunk_dir: str | Path | None = None,
    segmentation_result_path: str | Path | None = None,
    variant: str = "auto",
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    chunk_max_tokens: int = 16_000,
    model=None,
) -> ComprasActaResult:
    graph = create_compras_acta_graph()
    if audio_path is None and transcript_path is None and (chunk_dir is None or segmentation_result_path is None):
        raise ValueError("Provide audio_path, transcript_path, or both chunk_dir and segmentation_result_path.")
    final_state = graph.invoke(
        {
            "audio_path": None if audio_path is None else str(Path(audio_path).expanduser().resolve()),
            "transcript_path": None if transcript_path is None else str(Path(transcript_path).expanduser().resolve()),
            "ppt_path": None if ppt_path is None else str(Path(ppt_path).expanduser().resolve()),
            "output_dir": str(Path(output_dir).expanduser().resolve()),
            "input_chunk_dir": None if chunk_dir is None else str(Path(chunk_dir).expanduser().resolve()),
            "input_segmentation_result_path": None
            if segmentation_result_path is None
            else str(Path(segmentation_result_path).expanduser().resolve()),
            "variant": variant,
            "max_themes": max_themes,
            "max_revision_rounds": max_revision_rounds,
            "chunk_max_tokens": chunk_max_tokens,
            "model": model,
        }
    )
    output_paths = final_state["output_paths"]
    return ComprasActaResult(
        variant=final_state["variant"],
        status=final_state["status"],
        audio_path=final_state.get("audio_path"),
        transcript_path=final_state["transcript_path"],
        transcript_json_path=final_state.get("transcript_json_path"),
        ppt_path=final_state.get("ppt_path"),
        output_dir=final_state["output_dir"],
        chunk_dir=final_state["chunk_dir"],
        segmentation_result_path=final_state["segmentation_result_path"],
        segmentation_markdown_path=final_state["segmentation_markdown_path"],
        acta_markdown_path=output_paths["acta_markdown"],
        acta_json_path=output_paths["acta_json"],
        approval_result=final_state["approval_result"],
    )


def prepare_run(state: ComprasActaGraphState) -> dict[str, object]:
    output_dir = Path(state["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    model = state.get("model") or build_compras_chat_model()
    chunk_dir = output_dir / "chunks"
    segmentation_result_path = output_dir / "segmentation_segments.json"
    segmentation_markdown_path = output_dir / "segmentation_segments.md"
    transcript_output_path = output_dir / "transcript.txt"
    transcript_json_output_path = output_dir / "transcript.json"
    input_chunk_dir = state.get("input_chunk_dir")
    input_segmentation_result_path = state.get("input_segmentation_result_path")
    resolved_variant = _resolve_variant(state.get("variant", "auto"), has_ppt=bool(state.get("ppt_path")))
    if input_chunk_dir and input_segmentation_result_path:
        return {
            "model": model,
            "variant": resolved_variant,
            "markdown_output_path": str(output_dir / "ppt_context.md"),
            "chunk_dir": input_chunk_dir,
            "segmentation_result_path": input_segmentation_result_path,
            "segmentation_markdown_path": str(segmentation_markdown_path),
        }
    return {
        "model": model,
        "variant": resolved_variant,
        "markdown_output_path": str(output_dir / "ppt_context.md"),
        "transcript_output_path": str(transcript_output_path),
        "transcript_json_output_path": str(transcript_json_output_path),
        "chunk_dir": str(chunk_dir),
        "segmentation_result_path": str(segmentation_result_path),
        "segmentation_markdown_path": str(segmentation_markdown_path),
    }


def route_after_prepare(state: ComprasActaGraphState) -> str:
    if state.get("audio_path"):
        return "transcribe_media"
    if state.get("transcript_path"):
        return "segmentation"
    return "approval_memo"


def transcribe_media_node(state: ComprasActaGraphState) -> dict[str, object]:
    result = transcribe_media_file(
        state["audio_path"],
        transcript_json_path=state["transcript_json_output_path"],
        transcript_text_path=state["transcript_output_path"],
    )
    return {
        "transcript_path": result.transcript_text_path,
        "transcript_json_path": result.transcript_json_path,
    }


def create_segmentation_subgraph():
    graph = StateGraph(ComprasActaGraphState)
    graph.add_node("run_segmentation_pipeline", run_segmentation_pipeline_node)
    graph.add_edge(START, "run_segmentation_pipeline")
    graph.add_edge("run_segmentation_pipeline", END)
    return graph.compile()


def run_segmentation_pipeline_node(state: ComprasActaGraphState) -> dict[str, object]:
    segmentation_result = run_segmentation_pipeline_from_file(
        state["transcript_path"],
        chunks_output_dir=state["chunk_dir"],
        max_tokens=state["chunk_max_tokens"],
        model=state["model"],
    )
    write_segmentation_outputs(
        segmentation_result,
        json_output=state["segmentation_result_path"],
        markdown_output=state["segmentation_markdown_path"],
    )
    return {
        "segmentation_result": segmentation_result.result,
    }


def capture_approval_result(state: ComprasActaGraphState) -> dict[str, object]:
    approval_result = {
        "variant": state["variant"],
        "status": state["status"],
        "ppt_context": state["ppt_context"].as_dict(),
        "chunks": [chunk.as_dict() for chunk in state["chunks"]],
        "themes": [theme.as_dict() for theme in state["themes"]],
        "assignments": [assignment.as_dict() for assignment in state["assignments"]],
        "drafts": [draft.as_dict() for draft in state["drafts"]],
        "clarification_requests": [request.as_dict() for request in state["clarification_requests"]],
        "executive_summary": state["executive_summary"],
        "approval_memo_markdown": state["approval_memo_markdown"],
        "final_validation": state["final_validation"].as_dict(),
    }
    return {"approval_result": approval_result}


def persist_result(state: ComprasActaGraphState) -> dict[str, object]:
    output_dir = Path(state["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    class _ApprovalResultProxy:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def __getattr__(self, name: str):
            value = self._payload[name]
            if name in {"ppt_context", "final_validation"} and isinstance(value, dict):
                return _DictProxy(value)
            if name in {"chunks", "themes", "assignments", "drafts", "clarification_requests"}:
                return [_DictProxy(item) for item in value]
            return value

        def as_dict(self) -> dict[str, Any]:
            return self._payload

    class _DictProxy:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def __getattr__(self, name: str):
            return self._payload[name]

        def as_dict(self) -> dict[str, Any]:
            return self._payload

    proxy = _ApprovalResultProxy(state["approval_result"])
    memo_paths = write_approval_memo_outputs(proxy, output_dir=output_dir)

    acta_markdown_path = output_dir / "acta_final.md"
    acta_markdown_path.write_text(proxy.approval_memo_markdown, encoding="utf-8")

    acta_json_path = output_dir / "acta_final.json"
    acta_json_path.write_text(json.dumps(proxy.as_dict(), ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "output_paths": {
            "acta_markdown": str(acta_markdown_path),
            "acta_json": str(acta_json_path),
            **memo_paths,
        }
    }


def _resolve_variant(variant: str, *, has_ppt: bool) -> Literal["ppt_led", "chunk_led"]:
    if variant == "auto":
        return "ppt_led" if has_ppt else "chunk_led"
    if variant == "ppt_led" and not has_ppt:
        return "chunk_led"
    return variant  # type: ignore[return-value]
