"""Grounded generation with citations via Gemini (free tier).

Return schema (stable — frontend /ask renders this directly):

    {
        "answer": str,
        "citations": [
            {"chunk_id": str, "source_file": str, "page_num": int}
        ]
    }

Routes add a `snippet` field on each citation for the evidence viewer.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from google.api_core import exceptions as google_exceptions

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")

FALLBACK = "I don't have enough information in the provided documents"
# 1.5-flash was retired on many free-tier keys (404). Prefer current Flash IDs.
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
GEMINI_FALLBACK_MODELS = (
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
)
REQUEST_TIMEOUT_S = 45

_CITATION_RE = re.compile(r"\[([A-Za-z0-9._-]+-p\d+-\d+)\]")

_model: genai.GenerativeModel | None = None
_model_name: str | None = None
_working_model: str | None = None


def generate_answer(query: str, chunks: list[dict]) -> dict:
    """Generate an answer strictly from retrieved chunks.

    Returns {"answer": str, "citations": [{"chunk_id", "source_file", "page_num"}]}.
    Citations are taken only from chunks that appear in the prompt — never invented.
    """
    if not chunks:
        return {"answer": FALLBACK, "citations": []}
    query = (query or "").strip()
    if not query:
        return {"answer": FALLBACK, "citations": []}

    by_id = {c["chunk_id"]: c for c in chunks if c.get("chunk_id")}
    prompt = build_prompt(query, chunks)

    try:
        raw = _call_gemini(prompt)
    except _GeminiError as exc:
        logger.warning("Gemini failed: %s", exc)
        return {"answer": str(exc), "citations": []}

    parsed = parse_llm_response(raw, by_id)
    return parsed


def build_prompt(query: str, chunks: list[dict]) -> str:
    """Prompt that forbids outside knowledge and requires chunk_id citations."""
    blocks = []
    for chunk in chunks:
        blocks.append(
            f"[chunk_id={chunk['chunk_id']} | source={chunk['source_file']} "
            f"| page={chunk['page_num']}]\n{chunk.get('text') or ''}"
        )
    context = "\n\n".join(blocks)
    return (
        "You are a grounded industrial troubleshooting assistant.\n"
        "Use ONLY the context chunks below. Do not use outside knowledge. "
        "Do not guess or fill gaps from general drive/PLC expertise.\n"
        f'If the context does not answer the question, set answer to exactly: "{FALLBACK}" '
        "and set cited_chunk_ids to an empty list.\n"
        "When the context does answer, cite the chunk_id of every chunk you used "
        "both in cited_chunk_ids and inline in the answer as [chunk_id].\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        "Respond with JSON only, no markdown fences, in this shape:\n"
        '{"answer": "<string>", "cited_chunk_ids": ["<chunk_id>", ...]}'
    )


def parse_llm_response(raw: str, by_id: dict[str, dict]) -> dict:
    """Extract answer + citations; drop any chunk_id not in the retrieved set."""
    payload = _extract_json(raw) or {}
    answer = str(payload.get("answer") or raw or "").strip()
    cited_ids = payload.get("cited_chunk_ids") or []
    if not isinstance(cited_ids, list):
        cited_ids = []
    cited_ids = [str(cid) for cid in cited_ids]

    if not cited_ids:
        cited_ids = _CITATION_RE.findall(answer)

    if FALLBACK.lower() in answer.lower():
        return {"answer": FALLBACK, "citations": []}

    citations = []
    seen: set[str] = set()
    for cid in cited_ids:
        if cid in seen or cid not in by_id:
            continue
        seen.add(cid)
        chunk = by_id[cid]
        citations.append(
            {
                "chunk_id": cid,
                "source_file": chunk.get("source_file", ""),
                "page_num": int(chunk.get("page_num", 0)),
            }
        )
    return {"answer": answer, "citations": citations}


class _GeminiError(Exception):
    """User-facing Gemini failure; generate_answer converts this to an answer string."""


def _call_gemini(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key or api_key in {"your_key_here", ""}:
        raise _GeminiError(
            "Gemini API key is missing. Set GEMINI_API_KEY in backend/.env."
        )

    try:
        return _generate_with_fallback(api_key, prompt)
    except google_exceptions.ResourceExhausted as exc:
        raise _GeminiError(
            "Gemini rate limit reached. Wait a minute and try again."
        ) from exc
    except (google_exceptions.DeadlineExceeded, TimeoutError) as exc:
        raise _GeminiError(
            "Gemini timed out. Try a shorter question, or retry."
        ) from exc
    except google_exceptions.ServiceUnavailable as exc:
        raise _GeminiError(
            "Gemini is temporarily unavailable. Please retry."
        ) from exc
    except google_exceptions.GoogleAPIError as exc:
        raise _GeminiError(f"Gemini API error: {exc}") from exc
    except ValueError as exc:
        # Empty/blocked candidates — response.text raises ValueError.
        raise _GeminiError(
            "Gemini returned no usable text (often a safety block). Please retry."
        ) from exc
    except _GeminiError:
        raise
    except Exception as exc:  # noqa: BLE001 — never crash the /ask path
        raise _GeminiError(f"Gemini request failed: {exc}") from exc


def _generate_with_fallback(api_key: str, prompt: str) -> str:
    last_error: Exception | None = None
    for name in _model_candidates():
        try:
            model = _get_model(api_key, name)
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
                request_options={"timeout": REQUEST_TIMEOUT_S},
            )
            text = (response.text or "").strip()
            global _working_model
            _working_model = name
            return text
        except google_exceptions.NotFound as exc:
            last_error = exc
            logger.warning("Gemini model %s not found; trying next", name)
            _reset_model()
            continue
        except google_exceptions.GoogleAPIError as exc:
            message = str(exc)
            if "404" in message and "not found" in message.lower():
                last_error = exc
                logger.warning("Gemini model %s not found; trying next", name)
                _reset_model()
                continue
            raise
    raise _GeminiError(
        f"No supported Gemini Flash model on this API key. Last error: {last_error}"
    )


def _model_candidates() -> list[str]:
    preferred = (
        _working_model
        or os.getenv("GEMINI_MODEL")
        or DEFAULT_GEMINI_MODEL
    )
    ordered = [preferred, *GEMINI_FALLBACK_MODELS]
    seen: set[str] = set()
    unique: list[str] = []
    for name in ordered:
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def _get_model(api_key: str, name: str) -> genai.GenerativeModel:
    global _model, _model_name
    if _model is None or _model_name != name:
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(name)
        _model_name = name
        logger.info("Initialized Gemini model %s", name)
    return _model


def _reset_model() -> None:
    global _model, _model_name
    _model = None
    _model_name = None


def _extract_json(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
