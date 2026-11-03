import { useEffect, useRef, useState } from 'react';
import { api, setCsrf } from './api';
import type { Activity, Dataset, Evidence, Finding, Health, Review, Run, Session } from './types';
import {
  exportAllowed,
  findingAmount,
  findingCategory,
  isActive,
  mergeEvents,
  stageFor,
  statusLabel,
} from './mapping.mjs';

type Page = 'Overview' | 'Investigations' | 'Findings' | 'Review Queue' | 'Audit History';
const pages: Page[] = ['Overview', 'Investigations', 'Findings', 'Review Queue', 'Audit History'];
const money = (value: string | undefined | null, currency = 'CAD') =>
  value == null
    ? '—'
    : new Intl.NumberFormat('en-CA', {
        style: 'currency',
        currency,
        maximumFractionDigits: 2,
      }).format(Number(value));
const count = (value: number | undefined | null) => (value == null ? '—' : value.toLocaleString());
function Glyph({ kind = 'grid' }: { kind?: string }) {
  const paths: Record<string, string> = {
    grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    pulse: 'M3 12h4l3-7 4 14 3-7h4',
    file: 'M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6 M9 16h6',
    check: 'M5 12l4 4L19 6',
    clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v6l4 2',
    arrow: 'M5 12h14 M14 7l5 5-5 5',
    lock: 'M6 11h12v10H6z M8 11V7a4 4 0 0 1 8 0v4',
    close: 'M6 6l12 12 M18 6L6 18',
  };
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[kind] ?? paths.file} />
    </svg>
  );
}
function Badge({ status }: { status: string }) {
  return <span className={'badge ' + status}>{statusLabel(status)}</span>;
}
function Metric({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>(
    () => pages.find((p) => p === decodeURIComponent(location.hash.slice(1))) ?? 'Overview',
  );
  const [session, setSession] = useState<Session | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [dataset, setDataset] = useState<Dataset | null>(null);
  const [runs, setRuns] = useState<Run[]>([]),
    [runId, setRunId] = useState(new URLSearchParams(location.search).get('run') ?? ''),
    [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<Activity[]>([]),
    [connection, setConnection] = useState('Not connected'),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false),
    [token, setToken] = useState(''),
    [launchOpen, setLaunchOpen] = useState(false),
    [paid, setPaid] = useState(false);
  const [inputPrice, setInputPrice] = useState(''),
    [cachedPrice, setCachedPrice] = useState(''),
    [outputPrice, setOutputPrice] = useState('');
  const [selected, setSelected] = useState<Finding | null>(null),
    [evidence, setEvidence] = useState<Evidence[]>([]),
    [evidenceLoading, setEvidenceLoading] = useState(false),
    [rationale, setRationale] = useState('');
  const [stateFilter, setStateFilter] = useState('all'),
    [reviewFilter, setReviewFilter] = useState('all'),
    [impactFilter, setImpactFilter] = useState('all');
  const selectedRun = useRef(runId);
  selectedRun.current = runId;
  const readable = !!session && (session.authenticated || session.mode === 'recorded');
  const recorded = session?.mode === 'recorded';
  async function refreshAll() {
    try {
      const [data, list] = await Promise.all([api<Dataset>('/dataset'), api<Run[]>('/runs')]);
      setDataset(data);
      setRuns(list);
      if (!runId && list.length) setRunId(list[0].id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function refreshRun(id: string) {
    try {
      const next = await api<Run>('/runs/' + id);
      if (selectedRun.current === id) setRun(next);
      setRuns((previous) =>
        [next, ...previous.filter((r) => r.id !== id)].sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    Promise.all([api<Session>('/session'), api<Health>('/health')])
      .then(([s, h]) => {
        setSession(s);
        setCsrf(s.csrf_token);
        setHealth(h);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    if (readable) void refreshAll();
  }, [readable]);
  useEffect(() => {
    const expired = () => {
      setCsrf(null);
      setSession((previous) =>
        previous ? { ...previous, authenticated: false, csrf_token: null } : null,
      );
      setRun(null);
      setEvents([]);
      setSelected(null);
    };
    window.addEventListener('ctc-session-expired', expired);
    return () => window.removeEventListener('ctc-session-expired', expired);
  }, []);
  useEffect(() => {
    history.replaceState(
      null,
      '',
      (runId ? '?run=' + encodeURIComponent(runId) : '') + '#' + encodeURIComponent(page),
    );
  }, [runId, page]);
  useEffect(() => {
    if (!readable || !runId) return;
    let disposed = false;
    setRun(null);
    setEvents([]);
    setSelected(null);
    setConnection('Connecting…');
    void refreshRun(runId);
    const stream = new EventSource('/api/runs/' + encodeURIComponent(runId) + '/events');
    const timer = setInterval(() => {
      if (!disposed) void refreshRun(runId);
    }, 1500);
    stream.onopen = () =>
      setConnection(recorded ? 'Recorded journal connected' : 'Journal connected');
    stream.addEventListener('activity', (message) => {
      const activity = JSON.parse((message as MessageEvent).data) as Activity;
      if (!disposed) setEvents((previous) => mergeEvents(previous, [activity]) as Activity[]);
    });
    stream.addEventListener('settled', () => {
      stream.close();
      clearInterval(timer);
      if (!disposed) {
        setConnection('Persisted history synchronized');
        void refreshRun(runId);
      }
    });
    stream.onerror = () => {
      if (!disposed) setConnection('Disconnected · reconnecting from last event');
    };
    return () => {
      disposed = true;
      clearInterval(timer);
      stream.close();
    };
  }, [runId, readable, recorded]);
  useEffect(() => {
    setRationale('');
    setEvidence([]);
    if (!selected || !runId) return;
    let cancelled = false;
    setEvidenceLoading(true);
    api<Evidence[]>(`/runs/${runId}/findings/${encodeURIComponent(selected.finding_id)}/evidence`)
      .then((data) => {
        if (!cancelled) setEvidence(data);
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        if (!cancelled) setEvidenceLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected?.finding_id, runId]);
  async function signIn(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const s = await api<Session>('/session', { method: 'POST', body: JSON.stringify({ token }) });
      setSession(s);
      setCsrf(s.csrf_token);
      setToken('');
      setLoginOpen(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function signOut() {
    setBusy(true);
    try {
      await api('/session', { method: 'DELETE' });
      setSession(null);
      setCsrf(null);
      setRuns([]);
      setRun(null);
      setEvents([]);
      location.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function launch(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const requestId = crypto.randomUUID();
      const created = await api<Run>('/runs', {
        method: 'POST',
        body: JSON.stringify({
          idempotency_key: requestId,
          acknowledge_paid: paid,
          input_price: inputPrice,
          cached_input_price: cachedPrice,
          output_price: outputPrice,
        }),
      });
      setRunId(created.id);
      setRun(created);
      setPage('Investigations');
      setLaunchOpen(false);
      setPaid(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function decide(decision: string) {
    if (!run || !selected) return;
    setBusy(true);
    setError('');
    try {
      const result = await api<{ run: Run }>(
        `/runs/${run.id}/findings/${encodeURIComponent(selected.finding_id)}/review`,
        {
          method: 'POST',
          body: JSON.stringify({
            decision,
            rationale,
            expected_revision: selected.data_revision,
            expected_version: selected.version,
          }),
        },
      );
      setRun(result.run);
      setSelected(result.run.findings.find((f) => f.finding_id === selected.finding_id) ?? null);
      setRationale('');
      await refreshRun(run.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    if (!run || !selected) return;
    setBusy(true);
    try {
      const response = await fetch(
        `/api/runs/${run.id}/findings/${encodeURIComponent(selected.finding_id)}/export`,
        { credentials: 'same-origin' },
      );
      if (!response.ok)
        throw new Error(
          'Export refused. A current verified finding and explicit export approval are required.',
        );
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = 'review-package.json';
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!loginOpen && !launchOpen && !selected) return;
    const previous = document.activeElement as HTMLElement | null;
    const handler = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll<HTMLElement>('[role="dialog"]');
      const dialog = dialogs[dialogs.length - 1];
      if (event.key === 'Escape') {
        setLoginOpen(false);
        setLaunchOpen(false);
        setSelected(null);
      }
      if (event.key === 'Tab' && dialog) {
        const controls = [
          ...dialog.querySelectorAll<HTMLElement>(
            'button:not(:disabled),input,select,textarea,a[href]',
          ),
        ];
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    const dialogs = document.querySelectorAll<HTMLElement>('[role="dialog"]');
    dialogs[dialogs.length - 1]?.querySelector<HTMLElement>('input,button')?.focus();
    document.addEventListener('keydown', handler);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = '';
      previous?.focus();
    };
  }, [loginOpen, launchOpen, selected?.finding_id]);
  const pending = run?.reviews.filter((r) => r.status === 'pending') ?? [];
  const verified = run?.findings.filter((f) => f.state === 'verified' && f.evidence_verified) ?? [];
  const reviewFor = (f: Finding) => run?.reviews.find((r) => r.finding_id === f.finding_id);
  const shown = (run?.findings ?? []).filter(
    (f) =>
      (page !== 'Review Queue' || reviewFor(f)?.status === 'pending') &&
      (stateFilter === 'all' || f.state === stateFilter) &&
      (reviewFilter === 'all' || reviewFor(f)?.status === reviewFilter) &&
      (impactFilter === 'all' || findingCategory(f) === impactFilter),
  );
  const currentFinding =
    selected && run?.findings.find((f) => f.finding_id === selected.finding_id);
  const currentReview = currentFinding ? reviewFor(currentFinding) : undefined;
  const liveActive = run && isActive(run.status);
  const stale = !!(
    dataset?.data_revision &&
    run?.data_revision &&
    dataset.data_revision !== run.data_revision
  );
  const table = (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Customer / group</th>
            <th>Issue</th>
            <th>Verification</th>
            <th>Calculated difference</th>
            <th>Financial category</th>
            <th>Sources</th>
            <th>Human review</th>
            <th>
              <span className="sr-only">Open evidence</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((f) => (
            <tr key={f.finding_id}>
              <td>
                <button className="text-button" onClick={() => setSelected(f)}>
                  {f.customer_ids.join(' · ')}
                </button>
                <small>
                  {f.customer_ids.length > 1 ? 'Cross-customer group' : 'Customer account'}
                </small>
              </td>
              <td>
                {findingCategory(f)}
                <small>
                  {f.origin === 'deterministic_conflict_guard'
                    ? 'Python conflict guard'
                    : 'Model-submitted hypothesis'}
                </small>
              </td>
              <td>
                <Badge status={f.state} />
                {f.requires_revalidation && <small>Revalidation required</small>}
              </td>
              <td className="amount">
                {money(findingAmount(f))}
                <small>
                  {findingAmount(f) == null
                    ? 'Amount unresolved or unverified'
                    : 'Potential difference · CAD'}
                </small>
              </td>
              <td>
                {(f.comparisons ?? [f.comparison])[0]?.financial_category?.replaceAll('_', ' ') ??
                  'Unresolved'}
              </td>
              <td>
                {f.evidence_ids.length}
                <small>{f.evidence_verified ? 'Evidence checked' : 'Not source verified'}</small>
              </td>
              <td>
                {reviewFor(f) ? (
                  <Badge status={reviewFor(f)!.status} />
                ) : (
                  <span className="muted">Not requested</span>
                )}
              </td>
              <td>
                <button
                  className="icon-button"
                  onClick={() => setSelected(f)}
                  aria-label={'Open evidence for ' + f.customer_ids.join(', ')}
                >
                  <Glyph kind="arrow" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {shown.length === 0 && (
        <div className="empty">
          <Glyph kind="file" />
          <h3>{run ? 'No findings in this view' : 'No investigation selected'}</h3>
          <p>
            {run
              ? 'Screening candidates are not verified findings. Change filters or inspect investigation activity.'
              : 'Select a saved run or launch a bounded investigation. Results appear only when the agent persists them.'}
          </p>
        </div>
      )}
    </div>
  );
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#Overview" onClick={() => setPage('Overview')}>
          <span className="brand-mark">L</span>
          <span>
            ledgerline<small>CONTRACT OPERATIONS</small>
          </span>
        </a>
        <span className="nav-label">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {pages.map((p, i) => (
            <button
              key={p}
              className={page === p ? 'nav-item active' : 'nav-item'}
              onClick={() => setPage(p)}
            >
              <Glyph kind={['grid', 'pulse', 'file', 'check', 'clock'][i]} />
              {p}
              {p === 'Review Queue' && pending.length > 0 && <b>{pending.length}</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <Glyph kind="lock" />
          <strong>Controlled by design</strong>
          <p>AI investigates. Python calculates. You decide.</p>
          <span>No billing writes</span>
        </div>
        <div className="workspace-id">
          <span className="avatar">CO</span>
          <div>
            Contract Operations<small>Local operator workspace</small>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span className="breadcrumb">Workspace</span>
            <span className="slash">/</span>
            {page}
          </div>
          <div className="topbar-actions">
            <span className="environment-dot" />
            {recorded ? 'Recorded Investigation' : 'Local · read-only billing'}
            {session?.authenticated ? (
              <button className="quiet" onClick={() => void signOut()} disabled={busy}>
                Sign out
              </button>
            ) : (
              !recorded && (
                <button className="quiet" onClick={() => setLoginOpen(true)}>
                  Operator sign in
                </button>
              )
            )}
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                CONTRACT & BILLING INTELLIGENCE <span>APRIL 2026</span>
              </div>
              <h1>
                {page === 'Overview'
                  ? 'From contract to clarity.'
                  : page === 'Investigations'
                    ? 'Follow the evidence.'
                    : page === 'Findings'
                      ? 'Findings, with the proof.'
                      : page === 'Review Queue'
                        ? 'Your judgment. Fully informed.'
                        : 'A record of every decision.'}
              </h1>
              <p>
                {page === 'Overview'
                  ? 'One workspace for AI-led investigation and human financial oversight.'
                  : page === 'Investigations'
                    ? 'Genuine tool selections, source retrieval and decisions from the persisted journal.'
                    : page === 'Review Queue'
                      ? 'Review and export approvals never authorize financial corrections.'
                      : 'Trace every finding back to its source, revision and review.'}
              </p>
            </div>
            <button
              className="primary"
              disabled={
                !session?.authenticated ||
                recorded ||
                busy ||
                !!liveActive ||
                !health?.launch_available
              }
              onClick={() => setLaunchOpen(true)}
            >
              <Glyph kind="pulse" />
              Run investigation
            </button>
          </div>
          {error && (
            <div className="notice error" role="alert">
              <strong>Action needs attention.</strong> {error}
              <button
                className="quiet"
                onClick={() => {
                  setError('');
                  if (readable) void refreshAll();
                }}
              >
                Dismiss / refresh
              </button>
            </div>
          )}
          {!recorded && health && !health.launch_available && (
            <div className="notice">
              <Glyph kind="lock" />
              <span>
                {!health.operator_configured
                  ? 'Configure the local operator credential to enable sign in.'
                  : !health.dataset_ready
                    ? 'Build the isolated public runtime to enable investigations.'
                    : !health.api_key_configured
                      ? 'OpenAI credentials are absent. History remains available; launch is disabled.'
                      : 'Launch is unavailable.'}{' '}
                No API key is sent to the browser.
              </span>
            </div>
          )}
          {stale && (
            <div className="notice error">
              This run uses an earlier source revision. Historical evidence remains visible;
              decisions and exports require a new investigation.
            </div>
          )}
          {recorded && (
            <div className="notice recorded">
              <Glyph kind="clock" />
              <span>
                <strong>Recorded Investigation.</strong> Historical genuine events only. Paid
                execution, review decisions and exports are disabled.
              </span>
            </div>
          )}
          {!readable ? (
            <section className="panel welcome">
              <div className="welcome-icon">
                <Glyph kind="lock" />
              </div>
              <div className="eyebrow">HUMAN OVERSIGHT, BUILT IN</div>
              <h2>
                A clearer path from signed terms
                <br />
                to billing confidence.
              </h2>
              <p>
                The agent screens records, challenges discrepancies against original contracts, and
                brings supported findings to a Contract & Billing Operations Specialist.
              </p>
              <div className="principles">
                <span>01 · Deterministic calculations</span>
                <span>02 · Cited source evidence</span>
                <span>03 · Explicit human review</span>
              </div>
              <button className="primary" onClick={() => setLoginOpen(true)}>
                Enter operator workspace
                <Glyph kind="arrow" />
              </button>
            </section>
          ) : (
            <>
              {loading ? (
                <div className="empty" role="status">
                  Loading persisted workspace…
                </div>
              ) : (
                <>
                  <div className="run-selector">
                    <div>
                      <span className="eyebrow">
                        {run?.mode === 'recorded'
                          ? 'RECORDED INVESTIGATION'
                          : 'SELECTED INVESTIGATION'}
                      </span>
                      <select
                        aria-label="Select investigation"
                        value={runId}
                        onChange={(e) => setRunId(e.target.value)}
                      >
                        <option value="">
                          {runs.length ? 'Select a run' : 'No saved investigations'}
                        </option>
                        {runs.map((r) => (
                          <option key={r.id} value={r.id}>
                            {new Date(r.created_at).toLocaleString()} · {statusLabel(r.status)} ·{' '}
                            {r.id.slice(0, 8)}
                          </option>
                        ))}
                      </select>
                    </div>
                    {run && (
                      <div className="run-status">
                        <Badge status={run.status} />
                        <span>{run.reason.replaceAll('_', ' ')}</span>
                      </div>
                    )}
                  </div>
                  {(page === 'Overview' || page === 'Investigations') && (
                    <>
                      <section className="metrics">
                        <Metric
                          label="Customers in source dataset"
                          value={count(dataset?.customer_count)}
                          note="Available inventory · not an audit result"
                        />
                        <Metric
                          label="April invoice records"
                          value={count(dataset?.invoice_count)}
                          note="Source records · CAD billing period"
                        />
                        <Metric
                          label="Potential additional receivables"
                          value={money(run?.financial_totals.additional_receivables_cad)}
                          note="Verified differences · no cash recovered"
                        />
                        <Metric
                          label="Potential customer credits"
                          value={money(run?.financial_totals.potential_credits_cad)}
                          note="Verified differences · no credit issued"
                        />
                      </section>
                      <div className="overview-grid">
                        <section className="panel progress-panel">
                          <div className="section-heading">
                            <div>
                              <span className="eyebrow">INVESTIGATION COVERAGE</span>
                              <h2>
                                {run ? 'A controlled view of the work.' : 'Ready when you are.'}
                              </h2>
                            </div>
                            {run && <Badge status={run.status} />}
                          </div>
                          <div className="coverage-numbers">
                            <div>
                              <strong>{count(run?.customers_compared.length)}</strong>
                              <span>Customers screened</span>
                            </div>
                            <div>
                              <strong>
                                {count(run?.customers_with_retrieved_documents.length)}
                              </strong>
                              <span>Source-investigated</span>
                            </div>
                            <div>
                              <strong>{run ? verified.length : '—'}</strong>
                              <span>Verified findings</span>
                            </div>
                            <div>
                              <strong>{run ? pending.length : '—'}</strong>
                              <span>Pending human reviews</span>
                            </div>
                          </div>
                          <progress
                            className="progress-track"
                            aria-label="Structured screening coverage"
                            value={run?.customers_compared.length ?? 0}
                            max={
                              dataset?.customer_count ??
                              Math.max(1, run?.customers_compared.length ?? 1)
                            }
                          />
                          <p className="caption">
                            {run?.screening_complete
                              ? 'Structured screening is complete. Findings and review coverage are separate requirements.'
                              : 'Screening checks structured records. Source investigation establishes the evidence behind a finding.'}
                          </p>
                          <div className="review-summary">
                            <span>
                              <b>
                                {run
                                  ? run.findings.filter((f) => f.state === 'proposed').length
                                  : '—'}
                              </b>{' '}
                              proposed / unresolved findings
                            </span>
                            <span>
                              <b>{count(run?.metrics.human_review_requests)}</b> reviews requested
                            </span>
                          </div>
                          <div className="control-strip">
                            <Glyph kind="lock" />
                            <span>
                              Potential billing differences are never presented as recovered cash or
                              workforce savings.
                            </span>
                          </div>
                        </section>
                        <section className="panel activity-panel">
                          <div className="section-heading">
                            <div>
                              <span className="eyebrow">
                                {recorded ? 'RECORDED ACTIVITY' : 'AGENT ACTIVITY'}
                              </span>
                              <h2>
                                {liveActive
                                  ? 'Investigation in motion'
                                  : 'Evidence leaves a trail.'}
                              </h2>
                            </div>
                            {liveActive && <span className="live-indicator">LIVE</span>}
                          </div>
                          <div className="connection">{run ? connection : 'No run started'}</div>
                          <ol className="activity-list">
                            {events.slice(-7).map((e) => (
                              <li key={e.sequence}>
                                <span
                                  className={
                                    'activity-dot ' + (e.type.includes('failed') ? 'warn' : '')
                                  }
                                />
                                <div>
                                  <span className="stage">{stageFor(e.type)}</span>
                                  <p>{e.summary}</p>
                                  <time>
                                    {new Date(e.timestamp).toLocaleTimeString()} · #{e.sequence} ·{' '}
                                    {e.actor}
                                  </time>
                                </div>
                              </li>
                            ))}
                          </ol>
                          {events.length === 0 && (
                            <div className="activity-empty">
                              {recorded
                                ? 'Import a sanitized genuine recording to see its historical events.'
                                : 'Activity appears only when the backend records a real event.'}
                            </div>
                          )}
                          <div className="activity-footer">
                            <span>Original sequence IDs · reconnectable SSE</span>
                            <Glyph kind="check" />
                          </div>
                        </section>
                      </div>
                    </>
                  )}
                  {(page === 'Overview' || page === 'Findings' || page === 'Review Queue') && (
                    <section className="panel findings-panel">
                      <div className="section-heading">
                        <div>
                          <span className="eyebrow">
                            {page === 'Review Queue'
                              ? 'HUMAN AUTHORIZATION'
                              : 'EVIDENCE-BACKED WORK'}
                          </span>
                          <h2>
                            {page === 'Review Queue' ? 'Pending decisions' : 'Findings explorer'}
                          </h2>
                        </div>
                        <span className="muted">{shown.length} findings in view</span>
                      </div>
                      <div className="filters">
                        <select
                          aria-label="Filter verification"
                          value={stateFilter}
                          onChange={(e) => setStateFilter(e.target.value)}
                        >
                          <option value="all">All verification states</option>
                          {['verified', 'proposed', 'retracted'].map((s) => (
                            <option key={s} value={s}>
                              {statusLabel(s)}
                            </option>
                          ))}
                        </select>
                        <select
                          aria-label="Filter review status"
                          value={reviewFilter}
                          onChange={(e) => setReviewFilter(e.target.value)}
                        >
                          <option value="all">All review states</option>
                          {[
                            'pending',
                            'approved',
                            'rejected',
                            'needs_information',
                            'invalidated',
                          ].map((s) => (
                            <option key={s} value={s}>
                              {statusLabel(s)}
                            </option>
                          ))}
                        </select>
                        <select
                          aria-label="Filter impact type"
                          value={impactFilter}
                          onChange={(e) => setImpactFilter(e.target.value)}
                        >
                          <option value="all">All impact types</option>
                          {[
                            'Potential receivable',
                            'Potential customer credit',
                            'Shared pricing pattern',
                            'Possible duplicate',
                            'Signed terms conflict',
                          ].map((s) => (
                            <option key={s}>{s}</option>
                          ))}
                        </select>
                      </div>
                      {table}
                    </section>
                  )}
                  {page === 'Investigations' && (
                    <section className="panel findings-panel">
                      <div className="section-heading">
                        <div>
                          <span className="eyebrow">STRUCTURED SCREENING</span>
                          <h2>Candidates are a starting point.</h2>
                        </div>
                        <span className="muted">Not verified findings</span>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Customer</th>
                              <th>Screening result</th>
                              <th>Expected</th>
                              <th>Billed</th>
                              <th>Difference</th>
                            </tr>
                          </thead>
                          <tbody>
                            {run?.candidates.map((c) => (
                              <tr key={c.customer_id}>
                                <td>{c.customer_id}</td>
                                <td>{c.status.replaceAll('_', ' ')}</td>
                                <td>{money(c.expected_cad)}</td>
                                <td>{money(c.billed_cad)}</td>
                                <td>
                                  {money(c.difference_cad)}
                                  {c.difference_cad == null && <small>Human judgment needed</small>}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!run?.candidates.length && (
                          <div className="empty">No screening candidates have been persisted.</div>
                        )}
                      </div>
                    </section>
                  )}
                  {(page === 'Overview' || page === 'Investigations') && (
                    <section className="panel telemetry">
                      <div className="section-heading">
                        <div>
                          <span className="eyebrow">OBSERVED EXECUTION · NO ROI ASSUMPTIONS</span>
                          <h2>Performance, without the guesswork.</h2>
                        </div>
                      </div>
                      <div className="telemetry-grid">
                        <Metric
                          label="Runtime"
                          value={
                            run?.metrics.duration_seconds == null
                              ? '—'
                              : run.metrics.duration_seconds.toFixed(1) + 's'
                          }
                          note={liveActive ? 'Elapsed wall time' : 'Persisted run duration'}
                        />
                        <Metric
                          label="Tool selections"
                          value={count(run?.metrics.agent_tool_calls)}
                          note="Actual dispatched calls"
                        />
                        <Metric
                          label="Responses requests"
                          value={count(run?.metrics.api_requests)}
                          note="Actual API requests"
                        />
                        <Metric
                          label="Input / output tokens"
                          value={
                            run
                              ? `${count(run.metrics.input_tokens)} / ${count(run.metrics.output_tokens)}`
                              : '—'
                          }
                          note={`Cached input: ${count(run?.metrics.cached_input_tokens)}`}
                        />
                        <Metric
                          label="Conservative estimated spend"
                          value={
                            run?.metrics.estimated_api_cost_usd == null
                              ? '—'
                              : 'US$' + run.metrics.estimated_api_cost_usd
                          }
                          note="Full-input rate · cooperative budget"
                        />
                        <Metric
                          label="Usage-priced estimate"
                          value={
                            run?.metrics.usage_priced_cost_usd == null
                              ? 'Unknown'
                              : 'US$' + run.metrics.usage_priced_cost_usd
                          }
                          note="Actual billed cost: unknown"
                        />
                      </div>
                      {run?.metrics.cost_accounting_complete === false && (
                        <p className="caption">
                          Reported usage is partial. An interrupted or failed request may have
                          unreturned usage; actual billed cost is unknown.
                        </p>
                      )}
                    </section>
                  )}
                  {page === 'Audit History' && (
                    <section className="panel">
                      <div className="section-heading">
                        <div>
                          <span className="eyebrow">PERSISTED INVESTIGATIONS</span>
                          <h2>A durable audit trail.</h2>
                        </div>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Started</th>
                              <th>Run</th>
                              <th>Status</th>
                              <th>Stop reason</th>
                              <th>Findings</th>
                              <th>Open</th>
                            </tr>
                          </thead>
                          <tbody>
                            {runs.map((r) => (
                              <tr key={r.id}>
                                <td>{new Date(r.created_at).toLocaleString()}</td>
                                <td>
                                  <code>{r.id.slice(0, 12)}</code>
                                  <small>
                                    {r.mode === 'recorded' ? 'Recorded Investigation' : r.model}
                                  </small>
                                </td>
                                <td>
                                  <Badge status={r.status} />
                                </td>
                                <td>{r.reason.replaceAll('_', ' ')}</td>
                                <td>{r.findings.length}</td>
                                <td>
                                  <button
                                    className="text-button"
                                    onClick={() => {
                                      setRunId(r.id);
                                      setPage('Investigations');
                                    }}
                                  >
                                    Inspect run →
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!runs.length && (
                          <div className="empty">
                            <h3>
                              {recorded ? 'No genuine recording imported' : 'No investigations yet'}
                            </h3>
                            <p>
                              {recorded
                                ? 'An operator must import and inspect a sanitized genuine run. This is an intentionally empty recorded workspace.'
                                : 'A launched investigation is persisted here, including partial or failed runs.'}
                            </p>
                          </div>
                        )}
                      </div>
                      {run && (
                        <details className="audit-events">
                          <summary>Selected run · full event timeline ({events.length})</summary>
                          {events.map((e) => (
                            <div key={e.sequence}>
                              <code>#{e.sequence}</code>
                              <time>{new Date(e.timestamp).toLocaleString()}</time>
                              <strong>{e.type}</strong>
                              <span>
                                {e.summary}
                                {e.decision && (
                                  <>
                                    {' '}
                                    · {statusLabel(e.decision)} by {e.reviewer} · version{' '}
                                    {e.finding_version}
                                    <br />
                                    {e.rationale}
                                  </>
                                )}
                              </span>
                            </div>
                          ))}
                        </details>
                      )}
                    </section>
                  )}
                </>
              )}
            </>
          )}
          <footer className="page-footer">
            <span>
              ledgerline <b> / </b> Contract & Billing Operations
            </span>
            <span>AI investigates · deterministic financial controls · human authorization</span>
          </footer>
        </main>
      </div>
      {loginOpen && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="login-title">
            <button
              className="modal-close icon-button"
              onClick={() => setLoginOpen(false)}
              aria-label="Close sign in"
            >
              <Glyph kind="close" />
            </button>
            <div className="eyebrow">LOCAL OPERATOR SESSION</div>
            <h2 id="login-title">Enter your workspace.</h2>
            <p>
              Use the operator credential configured on this local server. This is not your OpenAI
              API key.
            </p>
            <form onSubmit={signIn}>
              <label>
                Operator credential
                <input
                  type="password"
                  autoFocus
                  autoComplete="current-password"
                  value={token}
                  minLength={5}
                  maxLength={512}
                  required
                  onChange={(e) => setToken(e.target.value)}
                />
              </label>
              <button className="primary" disabled={busy}>
                {busy ? 'Signing in…' : 'Sign in securely'}
              </button>
            </form>
            <small>Session cookie is HttpOnly and expires after eight hours.</small>
          </section>
        </div>
      )}
      {launchOpen && (
        <div className="modal-backdrop">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="launch-title">
            <button
              className="modal-close icon-button"
              onClick={() => setLaunchOpen(false)}
              aria-label="Close investigation setup"
            >
              <Glyph kind="close" />
            </button>
            <div className="eyebrow">BOUNDED, READ-ONLY INVESTIGATION</div>
            <h2 id="launch-title">Let the agent investigate.</h2>
            <p>
              April 2026 · gpt-6.1-sol. The agent chooses its investigation path. Python owns every
              financial calculation.
            </p>
            <div className="limits">
              <span>35 tools</span>
              <span>40 Responses</span>
              <span>180 seconds</span>
              <span>US$1 estimated cap</span>
            </div>
            <form onSubmit={launch}>
              <p className="caption">
                Confirm current USD prices per million tokens. The estimated cap is cooperative, not
                a provider billing ceiling.
              </p>
              <div className="price-inputs">
                <label>
                  Input
                  <input
                    type="number"
                    min="0.001"
                    max="1000"
                    step="any"
                    value={inputPrice}
                    required
                    onChange={(e) => setInputPrice(e.target.value)}
                  />
                </label>
                <label>
                  Cached input
                  <input
                    type="number"
                    min="0"
                    max={inputPrice || 1000}
                    step="any"
                    value={cachedPrice}
                    required
                    onChange={(e) => setCachedPrice(e.target.value)}
                  />
                </label>
                <label>
                  Output
                  <input
                    type="number"
                    min="0.001"
                    max="1000"
                    step="any"
                    value={outputPrice}
                    required
                    onChange={(e) => setOutputPrice(e.target.value)}
                  />
                </label>
              </div>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={paid}
                  required
                  onChange={(e) => setPaid(e.target.checked)}
                />
                I authorize this one paid API investigation using the configured server credential.
              </label>
              <button className="primary" disabled={busy || !paid}>
                {busy ? 'Starting…' : 'Start one investigation'}
                <Glyph kind="arrow" />
              </button>
            </form>
          </section>
        </div>
      )}
      {selected && currentFinding && (
        <div className="drawer-backdrop" onClick={() => setSelected(null)}>
          <aside
            className="drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="finding-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-top">
              <span className="eyebrow">FINDING DETAIL · VERSION {currentFinding.version}</span>
              <button
                className="icon-button"
                onClick={() => setSelected(null)}
                aria-label="Close finding"
              >
                <Glyph kind="close" />
              </button>
            </div>
            <h2 id="finding-title">{currentFinding.customer_ids.join(' · ')}</h2>
            <h3>{findingCategory(currentFinding)}</h3>
            <div className="drawer-badges">
              <Badge status={currentFinding.state} />
              {currentReview && <Badge status={currentReview.status} />}
            </div>
            <div className="hypothesis">
              <span className="eyebrow">
                {currentFinding.origin === 'deterministic_conflict_guard'
                  ? 'PYTHON CONFLICT GUARD'
                  : 'AI HYPOTHESIS · NOT A LEGAL CONCLUSION'}
              </span>
              <p>
                {currentFinding.model_hypothesis ??
                  'Contradictory signed terms require human review. The calculator did not choose a payable term.'}
              </p>
            </div>
            <h3>Deterministic financial comparison</h3>
            <div className="comparison-cards">
              {(
                currentFinding.comparisons ??
                (currentFinding.comparison ? [currentFinding.comparison] : [])
              ).map((c) => (
                <div key={c.customer_id}>
                  <strong>{c.customer_id}</strong>
                  <dl>
                    <dt>Expected</dt>
                    <dd>{money(c.expected_cad)}</dd>
                    <dt>Billed</dt>
                    <dd>{money(c.billed_cad)}</dd>
                    <dt>Difference</dt>
                    <dd>{money(c.difference_cad)}</dd>
                  </dl>
                  {c.status === 'duplicate_invoice' && (
                    <p className="warning">
                      Multiple invoices need human reconciliation. Their sum is not confirmed
                      duplicate exposure; no payable invoice was selected.
                    </p>
                  )}
                  {c.status === 'conflict' && (
                    <p className="warning">
                      Conflicting signed amendments. No expected charge or financial difference can
                      be chosen automatically.
                    </p>
                  )}
                </div>
              ))}
            </div>
            <h3>
              Original evidence{' '}
              <span className="muted">{currentFinding.evidence_ids.length} citations</span>
            </h3>
            <p className="caption">
              {currentFinding.evidence_verified
                ? 'Sources were retrieved and checked by backend verification.'
                : 'This finding has not completed evidence verification.'}{' '}
              Historical sources come from this run’s journal.
            </p>
            {evidenceLoading ? (
              <p role="status">Loading recorded sources…</p>
            ) : evidence.length ? (
              evidence.map((doc) => (
                <details className="source" key={doc.document_id}>
                  <summary>
                    {doc.document_id}
                    <span>
                      {doc.redacted
                        ? 'Sanitized recording'
                        : doc.kind === 'invoice'
                          ? 'Invoice record'
                          : 'Original source'}
                    </span>
                  </summary>
                  {doc.sha256 && (
                    <small>
                      {doc.redacted ? 'Original SHA-256 (before redaction)' : 'SHA-256'}{' '}
                      {doc.sha256}
                    </small>
                  )}
                  <pre>{doc.text ?? JSON.stringify(doc.record, null, 2)}</pre>
                </details>
              ))
            ) : (
              <p className="notice">
                No source text was retrieved for this finding. Citations alone do not establish
                evidence verification.
              </p>
            )}
            <h3>Review & authorization</h3>
            <p className="caption">
              {currentReview?.action === 'export'
                ? 'This request authorizes an evidence export only.'
                : 'This request authorizes review only, not an export or financial correction.'}{' '}
              Pending review is not approval.
            </p>
            {currentReview?.status === 'pending' && !recorded && !liveActive && (
              <>
                <label>
                  Decision rationale
                  <textarea
                    value={rationale}
                    minLength={5}
                    maxLength={1000}
                    onChange={(e) => setRationale(e.target.value)}
                    placeholder="Explain the evidence and the judgment behind your decision."
                  />
                </label>
                <div className="decision-actions">
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      stale ||
                      rationale.trim().length < 5 ||
                      currentFinding.state !== 'verified' ||
                      !currentFinding.evidence_verified
                    }
                    onClick={() => void decide('approved')}
                  >
                    Approve {currentReview.action === 'export' ? 'export' : 'review only'}
                  </button>
                  <button
                    className="secondary"
                    disabled={busy || stale || rationale.trim().length < 5}
                    onClick={() => void decide('needs_information')}
                  >
                    Request clarification
                  </button>
                  <button
                    className="danger-button"
                    disabled={busy || stale || rationale.trim().length < 5}
                    onClick={() => void decide('rejected')}
                  >
                    Reject hypothesis
                  </button>
                </div>
                <p className="caption">
                  Clarification records a needs-information decision for this version. It does not
                  resume the agent; fresh evidence requires a new investigation.
                </p>
              </>
            )}
            {liveActive && (
              <p className="notice">Review is locked while this investigation is running.</p>
            )}
            {currentReview?.decision && (
              <div className="decision-record">
                <strong>{statusLabel(currentReview.decision.decision)}</strong>
                <p>
                  {currentReview.decision.rationale ??
                    'No rationale was captured by this historical CLI version.'}
                </p>
                <small>
                  {currentReview.decision.reviewer} ·{' '}
                  {new Date(currentReview.decision.decided_at).toLocaleString()}
                </small>
              </div>
            )}
            <button
              className="secondary"
              disabled={busy || stale || !run || !exportAllowed(run, currentFinding, currentReview)}
              onClick={() => void download()}
            >
              Download approved evidence package
            </button>
            <div className="revision">
              <strong>Evidence revision</strong>
              <code>{currentFinding.data_revision}</code>
              <small>
                Finding {currentFinding.finding_id} · Event snapshot {run?.report_event_sequence} /
                journal {run?.last_event_sequence}
              </small>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
