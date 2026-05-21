from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agents.shared_tools.segmentation_agent import write_chunks_to_directory
from audio_tools.azure import AzureBlobAudioStorage, transcript_to_continuous_text, transcribe_audio
from audio_tools.prepare_audio import run_audio_pipeline

DEFAULT_INPUT = Path("/Users/lasagna0/Downloads/video1083416983.mp4")
DEFAULT_PREPARED_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_prepared.wav"
DEFAULT_TRANSCRIPT_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_transcript.json"
DEFAULT_CONTINUOUS_TEXT_OUTPUT = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_transcript.txt"
DEFAULT_CHUNKS_OUTPUT_DIR = PROJECT_ROOT / "tests" / "outputs" / "video1083416983_chunks_16k"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env.azure.local"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the prepare-audio and Azure transcription pipeline against a fixed local video."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to the input video or audio file.",
    )
    parser.add_argument(
        "--prepared-output",
        type=Path,
        default=DEFAULT_PREPARED_OUTPUT,
        help="Where to save the prepared WAV output.",
    )
    parser.add_argument(
        "--transcript-output",
        type=Path,
        default=DEFAULT_TRANSCRIPT_OUTPUT,
        help="Where to save the transcript JSON output.",
    )
    parser.add_argument(
        "--continuous-text-output",
        type=Path,
        default=DEFAULT_CONTINUOUS_TEXT_OUTPUT,
        help="Where to save the transcript as continuous plain text for later splitting.",
    )
    parser.add_argument(
        "--chunks-output-dir",
        type=Path,
        default=DEFAULT_CHUNKS_OUTPUT_DIR,
        help="Directory where chunked transcript text files and metadata will be written.",
    )
    parser.add_argument(
        "--chunk-max-tokens",
        type=int,
        default=16_000,
        help="Maximum token count per chunk using o200k_base.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Optional env file with Azure settings.",
    )
    parser.add_argument(
        "--sr",
        type=int,
        default=44100,
        help="Target sample rate for prepared audio.",
    )
    parser.add_argument(
        "--cleanup-uploaded-blob",
        action="store_true",
        help="Delete the temporary blob after batch transcription finishes.",
    )
    return parser


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_storage_manager() -> AzureBlobAudioStorage | None:
    try:
        return AzureBlobAudioStorage.from_env()
    except ValueError:
        return None


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_chunks(text: str, output_dir: Path, *, max_tokens: int) -> list[dict[str, int | str]]:
    metadata = write_chunks_to_directory(
        text,
        output_dir,
        max_tokens=max_tokens,
    )
    metadata_path = output_dir / "chunks.json"
    logging.info("Chunk metadata written to %s", metadata_path)
    logging.info("Generated %s chunk(s) with max_tokens=%s", len(metadata), max_tokens)
    return metadata


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    load_env_file(args.env_file)

    input_path = args.input.expanduser().resolve()
    prepared_output = args.prepared_output.expanduser().resolve()
    transcript_output = args.transcript_output.expanduser().resolve()
    continuous_text_output = args.continuous_text_output.expanduser().resolve()
    chunks_output_dir = args.chunks_output_dir.expanduser().resolve()

    if not input_path.exists():
        parser.error(f"Input file does not exist: {input_path}")

    try:
        logging.info("Preparing audio from %s", input_path)
        audio, sr = run_audio_pipeline(str(input_path), target_sr=args.sr)

        ensure_parent(prepared_output)
        sf.write(prepared_output, audio, sr)
        logging.info("Prepared audio written to %s", prepared_output)

        storage_manager = resolve_storage_manager()
        logging.info(
            "Running transcription with storage manager: %s",
            "enabled" if storage_manager is not None else "disabled",
        )

        transcript = transcribe_audio(
            (audio, sr),
            storage_manager=storage_manager,
            route_filename=prepared_output.name,
            cleanup_uploaded_blob=args.cleanup_uploaded_blob,
        )

        ensure_parent(transcript_output)
        transcript_output.write_text(
            json.dumps(transcript, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        logging.info("Transcript written to %s", transcript_output)

        continuous_text = transcript_to_continuous_text(transcript)
        ensure_parent(continuous_text_output)
        continuous_text_output.write_text(continuous_text, encoding="utf-8")
        logging.info("Continuous transcript written to %s", continuous_text_output)
        write_chunks(
            continuous_text,
            chunks_output_dir,
            max_tokens=args.chunk_max_tokens,
        )
        logging.info("Transcription mode: %s", transcript.get("mode"))

        text = continuous_text.strip()
        if text:
            logging.info("Transcript preview:\n%s", text[:1000])
        elif transcript.get("transcriptions"):
            logging.info("Batch transcription returned %s transcription payload(s).", len(transcript["transcriptions"]))
        else:
            logging.info("No transcript text returned.")

        return 0
    except Exception as exc:
        logging.exception("Video pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
