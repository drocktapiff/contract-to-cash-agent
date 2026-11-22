import { useState } from 'react';
import './management-performance.css';
export type RecordSet = {
  id: string;
  label: string;
  item_ids: string[];
  event_ids: string[];
  count: number;
  share: number;
  description: string;
  owner: string;
  category: string;
  rate?: number | null;
  breakdowns?: RecordSet[];
};
export type Performance = {
  kpis: RecordSet[];
  distribution: RecordSet[];
  contributions: RecordSet[];
  legacy_closed: RecordSet;
  total: number;
  reconciled: boolean;
  methodology: string;
};
type Selection = {
  id: string;
  label: string;
  item_ids: string[];
  event_ids: string[];
  document_ids?: string[];
};
const count = (n: number) => new Intl.NumberFormat('en-CA').format(n);
const percent = (n: number) =>
  new Intl.NumberFormat('en-CA', { style: 'percent', maximumFractionDigits: 1 }).format(n);
export default function ManagementPerformance({
  data,
  documents,
  onSelect,
}: {
  data: Performance;
  documents: Selection & { count: number };
  onSelect: (s: Selection) => void;
}) {
  const [hover, setHover] = useState<RecordSet | null>(null);
  return (
    <section className="mp-performance" aria-label="Management performance dashboard">
      <div className="mp-context">
        <button onClick={() => onSelect(documents)}>
          {count(documents.count)} source documents
        </button>
        <span aria-hidden="true">/</span>
        <span>{count(data.total)} distinct work items</span>
      </div>
      <div className="mp-kpis" aria-label="Headline performance metrics">
        {data.kpis.map((k) => (
          <button
            key={k.id}
            data-testid={'mp-kpi-' + k.id}
            onClick={() => onSelect(k)}
            title={k.description}
          >
            <span>{k.label}</span>
            <strong>
              {k.id === 'preparation_rate'
                ? k.rate === null
                  ? '—'
                  : percent(k.rate!)
                : count(k.count)}
            </strong>
            <small>
              {k.id === 'identified'
                ? 'Saved in this session'
                : k.id === 'reviewed_closed'
                  ? 'After human verification'
                  : k.id === 'open'
                    ? 'Current unresolved cases'
                    : `${count(k.count)} checks prepared`}
            </small>
            <span className="mp-kpi-arrow" aria-hidden="true">
              →
            </span>
          </button>
        ))}
      </div>
      {data.legacy_closed.count > 0 && (
        <button className="mp-legacy" onClick={() => onSelect(data.legacy_closed)}>
          {data.legacy_closed.count} legacy closures have no recorded human review. Inspect
          historical cases →
        </button>
      )}
      <section className="mp-card mp-distribution" aria-label="Current Work Distribution">
        <header>
          <h2>Current Work Distribution</h2>
          <span className="mp-reconciled" role="status">
            {data.reconciled
              ? `${count(data.total)} of ${count(data.total)} accounted for`
              : 'Reconciliation requires investigation'}
          </span>
        </header>
        <div className="mp-segments" role="group" aria-label="Current state partition">
          {data.distribution.map((n) => (
            <button
              key={n.id}
              className={'mp-segment mp-color-' + n.category}
              style={{ flexGrow: n.count }}
              aria-label={`${n.label}: ${n.count} work items, ${percent(n.share)}`}
              onMouseEnter={() => setHover(n)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(n)}
              onBlur={() => setHover(null)}
              onClick={() => {
                setHover(null);
                onSelect(n);
              }}
            >
              {n.share >= 0.07 && <span>{count(n.count)}</span>}
            </button>
          ))}
        </div>
        {data.total === 0 && <p>No work items in this session.</p>}
        <div className="mp-legend">
          {data.distribution.map((n) => (
            <button
              key={n.id}
              onClick={() => onSelect(n)}
              onMouseEnter={() => setHover(n)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(n)}
              onBlur={() => setHover(null)}
              aria-label={`Inspect ${n.label}: ${n.count} cases`}
            >
              <span className={'mp-dot mp-color-' + n.category} aria-hidden="true" />
              <span>{n.label}</span>
              <strong>{count(n.count)}</strong>
              <small>{percent(n.share)}</small>
            </button>
          ))}
        </div>
        {hover && (
          <div className="mp-tooltip" role="tooltip">
            <strong>
              {hover.label} · {hover.count} · {percent(hover.share)}
            </strong>
            <span>{hover.description}</span>
            <small>Decision responsibility: {hover.owner}</small>
          </div>
        )}
      </section>
      <section className="mp-card mp-functions" aria-label="Work Handled by Each Function">
        <header>
          <h2>Work Handled by Each Function</h2>
          <details className="mp-info">
            <summary aria-label="About contribution counts">i</summary>
            <p>
              Cases can be handled by more than one function. These contributions overlap; they are
              not additive outcomes. Bulk attestation is not individual inspection. Management
              handoffs and coordination are not financial approval.
            </p>
          </details>
        </header>
        {data.contributions.map((c) => (
          <div key={c.id} className={'mp-function mp-function-' + c.category}>
            <button
              className="mp-function-main"
              data-testid={'mp-' + c.id}
              onClick={() => onSelect(c)}
              title={c.description}
              aria-label={`${c.label}: ${c.count} work items`}
            >
              <span className="mp-function-label">
                <span className={'mp-function-icon mp-color-' + c.category} aria-hidden="true">
                  {c.category === 'automation' ? 'L' : c.category === 'maya' ? 'MT' : 'SC'}
                </span>
                <span>{c.label}</span>
              </span>
              <span className="mp-track" aria-hidden="true">
                <span
                  className={'mp-fill mp-color-' + c.category}
                  style={{ width: percent(c.share) }}
                />
              </span>
              <strong>
                {count(c.count)}
                <span aria-hidden="true"> →</span>
              </strong>
            </button>
            {Boolean(c.breakdowns?.length) && (
              <div className="mp-breakdowns">
                {c.breakdowns!.map((b) => (
                  <button
                    key={b.id}
                    onClick={() => onSelect(b)}
                    title={b.description || c.description}
                  >
                    {b.label}
                    <strong>{count(b.count)}</strong>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </section>
    </section>
  );
}
