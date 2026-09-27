# Architecture

TechDoc Copilot is a local-first RAG loop for industrial troubleshooting. The pitch is not “a smarter chatbot.” It is **an answer you can audit**: retrieved passages, constrained generation, and a UI that shows the proof next to the claim.

## Pipeline

```
Ingest          Index                 Retrieve              Answer
------          -----                 --------              ------
PDF upload  ->  MiniLM + Chroma   ->  dense k-NN        ->  Gemini Flash
PyMuPDF         BM25 in-memory        BM25 keyword          context = chunks only
Tesseract OCR   chunk metadata        RRF fusion            citations from chunk_id
table chunker   {source, page, id}    top_k hits            snippet for Proof pane
```

### 1. Ingest

| Stage | Module | Job |
| --- | --- | --- |
| Load | `backend/app/ingestion/loader.py` | PyMuPDF text; flag sparse pages; list embedded images by `xref` (bytes not stored) |
| OCR | `backend/app/ingestion/ocr.py` | Rasterize scanned pages; Tesseract; never crash the pipeline |
| Chunk | `backend/app/ingestion/chunker.py` | ~400 word windows, 50 overlap; keep table-like blocks whole |

Chunk contract (fixed):

```
{ text, source_file, page_num, chunk_id, is_table }
```

`chunk_id` looks like `sample_drive_manual-p2-1`. That id is the citation key all the way to the UI.

Corrupt, empty, encrypted, or non-PDF uploads fail with a short JSON `detail`, not a stack trace.

### 2. Index

- **Dense:** Chroma `PersistentClient` under `CHROMA_PERSIST_DIR`, embeddings `all-MiniLM-L6-v2` (local, free). Skip existing `source_file::chunk_id`.
- **Sparse:** `rank_bm25.BM25Okapi` in memory. Tokens keep codes like `3210` / `E04`. After process restart, BM25 is rebuilt from Chroma on first search.

### 3. Retrieve

`hybrid_search(query, top_k=5)` (signature frozen):

1. Query Chroma and BM25 for extra candidates.
2. Reciprocal rank fusion (`1 / (60 + rank)`).
3. Dedupe on `chunk_id`.
4. Return `{ text, source_file, page_num, chunk_id, is_table, score }`.

### 4. Answer

`generate_answer(query, chunks)` (signature frozen):

- Prompt contains **only** retrieved chunk text.
- Instructs: answer from context, or exactly *I don't have enough information in the provided documents*.
- Parses JSON `{ answer, cited_chunk_ids }`; drops ids not in the retrieved set.
- Gemini timeout / rate limit / missing key → that message as `answer`, empty `citations` (HTTP still 200 so the contract stays `{ answer, citations }`). The UI treats those strings as retryable errors.

`POST /ask` adds `snippet` (~150 chars) so the Proof pane does not need a second lookup.

## Why these tools (all free)

| Piece | Choice | Why |
| --- | --- | --- |
| PDF | PyMuPDF | Local, no API |
| OCR | Tesseract | Optional system binary; skip if missing |
| Embeddings | sentence-transformers MiniLM | On-device, no paid vector API |
| Vectors | Chroma persist | Local disk, no hosted DB |
| Keyword | rank-bm25 | Catches fault codes dense search can miss |
| Fusion | RRF | No extra model, no weight tuning |
| LLM | Gemini Flash free tier | Grounded generation only; not used for embeddings |
| UI | React + Vite + CSS | No paid component kit |

Paid APIs, hosted vector DBs, and closed UI kits are out of scope for this prototype.

## Citation / evidence data flow

```
chunker metadata
    -> Chroma metadatas + BM25 payload
    -> hybrid_search hit
    -> generate_answer citations { chunk_id, source_file, page_num }
    -> /ask adds snippet from the hit text
    -> ChatWindow chips "Source: p.{page_num}"
    -> EvidenceViewer Proof card: file, page, chunk_id, snippet
```

The Proof panel is labeled **From the manual — not the model**. That split is the product: the left column is the answer; the right column is the passage it used.

## API surface

- `POST /ingest` — multipart PDF, max 25 MB, must start with `%PDF`. Success: `{ status, filename }` plus `chunks` / `newly_embedded`.
- `POST /ask` — `{ query }` (non-empty, max 2000 chars). Success: `{ answer, citations[] }`.
- Failures: `{ detail: string }` with 4xx/5xx. No raw tracebacks to the client.

CORS allows `http://localhost:5173`.
