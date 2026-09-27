"""Index ingested chunks and run sample troubleshooting queries through hybrid search.

Usage (from the backend/ directory):

    python scripts/test_retrieval.py
    python scripts/test_retrieval.py --pdf data/raw/sample_drive_manual.pdf
    python scripts/test_retrieval.py --query "how do I reset error code E04?"

Loads data/processed/chunks.json if present (written by test_ingestion.py).
Otherwise re-runs ingestion on --pdf (default: sample_drive_manual.pdf).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.ingestion import ingest_pdf  # noqa: E402
from app.retrieval.hybrid import hybrid_search, index_chunks  # noqa: E402

CHUNKS_CACHE = BACKEND_ROOT / "data" / "processed" / "chunks.json"
DEFAULT_PDF = BACKEND_ROOT / "data" / "raw" / "sample_drive_manual.pdf"
SNIPPET_CHARS = 180

# Mix of a generic example (E04) and queries that match the sample drive manual.
DEFAULT_QUERIES = [
    "how do I reset error code E04?",
    "drive trips on DC overvoltage during deceleration",
    "what does fault code 3210 mean",
    "STO inputs open first check",
    "how to inspect the brake resistor",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo hybrid retrieval")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF,
        help="Sample PDF used when no cached chunks exist",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Override default questions (repeatable)",
    )
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def load_chunks(pdf_path: Path) -> list[dict]:
    if CHUNKS_CACHE.is_file():
        chunks = json.loads(CHUNKS_CACHE.read_text(encoding="utf-8"))
        print(f"loaded {len(chunks)} cached chunks from {CHUNKS_CACHE}")
        return chunks
    if not pdf_path.is_file():
        raise SystemExit(
            f"No cached chunks at {CHUNKS_CACHE} and PDF not found: {pdf_path}\n"
            "Run: python scripts/generate_sample_pdf.py"
        )
    print(f"no cache; ingesting {pdf_path}")
    chunks = ingest_pdf(str(pdf_path))
    CHUNKS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHUNKS_CACHE.write_text(json.dumps(chunks, indent=2), encoding="utf-8")
    print(f"wrote {len(chunks)} chunks to {CHUNKS_CACHE}")
    return chunks


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "…"


def run(queries: list[str], pdf_path: Path, top_k: int) -> None:
    chunks = load_chunks(pdf_path)
    added = index_chunks(chunks)
    print(f"indexed {len(chunks)} chunks ({added} newly embedded)\n")

    for query in queries:
        print(f"Q: {query}")
        hits = hybrid_search(query, top_k=top_k)
        if not hits:
            print("  (no hits)\n")
            continue
        for rank, hit in enumerate(hits, start=1):
            print(
                f"  {rank}. {hit['source_file']}  p.{hit['page_num']}  "
                f"id={hit['chunk_id']}  table={hit['is_table']}  "
                f"score={hit['score']:.4f}"
            )
            print(f"     {snippet(hit['text'])}")
        print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    queries = args.queries or DEFAULT_QUERIES
    run(queries, args.pdf, args.top_k)


if __name__ == "__main__":
    main()
