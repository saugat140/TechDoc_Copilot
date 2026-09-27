"""Tesseract OCR for scanned / image-only PDF pages.

Pipeline entry: ocr_pages(pages) rasterizes each is_scanned page, runs
Tesseract, and writes the result back into page["text"]. Failures log a
warning and leave the existing text in place — they never raise.
"""

from __future__ import annotations

import logging
from typing import Any

import fitz
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

# ~144 DPI; enough for body text without huge pixmaps.
RASTER_ZOOM = 2.0

# If OCR output is long but mostly non-alphanumeric, treat as garbled.
GARBLE_MIN_LEN = 30
GARBLE_ALNUM_RATIO = 0.3


def ocr_pages(pages: list[dict], source_path: str | None = None) -> list[dict]:
    """Run OCR on pages flagged is_scanned; return the same list mutated in place.

    source_path defaults to pages[0]["source_path"] from loader.load_document().
    Non-scanned pages are left unchanged.
    """
    scanned = [p for p in pages if p.get("is_scanned")]
    if not scanned:
        return pages or []

    path = source_path or scanned[0].get("source_path") or pages[0].get("source_path")
    if not path:
        logger.warning("No source_path for OCR; skipping %s scanned pages", len(scanned))
        return pages

    if not tesseract_available():
        logger.warning(
            "Tesseract binary not found on PATH; skipping OCR on %s pages",
            len(scanned),
        )
        return pages

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reopen PDF for OCR (%s): %s", path, exc)
        return pages

    try:
        for page in scanned:
            page_num = page["page_num"]
            try:
                image = rasterize_page(doc, page_num)
                ocr_text = ocr_page(image)
            except Exception as exc:  # noqa: BLE001 — never crash the pipeline
                logger.warning("OCR failed on page %s of %s: %s", page_num, path, exc)
                continue

            if not ocr_text.strip():
                logger.warning("OCR produced empty text on page %s of %s", page_num, path)
                continue
            if is_garbled(ocr_text):
                logger.warning(
                    "OCR text looks garbled on page %s of %s; keeping it anyway",
                    page_num,
                    path,
                )
            page["text"] = ocr_text
    finally:
        doc.close()

    return pages


def tesseract_available() -> bool:
    """True when the Tesseract binary can be invoked."""
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return False
    except Exception:  # noqa: BLE001
        return False
    return True


def rasterize_page(doc: fitz.Document, page_num: int) -> Image.Image:
    """Render a 1-based page to an RGB PIL image."""
    page = doc.load_page(page_num - 1)
    matrix = fitz.Matrix(RASTER_ZOOM, RASTER_ZOOM)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def ocr_page(image: Any) -> str:
    """Run Tesseract on a PIL Image (or anything image_to_string accepts).

    Returns empty string on Tesseract errors so callers can log and continue.
    """
    try:
        text = pytesseract.image_to_string(image) or ""
    except pytesseract.TesseractNotFoundError:
        logger.warning(
            "Tesseract binary not found on PATH; install Tesseract OCR locally"
        )
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tesseract raised: %s", exc)
        return ""
    return text.strip()


def is_garbled(text: str) -> bool:
    """Heuristic: long strings with very few letters/digits are likely OCR junk."""
    stripped = text.strip()
    if len(stripped) < GARBLE_MIN_LEN:
        return False
    alnum = sum(1 for ch in stripped if ch.isalnum())
    return (alnum / len(stripped)) < GARBLE_ALNUM_RATIO
