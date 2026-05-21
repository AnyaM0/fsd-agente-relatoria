"""
This module provides the pipeline for transcript processing using the azure Speech services and audio preprocessing.
"""
from typing import Any

from audio_tools.azure import AzureBlobAudioStorage, transcribe_audio
from audio_tools.prepare_audio import run_audio_pipeline


def _resolve_storage_manager() -> AzureBlobAudioStorage | None:
    try:
        return AzureBlobAudioStorage.from_env()
    except ValueError:
        return None

class TranscriptProcessPipeline:
    def __init__(self, audio_path: str):
        self.audio_path = audio_path

    def run(self) -> dict[str, Any]:
        audio, sr = run_audio_pipeline(self.audio_path)
        transcript = transcribe_audio(
            (audio, sr),
            storage_manager=_resolve_storage_manager(),
        )
        return transcript
