from app.ingestion.chunker import chunk_pages
from app.ingestion.loader import load_document
from app.ingestion.ocr import ocr_pages


def ingest_pdf(path: str) -> list[dict]:
    """Load, OCR scanned pages, and chunk. Returns the chunk list for retrieval."""
    pages = load_document(path)
    ocr_pages(pages)
    return chunk_pages(pages)


__all__ = ["load_document", "ocr_pages", "chunk_pages", "ingest_pdf"]
