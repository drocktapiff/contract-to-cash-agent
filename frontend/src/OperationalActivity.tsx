import { useEffect, useState } from 'react';
import { api } from './api';
import './human-review-activity.css';
type ActivityEvent = {
  id: string;
  type: string;
  at: string;
  actor: string;
  actor_kind: string;
  before: string | null;
  after: string | null;
  operation_id: string | null;
  item_id: string | null;
  rationale: string;
  details: Record<string, unknown>;
  source_hashes: string[];
};
type Point = {
  id: string;
  series: string;
  at: string;
  first_at: string;
  count: number;
  value: number;
  event_count: number;
  cumulative_events: number;
  marker: string;
  outcomes: string[];
  operation_ids: string[];
  items: { id: string; customer_id: string; status: string; lifecycle_label: string }[];
  events: ActivityEvent[];
};
type Model = {
  session_id: string;
  series: Record<string, { label: string; colour: string }>;
  points: Point[];
  metrics: Record<string, { label: string; ids: string[]; value: number | null; basis?: string }>;
  range: { start: string | null; end: string | null };
  operations: string[];
  distinct_closed: number;
  legacy_closed: number;
  methodology: string;
};
const OUTCOMES: Record<string, string> = {
  all: 'All recorded contributions',
  prepared: 'Prepared by automation',
  awaiting_review: 'Awaiting review (current cohort)',
  approved_individual: 'Approved individually',
  approved_bulk: 'Bulk approved',
  rejected: 'Rejected',
  closed: 'Reviewed & Closed',
  escalated: 'Escalated to Sarah (received)',
  management_complete: 'Management review completed',
  returned: 'Returned to Maya',
  corrective: 'Corrective actions',
  legacy_closed: 'Legacy automated closures',
  management_coordination: 'Management coordination',
  evidence_requested: 'Evidence requested by Maya',
  review_escalated: 'Reviewed for escalation by Maya',
};
const time = (value: string | number) =>
  new Date(value).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
  });
const timestamp = (value: string) =>
  new Date(value).toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
  });
const clean = (s: string) => s.replaceAll('_', ' ');
export default function OperationalActivity({
  sid,
  revision,
  onOpen,
  onCases,
}: {
  sid: string;
  revision: unknown;
  onOpen: (id: string) => void;
  onCases: (ids: string[]) => void;
}) {
  const [data, setData] = useState<Model | null>(null),
    [mode, setMode] = useState('cumulative'),
    [group, setGroup] = useState('operation'),
    [outcome, setOutcome] = useState('all'),
    [series, setSeries] = useState(['automation', 'maya', 'sarah']),
    [operation, setOperation] = useState(''),
    [range, setRange] = useState('all'),
    [selected, setSelected] = useState<Point | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false),
    [hover, setHover] = useState<Point | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setSelected(null);
    const query = new URLSearchParams({ mode, group, outcome, series: series.join(',') });
    if (operation) query.set('operation', operation);
    if (range !== 'all' && data?.range.end) {
      query.set(
        'start',
        new Date(
          new Date(data.range.end).getTime() - (range === 'minute' ? 60000 : 3600000),
        ).toISOString(),
      );
    }
    void api<Model>(`/document-workspace/sessions/${sid}/activity?${query}`)
      .then((v) => {
        if (active) {
          setData(v);
          setError('');
        }
      })
      .catch((e) => active && setError((e as Error).message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [sid, revision, mode, group, outcome, series.join(','), operation, range]);
  const points = loading ? [] : (data?.points ?? []),
    times = points.map((p) => Date.parse(p.at)),
    min = times.length ? Math.min(...times) : 0,
    max = times.length ? Math.max(...times) : 0,
    span = Math.max(1, max - min),
    highest = Math.max(1, ...points.map((p) => p.value));
  const x = (p: Point) => (max === min ? 442 : 72 + ((Date.parse(p.at) - min) / span) * 740),
    y = (p: Point) => 282 - (p.value / highest) * 230;
  function choose(p: Point) {
    setSelected(p);
    setHover(null);
  }
  function marker(p: Point) {
    const cx = x(p),
      cy = y(p),
      size = p.series === 'automation' ? 10 : p.series === 'maya' ? 7 : 5;
    const common = {
      stroke: `var(--oa-${p.series})`,
      strokeWidth: 2.5,
      fill: 'var(--oa-surface)',
      tabIndex: 0,
      role: 'button',
      'aria-label': `${data!.series[p.series].label}: ${p.count} work items, ${p.outcomes.map((o) => OUTCOMES[o]).join(', ')}, ${time(p.at)}`,
      onClick: () => choose(p),
      onFocus: () => setHover(p),
      onBlur: () => setHover(null),
      onMouseEnter: () => setHover(p),
      onMouseLeave: () => setHover(null),
      onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          choose(p);
        }
      },
    };
    if (p.marker === 'circle') return <circle key={p.id} cx={cx} cy={cy} r={size} {...common} />;
    if (p.marker === 'square')
      return (
        <rect
          key={p.id}
          x={cx - size}
          y={cy - size}
          width={size * 2}
          height={size * 2}
          {...common}
        />
      );
    if (p.marker === 'cross')
      return (
        <path
          key={p.id}
          d={`M${cx - size},${cy - size} L${cx + size},${cy + size} M${cx - size},${cy + size} L${cx + size},${cy - size}`}
          {...common}
        />
      );
    return (
      <path
        key={p.id}
        d={
          p.marker === 'triangle'
            ? `M${cx},${cy - size} L${cx + size},${cy + size} L${cx - size},${cy + size} Z`
            : `M${cx},${cy - size} L${cx + size},${cy} L${cx},${cy + size} L${cx - size},${cy} Z`
        }
        {...common}
      />
    );
  }
  return (
    <section className="oa-panel" aria-label="Operational Activity">
      <header>
        <div>
          <span className="mw-eyebrow">AUTOMATION → HUMAN VERIFICATION → MANAGEMENT OVERSIGHT</span>
          <h3>Operational Activity</h3>
          <p>
            Actual persisted activity · session {sid.slice(0, 8)}. Contributions overlap; they are
            not additive completed work.
          </p>
        </div>
        {loading && <span role="status">Loading recorded events…</span>}
      </header>
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <div className="oa-controls">
            <fieldset>
              <legend>Activity series</legend>
              {Object.entries(data.series).map(([key, s]) => (
                <label key={key} className={'oa-legend oa-' + key}>
                  <input
                    type="checkbox"
                    checked={series.includes(key)}
                    onChange={(e) =>
                      setSeries((v) =>
                        e.target.checked ? [...v, key] : v.filter((i) => i !== key),
                      )
                    }
                  />
                  <span aria-hidden="true">
                    {key === 'automation' ? '○' : key === 'maya' ? '◇' : '△'}
                  </span>
                  {s.label}
                </label>
              ))}
            </fieldset>
            <label>
              Activity view
              <select
                aria-label="Activity view"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="cumulative">Cumulative unique work per actor</option>
                <option value="interval">Activity per recorded interval</option>
              </select>
            </label>
            <label>
              Activity outcome
              <select
                aria-label="Activity outcome"
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
              >
                {Object.entries(OUTCOMES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Time grouping
              <select
                aria-label="Time grouping"
                value={group}
                onChange={(e) => setGroup(e.target.value)}
              >
                {['operation', 'second', 'minute', 'hour'].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Recorded time range
              <select
                aria-label="Recorded time range"
                value={range}
                onChange={(e) => setRange(e.target.value)}
              >
                <option value="all">All recorded time</option>
                <option value="minute">Last recorded minute</option>
                <option value="hour">Last recorded hour</option>
              </select>
            </label>
            <label>
              Operation zoom
              <select
                aria-label="Operation zoom"
                value={operation}
                onChange={(e) => setOperation(e.target.value)}
              >
                <option value="">All operations</option>
                {data.operations.map((o) => (
                  <option value={o} key={o}>
                    Operation {o.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="oa-chart">
            <svg
              viewBox="0 0 850 340"
              role="group"
              aria-label="Interactive activity graph; actual event time and distinct work-item contributions"
            >
              <title>Ledgerline automation, Maya review and Sarah management activity</title>
              <desc>
                Lines share the same actual time axis. Points may overlap. Use Tab and Enter to
                select a point, or the accessible recorded-point list below.
              </desc>
              <text x="72" y="22" className="oa-axis">
                Unique work items per actor / selected metric
              </text>
              {[
                ...new Set([
                  0,
                  Math.ceil(highest / 4),
                  Math.ceil(highest / 2),
                  Math.ceil((highest * 3) / 4),
                  highest,
                ]),
              ].map((t) => (
                <g key={t}>
                  <line
                    x1="72"
                    x2="812"
                    y1={282 - (t / highest) * 230}
                    y2={282 - (t / highest) * 230}
                    className="oa-grid"
                  />
                  <text x="58" y={287 - (t / highest) * 230} textAnchor="end" className="oa-axis">
                    {t}
                  </text>
                </g>
              ))}
              <line x1="72" x2="812" y1="282" y2="282" className="oa-grid" />
              {Object.entries(data.series)
                .filter(([k]) => series.includes(k))
                .map(([key, s]) => (
                  <polyline
                    key={key}
                    points={points
                      .filter((p) => p.series === key)
                      .map((p) => `${x(p)},${y(p)}`)
                      .join(' ')}
                    fill="none"
                    stroke={`var(--oa-${key})`}
                    strokeWidth="2"
                  />
                ))}
              {points.map(marker)}
              <text x="72" y="309" className="oa-axis">
                {points.length ? time(min) : 'No recorded events'}
              </text>
              <text x="812" y="309" textAnchor="end" className="oa-axis">
                {points.length ? time(max) : ''}
              </text>
              <text x="442" y="333" textAnchor="middle" className="oa-axis">
                Actual event time ·{' '}
                {group === 'operation'
                  ? 'latest contributing timestamp per operation'
                  : group + ' grouping'}
              </text>
            </svg>
            {hover && (
              <p role="status" className="oa-tooltip">
                {data.series[hover.series].label} · {hover.value}{' '}
                {mode === 'cumulative'
                  ? 'cumulative unique work items'
                  : 'unique work items in this interval'}{' '}
                · {hover.event_count} contributing events · {timestamp(hover.at)}
              </p>
            )}
            {!loading && !points.length && <p>No recorded activity matches these filters.</p>}
          </div>
          <details className="oa-point-list">
            <summary>Accessible recorded activity points ({points.length})</summary>
            {points.map((p) => (
              <button key={p.id} onClick={() => choose(p)}>
                {data.series[p.series].label} · {time(p.at)} · {p.count} work items ·{' '}
                {p.outcomes.map((o) => OUTCOMES[o]).join(', ')}
              </button>
            ))}
          </details>
          {selected && (
            <section className="oa-drill" aria-label="Activity point details">
              <div className="mw-detail-top">
                <h4>
                  {data.series[selected.series].label} ·{' '}
                  {selected.outcomes.map((o) => OUTCOMES[o]).join(', ')}
                </h4>
                <button onClick={() => setSelected(null)}>Close activity details</button>
              </div>
              <p>
                {timestamp(selected.first_at)} → {timestamp(selected.at)}. {selected.count} distinct
                work items, {selected.event_count} actual events. Plotted value: {selected.value}.
              </p>
              <p>Source operation IDs: {selected.operation_ids.join(', ')}</p>
              <button onClick={() => onCases(selected.items.map((i) => i.id))}>
                Inspect all contributing work
              </button>
              <div className="oa-cases">
                {selected.items.map((i) => (
                  <button key={i.id} onClick={() => onOpen(i.id)}>
                    {i.customer_id} · {i.id} · Current status: {i.lifecycle_label}
                  </button>
                ))}
              </div>
              <details open>
                <summary>Actual contributing decisions and events</summary>
                {selected.events.map((e) => (
                  <article key={e.id}>
                    <strong>{clean(e.type)}</strong>
                    <p>
                      {e.actor} · {e.actor_kind} · {timestamp(e.at)}
                    </p>
                    <p>
                      {e.before ?? 'No prior status'} → {e.after ?? 'No case status transition'}
                    </p>
                    <p>{e.rationale}</p>
                    {Boolean(e.details.attestation) && (
                      <p>Review type: {String(e.details.attestation)}</p>
                    )}
                    <details>
                      <summary>Audit references, evidence hashes and decision details</summary>
                      <pre>
                        {JSON.stringify(
                          {
                            event_id: e.id,
                            item_version: e.details.reviewed_version,
                            operation: e.operation_id,
                            evidence_hashes: e.source_hashes,
                            details: e.details,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </article>
                ))}
              </details>
            </section>
          )}
          <p>
            Review quality metrics below cover the whole selected session; chart filters do not
            redefine completed work.
          </p>
          <section className="oa-quality" aria-label="Review quality metrics">
            {Object.entries(data.metrics).map(([key, m]) => (
              <button
                key={key}
                onClick={() => onCases(m.ids)}
                aria-label={`${m.label}: ${m.value === null ? 'Not Measured' : key === 'acceptance_rate' ? new Intl.NumberFormat('en-CA', { style: 'percent', maximumFractionDigits: 1 }).format(m.value) : key === 'turnaround' ? m.value.toFixed(2) : m.value}. Inspect supporting work`}
              >
                <span>{m.label}</span>
                <strong>
                  {m.value === null
                    ? 'Not Measured'
                    : key === 'acceptance_rate'
                      ? new Intl.NumberFormat('en-CA', {
                          style: 'percent',
                          maximumFractionDigits: 1,
                        }).format(m.value)
                      : key === 'turnaround'
                        ? m.value.toFixed(2)
                        : m.value}
                </strong>
                {m.basis && <small>{m.basis}</small>}
              </button>
            ))}
          </section>
          <details>
            <summary>Activity methodology and overlap</summary>
            <p>{data.methodology}</p>
            <p>
              {data.distinct_closed} distinct currently closed work items; {data.legacy_closed}{' '}
              legacy closures have no recorded human review. Human hands-on labor: Not Measured.
            </p>
            <p>
              Symbols distinguish preparation (circle), individual approval (diamond), bulk
              attestation (square), rejection/return (cross) and received escalation (triangle). An
              operation with mixed outcomes uses a diamond; inspect its contributing events.
            </p>
          </details>
        </>
      )}
    </section>
  );
}
