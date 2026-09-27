"""Load PDF manuals into per-page records via PyMuPDF.

Each page is a dict with this stable shape (used by ocr.py and chunker.py):

    {
        "page_num": int,          # 1-based page index
        "text": str,              # native extractable text (may be empty)
        "is_scanned": bool,       # True when native text is too sparse for retrieval
        "images": list[dict],     # embedded diagrams; see extract_page_images()
        "source_file": str,       # filename only, e.g. "ACS880_manual.pdf"
        "source_path": str,       # path passed to load_document(), for OCR rasterize
    }
"""

from __future__ import annotations

import logging
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

# Pages with fewer than this many stripped characters are treated as scanned.
MIN_NATIVE_TEXT_CHARS = 50


def load_document(path: str) -> list[dict]:
    """Open a PDF and return one record per page.

    Native text is extracted where present. Image-only / scanned pages are
    flagged with is_scanned=True so ocr.py can rasterize them. Embedded
    images are listed (not inlined as bytes) so diagrams can be looked up
    later by xref + page_num.
    """
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    source_file = pdf_path.name
    source_path = str(pdf_path)
    pages: list[dict] = []

    try:
        doc = fitz.open(source_path)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "This file could not be opened as a PDF. It may be corrupt or not a PDF."
        ) from exc

    try:
        if getattr(doc, "is_encrypted", False) and getattr(doc, "needs_pass", True):
            raise ValueError("Password-protected PDFs are not supported.")
        if doc.page_count == 0:
            raise ValueError("The PDF has no pages.")

        for index, page in enumerate(doc):
            page_num = index + 1
            text = extract_page_text(page)
            images = extract_page_images(doc, page, page_num)
            scanned = is_scanned_page(text)
            if scanned:
                logger.info(
                    "Page %s of %s flagged for OCR (%s native chars)",
                    page_num,
                    source_file,
                    len(text.strip()),
                )
            pages.append(
                {
                    "page_num": page_num,
                    "text": text,
                    "is_scanned": scanned,
                    "images": images,
                    "source_file": source_file,
                    "source_path": source_path,
                }
            )
    finally:
        doc.close()

    logger.info("Loaded %s pages from %s", len(pages), source_file)
    return pages


def extract_page_text(page: fitz.Page) -> str:
    """Return native text from a PyMuPDF page, stripped of trailing whitespace."""
    return (page.get_text("text") or "").strip()


def is_scanned_page(text: str, min_chars: int = MIN_NATIVE_TEXT_CHARS) -> bool:
    """True when the page has too little extractable text to use as-is."""
    return len(text.strip()) < min_chars


def extract_page_images(
    doc: fitz.Document, page: fitz.Page, page_num: int
) -> list[dict]:
    """List embedded images on a page for later diagram lookup.

    Each image dict:
        page_num, index, xref, width, height, ext
    Bytes are not stored here — re-extract with doc.extract_image(xref).
    """
    images: list[dict] = []
    for index, img in enumerate(page.get_images(full=True)):
        xref = img[0]
        try:
            extracted = doc.extract_image(xref)
        except Exception as exc:  # noqa: BLE001 — skip unreadable xrefs
            logger.warning(
                "Could not extract image xref=%s on page %s: %s",
                xref,
                page_num,
                exc,
            )
            continue
        images.append(
            {
                "page_num": page_num,
                "index": index,
                "xref": xref,
                "width": extracted.get("width", img[2]),
                "height": extracted.get("height", img[3]),
                "ext": extracted.get("ext", "png"),
            }
        )
    return images
