import { useEffect, useState } from 'react';
import { api } from './api';
type Handoff = {
  item: {
    work_item_id: string;
    customer_id: string;
    customer_name?: string;
    status: string;
    priority: string;
    oversight?: {
      requested_at: string;
      requested_by: string;
      reason: string;
      item_note?: string;
      id: string;
    };
    business: {
      title: string;
      case_owner: string;
      current_decision_owner: string;
      waiting_on_department: string | null;
      impact_text: string;
    };
    event_history: { type?: string; at: string; rationale?: string }[];
  };
  documents: { document_id: string; file_hash: string }[];
};
export default function ManagementInbox({
  sid,
  revision,
  onOpen,
}: {
  sid: string;
  revision: unknown;
  onOpen: (id: string) => void;
}) {
  const [rows, setRows] = useState<Handoff[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    setLoading(true);
    void api<{ items: Handoff[] }>(`/document-workspace/sessions/${sid}/management-inbox`)
      .then((r) => {
        if (live) {
          setRows(
            [...r.items].sort(
              (a, b) =>
                Number(b.item.priority === 'High') - Number(a.item.priority === 'High') ||
                Number(b.item.status === 'Awaiting Financial Review') -
                  Number(a.item.status === 'Awaiting Financial Review') ||
                a.item.customer_id.localeCompare(b.item.customer_id),
            ),
          );
          setError('');
        }
      })
      .catch((e) => live && setError((e as Error).message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [sid, revision]);
  return (
    <section className="mw-inbox" aria-label="Sarah’s management inbox">
      <span className="mw-eyebrow">MANAGEMENT OVERSIGHT · READ ONLY</span>
      <h2>Sarah’s Management Inbox</h2>
      <p>
        Coordinate unresolved work. Finance and contractual authorities retain their decisions; a
        handoff is not an approval.
      </p>
      {loading && <p role="status">Retrieving persisted handoffs and original evidence…</p>}
      {error && (
        <p role="alert" className="mw-alert">
          {error}
        </p>
      )}
      <strong>{rows.length} oversight cases</strong>
      {!loading && !rows.length && <p>No cases have been handed off in this session.</p>}
      <div className="mw-inbox-grid">
        {rows.map(({ item: w, documents }) => {
          const legacy = w.event_history.filter((e) => e.type === 'escalated').at(-1);
          return (
            <article key={w.work_item_id}>
              <div className="mw-detail-top">
                <h3>{w.business.title}</h3>
                <span className="mw-priority">{w.priority}</span>
              </div>
              <p>
                {w.customer_name ?? w.customer_id} · {w.customer_id}
              </p>
              <dl>
                <div>
                  <dt>Case owner</dt>
                  <dd>{w.business.case_owner}</dd>
                </div>
                <div>
                  <dt>Management oversight</dt>
                  <dd>Sarah Chen</dd>
                </div>
                <div>
                  <dt>Current decision owner</dt>
                  <dd>{w.business.current_decision_owner}</dd>
                </div>
                <div>
                  <dt>Workflow status</dt>
                  <dd>{w.status}</dd>
                </div>
                <div>
                  <dt>Waiting on</dt>
                  <dd>{w.business.waiting_on_department ?? 'Management coordination'}</dd>
                </div>
                <div>
                  <dt>Potential impact</dt>
                  <dd>{w.business.impact_text}</dd>
                </div>
              </dl>
              <p>
                <strong>Escalation reason:</strong>{' '}
                {w.oversight?.reason ?? legacy?.rationale ?? 'Retained management escalation'}
              </p>
              {w.oversight?.item_note && (
                <p>
                  <strong>Item note:</strong> {w.oversight.item_note}
                </p>
              )}
              <small>
                {new Date(w.oversight?.requested_at ?? legacy?.at ?? '').toLocaleString()} ·{' '}
                {w.oversight?.requested_by ?? 'Retained audit attribution'}
              </small>
              <div className="mw-command-row">
                <button onClick={() => onOpen(w.work_item_id)}>View case &amp; full history</button>
              </div>
              <details>
                <summary>Original supporting PDFs ({documents.length})</summary>
                {documents.map((d) => (
                  <p key={d.file_hash}>
                    <a
                      href={`/api/document-workspace/sessions/${sid}/evidence/${d.file_hash}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {d.document_id} ↗
                    </a>
                  </p>
                ))}
              </details>
            </article>
          );
        })}
      </div>
      <p className="mw-inbox-boundary">
        Read-only presentation view, not authenticated role-based access control. No budget, credit,
        invoice, export or contract authorization is granted here.
      </p>
    </section>
  );
}
