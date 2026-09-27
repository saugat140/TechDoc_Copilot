"""Hybrid retrieval: Chroma dense search + BM25, fused with RRF.

Return schema from hybrid_search() is the /ask + citation contract
(do not rename keys):

    {
        "text": str,
        "source_file": str,
        "page_num": int,
        "chunk_id": str,
        "is_table": bool,
        "score": float,   # reciprocal rank fusion score, higher is better
    }

Duplicate chunk_ids across the two ranked lists are merged into one entry.
"""

from __future__ import annotations

import logging

from app.retrieval.keyword_search import BM25Index
from app.retrieval.vector_store import add_chunks, get_all_chunks, query as vector_query

logger = logging.getLogger(__name__)

# Standard RRF constant; no per-query tuning.
RRF_K = 60
# Pull extra candidates from each retriever so fusion has room to rerank.
CANDIDATE_MULTIPLIER = 4

_bm25 = BM25Index()


def index_chunks(chunks: list[dict]) -> int:
    """Upsert new chunks into Chroma, then rebuild BM25 over the full corpus.

    BM25 stays in memory; Chroma is the source of truth across restarts.
    """
    added = add_chunks(chunks)
    corpus = get_all_chunks()
    _bm25.build(corpus)
    logger.info("Indexed corpus: chroma_added=%s bm25_size=%s", added, len(corpus))
    return added


def hybrid_search(query: str, top_k: int = 5) -> list[dict]:
    """Retrieve with vector + BM25, fuse with RRF, return top_k unique chunks.

    Rebuilds the in-memory BM25 index from Chroma if this process has not
    indexed yet (e.g. after a server restart).
    """
    if not (query or "").strip() or top_k <= 0:
        return []

    _ensure_bm25()
    fetch = max(top_k * CANDIDATE_MULTIPLIER, top_k)
    dense = vector_query(query, n_results=fetch)
    sparse = _bm25.search(query, n_results=fetch)
    fused = reciprocal_rank_fusion(dense, sparse, top_k=top_k)
    logger.info(
        "hybrid_search %r -> %s hits (dense=%s sparse=%s)",
        query[:80],
        len(fused),
        len(dense),
        len(sparse),
    )
    return fused


def reciprocal_rank_fusion(
    dense: list[dict],
    sparse: list[dict],
    top_k: int,
    k: int = RRF_K,
) -> list[dict]:
    """Merge two ranked lists by chunk_id using RRF: 1 / (k + rank)."""
    rrf_scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for rank, hit in enumerate(dense, start=1):
        cid = hit.get("chunk_id")
        if not cid:
            continue
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
        payloads[cid] = hit

    for rank, hit in enumerate(sparse, start=1):
        cid = hit.get("chunk_id")
        if not cid:
            continue
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in payloads:
            payloads[cid] = hit

    ordered = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
    results: list[dict] = []
    for cid, score in ordered[:top_k]:
        hit = dict(payloads[cid])
        hit["score"] = score
        results.append(hit)
    return results


def _ensure_bm25() -> None:
    if _bm25.is_built():
        return
    corpus = get_all_chunks()
    if corpus:
        _bm25.build(corpus)
