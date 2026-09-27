# TechDoc Copilot

A citation-backed assistant for industrial troubleshooting. Upload a PDF manual, ask a question, and get an answer grounded in that document — with the source page and snippet shown next to the reply.

Built for ABB Accelerator 2026 (Theme 2). Retrieval and embeddings run locally. Generation uses the Gemini API free tier.

## Quick start

You need Python 3.10+, Node.js 18+, and a [Gemini API key](https://aistudio.google.com/apikey).

**API** (terminal 1):

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
```

Put your key in `backend/.env` as `GEMINI_API_KEY`, then:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

http://127.0.0.1:8000/health should return `{"status":"ok"}`.

**UI** (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The browser talks to the API on port 8000, so both processes need to stay running.

A small sample manual:

```bash
cd backend
python scripts/generate_sample_pdf.py
```

Upload `backend/data/raw/sample_drive_manual.pdf` in the UI, wait until the status bar says ready, then ask about the document.

## What’s in the repo

```
backend/     FastAPI app — ingest, search, grounded Q&A
frontend/    React (Vite) chat + evidence panel
docs/        Architecture notes
```

How the pieces connect is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Notes

- Answers are limited to retrieved chunks. If the PDF does not cover the question, the assistant should say it does not have enough information.
- Scanned pages need [Tesseract](https://github.com/tesseract-ocr/tesseract) on your PATH. Text PDFs work without it.
- First ingest downloads the local embedding model (`all-MiniLM-L6-v2`). Later runs reuse it.
- Set `GEMINI_MODEL=gemini-flash-latest` in `.env` if older Gemini 1.5 model names return 404.
- Large or fully scanned PDFs are slow to index; start with the sample file or a short text excerpt.
