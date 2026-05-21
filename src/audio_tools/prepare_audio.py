import io
import subprocess
from logging import getLogger
from pathlib import Path
from typing import Any, Callable

import librosa
import numpy as np
import noisereduce as nr
import soundfile as sf
from numpy.typing import NDArray
from pedalboard import Pedalboard, NoiseGate, Compressor, LowShelfFilter, Gain

logger = getLogger(__name__)

VIDEO_TYPES = {".mp4", ".avi", ".mov", ".mkv"}
ADMISSIBLE_AUDIO_TYPES = {".wav", ".mp3", ".flac", ".aac"}
MAX_FULL_NOISE_REDUCTION_SECONDS = 20 * 60

ProgressCallback = Callable[[str, dict[str, Any] | None], None]


def _notify(progress_callback: ProgressCallback | None, event: str, **payload: Any) -> None:
    if progress_callback is None:
        return
    progress_callback(event, payload or None)


def _its_video(file: Path) -> bool:
    return file.suffix.lower() in VIDEO_TYPES


def _verify_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg and add it to PATH.") from e


def extract_audio_to_memory(
    video_path: Path,
    target_sr: int = 44100,
    progress_callback: ProgressCallback | None = None,
) -> tuple[NDArray[np.float32], int]:
    _notify(progress_callback, "extract_audio_started", path=str(video_path), target_sr=target_sr)
    result = subprocess.run(
        [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(target_sr),
            "-ac", "1",
            "-f", "wav",
            "pipe:1",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    audio_bytes = io.BytesIO(result.stdout)
    audio, sr = sf.read(audio_bytes, dtype="float32")
    _notify(
        progress_callback,
        "extract_audio_completed",
        sample_rate=sr,
        samples=int(audio.shape[0]) if hasattr(audio, "shape") else 0,
    )
    return audio, sr


def _resample_audio(audio: NDArray[np.float32], source_sr: int, target_sr: int | None) -> tuple[NDArray[np.float32], int]:
    if target_sr is None or target_sr == source_sr:
        return audio, source_sr

    if target_sr <= 0:
        raise ValueError("target_sr must be greater than zero.")

    if audio.ndim == 1:
        resampled = librosa.resample(audio, orig_sr=source_sr, target_sr=target_sr)
    else:
        resampled = librosa.resample(audio, orig_sr=source_sr, target_sr=target_sr, axis=0)

    return np.asarray(resampled, dtype=np.float32), target_sr


def audit_file_type(
    file_path: Path,
    convert_to_audio: bool = True,
    target_sr: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[NDArray[np.float32], int]:
    suffix = file_path.suffix.lower()

    if _its_video(file_path):
        logger.info("Video file detected: %s", file_path)
        _notify(progress_callback, "video_detected", path=str(file_path), suffix=suffix)
        if not convert_to_audio:
            raise ValueError("Video files are not supported without conversion.")

        logger.info("Extracting audio from video to memory...")
        _notify(progress_callback, "ffmpeg_check_started", path=str(file_path))
        _verify_ffmpeg()
        _notify(progress_callback, "ffmpeg_check_completed", path=str(file_path))
        video_target_sr = target_sr or 44100
        return extract_audio_to_memory(
            file_path,
            target_sr=video_target_sr,
            progress_callback=progress_callback,
        )

    if suffix in ADMISSIBLE_AUDIO_TYPES:
        logger.info("Audio file detected: %s", file_path)
        _notify(progress_callback, "audio_detected", path=str(file_path), suffix=suffix)
        audio, sr = sf.read(file_path, dtype="float32")
        _notify(
            progress_callback,
            "audio_loaded",
            sample_rate=sr,
            samples=int(audio.shape[0]) if hasattr(audio, "shape") else 0,
        )
        return _resample_audio(audio, sr, target_sr)

    raise ValueError(f"Unsupported file type: {suffix}")


def _load_audio(
    path: str,
    target_sr: int | None = None,
    convert_to_audio: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> tuple[NDArray[np.float32], int]:
    try:
        _notify(progress_callback, "load_audio_started", path=path, target_sr=target_sr)
        return audit_file_type(
            Path(path),
            convert_to_audio=convert_to_audio,
            target_sr=target_sr,
            progress_callback=progress_callback,
        )
    except Exception as e:
        logger.error("Error loading audio: %s", e)
        _notify(progress_callback, "load_audio_failed", path=path, error=str(e))
        raise TypeError(f"Unsupported file type or error processing file: {e}") from e


def _load_pedal_board() -> Pedalboard:
    return Pedalboard([
        NoiseGate(threshold_db=-30, ratio=1.5, release_ms=250),
        Compressor(threshold_db=-16, ratio=4),
        LowShelfFilter(cutoff_frequency_hz=400, gain_db=10, q=1),
        Gain(gain_db=2),
    ])


def audio_enhancement(
    audio: NDArray[np.float32],
    sr: int,
    progress_callback: ProgressCallback | None = None,
) -> NDArray[np.float32]:
    duration_seconds = float(audio.shape[0] / sr) if sr and hasattr(audio, "shape") else 0.0
    use_light_mode = duration_seconds > MAX_FULL_NOISE_REDUCTION_SECONDS
    _notify(
        progress_callback,
        "enhancement_mode_selected",
        mode="light" if use_light_mode else "full",
        duration_seconds=round(duration_seconds, 2),
        threshold_seconds=MAX_FULL_NOISE_REDUCTION_SECONDS,
    )
    if use_light_mode:
        reduced_noise = audio
    else:
        _notify(progress_callback, "noise_reduction_started", duration_seconds=round(duration_seconds, 2))
        reduced_noise = nr.reduce_noise(y=audio, sr=sr, stationary=True, prop_decrease=0.75)
        _notify(progress_callback, "noise_reduction_completed", duration_seconds=round(duration_seconds, 2))

    _notify(progress_callback, "pedalboard_started", sample_rate=sr)
    board = _load_pedal_board()
    effected = board(reduced_noise, sr)
    _notify(progress_callback, "pedalboard_completed", sample_rate=sr)
    return np.asarray(effected, dtype=np.float32)


def run_audio_pipeline(
    audio_path: str,
    target_sr: int | None = None,
    convert_to_audio: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> tuple[NDArray[np.float32], int]:
    audio, sr = _load_audio(
        audio_path,
        target_sr=target_sr,
        convert_to_audio=convert_to_audio,
        progress_callback=progress_callback,
    )
    _notify(
        progress_callback,
        "audio_loaded_for_processing",
        sample_rate=sr,
        samples=int(audio.shape[0]) if hasattr(audio, "shape") else 0,
    )
    enhanced = audio_enhancement(audio, sr, progress_callback=progress_callback)
    _notify(
        progress_callback,
        "audio_pipeline_completed",
        sample_rate=sr,
        samples=int(enhanced.shape[0]) if hasattr(enhanced, "shape") else 0,
    )
    return enhanced, sr
