"""Run loader -> OCR -> chunker on a sample PDF and print a sanity-check summary.

Usage (from the backend/ directory):

    python scripts/test_ingestion.py path/to/manual.pdf
    python scripts/test_ingestion.py path/to/manual.pdf --all

Requires PyMuPDF (in requirements.txt). Tesseract must be installed on PATH
for scanned pages; missing Tesseract logs a warning and continues.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.ingestion.chunker import chunk_pages  # noqa: E402
from app.ingestion.loader import load_document  # noqa: E402
from app.ingestion.ocr import ocr_pages  # noqa: E402

CHUNKS_CACHE = BACKEND_ROOT / "data" / "processed" / "chunks.json"

PREVIEW_CHARS = 400


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo the ingestion pipeline")
    parser.add_argument("pdf", type=Path, help="Path to a sample PDF manual")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print every chunk, not just the first two",
    )
    return parser.parse_args()


def _write_chunk_cache(chunks: list[dict]) -> None:
    CHUNKS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CHUNKS_CACHE.write_text(json.dumps(chunks, indent=2), encoding="utf-8")
    print(f"cached chunks: {CHUNKS_CACHE}")


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "…"


def run(pdf_path: Path, show_all: bool = False) -> None:
    pages = load_document(str(pdf_path))
    ocr_pages(pages)
    chunks = chunk_pages(pages)
    _write_chunk_cache(chunks)

    scanned = sum(1 for p in pages if p.get("is_scanned"))
    shown = chunks if show_all else chunks[:2]
    print(f"file:          {pdf_path.name}")
    print(f"total pages:   {len(pages)}")
    print(f"needed OCR:    {scanned}")
    print(f"total chunks:  {len(chunks)}")
    print()

    print("pages:")
    for page in pages:
        print(
            f"  p{page['page_num']}: scanned={page['is_scanned']} "
            f"chars={len(page.get('text') or '')} "
            f"images={len(page.get('images') or [])}"
        )
    print()

    for i, chunk in enumerate(shown, start=1):
        print(f"--- chunk {i} ---")
        print(f"chunk_id:     {chunk['chunk_id']}")
        print(f"source_file:  {chunk['source_file']}")
        print(f"page_num:     {chunk['page_num']}")
        print(f"is_table:     {chunk['is_table']}")
        print(f"text:         {preview(chunk['text'])}")
        print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    if not args.pdf.is_file():
        raise SystemExit(f"PDF not found: {args.pdf}")
    run(args.pdf, show_all=args.all)


if __name__ == "__main__":
    main()
