"""Persistent Chroma vector store with local MiniLM embeddings.

Hit schema (shared with keyword_search.py and hybrid.py — do not rename keys;
Days 6-7 /ask + citations consume this):

    {
        "text": str,
        "source_file": str,
        "page_num": int,
        "chunk_id": str,
        "is_table": bool,
        "score": float,   # cosine similarity in [0, 1], higher is better
    }

Chunk input contract from ingestion (fixed):
    {text, source_file, page_num, chunk_id, is_table}
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "techdoc"

_client: chromadb.PersistentClient | None = None
_collection: Any = None
_embed_fn: SentenceTransformerEmbeddingFunction | None = None


def persist_dir() -> Path:
    """Resolve CHROMA_PERSIST_DIR relative to the backend/ folder."""
    raw = os.getenv("CHROMA_PERSIST_DIR", "./data/processed/chroma")
    path = Path(raw)
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _embedding_fn() -> SentenceTransformerEmbeddingFunction:
    global _embed_fn
    if _embed_fn is None:
        _embed_fn = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    return _embed_fn


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        path = str(persist_dir())
        _client = chromadb.PersistentClient(path=path)
        logger.info("Opened Chroma PersistentClient at %s", path)
    return _client


def get_collection(name: str = COLLECTION_NAME) -> Any:
    """Return the persistent Chroma collection, creating it if needed."""
    global _collection
    if _collection is None or _collection.name != name:
        _collection = get_client().get_or_create_collection(
            name=name,
            embedding_function=_embedding_fn(),
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def chunk_doc_id(chunk: dict) -> str:
    """Stable Chroma ID from the ingestion metadata pair (source_file, chunk_id)."""
    return f"{chunk['source_file']}::{chunk['chunk_id']}"


def add_chunks(chunks: list[dict], collection: Any | None = None) -> int:
    """Embed and add new chunks. Skips any (source_file, chunk_id) already stored.

    Returns the number of chunks actually embedded.
    """
    coll = collection or get_collection()
    if not chunks:
        return 0

    ids = [chunk_doc_id(c) for c in chunks]
    existing = set()
    # collection.get on a missing id returns only the ids that exist.
    found = coll.get(ids=ids)
    existing.update(found.get("ids") or [])

    new_chunks = [c for c, cid in zip(chunks, ids) if cid not in existing]
    skipped = len(chunks) - len(new_chunks)
    if skipped:
        logger.info("Skipping %s already-indexed chunks", skipped)
    if not new_chunks:
        return 0

    coll.add(
        ids=[chunk_doc_id(c) for c in new_chunks],
        documents=[c["text"] for c in new_chunks],
        metadatas=[_metadata_from_chunk(c) for c in new_chunks],
    )
    logger.info("Embedded %s chunks into Chroma", len(new_chunks))
    return len(new_chunks)


def query(text: str, n_results: int = 8, collection: Any | None = None) -> list[dict]:
    """Nearest-neighbor search. Returns hits in the shared schema, highest score first."""
    coll = collection or get_collection()
    count = coll.count()
    if count == 0 or not (text or "").strip():
        return []

    n = min(n_results, count)
    raw = coll.query(
        query_texts=[text],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )
    documents = (raw.get("documents") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    hits: list[dict] = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        hits.append(_hit(doc, meta, score=_cosine_similarity(dist)))
    return hits


def get_all_chunks(collection: Any | None = None) -> list[dict]:
    """Load every stored chunk. Used to rebuild the in-memory BM25 index after restart."""
    coll = collection or get_collection()
    if coll.count() == 0:
        return []
    raw = coll.get(include=["documents", "metadatas"])
    hits: list[dict] = []
    for doc, meta in zip(raw.get("documents") or [], raw.get("metadatas") or []):
        hits.append(_hit(doc, meta, score=0.0))
    return hits


def _metadata_from_chunk(chunk: dict) -> dict:
    """Chroma only accepts str/int/float/bool metadata values."""
    return {
        "source_file": str(chunk["source_file"]),
        "page_num": int(chunk["page_num"]),
        "chunk_id": str(chunk["chunk_id"]),
        "is_table": bool(chunk["is_table"]),
    }


def _cosine_similarity(distance: float) -> float:
    """Chroma cosine space stores distance = 1 - cosine_similarity."""
    return float(1.0 - distance)


def _hit(text: str, meta: dict | None, score: float) -> dict:
    meta = meta or {}
    return {
        "text": text or "",
        "source_file": meta.get("source_file", ""),
        "page_num": int(meta.get("page_num", 0)),
        "chunk_id": meta.get("chunk_id", ""),
        "is_table": bool(meta.get("is_table", False)),
        "score": float(score),
    }
