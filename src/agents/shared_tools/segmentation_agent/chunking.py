from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import tiktoken

DEFAULT_TOKEN_ENCODING = "o200k_base"
DEFAULT_MAX_TOKENS = 256_000

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")


@dataclass(frozen=True)
class TokenChunk:
    index: int
    text: str
    token_count: int
    start_token: int
    end_token: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SegmentChunk = TokenChunk


class TokenChunker:
    def __init__(
        self,
        *,
        encoding_name: str = DEFAULT_TOKEN_ENCODING,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero.")

        self.encoding_name = encoding_name
        self.max_tokens = max_tokens
        self._encoding = tiktoken.get_encoding(encoding_name)

    def encode(self, text: str) -> list[int]:
        return self._encoding.encode(text)

    def decode(self, tokens: list[int]) -> str:
        return self._encoding.decode(tokens)

    def count_tokens(self, text: str) -> int:
        return len(self.encode(text))

    def split_text(self, text: str) -> list[TokenChunk]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        units = self._split_into_units(normalized)
        chunks: list[TokenChunk] = []
        current_text = ""
        current_token_cursor = 0

        for unit in units:
            if not current_text:
                current_text = unit
                continue

            candidate = f"{current_text}\n\n{unit}"
            if self.count_tokens(candidate) <= self.max_tokens:
                current_text = candidate
                continue

            current_token_cursor = self._append_chunk(
                chunks,
                text=current_text,
                start_token=current_token_cursor,
            )
            current_text = unit

        if current_text:
            self._append_chunk(
                chunks,
                text=current_text,
                start_token=current_token_cursor,
            )

        return chunks

    def split_file(self, path: str | Path, *, encoding: str = "utf-8") -> list[TokenChunk]:
        file_path = Path(path).expanduser().resolve()
        return self.split_text(file_path.read_text(encoding=encoding))

    def split_text_as_dicts(self, text: str) -> list[dict[str, Any]]:
        return [chunk.as_dict() for chunk in self.split_text(text)]

    def _append_chunk(
        self,
        chunks: list[TokenChunk],
        *,
        text: str,
        start_token: int,
    ) -> int:
        token_count = self.count_tokens(text)
        chunk = TokenChunk(
            index=len(chunks),
            text=text,
            token_count=token_count,
            start_token=start_token,
            end_token=start_token + token_count,
        )
        chunks.append(chunk)
        return chunk.end_token

    def _split_into_units(self, text: str) -> list[str]:
        paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT_RE.split(text) if part.strip()]
        if not paragraphs:
            paragraphs = [text]

        units: list[str] = []
        for paragraph in paragraphs:
            units.extend(self._split_oversized_block(paragraph))

        return units

    def _split_oversized_block(self, text: str) -> list[str]:
        if self.count_tokens(text) <= self.max_tokens:
            return [text]

        sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]
        if len(sentences) > 1:
            return self._pack_smaller_units(sentences)

        return self._hard_split(text)

    def _pack_smaller_units(self, units: list[str]) -> list[str]:
        packed: list[str] = []
        current_text = ""

        for unit in units:
            if self.count_tokens(unit) > self.max_tokens:
                if current_text:
                    packed.append(current_text)
                    current_text = ""
                packed.extend(self._hard_split(unit))
                continue

            if not current_text:
                current_text = unit
                continue

            candidate = f"{current_text} {unit}"
            if self.count_tokens(candidate) <= self.max_tokens:
                current_text = candidate
            else:
                packed.append(current_text)
                current_text = unit

        if current_text:
            packed.append(current_text)

        return packed

    def _hard_split(self, text: str) -> list[str]:
        tokens = self.encode(text)
        chunks: list[str] = []
        start = 0

        while start < len(tokens):
            end = min(start + self.max_tokens, len(tokens))
            chunk_text = ""

            while end > start:
                chunk_text = self.decode(tokens[start:end]).strip()
                if chunk_text and self.count_tokens(chunk_text) <= self.max_tokens:
                    break
                end -= 1

            if not chunk_text:
                raise ValueError("Failed to generate a non-empty chunk during hard split.")

            chunks.append(chunk_text)
            start = end

        return chunks

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return ""
        return normalized


SegmentationAgent = TokenChunker


def split_text(
    text: str,
    *,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[TokenChunk]:
    chunker = TokenChunker(
        encoding_name=encoding_name,
        max_tokens=max_tokens,
    )
    return chunker.split_text(text)


def write_chunks_to_directory(
    text: str,
    output_dir: str | Path,
    *,
    encoding_name: str = DEFAULT_TOKEN_ENCODING,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    encoding: str = "utf-8",
) -> list[dict[str, Any]]:
    chunker = TokenChunker(
        encoding_name=encoding_name,
        max_tokens=max_tokens,
    )
    chunks = chunker.split_text(text)

    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    metadata: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_path = directory / f"chunk_{chunk.index:04d}.txt"
        chunk_path.write_text(chunk.text, encoding=encoding)
        metadata.append(
            {
                "index": chunk.index,
                "path": str(chunk_path),
                "token_count": chunk.token_count,
                "start_token": chunk.start_token,
                "end_token": chunk.end_token,
            }
        )

    metadata_path = directory / "chunks.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2), encoding=encoding)
    return metadata
