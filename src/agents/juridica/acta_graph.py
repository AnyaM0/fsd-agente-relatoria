from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.juridica.llm import build_juridica_chat_model
from agents.juridica.minutes import create_juridica_minutes_graph, write_juridica_minutes_outputs
from agents.shared_tools.meeting_minutes import transcribe_media_file
from agents.shared_tools.segmentation_agent.pipeline import run_segmentation_pipeline_from_file, write_segmentation_outputs


@dataclass(frozen=True)
class JuridicaActaResult:
    variant: Literal["ppt_led", "chunk_led"]
    status: str
    audio_path: str | None
    transcript_path: str | None
    transcript_json_path: str | None
    ppt_path: str | None
    output_dir: str
    chunk_dir: str
    segmentation_result_path: str
    acta_markdown_path: str
    acta_json_path: str
    juridica_result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class JuridicaActaGraphState(TypedDict, total=False):
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
    juridica_result: dict[str, Any]
    output_paths: dict[str, str]
    status: str
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
    acta_markdown: str
    final_validation: Any


def create_juridica_acta_graph():
    graph = StateGraph(JuridicaActaGraphState)
    graph.add_node("prepare_run", prepare_run)
    graph.add_node("transcribe_media", transcribe_media_node)
    graph.add_node("segmentation", create_segmentation_subgraph())
    graph.add_node("juridica_minutes", create_juridica_minutes_graph())
    graph.add_node("capture_juridica_result", capture_juridica_result)
    graph.add_node("persist_result", persist_result)

    graph.add_edge(START, "prepare_run")
    graph.add_conditional_edges("prepare_run", route_after_prepare, {"transcribe_media": "transcribe_media", "segmentation": "segmentation", "juridica_minutes": "juridica_minutes"})
    graph.add_edge("transcribe_media", "segmentation")
    graph.add_edge("segmentation", "juridica_minutes")
    graph.add_edge("juridica_minutes", "capture_juridica_result")
    graph.add_edge("capture_juridica_result", "persist_result")
    graph.add_edge("persist_result", END)
    return graph.compile()


def run_juridica_acta_graph(
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
) -> JuridicaActaResult:
    graph = create_juridica_acta_graph()
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
    return JuridicaActaResult(
        variant=final_state["variant"],
        status=final_state["status"],
        audio_path=final_state.get("audio_path"),
        transcript_path=final_state["transcript_path"],
        transcript_json_path=final_state.get("transcript_json_path"),
        ppt_path=final_state.get("ppt_path"),
        output_dir=final_state["output_dir"],
        chunk_dir=final_state["chunk_dir"],
        segmentation_result_path=final_state["segmentation_result_path"],
        acta_markdown_path=output_paths["acta_markdown"],
        acta_json_path=output_paths["acta_json"],
        juridica_result=final_state["juridica_result"],
    )


def prepare_run(state: JuridicaActaGraphState) -> dict[str, object]:
    output_dir = Path(state["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    model = state.get("model") or build_juridica_chat_model()
    resolved_variant = _resolve_variant(state.get("variant", "auto"), has_ppt=bool(state.get("ppt_path")))
    input_chunk_dir = state.get("input_chunk_dir")
    input_segmentation_result_path = state.get("input_segmentation_result_path")
    if input_chunk_dir and input_segmentation_result_path:
        return {
            "model": model,
            "variant": resolved_variant,
            "markdown_output_path": str(output_dir / "ppt_context.md"),
            "chunk_dir": input_chunk_dir,
            "segmentation_result_path": input_segmentation_result_path,
            "segmentation_markdown_path": str(output_dir / "segmentation_segments.md"),
        }
    return {
        "model": model,
        "variant": resolved_variant,
        "markdown_output_path": str(output_dir / "ppt_context.md"),
        "transcript_output_path": str(output_dir / "transcript.txt"),
        "transcript_json_output_path": str(output_dir / "transcript.json"),
        "chunk_dir": str(output_dir / "chunks"),
        "segmentation_result_path": str(output_dir / "segmentation_segments.json"),
        "segmentation_markdown_path": str(output_dir / "segmentation_segments.md"),
    }


def route_after_prepare(state: JuridicaActaGraphState) -> str:
    if state.get("audio_path"):
        return "transcribe_media"
    if state.get("transcript_path"):
        return "segmentation"
    return "juridica_minutes"


def transcribe_media_node(state: JuridicaActaGraphState) -> dict[str, object]:
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
    graph = StateGraph(JuridicaActaGraphState)
    graph.add_node("run_segmentation_pipeline", run_segmentation_pipeline_node)
    graph.add_edge(START, "run_segmentation_pipeline")
    graph.add_edge("run_segmentation_pipeline", END)
    return graph.compile()


def run_segmentation_pipeline_node(state: JuridicaActaGraphState) -> dict[str, object]:
    result = run_segmentation_pipeline_from_file(
        state["transcript_path"],
        chunks_output_dir=state["chunk_dir"],
        max_tokens=state["chunk_max_tokens"],
        model=state["model"],
    )
    write_segmentation_outputs(result, json_output=state["segmentation_result_path"], markdown_output=state["segmentation_markdown_path"])
    return {}


def capture_juridica_result(state: JuridicaActaGraphState) -> dict[str, object]:
    juridica_result = {
        "variant": state["variant"],
        "status": state["status"],
        "ppt_context": state["ppt_context"].as_dict(),
        "chunks": [item.as_dict() for item in state["chunks"]],
        "themes": [item.as_dict() for item in state["themes"]],
        "assignments": [item.as_dict() for item in state["assignments"]],
        "drafts": [item.as_dict() for item in state["drafts"]],
        "clarification_requests": [item.as_dict() for item in state["clarification_requests"]],
        "executive_summary": state["executive_summary"],
        "acta_markdown": state["acta_markdown"],
        "final_validation": state["final_validation"].as_dict(),
    }
    return {"juridica_result": juridica_result}


def persist_result(state: JuridicaActaGraphState) -> dict[str, object]:
    output_dir = Path(state["output_dir"]).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    class _DictProxy:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def __getattr__(self, name: str):
            value = self._payload[name]
            if isinstance(value, dict):
                return _DictProxy(value)
            if isinstance(value, list):
                return [_DictProxy(item) if isinstance(item, dict) else item for item in value]
            return value

        def as_dict(self) -> dict[str, Any]:
            return self._payload

    proxy = _DictProxy(state["juridica_result"])
    paths = write_juridica_minutes_outputs(proxy, output_dir=output_dir)

    acta_json_path = output_dir / "acta_juridica_final.json"
    acta_json_path.write_text(json.dumps(proxy.as_dict(), ensure_ascii=True, indent=2), encoding="utf-8")
    acta_markdown_path = output_dir / "acta_juridica_final.md"
    acta_markdown_path.write_text(proxy.acta_markdown, encoding="utf-8")

    return {"output_paths": {"acta_json": str(acta_json_path), "acta_markdown": str(acta_markdown_path), **paths}}


def _resolve_variant(variant: str, *, has_ppt: bool) -> Literal["ppt_led", "chunk_led"]:
    if variant == "auto":
        return "ppt_led" if has_ppt else "chunk_led"
    if variant == "ppt_led" and not has_ppt:
        return "chunk_led"
    return variant  # type: ignore[return-value]
