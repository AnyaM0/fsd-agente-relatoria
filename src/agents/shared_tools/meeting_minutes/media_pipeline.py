from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from audio_tools.azure import AzureBlobAudioStorage, transcribe_audio, transcript_to_continuous_text
from audio_tools.prepare_audio import run_audio_pipeline

DEFAULT_TRANSCRIPTION_TARGET_SR = 16_000


@dataclass(frozen=True)
class MediaTranscriptResult:
    media_path: str
    transcript: dict[str, Any]
    continuous_text: str
    transcript_json_path: str
    transcript_text_path: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_storage_manager() -> AzureBlobAudioStorage | None:
    try:
        return AzureBlobAudioStorage.from_env()
    except ValueError:
        return None


def transcribe_media_file(
    media_path: str | Path,
    *,
    transcript_json_path: str | Path,
    transcript_text_path: str | Path,
    cleanup_uploaded_blob: bool = True,
    target_sr: int = DEFAULT_TRANSCRIPTION_TARGET_SR,
) -> MediaTranscriptResult:
    resolved_media_path = Path(media_path).expanduser().resolve()
    audio, sample_rate = run_audio_pipeline(str(resolved_media_path), target_sr=target_sr)
    transcript = transcribe_audio(
        (audio, sample_rate),
        storage_manager=resolve_storage_manager(),
        cleanup_uploaded_blob=cleanup_uploaded_blob,
        route_filename=resolved_media_path.with_suffix(".wav").name,
    )
    continuous_text = transcript.get("continuous_text") or transcript_to_continuous_text(transcript)

    transcript_json = Path(transcript_json_path).expanduser().resolve()
    transcript_json.parent.mkdir(parents=True, exist_ok=True)
    transcript_json.write_text(
        json.dumps(transcript, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    transcript_text = Path(transcript_text_path).expanduser().resolve()
    transcript_text.parent.mkdir(parents=True, exist_ok=True)
    transcript_text.write_text(continuous_text, encoding="utf-8")

    return MediaTranscriptResult(
        media_path=str(resolved_media_path),
        transcript=transcript,
        continuous_text=continuous_text,
        transcript_json_path=str(transcript_json),
        transcript_text_path=str(transcript_text),
    )
