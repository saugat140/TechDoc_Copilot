from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.ingestion import ingest_pdf
from app.qa.answer import generate_answer
from app.retrieval.hybrid import hybrid_search, index_chunks

logger = logging.getLogger(__name__)

router = APIRouter()

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = BACKEND_ROOT / "data" / "raw"
SNIPPET_CHARS = 150
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_QUERY_CHARS = 2000
PDF_MAGIC = b"%PDF"
ASK_TIMEOUT_S = 90
INGEST_TIMEOUT_S = 180

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class Question(BaseModel):
    query: str = Field(..., max_length=MAX_QUERY_CHARS)

    @field_validator("query")
    @classmethod
    def query_must_be_nonempty(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("query is required")
        return text


@router.post("/ingest")
async def ingest_document(file: UploadFile):
    """Save the PDF, run loader -> ocr -> chunker, then index Chroma + BM25.

    Response keeps filename/status and adds chunk counts so the UI can confirm ingest.
    """
    filename = file.filename or "upload.pdf"
    suffix = Path(filename).suffix.lower()
    content_type = (file.content_type or "").lower()
    if suffix != ".pdf" and content_type not in {"application/pdf", "application/x-pdf"}:
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail="PDF is too large (max 25 MB). Use a shorter excerpt for the demo.",
        )
    if not payload.lstrip().startswith(PDF_MAGIC):
        raise HTTPException(status_code=400, detail="File is not a valid PDF")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = _unique_dest(filename)
    try:
        dest.write_bytes(payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not save the PDF (file is open in Cursor or another app). "
                "Close it and retry."
            ),
        ) from exc

    try:
        chunks = await asyncio.wait_for(
            asyncio.to_thread(ingest_pdf, str(dest)),
            timeout=INGEST_TIMEOUT_S,
        )
        if not chunks:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No text could be extracted. The PDF may be scanned "
                    "(install Tesseract) or empty."
                ),
            )
        added = await asyncio.wait_for(
            asyncio.to_thread(index_chunks, chunks),
            timeout=INGEST_TIMEOUT_S,
        )
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Ingest timed out. Use a smaller, text-based PDF.",
        ) from exc
    except Exception:
        logger.exception("Ingest failed for %s", filename)
        raise HTTPException(
            status_code=500,
            detail="Ingest failed. Try a smaller text-based PDF.",
        ) from None

    return {
        "status": "indexed",
        "filename": filename,
        "chunks": len(chunks),
        "newly_embedded": added,
    }


@router.post("/ask")
async def ask(question: Question):
    """hybrid_search -> generate_answer. Citations include a ~150 char snippet."""
    query = question.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    try:
        hits = await asyncio.wait_for(
            asyncio.to_thread(hybrid_search, query, 5),
            timeout=ASK_TIMEOUT_S,
        )
        result = await asyncio.wait_for(
            asyncio.to_thread(generate_answer, query, hits),
            timeout=ASK_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="The question timed out. Retry, or ask a shorter question.",
        ) from exc
    except Exception:
        logger.exception("Ask failed")
        raise HTTPException(
            status_code=500,
            detail="Could not answer right now. Please retry.",
        ) from None

    by_id = {h["chunk_id"]: h for h in hits}

    citations = []
    for cite in result.get("citations") or []:
        chunk = by_id.get(cite["chunk_id"], {})
        citations.append(
            {
                "chunk_id": cite["chunk_id"],
                "source_file": cite.get("source_file", ""),
                "page_num": cite.get("page_num", 0),
                "snippet": _snippet(chunk.get("text") or ""),
            }
        )
    return {"answer": result.get("answer") or "", "citations": citations}


def _safe_filename(name: str) -> str:
    stem = Path(name).name
    cleaned = _SAFE_NAME.sub("_", stem)
    return cleaned or "upload.pdf"


def _unique_dest(name: str) -> Path:
    """Write ingest copies under a unique name so a locked sample PDF is never overwritten."""
    safe = Path(_safe_filename(name))
    return RAW_DIR / f"{safe.stem}_{uuid.uuid4().hex[:8]}{safe.suffix or '.pdf'}"


def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "…"
