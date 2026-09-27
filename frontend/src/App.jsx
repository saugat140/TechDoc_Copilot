import { useState } from "react";
import ChatWindow from "./components/ChatWindow.jsx";
import EvidenceViewer from "./components/EvidenceViewer.jsx";

const API_BASE = "http://localhost:8000";
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const INGEST_TIMEOUT_MS = 180000;
const ASK_TIMEOUT_MS = 90000;

const SERVICE_ERROR = /gemini (rate limit|timed out|api key is missing|temporarily unavailable|request failed)|timed out|cannot reach the api/i;

export default function App() {
  const [messages, setMessages] = useState([]);
  const [ingest, setIngest] = useState({ phase: "idle", filename: "", detail: "" });
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [asking, setAsking] = useState(false);

  const ready = ingest.phase === "ready";

  async function handleIngest(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setIngest({
        phase: "error",
        filename: file.name,
        detail: "Only PDF files are supported",
      });
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setIngest({
        phase: "error",
        filename: file.name,
        detail: "PDF is too large (max 25 MB)",
      });
      return;
    }

    setIngest({ phase: "uploading", filename: file.name, detail: "" });
    setSelectedCitation(null);

    const form = new FormData();
    form.append("file", file);
    setIngest({ phase: "processing", filename: file.name, detail: "" });

    try {
      const { res, data } = await fetchJson(
        `${API_BASE}/ingest`,
        { method: "POST", body: form },
        INGEST_TIMEOUT_MS
      );
      if (!res.ok) {
        throw new Error(errorDetail(data, `Upload failed (${res.status})`));
      }
      const extra = data.chunks != null ? `${data.chunks} chunks indexed` : data.status;
      setIngest({
        phase: "ready",
        filename: data.filename || file.name,
        detail: extra,
      });
    } catch (err) {
      setIngest({
        phase: "error",
        filename: file.name,
        detail: err.message || "Ingest failed",
      });
    }
  }

  async function handleAsk(query, { echoUser = true } = {}) {
    const text = query.trim();
    if (!text || asking) return;

    if (echoUser) {
      setMessages((prev) => [...prev, { role: "user", content: text }]);
    }
    setAsking(true);
    try {
      const { res, data } = await fetchJson(
        `${API_BASE}/ask`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: text }),
        },
        ASK_TIMEOUT_MS
      );
      if (!res.ok) {
        throw new Error(errorDetail(data, `Ask failed (${res.status})`));
      }
      const answer = data.answer || "";
      const citations = data.citations ?? [];
      if (SERVICE_ERROR.test(answer)) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: answer, error: true, retryQuery: text },
        ]);
        return;
      }
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: answer, citations },
      ]);
      if (citations.length) {
        setSelectedCitation(citations[0]);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: err.message || "Request failed",
          error: true,
          retryQuery: text,
        },
      ]);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>TechDoc Copilot</h1>
          <p>Grounded answers from your manuals — every claim has a page.</p>
        </div>
        <label className="upload">
          <span>Upload PDF</span>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleIngest(file);
              e.target.value = "";
            }}
          />
        </label>
      </header>

      <div className={`ingest-bar ingest-${ingest.phase}`} role="status">
        <IngestStatus ingest={ingest} />
      </div>

      <div className="layout">
        <ChatWindow
          messages={messages}
          asking={asking}
          ready={ready}
          onAsk={handleAsk}
          onSelectCitation={setSelectedCitation}
          selectedCitation={selectedCitation}
        />
        <EvidenceViewer citation={selectedCitation} />
      </div>
    </div>
  );
}

function IngestStatus({ ingest }) {
  if (ingest.phase === "idle") {
    return <span>Upload a PDF manual before asking questions.</span>;
  }
  if (ingest.phase === "uploading") {
    return <span>Uploading {ingest.filename}…</span>;
  }
  if (ingest.phase === "processing") {
    return (
      <span>
        Processing {ingest.filename} (chunk + index)… you can ask when this finishes.
      </span>
    );
  }
  if (ingest.phase === "error") {
    return <span>Ingest failed: {ingest.detail}. Choose another PDF to retry.</span>;
  }
  return (
    <span>
      Ready — {ingest.filename}
      {ingest.detail ? ` (${ingest.detail})` : ""}. Ask a troubleshooting question.
    </span>
  );
}

function errorDetail(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "string" ? item : item.msg || JSON.stringify(item)))
      .join("; ");
  }
  return fallback;
}

async function fetchJson(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    const data = await res.json().catch(() => ({}));
    return { res, data };
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("Request timed out. Please retry.");
    }
    throw new Error(
      "Cannot reach the API at localhost:8000. Start uvicorn, then retry."
    );
  } finally {
    clearTimeout(timer);
  }
}
