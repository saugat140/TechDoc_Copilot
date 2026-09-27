"""Split page text into retrieval chunks with stable citation metadata.

Chunk schema (do not rename keys — retrieval/Chroma and citations depend on them):

    {
        "text": str,            # chunk body
        "source_file": str,     # original PDF filename
        "page_num": int,        # 1-based page the text came from
        "chunk_id": str,        # "{stem}-p{page}-{index}" unique within a document
        "is_table": bool,       # True if this chunk is a detected table block
    }

Token counts are word-count approximations (no extra tokenizer dependency).
Target window is ~400 tokens with ~50 token overlap. Table blocks are never
split, even when they exceed the target size.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_TOKENS = 400
OVERLAP_TOKENS = 50
MAX_TOKENS = 500

# Treat a line as tabular when it has column delimiters.
_MULTI_SPACE = re.compile(r" {2,}")


def chunk_pages(pages: list[dict]) -> list[dict]:
    """Chunk each page independently so page_num on every chunk is accurate.

    Pages with empty text produce no chunks. chunk_id index restarts per page.
    """
    chunks: list[dict] = []
    for page in pages:
        page_chunks = chunk_page(page)
        chunks.extend(page_chunks)
    logger.info("Produced %s chunks from %s pages", len(chunks), len(pages))
    return chunks


def chunk_page(page: dict) -> list[dict]:
    """Turn one page record into zero or more chunks."""
    text = (page.get("text") or "").strip()
    if not text:
        return []

    source_file = page.get("source_file") or Path(page.get("source_path", "unknown")).name
    page_num = int(page.get("page_num") or 0)
    stem = _source_stem(source_file)

    chunks: list[dict] = []
    for block_text, is_table in split_into_blocks(text):
        pieces = [block_text] if is_table else window_text(block_text)
        for piece in pieces:
            index = len(chunks)
            chunks.append(
                make_chunk(
                    text=piece,
                    source_file=source_file,
                    page_num=page_num,
                    chunk_id=f"{stem}-p{page_num}-{index}",
                    is_table=is_table,
                )
            )
    return chunks


def make_chunk(
    text: str,
    source_file: str,
    page_num: int,
    chunk_id: str,
    is_table: bool,
) -> dict:
    """Build a chunk dict. Keys here are the citation contract."""
    return {
        "text": text,
        "source_file": source_file,
        "page_num": page_num,
        "chunk_id": chunk_id,
        "is_table": is_table,
    }


def estimate_tokens(text: str) -> int:
    """Approximate token count as whitespace-separated words."""
    words = text.split()
    return max(1, len(words)) if text.strip() else 0


def is_table_line(line: str) -> bool:
    """True if a line looks like a table row (pipes, tabs, or aligned columns)."""
    stripped = line.rstrip()
    if not stripped.strip():
        return False
    if stripped.count("|") >= 2:
        return True
    if "\t" in stripped:
        return True
    if len(_MULTI_SPACE.findall(stripped)) >= 2:
        return True
    return False


def split_into_blocks(text: str) -> list[tuple[str, bool]]:
    """Split page text into (block_text, is_table) runs.

    A table run starts only when at least two consecutive non-blank lines
    look tabular, so a single spaced heading is not treated as a table.
    Blank lines inside a table stay in that table block.
    """
    lines = text.splitlines()
    if not lines:
        return []

    kinds = [_classify_line(line) for line in lines]
    blocks: list[tuple[str, bool]] = []
    i = 0
    while i < len(lines):
        if kinds[i] == "blank":
            i += 1
            continue
        if kinds[i] == "table" and _table_run_starts_at(kinds, i):
            j = _end_of_table(kinds, i)
            block = "\n".join(lines[i:j]).strip()
            if block:
                blocks.append((block, True))
            i = j
        else:
            j = i + 1
            while j < len(lines) and not (
                kinds[j] == "table" and _table_run_starts_at(kinds, j)
            ):
                j += 1
            block = "\n".join(lines[i:j]).strip()
            if block:
                blocks.append((block, False))
            i = j
    return blocks


def window_text(
    text: str,
    target: int = TARGET_TOKENS,
    overlap: int = OVERLAP_TOKENS,
    max_tokens: int = MAX_TOKENS,
) -> list[str]:
    """Sliding window over words. overlap is applied between consecutive windows."""
    words = text.split()
    if not words:
        return []
    if len(words) <= max_tokens:
        return [text.strip()]

    size = target
    step = max(1, size - overlap)
    windows: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + size, len(words))
        windows.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step
    return windows


def _source_stem(source_file: str) -> str:
    raw = Path(source_file).stem or "doc"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", raw)


def _classify_line(line: str) -> str:
    if not line.strip():
        return "blank"
    if is_table_line(line):
        return "table"
    return "prose"


def _table_run_starts_at(kinds: list[str], index: int) -> bool:
    """Need two table lines in a row (blanks ignored) to start a table block."""
    seen = 0
    for kind in kinds[index:]:
        if kind == "blank":
            continue
        if kind != "table":
            return False
        seen += 1
        if seen >= 2:
            return True
    return False


def _end_of_table(kinds: list[str], start: int) -> int:
    j = start
    last_table = start
    while j < len(kinds):
        if kinds[j] == "table":
            last_table = j
            j += 1
            continue
        if kinds[j] == "blank":
            k = j
            while k < len(kinds) and kinds[k] == "blank":
                k += 1
            if k < len(kinds) and kinds[k] == "table":
                j = k
                continue
            break
        break
    return last_table + 1
