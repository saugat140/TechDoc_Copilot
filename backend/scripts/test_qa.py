"""End-to-end grounded Q&A demo: ingest a sample PDF, ask, print citations.

Usage (from the backend/ directory):

    python scripts/test_qa.py
    python scripts/test_qa.py --pdf data/raw/sample_drive_manual.pdf

Requires GEMINI_API_KEY in backend/.env (Gemini free tier).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.ingestion import ingest_pdf  # noqa: E402
from app.qa.answer import generate_answer  # noqa: E402
from app.retrieval.hybrid import hybrid_search, index_chunks  # noqa: E402

DEFAULT_PDF = BACKEND_ROOT / "data" / "raw" / "sample_drive_manual.pdf"

# Last question is intentionally unanswerable from the sample excerpt.
DEFAULT_QUERIES = [
    "What does fault 3210 mean and what should I check first?",
    "The drive trips on DC overvoltage during deceleration. What should I do?",
    "STO inputs are open. What is the first check?",
    "How do I inspect the brake resistor for an open circuit?",
    "What is the gearbox oil change interval for this drive?",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo grounded Q&A")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def run(pdf_path: Path, queries: list[str], top_k: int) -> None:
    if not pdf_path.is_file():
        raise SystemExit(
            f"PDF not found: {pdf_path}\nRun: python scripts/generate_sample_pdf.py"
        )

    print(f"ingesting {pdf_path.name} …")
    chunks = ingest_pdf(str(pdf_path))
    added = index_chunks(chunks)
    print(f"indexed {len(chunks)} chunks ({added} newly embedded)\n")

    for query in queries:
        print(f"Q: {query}")
        hits = hybrid_search(query, top_k=top_k)
        result = generate_answer(query, hits)
        print(f"A: {result['answer']}\n")
        cites = result.get("citations") or []
        if not cites:
            print("  citations: (none)")
        for cite in cites:
            print(
                f"  - {cite['source_file']} p.{cite['page_num']}  id={cite['chunk_id']}"
            )
        print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    run(args.pdf, args.queries or DEFAULT_QUERIES, args.top_k)


if __name__ == "__main__":
    main()
