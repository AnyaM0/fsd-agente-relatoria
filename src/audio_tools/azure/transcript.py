from __future__ import annotations

import io
import os
import re
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np
import requests
import soundfile as sf
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import (
    EnhancedModeProperties,
    PhraseListProperties,
    ProfanityFilterMode,
    TranscriptionContent,
    TranscriptionDiarizationOptions,
    TranscriptionOptions,
)
from azure.core.credentials import AccessToken, AzureKeyCredential, TokenCredential
from azure.identity import DefaultAzureCredential
from numpy.typing import NDArray

from audio_tools.azure.upload_audio import AzureBlobAudioStorage, UploadedAudioBlob

DEFAULT_SPEECH_REGION = "eastus2"
DEFAULT_LOCALE = "es-CO"
DEFAULT_PROMPTS = [
    "This audio is from a committee meeting.",
    "Focus on committee-relevant information and ignore off-topic social chatter.",
    "Represent monetary values, codes, and identifiers in numeric form whenever possible.",
    "The spoken language is Colombian Spanish.",
]
FAST_MAX_DURATION_SECONDS = 2 * 60 * 60
FAST_MAX_FILE_SIZE_BYTES = 300 * 1024 * 1024
BATCH_MAX_FILE_SIZE_BYTES = 1024 * 1024 * 1024

PreparedAudioInput = tuple[NDArray[np.float32], int]


@dataclass(frozen=True)
class AudioPayload:
    source_kind: str
    file_path: Path | None
    filename: str
    duration_seconds: float
    size_bytes: int
    audio_bytes: bytes | None
    sample_rate: int | None
    channels: int


@dataclass(frozen=True)
class SubmittedBatchTranscription:
    transcription_id: str
    transcription_url: str
    submitted_at: str | None
    status: str | None
    display_name: str
    locale: str


def _normalize_speech_endpoint(
    endpoint: str | None = None,
    speech_region: str | None = None,
) -> str:
    if endpoint:
        return endpoint.rstrip("/")

    region = speech_region or os.getenv("AZURE_SPEECH_REGION") or DEFAULT_SPEECH_REGION
    return f"https://{region}.api.cognitive.microsoft.com"


def _build_credential(
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
) -> TokenCredential | AzureKeyCredential:
    if credential is not None:
        return credential

    resolved_api_key = api_key or os.getenv("AZURE_SPEECH_API_KEY")
    if resolved_api_key:
        return AzureKeyCredential(resolved_api_key)

    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def _resolve_audio_file(audio_file: str | Path) -> Path:
    path = Path(audio_file).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Audio path must be a file: {path}")
    return path


def _normalize_waveform(audio: NDArray[np.floating[Any]]) -> NDArray[np.float32]:
    waveform = np.asarray(audio, dtype=np.float32)

    if waveform.ndim == 1:
        return waveform

    if waveform.ndim != 2:
        raise ValueError("Audio ndarray must be 1D or 2D.")

    if waveform.shape[0] <= 8 < waveform.shape[1]:
        waveform = waveform.T
    elif waveform.shape[1] <= 8:
        waveform = waveform
    else:
        raise ValueError(
            "2D audio ndarray must have an identifiable channel dimension (<= 8 channels)."
        )

    return np.ascontiguousarray(waveform, dtype=np.float32)


def float32_ndarray_to_wav_bytes(audio: NDArray[np.floating[Any]], sample_rate: int) -> bytes:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be greater than zero.")

    waveform = _normalize_waveform(audio)
    waveform = np.clip(waveform, -1.0, 1.0)
    pcm16 = (waveform * 32767.0).astype(np.int16)

    n_channels = 1 if pcm16.ndim == 1 else pcm16.shape[1]
    frames = pcm16.tobytes()

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(n_channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)

    return buffer.getvalue()


def _build_audio_payload(
    audio_source: str | Path | NDArray[np.floating[Any]] | PreparedAudioInput,
    sample_rate: int | None = None,
    *,
    filename: str = "prepared-audio.wav",
) -> AudioPayload:
    if isinstance(audio_source, tuple):
        if len(audio_source) != 2 or not isinstance(audio_source[0], np.ndarray):
            raise TypeError("Prepared audio tuples must look like (np.ndarray, sample_rate).")
        if sample_rate is not None and sample_rate != int(audio_source[1]):
            raise ValueError("sample_rate conflicts with the rate inside the prepared audio tuple.")
        audio_source, sample_rate = audio_source[0], int(audio_source[1])

    if isinstance(audio_source, np.ndarray):
        if sample_rate is None:
            raise ValueError("sample_rate is required when audio_source is a numpy array.")

        waveform = _normalize_waveform(audio_source)
        wav_bytes = float32_ndarray_to_wav_bytes(waveform, sample_rate)
        channels = 1 if waveform.ndim == 1 else waveform.shape[1]
        duration_seconds = float(waveform.shape[0]) / float(sample_rate)

        return AudioPayload(
            source_kind="ndarray",
            file_path=None,
            filename=filename if filename.lower().endswith(".wav") else f"{filename}.wav",
            duration_seconds=duration_seconds,
            size_bytes=len(wav_bytes),
            audio_bytes=wav_bytes,
            sample_rate=sample_rate,
            channels=channels,
        )

    path = _resolve_audio_file(audio_source)
    info = sf.info(path)
    duration_seconds = float(info.frames) / float(info.samplerate)

    return AudioPayload(
        source_kind="file",
        file_path=path,
        filename=path.name,
        duration_seconds=duration_seconds,
        size_bytes=path.stat().st_size,
        audio_bytes=None,
        sample_rate=info.samplerate,
        channels=info.channels,
    )


def _build_transcription_options(
    *,
    locales: Sequence[str] | None = None,
    prompt: Sequence[str] | None = None,
    phrase_list: Sequence[str] | None = None,
    diarization_max_speakers: int | None = None,
    active_channels: Sequence[int] | None = None,
    profanity_filter_mode: str | ProfanityFilterMode = ProfanityFilterMode.MASKED,
) -> TranscriptionOptions:
    options = TranscriptionOptions(
        locales=list(locales) if locales else [DEFAULT_LOCALE],
        profanity_filter_mode=profanity_filter_mode,
    )

    if active_channels is not None:
        options.active_channels = list(active_channels)

    if prompt:
        options.enhanced_mode = EnhancedModeProperties(
            task="transcribe",
            prompt=list(prompt),
        )

    if phrase_list:
        options.phrase_list = PhraseListProperties(
            phrases=list(phrase_list),
            biasing_weight=1.5,
        )

    if diarization_max_speakers is not None:
        options.diarization_options = TranscriptionDiarizationOptions(
            enabled=True,
            max_speakers=diarization_max_speakers,
        )

    return options


def _serialize_transcription_result(result: Any) -> dict[str, Any]:
    combined_phrases = [
        {
            "channel": getattr(item, "channel", None),
            "text": getattr(item, "text", ""),
        }
        for item in getattr(result, "combined_phrases", []) or []
    ]

    phrases = []
    for item in getattr(result, "phrases", []) or []:
        words = [
            {
                "text": getattr(word, "text", ""),
                "offset_milliseconds": getattr(word, "offset_milliseconds", None),
                "duration_milliseconds": getattr(word, "duration_milliseconds", None),
            }
            for word in getattr(item, "words", []) or []
        ]

        phrases.append(
            {
                "channel": getattr(item, "channel", None),
                "speaker": getattr(item, "speaker", None),
                "locale": getattr(item, "locale", None),
                "offset_milliseconds": getattr(item, "offset_milliseconds", None),
                "duration_milliseconds": getattr(item, "duration_milliseconds", None),
                "confidence": getattr(item, "confidence", None),
                "text": getattr(item, "text", ""),
                "words": words,
            }
        )

    return {
        "text": " ".join(item["text"] for item in combined_phrases if item["text"]).strip(),
        "duration_milliseconds": getattr(result, "duration_milliseconds", None),
        "combined_phrases": combined_phrases,
        "phrases": phrases,
        "raw": result.as_dict() if hasattr(result, "as_dict") else result,
    }


def _normalize_continuous_text(*parts: str) -> str:
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return " ".join(text.split())


def transcript_to_continuous_text(transcript: dict[str, Any]) -> str:
    if not transcript:
        return ""

    text = _normalize_continuous_text(str(transcript.get("text", "")))
    if text:
        return text

    combined_phrases = transcript.get("combined_phrases") or []
    text = _normalize_continuous_text(
        *(str(item.get("text", "")) for item in combined_phrases if isinstance(item, dict))
    )
    if text:
        return text

    phrases = transcript.get("phrases") or []
    text = _normalize_continuous_text(
        *(str(item.get("text", "")) for item in phrases if isinstance(item, dict))
    )
    if text:
        return text

    transcriptions = transcript.get("transcriptions") or []
    collected_parts: list[str] = []
    for item in transcriptions:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, dict):
            continue

        combined_recognized = content.get("combinedRecognizedPhrases") or []
        combined_text = _normalize_continuous_text(
            *(
                str(
                    phrase.get("display")
                    or phrase.get("itn")
                    or phrase.get("lexical")
                    or ""
                )
                for phrase in combined_recognized
                if isinstance(phrase, dict)
            )
        )
        if combined_text:
            collected_parts.append(combined_text)
            continue

        recognized = content.get("recognizedPhrases") or []
        recognized_text = _normalize_continuous_text(
            *(
                str(
                    phrase.get("nBest", [{}])[0].get("display")
                    if isinstance(phrase.get("nBest"), list) and phrase.get("nBest")
                    else phrase.get("display", "")
                )
                for phrase in recognized
                if isinstance(phrase, dict)
            )
        )
        if recognized_text:
            collected_parts.append(recognized_text)

    return _normalize_continuous_text(*collected_parts)


def _attach_continuous_text(transcript: dict[str, Any]) -> dict[str, Any]:
    continuous_text = transcript_to_continuous_text(transcript)
    transcript["continuous_text"] = continuous_text
    if not transcript.get("text"):
        transcript["text"] = continuous_text
    return transcript


def _fast_route_allowed(payload: AudioPayload) -> bool:
    return (
        payload.duration_seconds < FAST_MAX_DURATION_SECONDS
        and payload.size_bytes <= FAST_MAX_FILE_SIZE_BYTES
    )


def _payload_route(payload: AudioPayload) -> str:
    return "fast" if _fast_route_allowed(payload) else "batch"


def _upload_payload(
    payload: AudioPayload,
    *,
    storage_manager: AzureBlobAudioStorage,
    sas_expiry_seconds: int,
) -> UploadedAudioBlob:
    if payload.file_path is not None:
        return storage_manager.upload_audio_file(
            payload.file_path,
            sas_expiry_seconds=sas_expiry_seconds,
        )

    if payload.audio_bytes is None:
        raise ValueError("In-memory audio payload is missing audio bytes.")

    return storage_manager.upload_audio_bytes(
        payload.audio_bytes,
        filename=payload.filename,
        sas_expiry_seconds=sas_expiry_seconds,
    )


def _transcribe_fast_payload(
    payload: AudioPayload,
    *,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    locales: Sequence[str] | None = None,
    prompt: Sequence[str] | None = None,
    phrase_list: Sequence[str] | None = None,
    diarization_max_speakers: int | None = None,
    active_channels: Sequence[int] | None = None,
    profanity_filter_mode: str | ProfanityFilterMode = ProfanityFilterMode.MASKED,
) -> dict[str, Any]:
    speech_endpoint = _normalize_speech_endpoint(endpoint, speech_region)
    resolved_credential = _build_credential(credential, api_key)
    options = _build_transcription_options(
        locales=locales,
        prompt=prompt,
        phrase_list=phrase_list,
        diarization_max_speakers=diarization_max_speakers,
        active_channels=active_channels,
        profanity_filter_mode=profanity_filter_mode,
    )

    client = TranscriptionClient(
        endpoint=speech_endpoint,
        credential=resolved_credential,
    )

    try:
        if payload.file_path is not None:
            with payload.file_path.open("rb") as audio_stream:
                request_content = TranscriptionContent(definition=options, audio=audio_stream)
                result = client.transcribe(request_content)
        else:
            request_audio = (payload.filename, io.BytesIO(payload.audio_bytes or b""), "audio/wav")
            request_content = TranscriptionContent(definition=options, audio=request_audio)
            result = client.transcribe(request_content)
    finally:
        client.close()

    response = _serialize_transcription_result(result)
    response.update(
        {
            "mode": "fast",
            "audio_file": str(payload.file_path) if payload.file_path else None,
            "audio_filename": payload.filename,
            "duration_seconds": payload.duration_seconds,
            "size_bytes": payload.size_bytes,
            "sample_rate": payload.sample_rate,
            "channels": payload.channels,
        }
    )
    return _attach_continuous_text(response)


def _build_auth_headers(
    credential: TokenCredential | AzureKeyCredential,
) -> dict[str, str]:
    if isinstance(credential, AzureKeyCredential):
        return {
            "Ocp-Apim-Subscription-Key": credential.key,
            "Content-Type": "application/json",
        }

    token: AccessToken = credential.get_token("https://cognitiveservices.azure.com/.default")
    return {
        "Authorization": f"Bearer {token.token}",
        "Content-Type": "application/json",
    }


def _extract_transcription_id(transcription_url: str) -> str:
    match = re.search(r"/transcriptions/([^/?]+)", transcription_url)
    if not match:
        return transcription_url.rstrip("/").split("/")[-1]
    return match.group(1)


def resolve_transcription_route(
    audio_source: str | Path | NDArray[np.floating[Any]] | PreparedAudioInput,
    sample_rate: int | None = None,
    *,
    route_filename: str = "prepared-audio.wav",
) -> Literal["fast", "batch"]:
    payload = _build_audio_payload(
        audio_source,
        sample_rate,
        filename=route_filename,
    )
    return _payload_route(payload)


def submit_batch_transcription_urls(
    content_urls: Sequence[str],
    *,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    locale: str = DEFAULT_LOCALE,
    display_name: str = "batch-transcription",
    api_version: str = "2024-11-15",
    word_level_timestamps: bool = False,
    display_form_word_level_timestamps: bool = False,
    channels: Sequence[int] | None = None,
    destination_container_url: str | None = None,
    time_to_live_hours: int = 48,
) -> SubmittedBatchTranscription:
    if not content_urls:
        raise ValueError("content_urls no puede estar vacio.")

    speech_endpoint = _normalize_speech_endpoint(endpoint, speech_region)
    resolved_credential = _build_credential(credential, api_key)
    base_url = f"{speech_endpoint}/speechtotext"
    headers = _build_auth_headers(resolved_credential)

    properties: dict[str, Any] = {
        "wordLevelTimestampsEnabled": word_level_timestamps,
        "displayFormWordLevelTimestampsEnabled": display_form_word_level_timestamps,
        "timeToLiveHours": time_to_live_hours,
    }
    if channels is not None:
        properties["channels"] = list(channels)

    payload: dict[str, Any] = {
        "displayName": display_name,
        "locale": locale,
        "contentUrls": list(content_urls),
        "properties": properties,
    }
    if destination_container_url:
        payload["destinationContainerUrl"] = destination_container_url

    submit_url = f"{base_url}/transcriptions:submit?api-version={api_version}"
    submit_resp = requests.post(
        submit_url,
        headers=headers,
        json=payload,
        timeout=120,
    )
    submit_resp.raise_for_status()
    submit_data = submit_resp.json()

    transcription_url = submit_data["self"]
    return SubmittedBatchTranscription(
        transcription_id=_extract_transcription_id(transcription_url),
        transcription_url=transcription_url,
        submitted_at=submit_data.get("createdDateTime"),
        status=submit_data.get("status"),
        display_name=display_name,
        locale=locale,
    )


def get_batch_transcription_status(
    transcription_url: str,
    *,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    resolved_credential = _build_credential(credential, api_key)
    headers = _build_auth_headers(resolved_credential)
    status_resp = requests.get(
        transcription_url,
        headers=headers,
        timeout=120,
    )
    status_resp.raise_for_status()
    payload = status_resp.json()
    payload["transcription_url"] = transcription_url
    payload["transcription_id"] = _extract_transcription_id(transcription_url)
    return payload


def fetch_batch_transcription_result(
    transcription_url: str,
    *,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    resolved_credential = _build_credential(credential, api_key)
    headers = _build_auth_headers(resolved_credential)
    final_status = get_batch_transcription_status(
        transcription_url,
        credential=resolved_credential,
    )

    if final_status.get("status") == "Failed":
        return _attach_continuous_text({
            "mode": "batch",
            "transcription_url": transcription_url,
            "transcription_id": _extract_transcription_id(transcription_url),
            "final_status": final_status,
            "files": [],
            "transcriptions": [],
            "reports": [],
        })

    if final_status.get("status") != "Succeeded":
        raise ValueError(
            f"Batch transcription is not completed yet: {final_status.get('status')!r}."
        )

    files_url = final_status["links"]["files"]
    files_resp = requests.get(
        files_url,
        headers=headers,
        timeout=120,
    )
    files_resp.raise_for_status()
    files = files_resp.json().get("values", [])

    transcription_results = []
    report_results = []

    for file_info in files:
        kind = file_info.get("kind")
        content_url = file_info.get("links", {}).get("contentUrl")
        if not content_url:
            continue

        content_resp = requests.get(content_url, timeout=120)
        content_resp.raise_for_status()

        try:
            content_json = content_resp.json()
        except ValueError:
            content_json = {"raw_text": content_resp.text}

        file_payload = {
            "name": file_info.get("name"),
            "kind": kind,
            "content": content_json,
        }

        if kind == "Transcription":
            transcription_results.append(file_payload)
        elif kind == "TranscriptionReport":
            report_results.append(file_payload)

    return _attach_continuous_text({
        "mode": "batch",
        "transcription_url": transcription_url,
        "transcription_id": _extract_transcription_id(transcription_url),
        "final_status": final_status,
        "files": files,
        "transcriptions": transcription_results,
        "reports": report_results,
    })


def _run_batch_transcription(
    content_urls: Sequence[str],
    *,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    locale: str = DEFAULT_LOCALE,
    display_name: str = "batch-transcription",
    poll_seconds: int = 20,
    api_version: str = "2024-11-15",
    word_level_timestamps: bool = False,
    display_form_word_level_timestamps: bool = False,
    channels: Sequence[int] | None = None,
    destination_container_url: str | None = None,
    time_to_live_hours: int = 48,
) -> dict[str, Any]:
    submission = submit_batch_transcription_urls(
        content_urls,
        endpoint=endpoint,
        speech_region=speech_region,
        credential=credential,
        api_key=api_key,
        locale=locale,
        display_name=display_name,
        api_version=api_version,
        word_level_timestamps=word_level_timestamps,
        display_form_word_level_timestamps=display_form_word_level_timestamps,
        channels=channels,
        destination_container_url=destination_container_url,
        time_to_live_hours=time_to_live_hours,
    )
    transcription_url = submission.transcription_url
    resolved_credential = _build_credential(credential, api_key)

    while True:
        final_status = get_batch_transcription_status(
            transcription_url,
            credential=resolved_credential,
        )

        status = final_status.get("status")
        if status in {"Succeeded", "Failed"}:
            break

        time.sleep(poll_seconds)

    return fetch_batch_transcription_result(
        transcription_url,
        credential=resolved_credential,
    )


def _transcribe_batch_payload(
    payload: AudioPayload,
    *,
    storage_manager: AzureBlobAudioStorage,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    locale: str = DEFAULT_LOCALE,
    display_name: str = "batch-transcription",
    poll_seconds: int = 20,
    api_version: str = "2024-11-15",
    word_level_timestamps: bool = False,
    display_form_word_level_timestamps: bool = False,
    channels: Sequence[int] | None = None,
    destination_container_url: str | None = None,
    time_to_live_hours: int = 48,
    sas_expiry_seconds: int = 24 * 3600,
    cleanup_uploaded_blob: bool = False,
) -> dict[str, Any]:
    if payload.size_bytes > BATCH_MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"Audio payload is too large for Azure batch transcription: {payload.size_bytes} bytes."
        )

    uploaded_blob = _upload_payload(
        payload,
        storage_manager=storage_manager,
        sas_expiry_seconds=sas_expiry_seconds,
    )

    try:
        response = _run_batch_transcription(
            [uploaded_blob.sas_url],
            endpoint=endpoint,
            speech_region=speech_region,
            credential=credential,
            api_key=api_key,
            locale=locale,
            display_name=display_name,
            poll_seconds=poll_seconds,
            api_version=api_version,
            word_level_timestamps=word_level_timestamps,
            display_form_word_level_timestamps=display_form_word_level_timestamps,
            channels=channels,
            destination_container_url=destination_container_url,
            time_to_live_hours=time_to_live_hours,
        )
    finally:
        if cleanup_uploaded_blob:
            storage_manager.delete_blob(uploaded_blob.blob_name)

    response.update(
        {
            "audio_file": str(payload.file_path) if payload.file_path else None,
            "audio_filename": payload.filename,
            "duration_seconds": payload.duration_seconds,
            "size_bytes": payload.size_bytes,
            "sample_rate": payload.sample_rate,
            "channels": payload.channels,
            "uploaded_blob": {
                "blob_name": uploaded_blob.blob_name,
                "blob_url": uploaded_blob.blob_url,
                "sas_url": uploaded_blob.sas_url,
                "expires_at": uploaded_blob.expires_at.isoformat(),
            },
        }
    )
    return _attach_continuous_text(response)


def submit_batch_transcription(
    audio_source: str | Path | NDArray[np.floating[Any]] | PreparedAudioInput,
    sample_rate: int | None = None,
    *,
    storage_manager: AzureBlobAudioStorage,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    route_filename: str = "prepared-audio.wav",
    locale: str = DEFAULT_LOCALE,
    display_name: str = "batch-transcription",
    api_version: str = "2024-11-15",
    word_level_timestamps: bool = False,
    display_form_word_level_timestamps: bool = False,
    active_channels: Sequence[int] | None = None,
    destination_container_url: str | None = None,
    time_to_live_hours: int = 48,
    sas_expiry_seconds: int = 24 * 3600,
) -> dict[str, Any]:
    payload = _build_audio_payload(
        audio_source,
        sample_rate,
        filename=route_filename,
    )
    if payload.size_bytes > BATCH_MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"Audio payload is too large for Azure batch transcription: {payload.size_bytes} bytes."
        )

    uploaded_blob = _upload_payload(
        payload,
        storage_manager=storage_manager,
        sas_expiry_seconds=sas_expiry_seconds,
    )
    submission = submit_batch_transcription_urls(
        [uploaded_blob.sas_url],
        endpoint=endpoint,
        speech_region=speech_region,
        credential=credential,
        api_key=api_key,
        locale=locale,
        display_name=display_name,
        api_version=api_version,
        word_level_timestamps=word_level_timestamps,
        display_form_word_level_timestamps=display_form_word_level_timestamps,
        channels=active_channels,
        destination_container_url=destination_container_url,
        time_to_live_hours=time_to_live_hours,
    )
    return {
        "mode": "batch",
        "transcription_id": submission.transcription_id,
        "transcription_url": submission.transcription_url,
        "submitted_at": submission.submitted_at,
        "status": submission.status,
        "locale": locale,
        "display_name": display_name,
        "audio_file": str(payload.file_path) if payload.file_path else None,
        "audio_filename": payload.filename,
        "duration_seconds": payload.duration_seconds,
        "size_bytes": payload.size_bytes,
        "sample_rate": payload.sample_rate,
        "channels": payload.channels,
        "uploaded_blob": {
            "blob_name": uploaded_blob.blob_name,
            "blob_url": uploaded_blob.blob_url,
            "sas_url": uploaded_blob.sas_url,
            "expires_at": uploaded_blob.expires_at.isoformat(),
        },
    }


def transcribe_audio(
    audio_source: str | Path | NDArray[np.floating[Any]] | PreparedAudioInput,
    sample_rate: int | None = None,
    *,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    locales: Sequence[str] | None = None,
    prompt: Sequence[str] | None = None,
    phrase_list: Sequence[str] | None = None,
    diarization_max_speakers: int | None = None,
    active_channels: Sequence[int] | None = None,
    profanity_filter_mode: str | ProfanityFilterMode = ProfanityFilterMode.MASKED,
    storage_manager: AzureBlobAudioStorage | None = None,
    route_filename: str = "prepared-audio.wav",
    batch_display_name: str = "batch-transcription",
    batch_locale: str = DEFAULT_LOCALE,
    poll_seconds: int = 20,
    api_version: str = "2024-11-15",
    word_level_timestamps: bool = False,
    display_form_word_level_timestamps: bool = False,
    destination_container_url: str | None = None,
    time_to_live_hours: int = 48,
    sas_expiry_seconds: int = 24 * 3600,
    cleanup_uploaded_blob: bool = False,
) -> dict[str, Any]:
    payload = _build_audio_payload(
        audio_source,
        sample_rate,
        filename=route_filename,
    )
    route = _payload_route(payload)

    if route == "fast":
        return _transcribe_fast_payload(
            payload,
            endpoint=endpoint,
            speech_region=speech_region,
            credential=credential,
            api_key=api_key,
            locales=locales,
            prompt=prompt,
            phrase_list=phrase_list,
            diarization_max_speakers=diarization_max_speakers,
            active_channels=active_channels,
            profanity_filter_mode=profanity_filter_mode,
        )

    if storage_manager is None:
        raise ValueError(
            "Batch route selected, but no storage_manager was provided. "
            "Azure batch transcription needs Blob Storage for local or in-memory audio."
        )

    return _transcribe_batch_payload(
        payload,
        storage_manager=storage_manager,
        endpoint=endpoint,
        speech_region=speech_region,
        credential=credential,
        api_key=api_key,
        locale=batch_locale,
        display_name=batch_display_name,
        poll_seconds=poll_seconds,
        api_version=api_version,
        word_level_timestamps=word_level_timestamps,
        display_form_word_level_timestamps=display_form_word_level_timestamps,
        channels=active_channels,
        destination_container_url=destination_container_url,
        time_to_live_hours=time_to_live_hours,
        sas_expiry_seconds=sas_expiry_seconds,
        cleanup_uploaded_blob=cleanup_uploaded_blob,
    )


def transcribe_audio_file(
    audio_file: str | Path,
    *,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    locales: Sequence[str] | None = None,
    prompt: Sequence[str] | None = None,
    phrase_list: Sequence[str] | None = None,
    diarization_max_speakers: int | None = None,
    active_channels: Sequence[int] | None = None,
    profanity_filter_mode: str | ProfanityFilterMode = ProfanityFilterMode.MASKED,
) -> dict[str, Any]:
    payload = _build_audio_payload(audio_file)
    return _transcribe_fast_payload(
        payload,
        endpoint=endpoint,
        speech_region=speech_region,
        credential=credential,
        api_key=api_key,
        locales=locales,
        prompt=prompt,
        phrase_list=phrase_list,
        diarization_max_speakers=diarization_max_speakers,
        active_channels=active_channels,
        profanity_filter_mode=profanity_filter_mode,
    )


def use_fast_transcription_with_prompt(
    audio_source: str | Path | NDArray[np.floating[Any]] | PreparedAudioInput,
    sample_rate: int | None = None,
    *,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    prompt: Sequence[str] | None = None,
    locales: Sequence[str] | None = None,
    phrase_list: Sequence[str] | None = None,
    diarization_max_speakers: int | None = None,
    active_channels: Sequence[int] | None = None,
    route_filename: str = "prepared-audio.wav",
) -> dict[str, Any]:
    payload = _build_audio_payload(
        audio_source,
        sample_rate,
        filename=route_filename,
    )
    return _transcribe_fast_payload(
        payload,
        endpoint=endpoint,
        speech_region=speech_region,
        credential=credential,
        api_key=api_key,
        locales=locales or [DEFAULT_LOCALE],
        prompt=prompt or DEFAULT_PROMPTS,
        phrase_list=phrase_list,
        diarization_max_speakers=diarization_max_speakers,
        active_channels=active_channels,
    )


def batch_transcribe_azure_speech(
    audio_files: Sequence[str | Path],
    *,
    endpoint: str | None = None,
    speech_region: str | None = None,
    credential: TokenCredential | AzureKeyCredential | None = None,
    api_key: str | None = None,
    locale: str = DEFAULT_LOCALE,
    display_name: str = "batch-transcription",
    poll_seconds: int = 20,
    api_version: str = "2024-11-15",
    word_level_timestamps: bool = False,
    display_form_word_level_timestamps: bool = False,
    channels: Sequence[int] | None = None,
    destination_container_url: str | None = None,
    time_to_live_hours: int = 48,
    storage_manager: AzureBlobAudioStorage | None = None,
    sas_expiry_seconds: int = 24 * 3600,
    cleanup_uploaded_blobs: bool = False,
) -> dict[str, Any]:
    if not audio_files:
        raise ValueError("audio_files no puede estar vacio.")

    content_urls: list[str] = []
    uploaded_blobs: list[UploadedAudioBlob] = []

    try:
        for item in audio_files:
            if isinstance(item, str) and item.startswith(("https://", "http://")):
                content_urls.append(item)
                continue

            if storage_manager is None:
                raise ValueError(
                    "Batch transcription needs Azure Storage for local files. "
                    "Pass storage_manager or pre-signed content URLs."
                )

            payload = _build_audio_payload(item)
            uploaded_blob = _upload_payload(
                payload,
                storage_manager=storage_manager,
                sas_expiry_seconds=sas_expiry_seconds,
            )
            uploaded_blobs.append(uploaded_blob)
            content_urls.append(uploaded_blob.sas_url)

        response = _run_batch_transcription(
            content_urls,
            endpoint=endpoint,
            speech_region=speech_region,
            credential=credential,
            api_key=api_key,
            locale=locale,
            display_name=display_name,
            poll_seconds=poll_seconds,
            api_version=api_version,
            word_level_timestamps=word_level_timestamps,
            display_form_word_level_timestamps=display_form_word_level_timestamps,
            channels=channels,
            destination_container_url=destination_container_url,
            time_to_live_hours=time_to_live_hours,
        )
        response["uploaded_blobs"] = [
            {
                "blob_name": blob.blob_name,
                "blob_url": blob.blob_url,
                "expires_at": blob.expires_at.isoformat(),
            }
            for blob in uploaded_blobs
        ]
        return _attach_continuous_text(response)
    finally:
        if cleanup_uploaded_blobs and storage_manager is not None:
            for blob in uploaded_blobs:
                storage_manager.delete_blob(blob.blob_name)
