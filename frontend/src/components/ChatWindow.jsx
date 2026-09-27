import { useEffect, useRef } from "react";

export default function ChatWindow({
  messages,
  asking,
  ready,
  onAsk,
  onSelectCitation,
  selectedCitation,
}) {
  const logRef = useRef(null);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, asking]);

  function submit(event) {
    event.preventDefault();
    const field = event.target.elements.query;
    const text = field.value.trim();
    if (!text || asking || !ready) return;
    field.value = "";
    onAsk(text);
  }

  return (
    <section className="panel chat-panel">
      <h2>Answer</h2>
      <div className="chat-log" ref={logRef}>
        {messages.length === 0 && !asking ? (
          <p className="placeholder">
            {ready
              ? "Ask a question about the uploaded manual."
              : "Upload a document first. Chat stays off until indexing finishes."}
          </p>
        ) : (
          messages.map((msg, i) => (
            <Message
              key={i}
              msg={msg}
              selectedCitation={selectedCitation}
              onSelectCitation={onSelectCitation}
              onRetry={(q) => onAsk(q, { echoUser: false })}
            />
          ))
        )}
        {asking ? (
          <div className="bubble assistant loading">
            <span className="dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            Looking up the manual…
          </div>
        ) : null}
      </div>
      <form className="chat-form" onSubmit={submit}>
        <input
          name="query"
          type="text"
          autoComplete="off"
          placeholder={
            ready
              ? "Ask a troubleshooting question"
              : "Upload a PDF to enable chat"
          }
          disabled={!ready || asking}
        />
        <button type="submit" disabled={!ready || asking}>
          Send
        </button>
      </form>
    </section>
  );
}

function Message({ msg, selectedCitation, onSelectCitation, onRetry }) {
  if (msg.role === "user") {
    return (
      <div className="bubble user">
        <div className="bubble-label">You</div>
        <div>{msg.content}</div>
      </div>
    );
  }

  if (msg.error) {
    return (
      <div className="bubble assistant error">
        <div className="bubble-label">Error</div>
        <div>{msg.content}</div>
        {msg.retryQuery ? (
          <button type="button" className="retry" onClick={() => onRetry(msg.retryQuery)}>
            Retry
          </button>
        ) : null}
      </div>
    );
  }

  const citations = msg.citations || [];
  return (
    <div className="bubble assistant">
      <div className="bubble-label">Assistant</div>
      <div className="answer-text">{msg.content}</div>
      {citations.length > 0 ? (
        <div className="chips">
          {citations.map((cite) => {
            const active =
              selectedCitation && selectedCitation.chunk_id === cite.chunk_id;
            return (
              <button
                key={cite.chunk_id}
                type="button"
                className={active ? "chip active" : "chip"}
                onClick={() => onSelectCitation(cite)}
                title={`${cite.source_file} p.${cite.page_num}`}
              >
                Source: p.{cite.page_num}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
