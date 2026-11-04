import { CollaborationSummary } from './CaseWorkflow';
import { useEffect, useRef, useState } from 'react';
import { api, bootstrapSession, setCsrf } from './api';
import type { Activity, Dataset, Finding, Health, ReviewSettings, Run, Session } from './types';
import {
  businessActivity,
  businessTimeline,
  businessTitle,
  exportAllowed,
  findingAmount,
  humanActionLabel,
  isActive,
  mergeEvents,
  needsAttention,
  statusLabel,
  stopExplanation,
} from './mapping.mjs';
import CaseDetail from './CaseDetail';

type Scene = 'start' | 'working' | 'summary' | 'attention' | 'history' | 'advanced';
const money = (value: string | null | undefined, currency = 'CAD') =>
  value == null
    ? 'Not available'
    : new Intl.NumberFormat('en-CA', { style: 'currency', currency }).format(Number(value));
const periodName = (period: string | undefined) =>
  period
    ? new Date(period + '-15T12:00:00Z').toLocaleDateString(undefined, {
        month: 'long',
        year: 'numeric',
      })
    : 'April 2026';
const date = (value: string) => new Date(value).toLocaleString();
function Mark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      L
    </span>
  );
}
function Badge({ value }: { value: string }) {
  return <span className={'badge ' + value}>{statusLabel(value)}</span>;
}

export default function App() {
  const [scene, setScene] = useState<Scene>(() =>
    ['start', 'working', 'summary', 'attention', 'history', 'advanced'].includes(
      location.hash.slice(1),
    )
      ? (location.hash.slice(1) as Scene)
      : 'start',
  );
  const [session, setSession] = useState<Session | null>(null),
    [health, setHealth] = useState<Health | null>(null),
    [dataset, setDataset] = useState<Dataset | null>(null),
    [pricing, setPricing] = useState<ReviewSettings | null>(null);
  const [runs, setRuns] = useState<Run[]>([]),
    [run, setRun] = useState<Run | null>(null),
    [runId, setRunId] = useState(new URLSearchParams(location.search).get('run') ?? '');
  const [events, setEvents] = useState<Activity[]>([]),
    [connection, setConnection] = useState('Connecting'),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState(false),
    [authorized, setAuthorized] = useState(false),
    [selectedId, setSelectedId] = useState('');
  const [inputPrice, setInputPrice] = useState(''),
    [cachedPrice, setCachedPrice] = useState(''),
    [outputPrice, setOutputPrice] = useState(''),
    [ratesChecked, setRatesChecked] = useState(false),
    [savedMessage, setSavedMessage] = useState('');
  const [filter, setFilter] = useState('all');
  const selectedRun = useRef(runId);
  selectedRun.current = runId;
  const recorded = session?.mode === 'recorded';
  const ready = !!session && (session.authenticated || recorded);
  const active = !!run && isActive(run.status);
  const currentFinding = run?.findings.find((f) => f.finding_id === selectedId);
  const reviewFor = (finding: Finding) =>
    run?.reviews.find((r) => r.finding_id === finding.finding_id);
  const humanFor = (finding: Finding) =>
    run?.interventions?.filter((r) => r.finding_id === finding.finding_id).at(-1);
  const workflowBadge = (finding: Finding) =>
    humanFor(finding) ? (
      <span className="badge pending">{humanActionLabel(humanFor(finding)!.action)}</span>
    ) : reviewFor(finding) ? (
      <Badge value={reviewFor(finding)!.status} />
    ) : null;
  const attention =
    run?.findings.filter((f) => needsAttention(f, run.reviews, run.interventions)) ?? [];
  const verified =
    run?.findings.filter(
      (f) =>
        f.state === 'verified' &&
        f.evidence_verified &&
        f.data_revision === run.data_revision &&
        !f.requires_revalidation,
    ) ?? [];
  const proposed = run?.findings.filter((f) => f.state === 'proposed') ?? [];
  const savedFindings = run?.findings.filter((f) => f.state !== 'retracted') ?? [];
  const stale = !!(
    dataset?.data_revision &&
    run?.data_revision &&
    dataset.data_revision !== (run.continuation?.base_revision ?? run.data_revision)
  );
  const businessEvents = businessTimeline(events);
  const latestActivity = businessEvents.at(-1)?.text;
  const runningRun = runs.find((r) => isActive(r.status));
  const selectedPeriod = periodName(dataset?.period ?? run?.period);

  async function loadWorkspace() {
    const [data, list, settings] = await Promise.allSettled([
      api<Dataset>('/dataset'),
      api<Run[]>('/runs'),
      api<ReviewSettings>('/admin/pricing'),
    ]);
    if (data.status === 'fulfilled') setDataset(data.value);
    if (list.status === 'fulfilled') {
      setRuns(list.value);
      if (!selectedRun.current && list.value.length) setRunId(list.value[0].id);
    }
    if (settings.status === 'fulfilled') setPricing(settings.value);
    const failures = [data, list, settings].filter((item) => item.status === 'rejected');
    if (failures.length)
      setError(failures.map((item) => (item as PromiseRejectedResult).reason.message).join(' '));
    setLoading(false);
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
    Promise.all([bootstrapSession(), api<Health>('/health')])
      .then(([s, h]) => {
        setSession(s);
        setCsrf(s.csrf_token);
        setHealth(h);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    if (ready) void loadWorkspace();
  }, [ready]);
  useEffect(() => {
    history.replaceState(
      null,
      '',
      (runId ? '?run=' + encodeURIComponent(runId) : '') + '#' + scene,
    );
  }, [runId, scene]);
  useEffect(() => {
    const reconnect = () => {
      setCsrf(null);
      void bootstrapSession()
        .then((s) => {
          setSession(s);
          setCsrf(s.csrf_token);
          setError(
            'Your local session was renewed. Check the saved review before deliberately retrying an action.',
          );
        })
        .catch((e) => setError(e.message));
    };
    window.addEventListener('ctc-session-expired', reconnect);
    return () => window.removeEventListener('ctc-session-expired', reconnect);
  }, []);
  useEffect(() => {
    if (!ready || !runId) return;
    let disposed = false;
    setRun(null);
    setEvents([]);
    setSelectedId('');
    setConnection('Connecting');
    void refreshRun(runId);
    const stream = new EventSource('/api/runs/' + encodeURIComponent(runId) + '/events');
    const timer = setInterval(() => {
      if (!disposed) void refreshRun(runId);
    }, 1200);
    stream.onopen = () =>
      setConnection(recorded ? 'Recorded history connected' : 'Activity connected');
    stream.addEventListener('activity', (message) => {
      if (!disposed)
        setEvents(
          (previous) =>
            mergeEvents(previous, [JSON.parse((message as MessageEvent).data)]) as Activity[],
        );
    });
    stream.addEventListener('settled', () => {
      stream.close();
      clearInterval(timer);
      if (!disposed) {
        setConnection('Saved history synchronized');
        void refreshRun(runId);
      }
    });
    stream.onerror = () => {
      if (!disposed) setConnection('Connection interrupted · reconnecting');
    };
    return () => {
      disposed = true;
      clearInterval(timer);
      stream.close();
    };
  }, [runId, ready, recorded]);
  useEffect(() => {
    if (scene === 'working' && run && !isActive(run.status)) setScene('summary');
  }, [run?.status, scene]);
  useEffect(() => {
    if (!confirmation) return;
    const old = document.activeElement as HTMLElement | null;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setConfirmation(false);
        setAuthorized(false);
      }
      if (event.key === 'Tab') {
        const controls = [
          ...document.querySelectorAll<HTMLElement>(
            '.confirmation button:not(:disabled),.confirmation input',
          ),
        ];
        const first = controls[0],
          last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener('keydown', handler);
    document.querySelector<HTMLElement>('.confirm-close')?.focus();
    return () => {
      document.removeEventListener('keydown', handler);
      old?.focus();
    };
  }, [confirmation]);
  async function beginReview() {
    setBusy(true);
    setError('');
    try {
      const created = await api<Run>('/billing-reviews', {
        method: 'POST',
        body: JSON.stringify({
          idempotency_key: crypto.randomUUID(),
          acknowledge_paid: authorized,
        }),
      });
      setRunId(created.id);
      setRun(created);
      setScene('working');
      setConfirmation(false);
      setAuthorized(false);
    } catch (e) {
      setError((e as Error).message);
      setConfirmation(false);
      void loadWorkspace();
    } finally {
      setBusy(false);
    }
  }
  async function savePricing(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setSavedMessage('');
    try {
      const state = await api<ReviewSettings>('/admin/pricing', {
        method: 'PUT',
        body: JSON.stringify({
          input_price: inputPrice,
          cached_input_price: cachedPrice,
          output_price: outputPrice,
          checked_current_official_rates: ratesChecked,
        }),
      });
      setPricing(state);
      setRatesChecked(false);
      setSavedMessage(
        'Administrator confirmation saved for 24 hours. Billing review can now be authorized.',
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function refreshHumanActivity(id: string) {
    try {
      const response = await fetch(`/api/runs/${id}/events?after=${events.at(-1)?.sequence ?? 0}`, {
        credentials: 'same-origin',
      });
      if (!response.ok) throw new Error();
      const saved = (await response.text())
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => JSON.parse(line.slice(6)))
        .filter((item) => Number.isInteger(item.sequence));
      setEvents((previous) => mergeEvents(previous, saved) as Activity[]);
    } catch {
      setError(
        'Your decision was saved, but activity could not refresh. Reopen this review to inspect its retained audit trail.',
      );
    }
  }
  async function decide(decision: string, rationale: string) {
    if (!run || !currentFinding) return;
    setBusy(true);
    setError('');
    try {
      const response = await api<{ run: Run }>(
        `/runs/${run.id}/findings/${encodeURIComponent(currentFinding.finding_id)}/review`,
        {
          method: 'POST',
          body: JSON.stringify({
            decision,
            rationale,
            expected_revision: currentFinding.data_revision,
            expected_version: currentFinding.version,
          }),
        },
      );
      setRun(response.run);
      await refreshRun(run.id);
      await refreshHumanActivity(run.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    if (!run || !currentFinding) return;
    setBusy(true);
    try {
      const response = await fetch(
        `/api/runs/${run.id}/findings/${encodeURIComponent(currentFinding.finding_id)}/export`,
        { credentials: 'same-origin' },
      );
      if (!response.ok)
        throw new Error('Export is not authorized for the current evidence and decision.');
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
  function selectRun(item: Run) {
    setRunId(item.id);
    setRun(item);
    setScene(isActive(item.status) ? 'working' : 'summary');
  }
  const advancedActivity = (
    <details className="technical activity-technical">
      <summary>View Technical Activity</summary>
      <p>
        {connection} · {run?.model ?? 'No review selected'}
      </p>
      {run && (
        <dl className="technical-metrics">
          <dt>Elapsed runtime</dt>
          <dd>{run.metrics.duration_seconds ?? 'Unknown'} seconds</dd>
          <dt>Tool calls / Responses requests</dt>
          <dd>
            {run.metrics.agent_tool_calls ?? 0} / {run.metrics.api_requests ?? 0}
          </dd>
          <dt>Input / output / cached tokens</dt>
          <dd>
            {run.metrics.input_tokens ?? 'Unknown'} / {run.metrics.output_tokens ?? 'Unknown'} /{' '}
            {run.metrics.cached_input_tokens ?? 'Unknown'}
          </dd>
          <dt>Conservative estimated API cost</dt>
          <dd>
            {run.metrics.estimated_api_cost_usd == null
              ? 'Unknown'
              : 'US$' + run.metrics.estimated_api_cost_usd}
          </dd>
          <dt>Usage-priced estimate</dt>
          <dd>
            {run.metrics.usage_priced_cost_usd == null
              ? 'Unknown'
              : 'US$' + run.metrics.usage_priced_cost_usd}
          </dd>
          <dt>Actual billed cost</dt>
          <dd>Unknown unless independently reconciled</dd>
        </dl>
      )}
      {run?.metrics.cost_accounting_complete === false && (
        <p>Returned usage may be incomplete following an interrupted request.</p>
      )}
      <ol className="technical-events">
        {events.map((event) => (
          <li key={event.sequence}>
            <time>{date(event.timestamp)}</time>
            <code>
              #{event.sequence} · {event.type}
              {event.tool ? ' · ' + event.tool : ''}
            </code>
            <span>{event.summary}</span>
            {event.decision && (
              <p>
                {statusLabel(event.decision)} · {event.reviewer} · {event.rationale}
              </p>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
  const findingList = (
    <div className="finding-list">
      {(run?.findings ?? [])
        .filter((f) => (filter === 'all' ? f.state !== 'retracted' : f.state === filter))
        .map((f) => (
          <button
            className="finding-row"
            key={f.finding_id}
            onClick={() => setSelectedId(f.finding_id)}
          >
            <span className={'item-symbol ' + f.state}>{f.state === 'verified' ? '✓' : '?'}</span>
            <span className="finding-copy">
              <strong>{businessTitle(f)}</strong>
              <small>
                {f.customer_ids.join(' · ')} · {f.evidence_ids.length} cited records
              </small>
            </span>
            <span className="finding-meta">
              <Badge value={f.state} />
              {workflowBadge(f)}
              <strong>
                {findingAmount(f) == null ? 'Amount unresolved' : money(findingAmount(f))}
              </strong>
            </span>
            <span aria-hidden="true">→</span>
          </button>
        ))}
      {!savedFindings.length && (
        <div className="empty">
          <h3>No findings have been saved.</h3>
          <p>
            Screening candidates are not verified findings. Check the saved activity for any
            incomplete work.
          </p>
        </div>
      )}
    </div>
  );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#start" onClick={() => setScene('start')}>
          <Mark />
          <span>
            ledgerline<small>YOUR BILLING DESK</small>
          </span>
        </a>
        <div className="sidebar-workspace">
          <span className="eyebrow">CONTRACT & BILLING OPERATIONS</span>
          <p>
            One workspace.
            <br />
            Your judgment at the center.
          </p>
        </div>
        <nav aria-label="Main navigation">
          <button
            className={
              ['start', 'working', 'summary'].includes(scene) ? 'nav-item active' : 'nav-item'
            }
            onClick={() => setScene('start')}
          >
            <span aria-hidden="true">▤</span>Billing review
          </button>
          <button
            className={scene === 'attention' ? 'nav-item active' : 'nav-item'}
            onClick={() => setScene('attention')}
          >
            <span aria-hidden="true">◇</span>Needs your attention
            {attention.length > 0 && <b>{attention.length}</b>}
          </button>
          <button
            className={scene === 'history' ? 'nav-item active' : 'nav-item'}
            onClick={() => setScene('history')}
          >
            <span aria-hidden="true">↶</span>Past reviews
          </button>
        </nav>
        <div className="sidebar-promise">
          <span className="promise-icon">✓</span>
          <strong>
            Investigation, delegated.
            <br />
            Decisions, retained.
          </strong>
          <p>The agent checks the records. You handle the judgment and authorization.</p>
        </div>
        <button className="advanced-link" onClick={() => setScene('advanced')}>
          Advanced Settings <span aria-hidden="true">↗</span>
        </button>
        <div className="local-profile">
          <span className="avatar">
            {(session?.reviewer ?? 'Local operator')
              .split(' ')
              .map((s) => s[0])
              .slice(0, 2)
              .join('')}
          </span>
          <div>
            {session?.reviewer ?? 'Local operator'}
            <small>
              {recorded ? 'Recorded investigation' : 'Local workspace · no billing writes'}
            </small>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Contract & Billing Operations{' '}
            <span className="crumb">
              /{' '}
              {scene === 'attention'
                ? 'Your decisions'
                : scene === 'advanced'
                  ? 'Administrator settings'
                  : scene === 'history'
                    ? 'Review history'
                    : 'Monthly review'}
            </span>
          </span>
          <span className="local-pill">
            <i />
            {recorded ? 'Recorded Investigation' : 'Local workspace'}
          </span>
        </header>
        <main>
          {error && (
            <div className="notice error" role="alert">
              <strong>Something needs attention.</strong> {error}
              <button
                className="plain"
                onClick={() => {
                  setError('');
                  void loadWorkspace();
                }}
              >
                Refresh
              </button>
            </div>
          )}
          {recorded && (
            <div className="notice recorded">
              <strong>Recorded Investigation.</strong> Historical events and results only. Paid
              execution and human decisions are disabled.
            </div>
          )}
          {stale && (
            <div className="notice error">
              The source records have changed since this review. Historical evidence is available,
              but a new investigation is needed before decisions or exports.
            </div>
          )}
          {!ready || loading ? (
            <section className="empty panel" role="status">
              <h1>Opening your billing desk…</h1>
              <p>The local workspace is loading its saved records.</p>
            </section>
          ) : (
            <>
              {scene === 'start' && (
                <section className="start-scene">
                  <div className="page-heading">
                    <span className="eyebrow">YOUR MONTHLY BILLING REVIEW</span>
                    <h1>
                      {recorded
                        ? 'Explore a recorded billing review.'
                        : `Your ${selectedPeriod} billing review is ready.`}
                    </h1>
                    <p>
                      Contracts change. Billing should keep up.
                      <br />
                      Let the agent reconcile the records, then bring the judgment back to you.
                    </p>
                  </div>
                  {recorded && !runs.length ? (
                    <section className="empty panel">
                      <h2>No genuine recording has been imported.</h2>
                      <p>
                        An operator must provide and inspect a sanitized genuine investigation. No
                        findings or activity have been invented.
                      </p>
                    </section>
                  ) : (
                    <div className="start-grid">
                      <section className="review-pack panel">
                        <div className="pack-heading">
                          <span className="eyebrow">RECORDS READY FOR REVIEW</span>
                          <span className="pack-badge">
                            {dataset?.currency ?? 'CAD'} · {periodName(dataset?.period)}
                          </span>
                        </div>
                        <div className="account-count">
                          <strong>{dataset?.customer_count ?? '—'}</strong>
                          <span>customer accounts</span>
                        </div>
                        <p>Agreements, amendments and invoices in one review.</p>
                        <div className="record-strip">
                          <span>▱ Contracts</span>
                          <span>≋ Amendments</span>
                          <span>▤ {dataset?.invoice_count ?? '—'} invoices</span>
                        </div>
                        <div className="start-actions">
                          {runningRun ? (
                            <button className="primary" onClick={() => selectRun(runningRun)}>
                              View review in progress <span>→</span>
                            </button>
                          ) : (
                            <button
                              className="primary"
                              disabled={
                                busy || recorded || !health?.launch_available || !pricing?.ready
                              }
                              onClick={() => {
                                setAuthorized(false);
                                setConfirmation(true);
                              }}
                            >
                              Start Billing Review <span>→</span>
                            </button>
                          )}
                          <small>Analyze customer agreements and invoices for discrepancies.</small>
                        </div>
                        {!recorded && (!pricing?.ready || !health?.launch_available) && (
                          <div className="setup-note">
                            <strong>Administrator setup needed</strong>
                            <p>
                              {pricing?.reason === 'administrator_confirmation_expired'
                                ? 'The pricing confirmation needs to be renewed before another paid review.'
                                : 'An administrator must finish investigation setup before a paid review can start.'}
                            </p>
                            <button className="plain" onClick={() => setScene('advanced')}>
                              Open Advanced Settings →
                            </button>
                          </div>
                        )}
                        <div className="review-limits">
                          <span>
                            Up to {Math.round((pricing?.limits.maximum_seconds ?? 180) / 60)}{' '}
                            minutes
                          </span>
                          <span>
                            US${pricing?.limits.spending_limit_usd ?? '1'} estimated spending limit
                          </span>
                        </div>
                        <p className="small muted">
                          Source inventory, not an investigation result. No billing changes are
                          made.
                        </p>
                      </section>
                      <section className="your-role">
                        <span className="eyebrow">HOW THE WORK IS SHARED</span>
                        <h2>
                          A second pair of eyes.
                          <br />A clear line of control.
                        </h2>
                        <div className="role-step">
                          <span>01</span>
                          <div>
                            <strong>The agent investigates</strong>
                            <p>
                              Checks invoices against agreements, reads amendments and looks for
                              patterns.
                            </p>
                          </div>
                        </div>
                        <div className="role-step">
                          <span>02</span>
                          <div>
                            <strong>You handle the judgment</strong>
                            <p>
                              Examine the original evidence, question ambiguous cases and record a
                              decision.
                            </p>
                          </div>
                        </div>
                        <div className="role-step">
                          <span>03</span>
                          <div>
                            <strong>Nothing is acted on silently</strong>
                            <p>
                              Paid reviews need confirmation. Findings and evidence exports need the
                              right authorization.
                            </p>
                          </div>
                        </div>
                      </section>
                    </div>
                  )}
                  {run && (
                    <button
                      className="resume-review panel"
                      onClick={() => setScene(active ? 'working' : 'summary')}
                    >
                      <span>
                        <strong>
                          {recorded
                            ? 'View the recorded review'
                            : 'Return to your latest saved review'}
                        </strong>
                        <small>
                          {date(run.created_at)} · {statusLabel(run.status)}
                        </small>
                      </span>
                      <span>→</span>
                    </button>
                  )}
                </section>
              )}
              {scene === 'working' && (
                <section className="work-scene">
                  <div className="page-heading">
                    <span className="eyebrow">REVIEW IN PROGRESS</span>
                    <h1>The agent is working through the records.</h1>
                    {run?.continuation && (
                      <p className="notice">
                        Continuing only {run.continuation.customer_ids.join(', ')} with your
                        registered evidence. This is a new scoped investigation.
                      </p>
                    )}
                    <p>
                      You can stay here or return later. Your review and its evidence are saved as
                      the work happens.
                    </p>
                  </div>
                  <section className="work-panel panel">
                    <div className="work-symbol" aria-hidden="true">
                      ▤
                    </div>
                    <div className="work-status">
                      <span className="eyebrow">
                        {recorded ? 'RECORDED ACTIVITY' : 'LATEST RECORDED ACTIVITY'}
                      </span>
                      <h2>{latestActivity ?? 'Waiting for the first investigation event.'}</h2>
                      <p>
                        {connection === 'Connection interrupted · reconnecting'
                          ? 'The connection was interrupted. Reconnecting to saved activity; the review is not being restarted.'
                          : 'Every update below comes from the investigation journal.'}
                      </p>
                    </div>
                    <div className="coverage">
                      <strong>{run?.customers_compared.length ?? 0}</strong>
                      <span>accounts screened</span>
                      <strong>{run?.customers_with_retrieved_documents.length ?? 0}</strong>
                      <span>accounts with source records retrieved</span>
                    </div>
                    <ol className="business-trail">
                      {businessEvents.slice(-5).map(({ event, text }) => (
                        <li key={event.sequence}>
                          <span className="trail-dot" />
                          <div>
                            <p>{text}</p>
                            <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
                          </div>
                        </li>
                      ))}
                    </ol>
                    <div className="work-footer">
                      You retain every human decision. An incomplete review will be labeled clearly.
                    </div>
                  </section>
                  {advancedActivity}
                </section>
              )}
              {scene === 'summary' && (
                <section className="summary-scene">
                  <div className="page-heading">
                    <span className="eyebrow">YOUR SAVED REVIEW</span>
                    <div className="heading-status">
                      <h1>
                        {run?.status === 'completed'
                          ? 'The review is ready for your judgment.'
                          : savedFindings.length
                            ? 'Useful findings. A clear view of what remains.'
                            : 'The review stopped before any findings were saved.'}
                      </h1>
                      {run && <Badge value={run.status} />}
                    </div>
                    <p>
                      {run ? stopExplanation(run) : 'Choose a saved review to see its findings.'}
                    </p>
                  </div>
                  {run?.continuation && (
                    <p className="notice">
                      Continued investigation · {run.continuation.customer_ids.join(', ')} only.
                      This is a new investigation linked to the original review; it does not cover
                      the whole dataset.
                    </p>
                  )}
                  {run && <CollaborationSummary run={run} onOpen={selectRun} />}
                  {run ? (
                    <>
                      <section className="outcome-panel panel">
                        <div className="outcome-intro">
                          <span className="eyebrow">WHAT THE INVESTIGATION SAVED</span>
                          <h2>
                            {verified.length} evidence-verified{' '}
                            {verified.length === 1 ? 'finding' : 'findings'}.
                          </h2>
                          <p>
                            {proposed.length} proposed or ambiguous{' '}
                            {proposed.length === 1 ? 'item' : 'items'} still need judgment.{' '}
                            {savedFindings.length} active saved items in total.
                          </p>
                          <button
                            className="primary"
                            disabled={!attention.length}
                            onClick={() => setScene('attention')}
                          >
                            Review Items Needing My Attention <span>{attention.length} →</span>
                          </button>
                        </div>
                        <div className="financial-outcomes">
                          <div>
                            <span>Potential additional receivables</span>
                            <strong>
                              {money(run.financial_totals.additional_receivables_cad)}
                            </strong>
                          </div>
                          <div>
                            <span>Potential customer credits</span>
                            <strong>{money(run.financial_totals.potential_credits_cad)}</strong>
                          </div>
                          <p>
                            Verified billing differences only. No cash recovered, credit issued or
                            billing record changed.
                          </p>
                        </div>
                      </section>
                      <section className="panel findings-panel">
                        <div className="section-heading">
                          <div>
                            <span className="eyebrow">THE FINDINGS</span>
                            <h2>A clear path back to the evidence.</h2>
                          </div>
                          <select
                            aria-label="Filter findings"
                            value={filter}
                            onChange={(event) => setFilter(event.target.value)}
                          >
                            <option value="all">All saved items</option>
                            <option value="verified">Evidence verified</option>
                            <option value="proposed">Needs further judgment</option>
                            <option value="retracted">Withdrawn items</option>
                          </select>
                        </div>
                        {findingList}
                      </section>
                      {advancedActivity}
                    </>
                  ) : (
                    <div className="empty panel">
                      No saved review is selected.{' '}
                      <button className="plain" onClick={() => setScene('history')}>
                        Choose a past review
                      </button>
                    </div>
                  )}
                </section>
              )}
              {scene === 'attention' && (
                <section className="attention-scene">
                  <div className="page-heading">
                    <span className="eyebrow">THIS IS WHERE YOU COME IN</span>
                    <h1>Needs Your Attention</h1>
                    <p>
                      The investigation has surfaced items for your judgment. You bring the context,
                      interpretation and authorization.
                    </p>
                  </div>
                  <div className="attention-note">
                    <span aria-hidden="true">◇</span>
                    <p>
                      Open the original records before deciding. A review approval never authorizes
                      an invoice correction.
                    </p>
                  </div>
                  <div className="attention-cards">
                    {attention.map((f) => {
                      return (
                        <article className="attention-card panel" key={f.finding_id}>
                          <div className="card-top">
                            <span className="eyebrow">{f.customer_ids.join(' · ')}</span>
                            {workflowBadge(f) ?? <Badge value={f.state} />}
                          </div>
                          <h2>{businessTitle(f)}</h2>
                          <p>
                            {f.comparisons?.some((c) => c.status === 'duplicate_invoice')
                              ? 'The invoice records need reconciliation. Multiple records alone do not prove a duplicate charge.'
                              : f.comparison?.status === 'conflict' ||
                                  f.comparisons?.some((c) => c.status === 'conflict')
                                ? 'Signed terms disagree. The agent cannot safely choose which term should apply.'
                                : f.evidence_verified
                                  ? 'The source-backed difference is ready for your requested review or export decision.'
                                  : 'This interpretation needs further evidence or judgment before it can be verified.'}
                          </p>
                          <div className="card-bottom">
                            <span>
                              {f.evidence_ids.length} cited records ·{' '}
                              {f.evidence_verified ? 'Evidence checked' : 'Verification incomplete'}
                            </span>
                            <button
                              className="secondary"
                              onClick={() => setSelectedId(f.finding_id)}
                            >
                              Examine this item →
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                  {!attention.length && (
                    <section className="empty panel">
                      <h2>
                        {run
                          ? 'No pending decisions in this review.'
                          : 'Choose a saved review first.'}
                      </h2>
                      <p>
                        {run
                          ? 'Decisions already made remain visible with their rationale in the findings and audit trail.'
                          : 'Start a review or select retained work from Past reviews.'}
                      </p>
                      <button
                        className="plain"
                        onClick={() => setScene(run ? 'summary' : 'history')}
                      >
                        {run ? 'View saved findings' : 'Open Past reviews'} →
                      </button>
                    </section>
                  )}
                </section>
              )}
              {scene === 'history' && (
                <section className="history-scene">
                  <div className="page-heading">
                    <span className="eyebrow">RETAINED WORK & DECISIONS</span>
                    <h1>Past reviews</h1>
                    <p>
                      Every saved review, including unfinished work. Refreshing or opening history
                      never starts a new investigation.
                    </p>
                  </div>
                  <div className="panel history-list">
                    {runs.map((item) => (
                      <button className="history-row" key={item.id} onClick={() => selectRun(item)}>
                        <span>
                          <strong>{periodName(item.period)} billing review</strong>
                          <small>
                            {date(item.created_at)}
                            {item.mode === 'recorded' ? ' · Recorded Investigation' : ''}
                          </small>
                        </span>
                        <Badge value={item.status} />
                        <span>{item.findings.length} saved items</span>
                        <b>→</b>
                      </button>
                    ))}
                    {!runs.length && (
                      <div className="empty">
                        <h2>
                          {recorded
                            ? 'No genuine recording has been imported.'
                            : 'Your first billing review starts here.'}
                        </h2>
                        <p>
                          {recorded
                            ? 'An operator must supply and inspect a sanitized genuine investigation. No demonstration findings have been invented.'
                            : 'Saved findings, evidence and human decisions will remain available here.'}
                        </p>
                      </div>
                    )}
                  </div>
                </section>
              )}
              {scene === 'advanced' && (
                <section className="advanced-scene">
                  <div className="page-heading">
                    <span className="eyebrow">ADMINISTRATOR WORKSPACE</span>
                    <h1>Advanced Settings</h1>
                    <p>
                      Technical configuration stays here. The employee workflow stays focused on
                      review and judgment.
                    </p>
                  </div>
                  <section className="panel admin-panel">
                    <h2>Confirm current investigation pricing</h2>
                    <p className="small muted">
                      Server API credential:{' '}
                      {health?.api_key_configured
                        ? 'configured (authorization not independently verified)'
                        : 'missing — configure it on the server, never in this browser'}
                    </p>
                    <p>
                      Open the{' '}
                      <a
                        href="https://developers.openai.com/api/docs/pricing"
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        official OpenAI pricing page ↗
                      </a>{' '}
                      and compare the current standard/default-tier text rates for{' '}
                      <strong>gpt-6.1-sol</strong>. No API request is made to verify pricing.
                      Confirmation is a local administrator attestation, not an independent price
                      feed.
                    </p>
                    {pricing?.profile && (
                      <div className="notice">
                        <span>
                          {pricing.ready
                            ? 'Pricing confirmation is current.'
                            : 'Pricing confirmation expired or needs attention.'}{' '}
                          Confirmed by {pricing.profile.confirmed_by} at{' '}
                          {date(pricing.profile.confirmed_at)}; expires{' '}
                          {date(pricing.profile.expires_at)}.
                        </span>
                      </div>
                    )}
                    {!recorded && (
                      <form onSubmit={savePricing}>
                        <div className="price-fields">
                          <label>
                            Input USD per million tokens
                            <input
                              type="number"
                              min="0.000001"
                              max="1000"
                              step="any"
                              required
                              value={inputPrice}
                              onChange={(event) => setInputPrice(event.target.value)}
                            />
                          </label>
                          <label>
                            Cached input USD per million tokens
                            <input
                              type="number"
                              min="0"
                              max={inputPrice || 1000}
                              step="any"
                              required
                              value={cachedPrice}
                              onChange={(event) => setCachedPrice(event.target.value)}
                            />
                          </label>
                          <label>
                            Output USD per million tokens
                            <input
                              type="number"
                              min="0.000001"
                              max="1000"
                              step="any"
                              required
                              value={outputPrice}
                              onChange={(event) => setOutputPrice(event.target.value)}
                            />
                          </label>
                        </div>
                        <label className="checkbox">
                          <input
                            type="checkbox"
                            required
                            checked={ratesChecked}
                            onChange={(event) => setRatesChecked(event.target.checked)}
                          />
                          I checked these rates against the current official pricing page for this
                          model and service tier.
                        </label>
                        <button
                          className="primary"
                          disabled={busy || !ratesChecked || !!runningRun}
                        >
                          Save pricing confirmation
                        </button>
                        {savedMessage && (
                          <p className="success" role="status">
                            {savedMessage}
                          </p>
                        )}
                      </form>
                    )}
                    <p className="small muted">
                      No guessed default rates. Confirmations expire after 24 hours. Review limits
                      remain {pricing?.limits.max_tool_calls ?? 35} tool calls,{' '}
                      {pricing?.limits.max_responses ?? 40} Responses,{' '}
                      {pricing?.limits.maximum_seconds ?? 180} seconds and US$
                      {pricing?.limits.spending_limit_usd ?? '1'} conservative estimated spend. The
                      cap is cooperative, not a billing guarantee.
                    </p>
                  </section>
                  <section className="panel admin-panel">
                    <h2>Technical traceability</h2>
                    <p>
                      Select a saved review to inspect original event sequences, API telemetry and
                      human decisions. Private reasoning, provider secrets and API keys are never
                      exposed.
                    </p>
                    <select
                      aria-label="Select technical review"
                      value={runId}
                      onChange={(event) => setRunId(event.target.value)}
                    >
                      <option value="">Select a review</option>
                      {runs.map((item) => (
                        <option value={item.id} key={item.id}>
                          {date(item.created_at)} · {statusLabel(item.status)}
                        </option>
                      ))}
                    </select>
                    {advancedActivity}
                  </section>
                  <p className="small muted">
                    Passwordless localhost mode is not public authentication. Network or hosted
                    deployment requires proper identity and authentication first.
                  </p>
                </section>
              )}
            </>
          )}
          <footer className="footer">
            <span>ledgerline / Contract & Billing Operations</span>
            <span>Evidence-led investigation. Human authorization.</span>
          </footer>
        </main>
      </div>
      {confirmation && (
        <div className="modal-shade">
          <section
            className="confirmation"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <button
              className="plain confirm-close"
              aria-label="Close review confirmation"
              onClick={() => {
                setConfirmation(false);
                setAuthorized(false);
              }}
            >
              Close ×
            </button>
            <span className="eyebrow">START THE WORK</span>
            <h2 id="confirm-title">Start Billing Review</h2>
            <p>
              Analyze customer agreements and invoices for discrepancies. The agent investigates;
              you retain judgment and authorization.
            </p>
            <div className="confirmation-limits">
              <span>Up to {Math.round((pricing?.limits.maximum_seconds ?? 180) / 60)} minutes</span>
              <span>US${pricing?.limits.spending_limit_usd ?? '1'} estimated spending limit</span>
            </div>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={authorized}
                onChange={(event) => setAuthorized(event.target.checked)}
              />
              I authorize this investigation.
            </label>
            <p className="small muted">
              This starts one paid investigation. No invoice, credit, collection or approval is
              automatic.
            </p>
            <button
              className="primary"
              disabled={busy || !authorized || !pricing?.ready}
              onClick={() => void beginReview()}
            >
              {busy ? 'Starting…' : 'Begin authorized review'} <span>→</span>
            </button>
          </section>
        </div>
      )}

      {run && currentFinding && (
        <CaseDetail
          key={run.id + currentFinding.finding_id}
          run={run}
          finding={currentFinding}
          review={reviewFor(currentFinding)}
          onClose={() => setSelectedId('')}
          onDecision={decide}
          onUpdated={(next) => {
            setRun(next);
            void refreshRun(next.id);
            void refreshHumanActivity(next.id);
          }}
          onContinue={(next) => {
            setSelectedId('');
            setRunId(next.id);
            setRun(next);
            setScene('working');
            void loadWorkspace();
          }}
          onExport={download}
          busy={busy}
          stale={stale}
        />
      )}
    </div>
  );
}
