from __future__ import annotations

import json
import re
from pathlib import Path

from agents.shared_tools.meeting_minutes.models import ChunkContext, ChunkSummaryRecord


_CHUNK_FILE_RE = re.compile(r"chunk_(\d+)\.txt$")


def load_chunk_contexts(chunk_dir: str | Path) -> list[ChunkContext]:
    resolved_dir = Path(chunk_dir).expanduser().resolve()
    if not resolved_dir.exists():
        raise FileNotFoundError(f"Chunk directory not found: {resolved_dir}")

    metadata_path = resolved_dir / "chunks.json"
    metadata_map: dict[int, dict[str, int]] = {}
    if metadata_path.exists():
        raw_items = json.loads(metadata_path.read_text(encoding="utf-8"))
        for item in raw_items:
            if "index" not in item:
                continue
            metadata_map[int(item["index"])] = item

    chunks: list[ChunkContext] = []
    for path in sorted(resolved_dir.glob("chunk_*.txt")):
        match = _CHUNK_FILE_RE.match(path.name)
        if match is None:
            continue
        index = int(match.group(1))
        metadata = metadata_map.get(index, {})
        chunks.append(
            ChunkContext(
                index=index,
                path=str(path),
                text=path.read_text(encoding="utf-8"),
                token_count=_int_or_none(metadata.get("token_count")),
                start_token=_int_or_none(metadata.get("start_token")),
                end_token=_int_or_none(metadata.get("end_token")),
            )
        )

    if not chunks:
        raise ValueError(f"No chunk_*.txt files found in {resolved_dir}")

    chunks.sort(key=lambda item: item.index)
    return chunks


def load_chunk_contexts_with_segmentation(
    chunk_dir: str | Path,
    *,
    segmentation_result_path: str | Path,
) -> list[ChunkContext]:
    chunks = load_chunk_contexts(chunk_dir)
    segmentation_path = Path(segmentation_result_path).expanduser().resolve()
    if not segmentation_path.exists():
        raise FileNotFoundError(f"Segmentation result not found: {segmentation_path}")

    data = json.loads(segmentation_path.read_text(encoding="utf-8"))
    summary_map: dict[int, ChunkSummaryRecord] = {}
    for item in data.get("processed_chunk_summaries", []):
        chunk_index = item.get("chunk_index")
        if chunk_index is None:
            continue
        summary_map[int(chunk_index)] = ChunkSummaryRecord(
            short_title=str(item.get("short_title") or "").strip(),
            summary=str(item.get("summary") or "").strip(),
            notable_points=[],
        )

    merged: list[ChunkContext] = []
    for chunk in chunks:
        merged.append(
            ChunkContext(
                index=chunk.index,
                path=chunk.path,
                text=chunk.text,
                token_count=chunk.token_count,
                start_token=chunk.start_token,
                end_token=chunk.end_token,
                summary=summary_map.get(chunk.index),
            )
        )

    missing = [chunk.index for chunk in merged if chunk.summary is None]
    if missing:
        raise ValueError(
            "Segmentation result is missing processed chunk summaries for chunk indices: "
            + ", ".join(str(index) for index in missing)
        )

    return merged


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    return int(value)
