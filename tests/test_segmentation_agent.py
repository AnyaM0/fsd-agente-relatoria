from __future__ import annotations

import unittest

from agents.shared_tools.segmentation_agent import SegmentationAgent


class SegmentationAgentTests(unittest.TestCase):
    def test_keeps_short_text_in_single_chunk(self) -> None:
        agent = SegmentationAgent(max_tokens=32)
        text = "Primer parrafo.\n\nSegundo parrafo corto."

        chunks = agent.split_text(text)

        self.assertEqual(len(chunks), 1)
        self.assertLessEqual(chunks[0].token_count, 32)
        self.assertIn("Primer parrafo.", chunks[0].text)
        self.assertIn("Segundo parrafo corto.", chunks[0].text)

    def test_splits_large_text_into_multiple_chunks_under_limit(self) -> None:
        agent = SegmentationAgent(max_tokens=20)
        paragraphs = [
            "Este es el primer bloque con varias palabras para forzar la segmentacion.",
            "Este es el segundo bloque con varias palabras para forzar la segmentacion.",
            "Este es el tercer bloque con varias palabras para forzar la segmentacion.",
        ]
        text = "\n\n".join(paragraphs)

        chunks = agent.split_text(text)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(chunk.token_count, 20)
            self.assertTrue(chunk.text)

        reconstructed = " ".join(chunk.text for chunk in chunks)
        self.assertIn("primer bloque", reconstructed)
        self.assertIn("tercer bloque", reconstructed)

    def test_hard_splits_single_oversized_block(self) -> None:
        agent = SegmentationAgent(max_tokens=10)
        text = "palabra " * 40

        chunks = agent.split_text(text)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(chunk.token_count, 10)

        reconstructed = " ".join(chunk.text for chunk in chunks)
        self.assertIn("palabra", reconstructed)


if __name__ == "__main__":
    unittest.main()
