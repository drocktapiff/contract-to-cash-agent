import { useEffect, useRef, useState } from 'react';
import { api, bootstrapSession, setCsrf } from './api';
import './document-workspace.css';

type Evidence = {
  file_hash: string;
  document_id: string;
  page: number;
  text: string;
  source_record_reference: string;
};
type Recommendation = {
  source: string;
  disposition: string;
  suggested_action: string;
  why: string;
  supporting_documents: string[];
  human_judgment: string;
};
type Work = {
  work_item_id: string;
  customer_id: string;
  customer_name?: string;
  contract_id: string;
  business_object_type: string;
  category: string;
  required_action: string;
  priority: string;
  assigned_owner: string;
  status: string;
  version: number;
  automation_eligible: boolean;
  human_review_required: boolean;
  eligibility_reason: string;
  financial_impact: Record<string, string> | null;
  evidence: Evidence[];
  recommendation: Recommendation;
  event_history: Event[];
  supporting_facts: Record<string, unknown>;
};
type Event = {
  id?: string;
  type?: string;
  event?: string;
  at: string;
  actor?: string;
  actor_kind?: string;
  rationale?: string;
  before?: string;
  after?: string;
  financial_action_executed?: boolean;
};
type Source = {
  document_id: string;
  file_hash: string;
  filename: string;
  document_type: string;
  fields: Record<string, string>;
  errors: string[];
};
type Snapshot = {
  session_id: string | null;
  active_session_id: string | null;
  read_only?: boolean;
  processing_active?: boolean;
  sessions: { id: string; created_at: string }[];
  items: Work[];
  metrics: Record<string, number>;
  telemetry: {
    human_interaction_count?: number;
    routine_completion_rate?: number;
    human_exception_rate?: number;
    escalation_rate?: number;
    error_count?: number;
    retry_count?: number;
    processing_duration_seconds?: number;
    intake_duration_seconds?: number;
    api_cost_usd?: string;
  };
  document_count?: number;
  customer_count?: number;
  provenance?: string;
};
type Detail = { item: Work; documents: Source[]; permitted_actions: string[]; read_only: boolean };
type Result = Record<string, number | string>;
type Action = { mode: string; label: string; item?: Work };
const labels: Record<string, string> = {
  auto: 'Auto Complete',
  routine: 'Complete routine check',
  request_evidence: 'Request more evidence',
  escalate: 'Escalate to Sarah',
  financial_review: 'Mark for authorized financial review',
  accept: 'Accept suggested workflow disposition',
  reject: 'Reject recommendation',
  review: 'Route to Maya for review',
  auto_all: 'Auto Complete All',
  load: 'Load Sample Documents',
  restart: 'Restart Demo',
};
const statuses: Record<string, string> = {
  Closed: 'Completed — administrative check',
  'Ready for Processing': 'Ready for processing',
};
const title = (s: string) => s.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());

export default function DocumentWorkspace() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [detail, setDetail] = useState<Detail | null>(null);
  const [filter, setFilter] = useState('All'),
    [search, setSearch] = useState(''),
    [limit, setLimit] = useState(25);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('');
  const [action, setAction] = useState<Action | null>(null),
    [actor, setActor] = useState('Local operator'),
    [rationale, setRationale] = useState(''),
    [evidence, setEvidence] = useState<string[]>([]),
    [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<Result | null>(null),
    [readOnly, setReadOnly] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    actionDialog = useRef<HTMLDialogElement>(null),
    opener = useRef<HTMLElement | null>(null);
  const lastRequest = useRef<{ key: string; body: object } | null>(null);
  const disabled = busy || readOnly || !!snapshot?.read_only || !!snapshot?.processing_active;
  async function refresh(sid?: string) {
    const next = await api<Snapshot>(
      sid ? `/document-workspace/sessions/${sid}` : '/document-workspace',
    );
    setSnapshot(next);
    return next;
  }
  useEffect(() => {
    let live = true;
    void bootstrapSession()
      .then((s) => {
        setCsrf(s.csrf_token);
        if (!live) return;
        setActor(s.reviewer ?? 'Local operator');
        setReadOnly(!s.authenticated || s.mode !== 'operator');
        return refresh();
      })
      .catch((e) => live && setError((e as Error).message));
    const expired = () => {
      setReadOnly(true);
      setError('Local session expired. Reload to reconnect; retained work is unchanged.');
    };
    window.addEventListener('ctc-session-expired', expired);
    return () => {
      live = false;
      window.removeEventListener('ctc-session-expired', expired);
    };
  }, []);
  useEffect(() => {
    if (!snapshot?.processing_active) return;
    const id = window.setInterval(() => {
      void refresh().catch((e) => setError((e as Error).message));
    }, 1500);
    return () => window.clearInterval(id);
  }, [snapshot?.processing_active]);
  useEffect(() => {
    if (detail) dialog.current?.showModal();
    else dialog.current?.close();
  }, [detail]);
  useEffect(() => {
    if (action) actionDialog.current?.showModal();
    else actionDialog.current?.close();
  }, [action]);
  function begin(mode: string, item?: Work) {
    setError('');
    setAction({
      mode,
      label: mode === 'routine' && !item ? 'Process Routine Work' : labels[mode],
      item,
    });
    setConfirmed(false);
    setEvidence([]);
    setRationale(
      mode === 'routine' && !item
        ? 'Revalidate and complete eligible read-only checks.'
        : mode === 'load'
          ? 'Load synthetic source PDFs into an isolated, unprocessed session.'
          : mode === 'restart'
            ? 'Create a fresh unprocessed session; retain the previous session and its audit history.'
            : '',
    );
  }
  async function openItem(work: Work, target?: HTMLElement) {
    setError('');
    if (target) opener.current = target;
    try {
      setDetail(
        await api<Detail>(
          `/document-workspace/sessions/${snapshot!.session_id}/items/${work.work_item_id}`,
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function closeDetail() {
    setDetail(null);
    opener.current?.focus();
  }
  async function submit() {
    if (!action || !confirmed || !actor.trim() || !rationale.trim()) return;
    setBusy(true);
    setError('');
    setResult(null);
    setNotice('Revalidating original PDF evidence and applying permitted workflow dispositions…');
    const sid = snapshot?.active_session_id,
      a = action;
    const fields = {
      actor: actor.trim(),
      rationale: rationale.trim(),
      confirmation: 'ADMINISTRATIVE WORKFLOW ONLY',
      expected_session: sid ?? null,
      expected_version: a.item?.version ?? null,
      evidence_hashes: evidence,
    };
    const key = JSON.stringify([sid, a.mode, a.item?.work_item_id, fields]);
    if (lastRequest.current?.key !== key)
      lastRequest.current = {
        key,
        body: { ...fields, operation_id: crypto.randomUUID().replaceAll('-', '') },
      };
    try {
      const path =
        a.mode === 'load' || a.mode === 'restart'
          ? `/document-workspace/${a.mode}`
          : a.item
            ? `/document-workspace/sessions/${sid}/items/${a.item.work_item_id}/${a.mode}`
            : `/document-workspace/sessions/${sid}/process/${a.mode}`;
      const answer = await api<Result | Snapshot>(path, {
        method: 'POST',
        body: JSON.stringify(lastRequest.current.body),
      });
      setAction(null);
      if (a.mode === 'load' || a.mode === 'restart') {
        setDetail(null);
        setResult(null);
        setFilter('All');
        setSearch('');
        setNotice(
          a.mode === 'restart'
            ? 'Fresh session ready. Previous work and decisions are retained.'
            : 'Sample PDFs are available in the active session. Existing decisions are retained.',
        );
      } else {
        setResult(answer as Result);
        setNotice(
          `${a.label}: administrative workflow recorded. No financial or contractual approval occurred.`,
        );
      }
      const next = await refresh();
      if (a.item && next.session_id === sid)
        setDetail(
          await api<Detail>(`/document-workspace/sessions/${sid}/items/${a.item.work_item_id}`),
        );
      lastRequest.current = null;
    } catch (e) {
      setError((e as Error).message);
      setNotice(
        'The operation was not confirmed in this browser. Retry the same form to reuse its operation ID, or refresh to inspect retained state.',
      );
    } finally {
      setBusy(false);
    }
  }
  const items = (snapshot?.items ?? []).filter(
    (w) =>
      (filter === 'All' ||
        (filter === 'Routine' && w.automation_eligible && w.status !== 'Closed') ||
        (filter === 'Needs Review' &&
          w.status !== 'Closed' &&
          w.status !== 'Escalated' &&
          w.human_review_required) ||
        (filter === 'Escalated' && w.status === 'Escalated') ||
        (filter === 'Completed' && w.status === 'Closed')) &&
      `${w.work_item_id} ${w.customer_id} ${w.customer_name ?? ''} ${w.required_action} ${w.category}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  items.sort(
    (a, b) =>
      Number(a.status === 'Closed') - Number(b.status === 'Closed') ||
      Number(b.priority === 'High') - Number(a.priority === 'High') ||
      a.customer_id.localeCompare(b.customer_id) ||
      a.category.localeCompare(b.category),
  );
  const financial = detail?.item.financial_impact;
  return (
    <div className="mywork">
      <header className="mw-top">
        <a className="mw-brand" href="/">
          Ledgerline<span>REVENUE OPERATIONS</span>
        </a>
        <div className="mw-persona">
          <span className="mw-avatar">MT</span>
          <div>
            <strong>Maya Tremblay</strong>
            <small>Revenue Operations Specialist</small>
          </div>
        </div>
        <a className="mw-legacy" href="/legacy">
          Advanced / Legacy workspace ↗
        </a>
      </header>
      <main>
        <div className="mw-heading">
          <div>
            <span className="mw-eyebrow">MY WORKSPACE</span>
            <h1>Revenue Operations — My Work</h1>
            <p>
              One queue for billing checks, contract evidence and the decisions that need a human.
            </p>
          </div>
          <span className="mw-local">127.0.0.1 · Local only</span>
        </div>
        {error && (
          <div className="mw-alert" role="alert">
            {error}
            <button onClick={() => void refresh().catch((e) => setError((e as Error).message))}>
              Refresh saved state
            </button>
          </div>
        )}
        <div className="mw-live" role="status" aria-live="polite">
          {notice ||
            (snapshot?.processing_active
              ? 'A saved operation is processing. This view will refresh when it finishes.'
              : '')}
        </div>
        {!snapshot?.session_id ? (
          <section className="mw-welcome">
            <span className="mw-eyebrow">DOCUMENTS → EVIDENCE → ACTION</span>
            <h2>Your work starts with the source.</h2>
            <p>
              Load Northstar Cloudworks’ fictional contracts, invoices and payments. Ledgerline
              reads the actual PDFs and creates a saved work queue.
            </p>
            <button
              className="mw-primary"
              disabled={disabled || !snapshot}
              onClick={() => begin('load')}
            >
              Load Sample Documents
            </button>
            <small>Synthetic documents. Genuine deterministic processing. No OpenAI usage.</small>
            {readOnly && (
              <p>
                This session is read-only. Open the legacy workspace for recorded investigations.
              </p>
            )}
          </section>
        ) : (
          <>
            <div className="mw-session">
              <div>
                <strong>Northstar Cloudworks</strong>
                <span>
                  {snapshot.document_count} source PDFs · {snapshot.customer_count} customer
                  accounts · April 2026
                </span>
                <small>{snapshot.provenance}</small>
              </div>
              <button disabled={disabled} onClick={() => begin('restart')}>
                Restart Demo
              </button>
            </div>
            {snapshot.read_only && (
              <p className="mw-alert">
                Retained session · Read-only audit view.{' '}
                <button
                  onClick={() => {
                    setDetail(null);
                    void refresh();
                  }}
                >
                  Return to active session
                </button>
              </p>
            )}
            <section className="mw-metrics" aria-label="Work metrics">
              {[
                ['Total work items', 'total'],
                ['Automatically completed', 'automatically_completed'],
                ['Awaiting Maya', 'awaiting_maya'],
                ['Escalated to management', 'escalated'],
              ].map(([label, key]) => (
                <article key={key}>
                  <span>{label}</span>
                  <strong data-testid={key}>{snapshot.metrics[key]}</strong>
                  <small>
                    {key === 'automatically_completed'
                      ? 'Revalidated administrative checks'
                      : key === 'total'
                        ? `${snapshot.metrics.routine_eligible} routine-eligible · ${snapshot.metrics.exceptions} exceptions`
                        : key === 'escalated'
                          ? 'Persisted in Sarah’s internal inbox'
                          : 'Open work and review coordination'}
                  </small>
                </article>
              ))}
            </section>
            <section className="mw-queue" aria-label="Revenue operations work queue">
              <div className="mw-queue-heading">
                <div>
                  <h2>Your work queue</h2>
                  <p>Complete supported checks. Keep uncertainty visible.</p>
                </div>
                <div className="mw-command-row">
                  <button
                    className="mw-primary"
                    disabled={disabled}
                    onClick={() => begin('routine')}
                  >
                    Process Routine Work
                  </button>
                  <button disabled={disabled} onClick={() => begin('auto_all')}>
                    Auto Complete All
                  </button>
                </div>
              </div>
              {result && (
                <section className="mw-result" aria-label="Processing result">
                  <h3>Recorded outcome</h3>
                  <dl>
                    {Object.entries({
                      'Automatically closed': 'automatically_closed',
                      'Routed to Maya': 'routed_to_maya',
                      'Escalated to Sarah': 'escalated_to_sarah',
                      'Awaiting evidence or authority': 'awaiting_evidence_or_authority',
                      'Unchanged due to safeguards': 'unchanged_due_to_safeguards',
                      Skipped: 'skipped',
                      Failed: 'failed',
                      'Items requiring review': 'items_requiring_review',
                      'Human queue remaining': 'human_queue_remaining',
                    }).map(([label, key]) => (
                      <div key={key}>
                        <dt>{label}</dt>
                        <dd>{result[key]}</dd>
                      </div>
                    ))}
                  </dl>
                  <small>
                    Administrative outcomes only. No invoices, credits, cash allocations or contract
                    authority were changed.
                  </small>
                </section>
              )}
              <div className="mw-filters">
                <div role="group" aria-label="Work queue filters">
                  {['All', 'Routine', 'Needs Review', 'Escalated', 'Completed'].map((f) => (
                    <button
                      key={f}
                      aria-pressed={f === filter}
                      onClick={() => {
                        setFilter(f);
                        setLimit(25);
                      }}
                    >
                      {f}
                    </button>
                  ))}
                </div>
                <input
                  aria-label="Search work items"
                  placeholder="Search customer or action"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setLimit(25);
                  }}
                />
              </div>
              <div className="mw-table-scroll">
                <table>
                  <thead>
                    <tr>
                      {[
                        'Work item / Customer',
                        'Document type',
                        'Required action',
                        'Priority',
                        'Assigned owner',
                        'Status',
                        'Recommended next action',
                      ].map((x) => (
                        <th key={x}>{x}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {items.slice(0, limit).map((w) => (
                      <tr key={w.work_item_id}>
                        <td>
                          <button
                            className="mw-item-link"
                            onClick={(e) => void openItem(w, e.currentTarget)}
                          >
                            <strong>{w.customer_name ?? w.customer_id}</strong>
                            <small>{w.customer_id}</small>
                            <small>{w.work_item_id}</small>
                            <span className="mw-sr">Open work item</span>
                          </button>
                        </td>
                        <td>{title(w.business_object_type)}</td>
                        <td>{w.required_action}</td>
                        <td>
                          <span className={`mw-priority ${w.priority === 'High' ? 'high' : ''}`}>
                            {w.priority}
                          </span>
                        </td>
                        <td>{w.assigned_owner}</td>
                        <td>
                          <span
                            className={`mw-status ${w.status === 'Closed' ? 'closed' : w.status === 'Escalated' ? 'escalated' : ''}`}
                          >
                            {statuses[w.status] ?? w.status}
                          </span>
                        </td>
                        <td>{w.recommendation.suggested_action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!items.length && <p className="mw-empty">No work items match this view.</p>}
              <div className="mw-table-footer">
                <span>
                  Showing {Math.min(limit, items.length)} of {items.length} matching work items
                </span>
                {limit < items.length && (
                  <button onClick={() => setLimit((v) => v + 25)}>Show more</button>
                )}
              </div>
            </section>
            <section className="mw-bottom">
              <details>
                <summary>Workflow telemetry</summary>
                <dl className="mw-telemetry">
                  {[
                    [
                      'Administrative throughput',
                      snapshot.items.filter((w) => w.status === 'Closed').length,
                    ],
                    [
                      'Routine check completion',
                      new Intl.NumberFormat('en-CA', {
                        style: 'percent',
                        maximumFractionDigits: 1,
                      }).format(snapshot.telemetry.routine_completion_rate ?? 0),
                    ],
                    [
                      'Human exception rate',
                      new Intl.NumberFormat('en-CA', {
                        style: 'percent',
                        maximumFractionDigits: 1,
                      }).format(snapshot.telemetry.human_exception_rate ?? 0),
                    ],
                    [
                      'Escalation rate',
                      new Intl.NumberFormat('en-CA', {
                        style: 'percent',
                        maximumFractionDigits: 1,
                      }).format(snapshot.telemetry.escalation_rate ?? 0),
                    ],
                    ['Human commands recorded', snapshot.telemetry.human_interaction_count],
                    ['Errors', snapshot.telemetry.error_count],
                    ['Retries', snapshot.telemetry.retry_count],
                    [
                      'PDF intake (wall-clock seconds)',
                      snapshot.telemetry.intake_duration_seconds ?? 'Not measured',
                    ],
                    [
                      'Workflow processing (wall-clock seconds)',
                      snapshot.telemetry.processing_duration_seconds,
                    ],
                    ['Document-session OpenAI cost (USD)', snapshot.telemetry.api_cost_usd],
                    ['Human labor / time saved', 'Not measured'],
                  ].map(([k, v]) => (
                    <div key={k}>
                      <dt>{k}</dt>
                      <dd>{v}</dd>
                    </div>
                  ))}
                </dl>
                <p>
                  Processing duration is not human labor time. No measured labor savings or ROI is
                  claimed. Persona names and entered reviewer attribution are not authenticated
                  role-based access control.
                </p>
              </details>
              <details>
                <summary>Retained sessions &amp; audit recovery</summary>
                {snapshot.sessions.map((s) => (
                  <p key={s.id}>
                    <button
                      onClick={() => {
                        setDetail(null);
                        void refresh(s.id).catch((e) => setError((e as Error).message));
                      }}
                    >
                      {s.id === snapshot.active_session_id ? 'Active' : 'Retained'} ·{' '}
                      {new Date(s.created_at).toLocaleString()}
                    </button>{' '}
                    <code>{s.id}</code>
                  </p>
                ))}
              </details>
            </section>
          </>
        )}
      </main>
      <footer className="mw-footer">
        Synthetic business documents · No financial execution or external communications ·
        Passwordless local mode is not suitable for public deployment.
      </footer>
      <dialog
        ref={dialog}
        className="mw-detail"
        onCancel={(e) => {
          e.preventDefault();
          closeDetail();
        }}
        aria-labelledby="mw-detail-title"
      >
        {detail && (
          <>
            <div className="mw-detail-top">
              <div>
                <span className="mw-eyebrow">
                  {detail.item.customer_id} · {detail.item.work_item_id}
                </span>
                <h2 id="mw-detail-title">{detail.item.required_action}</h2>
              </div>
              <button aria-label="Close work item" onClick={closeDetail}>
                Close ×
              </button>
            </div>
            <p>
              <span className="mw-status">
                {statuses[detail.item.status] ?? detail.item.status}
              </span>{' '}
              · {detail.item.assigned_owner} · Version {detail.item.version}
            </p>
            <section>
              <h3>Business problem</h3>
              <p>
                {detail.item.required_action}.{' '}
                {detail.item.automation_eligible
                  ? 'This is a supported read-only reconciliation check.'
                  : detail.item.eligibility_reason}
              </p>
              <p>Contract: {detail.item.contract_id}</p>
              {financial ? (
                <dl className="mw-financial">
                  {Object.entries(financial)
                    .filter(([k]) => k !== 'currency')
                    .map(([key, value]) => (
                      <div key={key}>
                        <dt>{title(key)}</dt>
                        <dd>
                          {financial.currency} {value}
                        </dd>
                      </div>
                    ))}
                </dl>
              ) : (
                <p className="mw-unknown">
                  Financial impact is not determinable from the current authoritative evidence.
                  Unknown is not zero.
                </p>
              )}
            </section>
            <section className="mw-suggestion">
              <span className="mw-eyebrow">SYSTEM RECOMMENDATION</span>
              <small>{detail.item.recommendation.source}</small>
              <h3>Suggested action</h3>
              <p>{detail.item.recommendation.suggested_action}</p>
              <h4>Why</h4>
              <p>{detail.item.recommendation.why}</p>
              <h4>What still requires human judgment</h4>
              <p>{detail.item.recommendation.human_judgment}</p>
            </section>
            <section>
              <h3>Supporting evidence</h3>
              <p>
                Original PDFs and fields extracted by Stage 1. References remain linked to the saved
                work item.
              </p>
              {detail.documents.map((doc) => (
                <details
                  className="mw-source"
                  key={doc.file_hash}
                  open={doc === detail.documents[0]}
                >
                  <summary>
                    {title(doc.document_type)} · {doc.document_id}
                  </summary>
                  <a
                    className="mw-pdf"
                    href={`/api/document-workspace/sessions/${snapshot?.session_id}/evidence/${doc.file_hash}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open original PDF ↗
                  </a>
                  {doc.errors.map((error) => (
                    <p className="mw-alert" key={error}>
                      {error}
                    </p>
                  ))}
                  <dl>
                    {Object.entries(doc.fields).map(([field, value]) => (
                      <div key={field}>
                        <dt>{field}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                  <details>
                    <summary>Evidence spans &amp; source integrity</summary>
                    <p>
                      SHA-256: <code>{doc.file_hash}</code>
                    </p>
                    {detail.item.evidence
                      .filter((e) => e.file_hash === doc.file_hash)
                      .map((e, i) => (
                        <blockquote key={i}>
                          <small>
                            Page {e.page} · {e.source_record_reference}
                          </small>
                          {e.text}
                        </blockquote>
                      ))}
                  </details>
                </details>
              ))}
            </section>
            <section>
              <h3>Available actions</h3>
              <p>
                Auto Complete applies the suggested permitted disposition. It does not
                unconditionally close exceptions.
              </p>
              <div className="mw-detail-actions">
                {detail.permitted_actions.map((mode) => (
                  <button
                    className={mode === 'auto' ? 'mw-primary' : ''}
                    key={mode}
                    disabled={disabled || detail.read_only}
                    onClick={() => begin(mode, detail.item)}
                  >
                    {labels[mode]}
                  </button>
                ))}
              </div>
              {detail.item.status === 'Escalated' && (
                <p>
                  Handed to Sarah’s persisted internal inbox. Contractual and financial authority
                  remain unresolved.
                </p>
              )}
              {detail.item.status === 'Awaiting Financial Review' && (
                <p>
                  Referred for separate financial authorization. This workspace has not approved or
                  executed a correction.
                </p>
              )}
              {detail.item.status === 'Closed' && (
                <p>Read-only check completed. No financial action was executed.</p>
              )}
            </section>
            <details>
              <summary>Audit history &amp; technical details</summary>
              <ol className="mw-audit">
                {detail.item.event_history.map((e, i) => (
                  <li key={e.id ?? i}>
                    <strong>{title(e.type ?? e.event ?? 'event')}</strong>
                    <time>{new Date(e.at).toLocaleString()}</time>
                    <small>
                      {e.actor_kind ?? 'deterministic_automation'} · {e.actor ?? 'Rules baseline'}
                      {e.before || e.after ? ` · ${e.before ?? '—'} → ${e.after ?? '—'}` : ''}
                    </small>
                    <p>{e.rationale}</p>
                  </li>
                ))}
              </ol>
            </details>
          </>
        )}
      </dialog>
      <dialog
        ref={actionDialog}
        className="mw-confirm"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setAction(null);
        }}
        aria-labelledby="mw-action-title"
      >
        {action && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <span className="mw-eyebrow">ADMINISTRATIVE WORKFLOW ONLY</span>
            <h2 id="mw-action-title">{action.label}</h2>
            <p>
              {action.mode === 'restart'
                ? 'Create a fresh, unprocessed demo session. Previous sessions, PDFs and actual human decisions remain retained. Legacy investigations, credentials, pricing and paid-run history are unchanged.'
                : action.mode === 'load'
                  ? 'Import the actual Stage 1 PDFs into an isolated demo session. No OpenAI calls or simulated human approvals.'
                  : 'Revalidate the source evidence, then apply only a permitted administrative disposition. Exceptions can be routed or deferred; no invoice, credit, cash or contractual approval is granted.'}
            </p>
            <label>
              Reviewer attribution
              <input
                required
                maxLength={120}
                value={actor}
                onChange={(e) => setActor(e.target.value)}
                disabled={busy}
              />
            </label>
            <small>Self-reported attribution in a local session, not authenticated identity.</small>
            <label htmlFor="mw-rationale">Rationale</label>
            <textarea
              id="mw-rationale"
              required
              maxLength={2000}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              disabled={busy}
            />
            {action.item && action.mode !== 'routine' && (
              <fieldset>
                <legend>Evidence reviewed — select at least one source</legend>
                {Object.entries(action.item.supporting_facts).map(([hash, fact]) => (
                  <label className="mw-checkbox" key={hash}>
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={evidence.includes(hash)}
                      onChange={(e) =>
                        setEvidence(
                          e.target.checked
                            ? [...evidence, hash]
                            : evidence.filter((x) => x !== hash),
                        )
                      }
                    />
                    {(fact as { document_id: string }).document_id}
                  </label>
                ))}
              </fieldset>
            )}
            <label className="mw-checkbox">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                disabled={busy}
              />
              I confirm this is administrative processing only; it does not authorize a financial
              correction or contractual determination.
            </label>
            {error && (
              <p role="alert" className="mw-alert">
                {error}
              </p>
            )}
            <div className="mw-command-row">
              <button
                type="submit"
                className="mw-primary"
                disabled={
                  busy ||
                  !confirmed ||
                  !actor.trim() ||
                  !rationale.trim() ||
                  !!(action.item && action.mode !== 'routine' && !evidence.length)
                }
              >
                {busy ? 'Processing saved work…' : 'Confirm ' + action.label}
              </button>
              <button type="button" disabled={busy} onClick={() => setAction(null)}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </dialog>
    </div>
  );
}
