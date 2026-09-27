"""In-memory BM25 keyword search over ingested chunks.

Persistence is not implemented — rebuild from Chroma via get_all_chunks()
on process start (see hybrid.index_chunks / hybrid_search). Add a pickle
dump later if the corpus outgrows a rebuild.

Hit schema matches vector_store.py (interchangeable):

    {
        "text": str,
        "source_file": str,
        "page_num": int,
        "chunk_id": str,
        "is_table": bool,
        "score": float,   # BM25 score, higher is better
    }
"""

from __future__ import annotations

import logging
import re
from typing import Any

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

# Keep error codes like E04 / 3210 as single tokens.
_TOKEN = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase and split on whitespace/punctuation. No stemmer, no stopwords."""
    return _TOKEN.findall((text or "").lower())


class BM25Index:
    """In-memory BM25Okapi index. Call build() to replace the corpus."""

    def __init__(self) -> None:
        self._chunks: list[dict] = []
        self._index: Any = None

    def build(self, chunks: list[dict]) -> None:
        """Tokenize chunk texts and (re)build the BM25 index from scratch."""
        self._chunks = list(chunks)
        tokenized = [tokenize(c.get("text") or "") for c in self._chunks]
        if not tokenized or all(len(toks) == 0 for toks in tokenized):
            self._index = None
            logger.info("BM25 index empty (%s chunks)", len(self._chunks))
            return
        self._index = BM25Okapi(tokenized)
        logger.info("Built BM25 index over %s chunks", len(self._chunks))

    def is_built(self) -> bool:
        return self._index is not None

    def search(self, query: str, n_results: int = 8) -> list[dict]:
        """Return top BM25 hits in the shared hit schema."""
        if self._index is None or not self._chunks:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []

        scores = self._index.get_scores(tokens)
        ranked = sorted(
            range(len(scores)),
            key=lambda i: float(scores[i]),
            reverse=True,
        )
        hits: list[dict] = []
        for i in ranked[:n_results]:
            score = float(scores[i])
            if score <= 0:
                break
            chunk = self._chunks[i]
            hits.append(
                {
                    "text": chunk.get("text") or "",
                    "source_file": chunk.get("source_file", ""),
                    "page_num": int(chunk.get("page_num", 0)),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "is_table": bool(chunk.get("is_table", False)),
                    "score": score,
                }
            )
        return hits
