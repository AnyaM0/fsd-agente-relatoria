from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.shared_tools.meeting_minutes.unified_pipeline import (
    list_supported_meeting_domains,
    resolve_meeting_input_source,
    run_meeting_pipeline,
)


class UnifiedPipelineTests(unittest.TestCase):
    def test_supported_domains_are_listed(self) -> None:
        self.assertEqual(list_supported_meeting_domains(), ("compras", "juridica"))

    def test_resolve_input_source(self) -> None:
        self.assertEqual(resolve_meeting_input_source(audio_path="meeting.mp4"), "audio")
        self.assertEqual(resolve_meeting_input_source(transcript_path="meeting.txt"), "transcript")
        self.assertEqual(
            resolve_meeting_input_source(
                chunk_dir="chunks",
                segmentation_result_path="segments.json",
            ),
            "chunks",
        )

    def test_resolve_input_source_rejects_incomplete_chunk_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "Provide both chunk_dir and segmentation_result_path together."):
            resolve_meeting_input_source(chunk_dir="chunks")

    def test_run_meeting_pipeline_dispatches_to_compras(self) -> None:
        fake_result = SimpleNamespace(
            variant="chunk_led",
            status="approved",
            output_dir="/tmp/compras_run",
            audio_path=None,
            transcript_path="/tmp/compras_run/transcript.txt",
            transcript_json_path="/tmp/compras_run/transcript.json",
            ppt_path=None,
            chunk_dir="/tmp/compras_run/chunks",
            segmentation_result_path="/tmp/compras_run/segmentation_segments.json",
            segmentation_markdown_path="/tmp/compras_run/segmentation_segments.md",
            acta_markdown_path="/tmp/compras_run/acta_final.md",
            acta_json_path="/tmp/compras_run/acta_final.json",
            approval_result={"status": "approved"},
        )
        with patch(
            "agents.shared_tools.meeting_minutes.unified_pipeline._run_compras_pipeline",
            return_value=fake_result,
        ) as runner:
            result = run_meeting_pipeline(
                domain="compras",
                transcript_path="meeting.txt",
                output_dir="/tmp/compras_run",
            )

        runner.assert_called_once()
        self.assertEqual(result.domain, "compras")
        self.assertEqual(result.input_source, "transcript")
        self.assertEqual(result.final_markdown_path, fake_result.acta_markdown_path)
        self.assertEqual(result.domain_result, {"status": "approved"})

    def test_run_meeting_pipeline_dispatches_to_juridica_and_infers_segmentation_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            inferred_markdown = output_dir / "segmentation_segments.md"
            inferred_markdown.write_text("# Segments", encoding="utf-8")

            fake_result = SimpleNamespace(
                variant="ppt_led",
                status="needs_review",
                output_dir=str(output_dir),
                audio_path=str(output_dir / "meeting.mp4"),
                transcript_path=str(output_dir / "transcript.txt"),
                transcript_json_path=str(output_dir / "transcript.json"),
                ppt_path=str(output_dir / "deck.pptx"),
                chunk_dir=str(output_dir / "chunks"),
                segmentation_result_path=str(output_dir / "segmentation_segments.json"),
                acta_markdown_path=str(output_dir / "acta_juridica.md"),
                acta_json_path=str(output_dir / "acta_juridica.json"),
                juridica_result={"status": "needs_review"},
            )
            with patch(
                "agents.shared_tools.meeting_minutes.unified_pipeline._run_juridica_pipeline",
                return_value=fake_result,
            ) as runner:
                result = run_meeting_pipeline(
                    domain="juridica",
                    audio_path=fake_result.audio_path,
                    ppt_path=fake_result.ppt_path,
                    output_dir=output_dir,
                )

        runner.assert_called_once()
        self.assertEqual(result.domain, "juridica")
        self.assertEqual(result.input_source, "audio")
        self.assertEqual(result.segmentation_markdown_path, str(inferred_markdown.resolve()))
        self.assertEqual(result.domain_result, {"status": "needs_review"})


if __name__ == "__main__":
    unittest.main()
