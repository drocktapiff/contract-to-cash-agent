import { useEffect, useRef, useState } from 'react';
import { api, bootstrapSession, setCsrf } from './api';
import './document-workspace.css';
import WorkWalkthrough from './WorkWalkthrough';
import ManagementInbox from './ManagementInbox';

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
type Business = {
  impact_text: string;
  management_oversight_owner: string | null;
  current_decision_owner: string;
  waiting_on_department: string | null;
  title: string;
  view: string;
  case_owner: string;
  waiting_on: string | null;
  next_action: string;
  why_it_matters: string;
};
type Work = {
  oversight?: {
    id: string;
    owner: string;
    reason: string;
    requested_at: string;
    requested_by: string;
  };
  business: Business;
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
    api_cost_complete?: boolean;
  };
  document_count?: number;
  customer_count?: number;
  last_bulk_operation?: { id: string; status: string; result: BulkResult };
  provenance?: string;
  business_counts: Record<string, number>;
  scenarios: { key: string; label: string; work_item_id: string | null }[];
};
type Detail = { item: Work; documents: Source[]; permitted_actions: string[]; read_only: boolean };
type Result = {
  [key: string]: number | string | Record<string, number>;
  queue_outcome: Record<string, number>;
};
type SelectedItem = { id: string; version: number; note?: string };
type BulkResult = {
  session_id: string;
  kind: 'selected';
  action: string;
  operation_id: string;
  status: string;
  partial: boolean;
  total_examined: number;
  checks_completed: number;
  requires_review: number;
  handoffs_created: number;
  handoffs_reused: number;
  blocked: number;
  failed: number;
  awaiting_finance: number;
  awaiting_evidence: number;
  sarah_direct: number;
  financial_actions_executed: number;
  duration_seconds: number;
  per_item: { id: string; outcome: string; reason: string; status?: string }[];
};
type Action = {
  mode: string;
  label: string;
  item?: Work;
  selected?: SelectedItem[];
  sessionId?: string;
};
const labels: Record<string, string> = {
  auto: 'Auto Complete',
  routine: 'Complete routine check',
  request_evidence: 'Request more evidence',
  escalate: 'Escalate to Sarah',
  financial_review: 'Mark for authorized financial review',
  accept: 'Accept suggested workflow disposition',
  reject: 'Reject recommendation',
  review: 'Route to Maya for review',
  auto_all: 'Process All Work',
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
  const [viewSarah, setViewSarah] = useState(false);
  const [selection, setSelection] = useState<{ sid: string | null; items: Record<string, number> }>(
    { sid: null, items: {} },
  );
  const [itemNotes, setItemNotes] = useState<Record<string, string>>({});
  const headerCheckbox = useRef<HTMLInputElement>(null);
  const [walkShown, setWalkShown] = useState(false);
  const [walkItem, setWalkItem] = useState<string | null>(null);
  const [filter, setFilter] = useState('All Work'),
    [search, setSearch] = useState(''),
    [page, setPage] = useState(0);
  const limit = 25;
  const setLimit = (_value: number) => setPage(0);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('');
  const [action, setAction] = useState<Action | null>(null),
    [actor, setActor] = useState('Local operator'),
    [rationale, setRationale] = useState(''),
    [evidence, setEvidence] = useState<string[]>([]),
    [confirmed, setConfirmed] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);
  const [result, setResult] = useState<Result | null>(null),
    [readOnly, setReadOnly] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    actionDialog = useRef<HTMLDialogElement>(null),
    opener = useRef<HTMLElement | null>(null);
  const lastRequest = useRef<{ key: string; body: object } | null>(null);
  const disabled =
    viewSarah || busy || readOnly || !!snapshot?.read_only || !!snapshot?.processing_active;
  async function refresh(sid?: string) {
    const next = await api<Snapshot>(
      sid ? `/document-workspace/sessions/${sid}` : '/document-workspace',
    );
    setSnapshot(next);
    if (next.last_bulk_operation?.status === 'completed')
      setBulkResult(next.last_bulk_operation.result);
    else setBulkResult(null);
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
    setWalkShown(false);
    setSelection({ sid: snapshot?.session_id ?? null, items: {} });
    setPage(0);
    setBulkResult(
      snapshot?.last_bulk_operation?.status === 'completed'
        ? snapshot.last_bulk_operation.result
        : null,
    );
  }, [snapshot?.session_id]);
  useEffect(() => {
    if (!snapshot?.session_id) return;
    setSelection((previous) =>
      previous.sid === snapshot.session_id
        ? {
            sid: previous.sid,
            items: Object.fromEntries(
              Object.entries(previous.items).filter(([id]) =>
                snapshot.items.some((w) => w.work_item_id === id && w.status !== 'Closed'),
              ),
            ),
          }
        : previous,
    );
  }, [snapshot]);
  useEffect(() => {
    if (detail) dialog.current?.showModal();
    else dialog.current?.close();
  }, [detail]);
  useEffect(() => {
    if (action) actionDialog.current?.showModal();
    else actionDialog.current?.close();
  }, [action]);
  function begin(mode: string, item?: Work, label?: string) {
    setError('');
    setAction({
      mode,
      label: label ?? (mode === 'routine' && !item ? 'Process Routine Work' : labels[mode]),
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
    if (action.selected) setBulkResult(null);
    setNotice('Revalidating original PDF evidence and applying permitted workflow dispositions…');
    const sid = action.sessionId ?? snapshot?.active_session_id,
      a = action;
    const fields = {
      actor: actor.trim(),
      rationale: rationale.trim(),
      confirmation: 'ADMINISTRATIVE WORKFLOW ONLY',
      expected_session: sid ?? null,
      expected_version: a.item?.version ?? null,
      evidence_hashes: evidence,
      ...(a.selected
        ? { selected: a.selected.map((x) => ({ ...x, note: itemNotes[x.id] ?? '' })) }
        : {}),
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
          : a.selected
            ? `/document-workspace/sessions/${sid}/selected/${a.mode === 'selected_close' ? 'close' : 'escalate'}`
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
        setFilter('All Work');
        setSearch('');
        setNotice(
          a.mode === 'restart'
            ? 'Fresh session ready. Previous work and decisions are retained.'
            : 'Sample PDFs are available in the active session. Existing decisions are retained.',
        );
      } else if (a.selected) {
        const selectedResult = answer as unknown as BulkResult;
        setBulkResult(selectedResult);
        setResult(null);
        setNotice(
          selectedResult.partial
            ? 'Some selected items were blocked or failed. Inspect the per-item outcomes.'
            : 'Selected workflow recorded. Review and oversight are not financial approval.',
        );
        setSelection({ sid: sid ?? null, items: {} });
      } else {
        setResult(answer as Result);
        setNotice(
          `${a.label}: administrative workflow recorded. No financial or contractual approval occurred.`,
        );
      }
      const next = await refresh();
      if (a.item && next.session_id === sid && !walkShown)
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
      (filter === 'All Work' ||
        w.business.view === filter ||
        ((filter === 'Sarah' || filter === 'Escalated to Sarah') &&
          (w.oversight || w.status === 'Escalated')) ||
        (filter === 'Finance' && w.status === 'Awaiting Financial Review') ||
        (filter === 'Missing evidence' && w.status === 'Awaiting Evidence')) &&
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
  const pageIndex = Math.min(page, Math.max(0, Math.ceil(items.length / limit) - 1));
  const visible = items.slice(pageIndex * limit, (pageIndex + 1) * limit);
  const selected = selection.sid === snapshot?.session_id ? selection.items : {};
  const selectedCount = Object.keys(selected).length;
  const selectable = (w: Work) => w.status !== 'Closed';
  const currentPage = visible.filter(selectable);
  const allPage = currentPage.length > 0 && currentPage.every((w) => w.work_item_id in selected);
  useEffect(() => {
    if (headerCheckbox.current)
      headerCheckbox.current.indeterminate =
        !allPage && currentPage.some((w) => w.work_item_id in selected);
  });
  function chooseMany(rows: Work[]) {
    if (!snapshot?.session_id) return;
    setSelection((prev) => ({
      sid: snapshot.session_id,
      items: {
        ...(prev.sid === snapshot.session_id ? prev.items : {}),
        ...Object.fromEntries(rows.filter(selectable).map((w) => [w.work_item_id, w.version])),
      },
    }));
  }
  function startSelected(mode: string) {
    if (!selectedCount || !snapshot?.session_id) return;
    setError('');
    setConfirmed(false);
    setRationale('');
    setItemNotes({});
    setEvidence([]);
    setAction({
      mode,
      label: mode === 'selected_close' ? 'AI Powered Close' : 'Escalate Selected to Sarah',
      sessionId: snapshot.session_id,
      selected: Object.entries(selected).map(([id, version]) => ({ id, version })),
    });
  }
  const financial = detail?.item.financial_impact;
  return (
    <div className="mywork">
      <header className="mw-top">
        <a className="mw-brand" href="/">
          Ledgerline<span>REVENUE OPERATIONS</span>
        </a>
        <div className="mw-persona">
          <span className="mw-avatar">{viewSarah ? 'SC' : 'MT'}</span>
          <div>
            <strong>{viewSarah ? 'Sarah Chen' : 'Maya Tremblay'}</strong>
            <small>
              {viewSarah
                ? 'Director of Revenue Operations · management coordination'
                : 'Revenue Operations Specialist'}
            </small>
          </div>
        </div>
        <button
          onClick={() => {
            setViewSarah((v) => !v);
            setDetail(null);
            setSelection({ sid: snapshot?.session_id ?? null, items: {} });
          }}
        >
          {viewSarah ? 'Maya — Revenue Operations' : 'Sarah — Management Command Center'}
        </button>
        <a className="mw-legacy" href="/legacy">
          Advanced / Legacy workspace ↗
        </a>
      </header>
      <main>
        <div className="mw-heading">
          <div>
            <span className="mw-eyebrow">MY WORKSPACE</span>
            <h1>
              {viewSarah
                ? 'Revenue Operations — Department Overview'
                : 'Revenue Operations — My Work'}
            </h1>
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
            {!viewSarah && (
              <section className="mw-metrics" aria-label="Work metrics">
                {[
                  ['Work received', 'total', snapshot.business_counts.total],
                  [
                    'Verified checks completed',
                    'automatically_completed',
                    snapshot.metrics.automatically_completed,
                  ],
                  ['Needs My Attention', 'needs_maya', snapshot.business_counts.needs_maya],
                  ['Awaiting Others', 'awaiting_others', snapshot.business_counts.awaiting_others],
                ].map(([label, key, value]) => (
                  <article key={key}>
                    <span>{label}</span>
                    <strong data-testid={key}>{value}</strong>
                    <small>
                      {key === 'total'
                        ? `${snapshot.metrics.routine_eligible} routine-eligible · ${snapshot.metrics.exceptions} exceptions`
                        : key === 'automatically_completed'
                          ? 'Administrative checks, not financial corrections'
                          : key === 'awaiting_others'
                            ? 'Sarah, Finance or missing documentation'
                            : 'Ready checks and decisions for Maya'}
                    </small>
                  </article>
                ))}
              </section>
            )}
            {viewSarah ? (
              <ManagementInbox
                key={snapshot.session_id}
                sid={snapshot.session_id}
                revision={snapshot}
                readOnly={readOnly || snapshot.read_only}
                onChanged={() => void refresh()}
                onOpen={(id) => {
                  const work = snapshot.items.find((w) => w.work_item_id === id);
                  if (work) void openItem(work);
                }}
              />
            ) : (
              <section className="mw-queue" aria-label="Revenue operations work queue">
                <div className="mw-queue-heading">
                  <div>
                    <h2>Your work queue</h2>
                    <p>Complete supported checks. Keep uncertainty visible.</p>
                  </div>
                  <div className="mw-command-row">
                    <button
                      disabled={busy}
                      onClick={() => {
                        setWalkItem(null);
                        setWalkShown(true);
                      }}
                    >
                      Show Me the Work
                    </button>
                    {selectedCount === 0 && (
                      <button
                        className="mw-primary"
                        disabled={disabled}
                        onClick={() => begin('auto_all')}
                      >
                        Process All Work
                      </button>
                    )}
                  </div>
                </div>
                {selectedCount > 0 && (
                  <section className="mw-bulk-toolbar" aria-label="Selected work actions">
                    <div>
                      <strong role="status" aria-live="polite">
                        {selectedCount} Work Items Selected
                      </strong>
                      <small>
                        Selection is scoped to this session. Current versions and PDF evidence are
                        checked on the server.
                      </small>
                    </div>
                    <div className="mw-command-row">
                      <button
                        className="mw-primary"
                        disabled={disabled}
                        onClick={() => startSelected('selected_close')}
                        aria-describedby="mw-automated-scope"
                      >
                        AI Powered Close
                      </button>
                      <button
                        disabled={disabled}
                        onClick={() => startSelected('selected_escalate')}
                      >
                        Escalate to Sarah
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => setSelection({ sid: snapshot.session_id, items: {} })}
                      >
                        Clear Selection
                      </button>
                    </div>
                    <p id="mw-automated-scope">
                      Automated evidence validation and financial rules. No live AI model used in
                      this demonstration.
                    </p>
                  </section>
                )}
                {bulkResult?.session_id === snapshot.session_id && (
                  <section className="mw-result" aria-label="Selected work outcome">
                    <h2>
                      {bulkResult.partial
                        ? 'Selected work needs attention'
                        : 'Selected workflow outcome'}
                    </h2>
                    <p>
                      {bulkResult.action === 'close'
                        ? 'Only supported administrative checks were completed. Unresolved cases remain open.'
                        : 'Sarah received oversight; financial and contractual authority did not transfer.'}
                    </p>
                    <dl>
                      {[
                        ['Items examined', 'total_examined'],
                        ['Routine checks completed', 'checks_completed'],
                        ['Requiring review', 'requires_review'],
                        ['Handoffs created', 'handoffs_created'],
                        ['Existing handoffs reused', 'handoffs_reused'],
                        ['Awaiting Finance', 'awaiting_finance'],
                        ['Awaiting evidence', 'awaiting_evidence'],
                        ['Sarah’s direct attention', 'sarah_direct'],
                        ['Blocked', 'blocked'],
                        ['Failed', 'failed'],
                        ['Unauthorized financial actions', 'financial_actions_executed'],
                      ].map(([label, key]) => (
                        <div key={key}>
                          <dt>{label}</dt>
                          <dd>{String(bulkResult[key as keyof BulkResult] ?? 0)}</dd>
                        </div>
                      ))}
                    </dl>
                    <button
                      disabled={disabled}
                      onClick={() =>
                        chooseMany(snapshot.items.filter((w) => w.status !== 'Closed'))
                      }
                    >
                      Select All Remaining Work
                    </button>
                    <small>
                      {snapshot.items.filter((w) => w.status === 'Closed').length} completed items
                      excluded. Existing Sarah handoffs may be selected and safely reused.
                    </small>
                    <details>
                      <summary>Per-item outcomes and exclusions</summary>
                      <ul>
                        {bulkResult.per_item.map((row) => (
                          <li key={row.id}>
                            <button
                              onClick={() => {
                                const work = snapshot.items.find((w) => w.work_item_id === row.id);
                                if (work) void openItem(work);
                              }}
                            >
                              {row.id}
                            </button>{' '}
                            — {title(row.outcome)}: {row.reason}
                          </li>
                        ))}
                      </ul>
                    </details>
                  </section>
                )}
                {snapshot.last_bulk_operation &&
                  snapshot.last_bulk_operation.status === 'interrupted' && (
                    <p className="mw-alert" role="alert">
                      The last selected operation is {snapshot.last_bulk_operation.status}. No
                      uncommitted success is claimed. Retry its operation ID or inspect the audit
                      history.
                    </p>
                  )}
                {result && (
                  <section className="mw-result" aria-label="Processing result">
                    <span className="mw-eyebrow">RECORDED WORKFLOW OUTCOME</span>
                    <h2>
                      {Number(result.failed) > 0
                        ? 'Processing needs review'
                        : "Here's What Ledgerline Accomplished"}
                    </h2>
                    {Number(result.failed) > 0 && (
                      <p role="alert">
                        Processing failed or was partial. Inspect the failed work before treating
                        any outcome as complete.
                      </p>
                    )}
                    <p>
                      Completed checks and work routed for another decision are different outcomes.
                      No revenue recovery or financial approval is claimed.
                    </p>
                    <dl>
                      {[
                        ['Total work examined', 'total_examined'],
                        ['Routine checks completed', 'checks_completed'],
                        ['Items skipped', 'skipped'],
                        ['Blocked or unchanged', 'unchanged_due_to_safeguards'],
                        ['Processing failures', 'failed'],
                        ['System processing duration (seconds)', 'duration_seconds'],
                      ].map(([label, key]) => (
                        <div key={key}>
                          <dt>{label}</dt>
                          <dd>{String(result[key] ?? 'Not recorded')}</dd>
                        </div>
                      ))}
                    </dl>
                    <h3>Where the work stands now</h3>
                    <div className="mw-queue-breakdown">
                      {[
                        ['Completed', 'completed', 'Completed'],
                        ['Needs Maya', 'needs_maya', 'Needs My Attention'],
                        ['Awaiting Sarah', 'awaiting_sarah', 'Sarah'],
                        ['Awaiting Finance', 'awaiting_finance', 'Finance'],
                        ['Awaiting missing evidence', 'awaiting_evidence', 'Missing evidence'],
                      ].map(([label, key, view]) => (
                        <button
                          key={key}
                          onClick={() => {
                            setFilter(view);
                            setSearch('');
                          }}
                        >
                          <strong>{snapshot.business_counts[key]}</strong>
                          {label}
                        </button>
                      ))}
                    </div>
                    <small>
                      These current-state counts come from the saved queue, not a projected success
                      rate. Open a group to inspect its work items. Runtime is not employee labor
                      time.
                    </small>
                  </section>
                )}
                <details className="mw-granular">
                  <summary>Granular processing controls</summary>
                  <button disabled={disabled} onClick={() => begin('routine')}>
                    Process Routine Work
                  </button>
                  <button
                    disabled={disabled}
                    onClick={() => begin('auto_all', undefined, 'Auto Complete All')}
                  >
                    Auto Complete All
                  </button>
                </details>
                <div className="mw-filters">
                  <div role="group" aria-label="Work queue filters">
                    {[
                      'Needs My Attention',
                      'Awaiting Others',
                      'Completed',
                      'All Work',
                      'Escalated to Sarah',
                    ].map((f) => (
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
                <div className="mw-selection-scope">
                  <button disabled={disabled} onClick={() => chooseMany(items)}>
                    Select All Matching
                  </button>
                  {!bulkResult && (
                    <button
                      disabled={disabled}
                      onClick={() =>
                        chooseMany(snapshot.items.filter((w) => w.status !== 'Closed'))
                      }
                    >
                      Select All Remaining Work
                    </button>
                  )}
                  <span>
                    {items.filter(selectable).length} matching actionable items;{' '}
                    {items.filter((w) => !selectable(w)).length} completed items excluded. Header
                    Select All applies only to this page.
                  </span>
                </div>
                <div className="mw-table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>
                          <input
                            type="checkbox"
                            aria-label="Select All"
                            ref={headerCheckbox}
                            disabled={disabled || !currentPage.length}
                            checked={allPage}
                            onChange={(e) => {
                              if (e.target.checked) chooseMany(currentPage);
                              else
                                setSelection((prev) => ({
                                  sid: snapshot.session_id,
                                  items: Object.fromEntries(
                                    Object.entries(prev.items).filter(
                                      ([id]) => !currentPage.some((w) => w.work_item_id === id),
                                    ),
                                  ),
                                }));
                            }}
                          />
                        </th>
                        {[
                          'Work item / Customer',
                          'Potential business impact',
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
                      {visible.map((w) => (
                        <tr key={w.work_item_id}>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={
                                'Select ' +
                                (w.customer_name ?? w.customer_id) +
                                ' — ' +
                                w.business.title +
                                ' — ' +
                                w.work_item_id
                              }
                              title={
                                w.status === 'Closed'
                                  ? 'Completed items cannot be acted upon'
                                  : w.oversight
                                    ? 'Sarah already oversees this item; escalation will reuse the handoff'
                                    : 'Select this work item'
                              }
                              disabled={disabled || !selectable(w)}
                              checked={w.work_item_id in selected}
                              onChange={(e) => {
                                if (e.target.checked) chooseMany([w]);
                                else
                                  setSelection((prev) => ({
                                    sid: snapshot.session_id,
                                    items: Object.fromEntries(
                                      Object.entries(prev.items).filter(
                                        ([id]) => id !== w.work_item_id,
                                      ),
                                    ),
                                  }));
                              }}
                            />
                          </td>
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
                          <td>{w.business.impact_text}</td>
                          <td>
                            {w.business.title}
                            <small className="mw-row-reason">{title(w.business_object_type)}</small>
                            <small className="mw-row-reason">{w.eligibility_reason}</small>
                          </td>
                          <td>
                            <span className={`mw-priority ${w.priority === 'High' ? 'high' : ''}`}>
                              {w.priority}
                            </span>
                          </td>
                          <td>
                            {w.business.case_owner}
                            <small className="mw-row-reason">
                              {w.business.waiting_on
                                ? `Waiting on ${w.business.waiting_on}`
                                : 'Next: Maya'}
                            </small>
                          </td>
                          <td>
                            <span
                              className={`mw-status ${w.status === 'Closed' ? 'closed' : w.status === 'Escalated' ? 'escalated' : ''}`}
                            >
                              {statuses[w.status] ?? w.status}
                            </span>
                          </td>
                          <td>{w.business.next_action}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!items.length && <p className="mw-empty">No work items match this view.</p>}
                <div className="mw-table-footer">
                  <span>
                    Showing {items.length ? pageIndex * limit + 1 : 0}–
                    {Math.min((pageIndex + 1) * limit, items.length)} of {items.length} matching
                    work items
                  </span>
                  <div className="mw-command-row">
                    <button disabled={pageIndex === 0} onClick={() => setPage(pageIndex - 1)}>
                      Previous Page
                    </button>
                    <span>
                      Page {pageIndex + 1} of {Math.max(1, Math.ceil(items.length / limit))}
                    </span>
                    <button
                      disabled={(pageIndex + 1) * limit >= items.length}
                      onClick={() => setPage(pageIndex + 1)}
                    >
                      Next Page
                    </button>
                  </div>
                </div>
              </section>
            )}
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
                    [
                      'Document-session OpenAI cost (USD)',
                      snapshot.telemetry.api_cost_complete === false
                        ? 'Unknown / incomplete usage'
                        : snapshot.telemetry.api_cost_usd,
                    ],
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
                <h2 id="mw-detail-title">{detail.item.business.title}</h2>
              </div>
              <button aria-label="Close work item" onClick={closeDetail}>
                Close ×
              </button>
            </div>
            <p>
              <span className="mw-status">
                {statuses[detail.item.status] ?? detail.item.status}
              </span>{' '}
              · Owner: {detail.item.business.case_owner} · Waiting on:{' '}
              {detail.item.business.waiting_on ?? 'Maya’s next action'}
            </p>
            {detail.item.business.management_oversight_owner && (
              <section className="mw-oversight">
                <strong>Management oversight: Sarah Chen</strong>
                <p>
                  Decision required from: {detail.item.business.current_decision_owner}. Status:{' '}
                  {detail.item.status}. No financial approval authority has transferred.
                </p>
                {detail.item.oversight && (
                  <p>
                    Handoff recorded {new Date(detail.item.oversight.requested_at).toLocaleString()}{' '}
                    · {detail.item.oversight.reason}
                  </p>
                )}
              </section>
            )}
            <button
              onClick={() => {
                setDetail(null);
                setWalkItem(detail.item.work_item_id);
                setWalkShown(true);
              }}
            >
              Show Me the Work
            </button>
            <section>
              <h3>What's happening?</h3>
              <p>
                {detail.item.required_action}.{' '}
                {detail.item.automation_eligible
                  ? 'This is a supported read-only reconciliation check.'
                  : detail.item.eligibility_reason}
              </p>
              <h3>Why does it matter?</h3>
              <p>{detail.item.business.why_it_matters}</p>
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
              <h3>What happens next?</h3>
              <p>{detail.item.business.next_action}</p>
              {detail.permitted_actions.includes(detail.item.recommendation.disposition) && (
                <button
                  className="mw-primary"
                  disabled={disabled}
                  onClick={() => begin(detail.item.recommendation.disposition, detail.item)}
                >
                  {
                    (
                      {
                        routine: 'Complete Verified Check',
                        financial_review: 'Refer to Financial Review',
                        escalate: 'Escalate to Sarah',
                        request_evidence: 'Request Missing Documentation',
                        review: 'Review Billing Difference',
                      } as Record<string, string>
                    )[detail.item.recommendation.disposition]
                  }
                </button>
              )}
              <h4>Why</h4>
              <p>{detail.item.recommendation.why}</p>
              <h4>What still requires human judgment</h4>
              <p>{detail.item.recommendation.human_judgment}</p>
            </section>
            <section>
              <h3>What did Ledgerline find?</h3>
              <h4>Supporting evidence</h4>
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
            <details>
              <summary>Other review actions</summary>
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
            </details>
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
                    <details>
                      <summary>Full recorded event</summary>
                      <pre>{JSON.stringify(e, null, 2)}</pre>
                    </details>
                  </li>
                ))}
              </ol>
            </details>
          </>
        )}
      </dialog>
      {walkShown && snapshot?.session_id && (
        <WorkWalkthrough
          sid={snapshot.session_id}
          scenarios={snapshot.scenarios}
          initialItem={walkItem}
          completedOperationId={
            typeof result?.operation_id === 'string' ? result.operation_id : undefined
          }
          revision={snapshot}
          disabled={disabled}
          onClose={() => setWalkShown(false)}
          onProcess={(item) => {
            void api<Detail>(
              `/document-workspace/sessions/${snapshot.session_id}/items/${item.work_item_id}`,
            )
              .then((d) => begin('auto', d.item, 'Process This Work Item'))
              .catch((e) => setError((e as Error).message));
          }}
          onRemaining={() => {
            setWalkShown(false);
            setSelection({ sid: snapshot.session_id, items: {} });
            begin('auto_all', undefined, 'Process All Remaining Work');
          }}
        />
      )}
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
            {action.selected && (
              <>
                <p>
                  {action.selected.length} selected work items. Current source evidence and captured
                  versions will be revalidated. Sarah provides oversight, not financial approval.
                </p>
                {action.mode === 'selected_close' && (
                  <p>
                    Automated evidence validation and financial rules. No live AI model used in this
                    demonstration.
                  </p>
                )}
                <details>
                  <summary>Optional per-item notes</summary>
                  {action.selected.map((row) => (
                    <label key={row.id}>
                      {row.id}
                      <textarea
                        maxLength={1000}
                        value={itemNotes[row.id] ?? ''}
                        onChange={(e) =>
                          setItemNotes((prev) => ({ ...prev, [row.id]: e.target.value }))
                        }
                        disabled={busy}
                      />
                    </label>
                  ))}
                </details>
              </>
            )}
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
