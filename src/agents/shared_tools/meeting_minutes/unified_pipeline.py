from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal


MeetingDomain = Literal["compras", "juridica", "proyectos"]
MeetingInputSource = Literal["audio", "transcript", "chunks"]

SUPPORTED_MEETING_DOMAINS: tuple[MeetingDomain, ...] = ("compras", "juridica", "proyectos")


@dataclass(frozen=True)
class MeetingPipelineResult:
    domain: MeetingDomain
    input_source: MeetingInputSource
    variant: Literal["ppt_led", "chunk_led"]
    status: str
    output_dir: str
    audio_path: str | None
    transcript_path: str | None
    transcript_json_path: str | None
    ppt_path: str | None
    chunk_dir: str
    segmentation_result_path: str
    segmentation_markdown_path: str | None
    final_markdown_path: str
    final_json_path: str
    domain_result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _DomainAdapter:
    domain: MeetingDomain
    result_payload_attr: str
    runner: Callable[..., Any]


def list_supported_meeting_domains() -> tuple[MeetingDomain, ...]:
    return SUPPORTED_MEETING_DOMAINS


def resolve_meeting_input_source(
    *,
    audio_path: str | Path | None = None,
    transcript_path: str | Path | None = None,
    chunk_dir: str | Path | None = None,
    segmentation_result_path: str | Path | None = None,
) -> MeetingInputSource:
    if audio_path is not None:
        return "audio"
    if transcript_path is not None:
        return "transcript"
    if chunk_dir is not None and segmentation_result_path is not None:
        return "chunks"
    if chunk_dir is not None or segmentation_result_path is not None:
        raise ValueError("Provide both chunk_dir and segmentation_result_path together.")
    raise ValueError("Provide audio_path, transcript_path, or both chunk_dir and segmentation_result_path.")


def run_meeting_pipeline(
    *,
    domain: MeetingDomain,
    output_dir: str | Path,
    audio_path: str | Path | None = None,
    transcript_path: str | Path | None = None,
    ppt_path: str | Path | None = None,
    chunk_dir: str | Path | None = None,
    segmentation_result_path: str | Path | None = None,
    variant: str = "auto",
    max_themes: int = 6,
    max_revision_rounds: int = 2,
    chunk_max_tokens: int = 16_000,
    model=None,
) -> MeetingPipelineResult:
    adapter = _get_domain_adapter(domain)
    input_source = resolve_meeting_input_source(
        audio_path=audio_path,
        transcript_path=transcript_path,
        chunk_dir=chunk_dir,
        segmentation_result_path=segmentation_result_path,
    )

    result = adapter.runner(
        audio_path=audio_path,
        transcript_path=transcript_path,
        ppt_path=ppt_path,
        output_dir=output_dir,
        chunk_dir=chunk_dir,
        segmentation_result_path=segmentation_result_path,
        variant=variant,
        max_themes=max_themes,
        max_revision_rounds=max_revision_rounds,
        chunk_max_tokens=chunk_max_tokens,
        model=model,
    )
    normalized_output_dir = str(Path(result.output_dir).expanduser().resolve())
    segmentation_markdown_path = _infer_segmentation_markdown_path(result)

    return MeetingPipelineResult(
        domain=domain,
        input_source=input_source,
        variant=result.variant,
        status=result.status,
        output_dir=normalized_output_dir,
        audio_path=result.audio_path,
        transcript_path=result.transcript_path,
        transcript_json_path=result.transcript_json_path,
        ppt_path=result.ppt_path,
        chunk_dir=result.chunk_dir,
        segmentation_result_path=result.segmentation_result_path,
        segmentation_markdown_path=segmentation_markdown_path,
        final_markdown_path=result.acta_markdown_path,
        final_json_path=result.acta_json_path,
        domain_result=getattr(result, adapter.result_payload_attr),
    )


def _get_domain_adapter(domain: MeetingDomain) -> _DomainAdapter:
    if domain == "compras":
        return _DomainAdapter(
            domain="compras",
            result_payload_attr="approval_result",
            runner=_run_compras_pipeline,
        )
    if domain == "juridica":
        return _DomainAdapter(
            domain="juridica",
            result_payload_attr="juridica_result",
            runner=_run_juridica_pipeline,
        )
    if domain == "proyectos":
        return _DomainAdapter(
            domain="proyectos",
            result_payload_attr="proyectos_result",
            runner=_run_proyectos_pipeline,
        )
    supported = ", ".join(SUPPORTED_MEETING_DOMAINS)
    raise ValueError(f"Unsupported meeting domain: {domain}. Supported domains: {supported}.")


def _run_compras_pipeline(**kwargs):
    from agents.compras import run_compras_acta_graph

    return run_compras_acta_graph(**kwargs)


def _run_juridica_pipeline(**kwargs):
    from agents.juridica import run_juridica_acta_graph

    return run_juridica_acta_graph(**kwargs)


def _run_proyectos_pipeline(**kwargs):
    from agents.proyectos import run_proyectos_acta_graph

    return run_proyectos_acta_graph(**kwargs)


def _infer_segmentation_markdown_path(result: Any) -> str | None:
    explicit_path = getattr(result, "segmentation_markdown_path", None)
    if explicit_path:
        return explicit_path
    candidate = Path(result.output_dir).expanduser().resolve() / "segmentation_segments.md"
    if candidate.exists():
        return str(candidate)
    return None


__all__ = [
    "MeetingDomain",
    "MeetingInputSource",
    "MeetingPipelineResult",
    "SUPPORTED_MEETING_DOMAINS",
    "list_supported_meeting_domains",
    "resolve_meeting_input_source",
    "run_meeting_pipeline",
]
