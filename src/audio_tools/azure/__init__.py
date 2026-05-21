"""Azure-related audio utilities."""

from audio_tools.azure.transcript import (
    batch_transcribe_azure_speech,
    fetch_batch_transcription_result,
    get_batch_transcription_status,
    resolve_transcription_route,
    submit_batch_transcription,
    transcript_to_continuous_text,
    transcribe_audio,
    transcribe_audio_file,
    use_fast_transcription_with_prompt,
)
from audio_tools.azure.upload_audio import AzureBlobAudioStorage, UploadedAudioBlob

__all__ = [
    "AzureBlobAudioStorage",
    "UploadedAudioBlob",
    "batch_transcribe_azure_speech",
    "fetch_batch_transcription_result",
    "get_batch_transcription_status",
    "resolve_transcription_route",
    "submit_batch_transcription",
    "transcript_to_continuous_text",
    "transcribe_audio",
    "transcribe_audio_file",
    "use_fast_transcription_with_prompt",
]
