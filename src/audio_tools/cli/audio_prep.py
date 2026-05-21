from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Allow running this file directly (e.g. `python src/audio_tools/cli/audio_prep.py ...`)
# without requiring the package to be installed. When invoked as a module
# (`python -m audio_tools.cli.audio_prep ...`) this block is skipped.
if __package__ in (None, ""):
    _src_root = Path(__file__).resolve().parents[2]  # .../src
    if str(_src_root) not in sys.path:
        sys.path.insert(0, str(_src_root))

from audio_tools.azure import AzureBlobAudioStorage, transcribe_audio
from audio_tools.prepare_audio import logger, run_audio_pipeline, sf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare audio and optionally transcribe it with Azure Speech-to-Text.")
    parser.add_argument("input_pos", nargs="?", help="Path to the audio/video file")
    parser.add_argument("--input", dest="input_opt", type=str, default=None, help="Path to the audio/video file")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to save the enhanced audio as WAV.",
    )
    parser.add_argument(
        "--sr",
        type=int,
        default=44100,
        help="Target sample rate for the prepared audio.",
    )
    parser.add_argument(
        "--no-convert-video",
        action="store_true",
        help="Reject video files instead of converting them to audio.",
    )
    parser.add_argument(
        "--also-transcribe",
        action="store_true",
        help="Also transcribe the prepared audio using Azure Speech-to-Text.",
    )
    parser.add_argument(
        "--transcript-output",
        type=str,
        default=None,
        help="Optional path to save the transcript JSON.",
    )
    parser.add_argument(
        "--cleanup-uploaded-blob",
        action="store_true",
        help="Delete the temporary blob after batch transcription finishes.",
    )
    return parser


def _resolve_storage_manager() -> AzureBlobAudioStorage | None:
    try:
        return AzureBlobAudioStorage.from_env()
    except ValueError:
        return None


def _write_transcript_output(path_str: str, transcript: dict) -> None:
    output_path = Path(path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(transcript, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def _log_transcript_summary(transcript: dict) -> None:
    mode = transcript.get("mode", "unknown")
    if mode == "fast":
        text = transcript.get("text", "").strip()
        logger.info("Transcription mode: %s", mode)
        logger.info("Transcript:\n%s", text or "<empty transcript>")
        return

    logger.info("Transcription mode: %s", mode)
    transcriptions = transcript.get("transcriptions", [])
    if transcriptions:
        logger.info("Batch transcription finished with %s result file(s).", len(transcriptions))
    else:
        logger.info("Batch transcription finished without transcription payloads.")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = build_parser()
    args = parser.parse_args()

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() != ".wav":
            logger.error("Output file must have a .wav extension")
            return 1

    input_value = args.input_opt or args.input_pos
    if not input_value:
        parser.error("the following arguments are required: input (positional) or --input")

    input_path = Path(input_value)
    if not input_path.exists():
        logger.error("Input file does not exist: %s", input_path)
        return 1

    try:
        audio, sr = run_audio_pipeline(
            str(input_path),
            target_sr=args.sr,
            convert_to_audio=not args.no_convert_video,
        )

        if args.output:
            output_path = Path(args.output)
            sf.write(output_path, audio, sr)
            logger.info("Enhanced audio saved to: %s", output_path)
        else:
            logger.info("Audio preparation completed successfully.")

        if args.also_transcribe:
            storage_manager = _resolve_storage_manager()
            transcript = transcribe_audio(
                (audio, sr),
                storage_manager=storage_manager,
                route_filename=f"{input_path.stem}-prepared.wav",
                cleanup_uploaded_blob=args.cleanup_uploaded_blob,
            )
            _log_transcript_summary(transcript)

            if args.transcript_output:
                _write_transcript_output(args.transcript_output, transcript)
                logger.info("Transcript JSON saved to: %s", args.transcript_output)

        return 0
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
