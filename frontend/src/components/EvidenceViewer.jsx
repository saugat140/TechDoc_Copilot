export default function EvidenceViewer({ citation }) {
  return (
    <section className="panel evidence-panel">
      <h2>Proof</h2>
      <div className="evidence-body">
        {citation ? (
          <article className="proof-card">
            <p className="proof-kicker">From the manual — not the model</p>
            <dl className="proof-meta">
              <div>
                <dt>File</dt>
                <dd>{citation.source_file || "—"}</dd>
              </div>
              <div>
                <dt>Page</dt>
                <dd>{citation.page_num}</dd>
              </div>
              <div>
                <dt>Chunk</dt>
                <dd>{citation.chunk_id}</dd>
              </div>
            </dl>
            <blockquote className="proof-snippet">
              {citation.snippet || "No snippet returned for this citation."}
            </blockquote>
          </article>
        ) : (
          <p className="placeholder">
            Click a <strong>Source: p.#</strong> chip on an answer to inspect the
            exact passage it used.
          </p>
        )}
      </div>
    </section>
  );
}
