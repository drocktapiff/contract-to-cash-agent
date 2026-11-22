import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import './work-lifecycle.css';

type Node = {
  id: string;
  label: string;
  category: string;
  column: number;
  subtitle: string;
  owner: string;
  count: number;
  item_ids: string[];
  document_ids: string[];
  event_ids: string[];
};
type Edge = {
  id: string;
  source: string;
  target: string;
  count: number;
  item_ids: string[];
  event_ids: string[];
};
type Case = {
  id: string;
  customer_id: string;
  customer_name: string;
  issue: string;
  status: string;
  case_owner: string;
  reviewer: string | null;
  decision_owner: string;
  oversight_status: string;
  document_ids: string[];
  automated_result: unknown;
  review: unknown;
  event_ids: string[];
  corrective_action_ids: string[];
};
type Doc = {
  id: string;
  filename: string;
  hash: string;
  customer_id: string;
  item_ids: string[];
  pdf_url: string;
};
type Event = {
  id: string;
  item_id: string;
  at: string;
  type: string;
  actor: string;
  actor_kind: string;
  before: string | null;
  after: string | null;
  rationale: string;
  details: Record<string, unknown>;
  simulated_activity: boolean;
};
type Action = {
  id: string;
  title: string;
  status: string;
  owner: string;
  outcome: string;
  provenance: string;
};
type Model = {
  session_id: string;
  read_only: boolean;
  provenance: string;
  nodes: Node[];
  edges: Edge[];
  current_state: Node[];
  metrics: Node[];
  items: Case[];
  documents: Doc[];
  events: Event[];
  corrective_actions: Action[];
  integrity: {
    total: number;
    accounted: number;
    reconciled: boolean;
    unclassified: number;
    diagnostics: unknown[];
  };
  methodology: string;
};
type Selection = {
  id: string;
  label: string;
  item_ids: string[];
  event_ids: string[];
  document_ids?: string[];
};
const STAGES = [
  'Intake',
  'Processing',
  'Human review',
  'Review decisions',
  'Outcome & handoff',
  'Management oversight',
];
const stamp = (s: string) =>
  s && !Number.isNaN(Date.parse(s)) ? new Date(s).toLocaleString() : 'Timestamp not recorded';
export default function WorkLifecycle({
  sid,
  revision,
  onOpen,
}: {
  sid: string;
  revision: unknown;
  onOpen: (id: string) => void;
}) {
  const [data, setData] = useState<Model | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(true),
    [mode, setMode] = useState('flow'),
    [selected, setSelected] = useState<Selection | null>(null),
    [query, setQuery] = useState(''),
    [status, setStatus] = useState('all'),
    [page, setPage] = useState(0),
    [paths, setPaths] = useState<{ edge: Edge; d: string; x: number; y: number }[]>([]);
  const canvas = useRef<HTMLDivElement>(null),
    dialog = useRef<HTMLDialogElement>(null),
    trigger = useRef<HTMLElement | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setSelected(null);
    setData(null);
    void api<Model>(`/document-workspace/sessions/${sid}/lifecycle`)
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
  }, [sid, revision]);
  useEffect(() => {
    if (selected) {
      dialog.current?.showModal();
    } else if (dialog.current?.open) {
      dialog.current.close();
      trigger.current?.focus();
    }
  }, [selected]);
  useEffect(() => {
    const root = canvas.current;
    if (!root || !data || mode !== 'flow') {
      setPaths([]);
      return;
    }
    const measure = () => {
      const bounds = root.getBoundingClientRect();
      setPaths(
        data.edges.flatMap((edge) => {
          const a = root.querySelector<HTMLElement>(`[data-node="${edge.source}"]`),
            b = root.querySelector<HTMLElement>(`[data-node="${edge.target}"]`);
          if (!a || !b) return [];
          const ar = a.getBoundingClientRect(),
            br = b.getBoundingClientRect();
          const same = ar.left === br.left;
          const side = same && edge.source !== 'documents';
          const ax = (same && !side ? ar.left + ar.width * 0.75 : ar.right) - bounds.left,
            ay = (same && !side ? ar.bottom : ar.top + ar.height / 2) - bounds.top,
            bx = (side ? br.right : same ? br.left + br.width * 0.75 : br.left) - bounds.left,
            by = (same && !side ? br.top : br.top + br.height / 2) - bounds.top;
          const mid = (ax + bx) / 2;
          const skip =
            Math.abs(
              data.nodes.find((n) => n.id === edge.target)!.column -
                data.nodes.find((n) => n.id === edge.source)!.column,
            ) > 1;
          const bottom =
            Math.max(
              ...Array.from(root.querySelectorAll<HTMLElement>('[data-node]')).map(
                (el) => el.getBoundingClientRect().bottom - bounds.top,
              ),
            ) + 24;
          const longPath = `M${ax},${ay} L${ax + 12},${ay} L${ax + 12},${bottom} L${bx - 12},${bottom} L${bx - 12},${by} L${bx},${by}`;
          return [
            {
              edge,
              d: skip
                ? longPath
                : side
                  ? `M${ax},${ay} C${ax + 24},${ay} ${bx + 24},${by} ${bx},${by}`
                  : same
                    ? `M${ax},${ay} C${ax + 24},${ay + 15} ${bx + 24},${by - 15} ${bx},${by}`
                    : `M${ax},${ay} C${mid},${ay} ${mid},${by} ${bx},${by}`,
              x: mid,
              y: skip ? bottom : (ay + by) / 2,
            },
          ];
        }),
      );
    };
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    root.querySelectorAll('button').forEach((el) => observer.observe(el));
    measure();
    return () => observer.disconnect();
  }, [data, mode]);
  function choose(s: Selection) {
    trigger.current = document.activeElement as HTMLElement;
    setQuery('');
    setStatus('all');
    setPage(0);
    setSelected(s);
  }
  const selectedDocs = selected?.id === 'documents';
  const cases = data?.items.filter((i) => selected?.item_ids.includes(i.id)) ?? [];
  const filtered = cases.filter(
    (i) =>
      (status === 'all' || i.status === status) &&
      `${i.id} ${i.customer_id} ${i.customer_name} ${i.issue} ${i.case_owner} ${i.decision_owner}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const docs =
    data?.documents.filter(
      (d) =>
        selected?.document_ids?.includes(d.id) &&
        `${d.filename} ${d.id} ${d.customer_id}`.toLowerCase().includes(query.toLowerCase()),
    ) ?? [];
  const pages = Math.ceil((selectedDocs ? docs.length : filtered.length) / 15);
  function node(n: Node) {
    return (
      <button
        key={n.id}
        data-node={n.id}
        className={'wl-node wl-' + n.category}
        onClick={() => choose(n)}
        aria-label={`${n.label}: ${n.count}. Inspect ${n.id === 'documents' ? 'documents' : 'work items'}`}
      >
        <span className="wl-node-label">{n.label}</span>
        <strong>{n.count}</strong>
        <span>{n.owner}</span>
        <small>{n.subtitle}</small>
      </button>
    );
  }
  function docLink(d: Doc) {
    return (
      <a key={d.id} href={d.pdf_url} target="_blank" rel="noreferrer">
        Open original PDF · {d.filename}
      </a>
    );
  }
  return (
    <section className="wl-panel" aria-label="Work Lifecycle & Accountability">
      <header>
        <div>
          <span className="mw-eyebrow">FROM SOURCE EVIDENCE TO HUMAN ACCOUNTABILITY</span>
          <h2>Work Lifecycle &amp; Accountability</h2>
          <p>What entered, who handled it, and what still needs a decision.</p>
        </div>
        <div className="wl-toggle" role="group" aria-label="Lifecycle visualization mode">
          <button
            aria-pressed={mode === 'flow'}
            onClick={() => {
              setMode('flow');
              setSelected(null);
            }}
          >
            Lifecycle Flow
          </button>
          <button
            aria-pressed={mode === 'state'}
            onClick={() => {
              setMode('state');
              setSelected(null);
            }}
          >
            Current State
          </button>
        </div>
      </header>
      {loading && <p role="status">Reading saved workflow…</p>}
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <div className="wl-metrics" aria-label="Lifecycle supporting metrics">
            {data.metrics.map((n) => (
              <button key={n.id} onClick={() => choose(n)}>
                <strong>{n.count}</strong>
                <span>{n.label}</span>
              </button>
            ))}
          </div>
          {mode === 'flow' ? (
            <>
              <p className="wl-note">
                Lifecycle contributions overlap. A case can pass through several stages; stage
                counts are not additive. Select a stage or connection to inspect its evidence.
              </p>
              <div
                className="wl-flow"
                ref={canvas}
                style={{
                  gridTemplateColumns: `repeat(${Math.max(...data.nodes.map((n) => n.column)) + 1}, minmax(0,1fr))`,
                }}
              >
                <svg className="wl-links" aria-hidden="true">
                  <defs>
                    <marker
                      id="wl-arrow"
                      viewBox="0 0 10 10"
                      refX="9"
                      refY="5"
                      markerWidth="5"
                      markerHeight="5"
                      orient="auto-start-reverse"
                    >
                      <path d="M0,0 L10,5 L0,10 z" />
                    </marker>
                  </defs>
                  {paths.map((p) => (
                    <g key={p.edge.id}>
                      <path
                        d={p.d}
                        strokeWidth={Math.min(5, 1 + Math.sqrt(p.edge.count) / 3)}
                        markerEnd="url(#wl-arrow)"
                      />
                      <path
                        className="wl-link-hit"
                        d={p.d}
                        onClick={() =>
                          choose({
                            ...p.edge,
                            label: `${data.nodes.find((n) => n.id === p.edge.source)?.label} → ${data.nodes.find((n) => n.id === p.edge.target)?.label}`,
                          })
                        }
                      />
                      <text x={p.x} y={p.y - 5} textAnchor="middle">
                        {p.edge.count}
                      </text>
                    </g>
                  ))}
                </svg>
                {STAGES.map(
                  (label, column) =>
                    data.nodes.some((n) => n.column === column) && (
                      <div className="wl-column" key={label}>
                        <h3>
                          <span>{column + 1}</span>
                          {label}
                        </h3>
                        {data.nodes.filter((n) => n.column === column).map(node)}
                      </div>
                    ),
                )}
              </div>
              <details className="wl-connections">
                <summary>Inspect recorded transitions ({data.edges.length})</summary>
                <div>
                  {data.edges.map((e) => (
                    <button
                      key={e.id}
                      onClick={() =>
                        choose({
                          ...e,
                          label: `${data.nodes.find((n) => n.id === e.source)?.label} → ${data.nodes.find((n) => n.id === e.target)?.label}`,
                        })
                      }
                    >
                      {data.nodes.find((n) => n.id === e.source)?.label} →{' '}
                      {data.nodes.find((n) => n.id === e.target)?.label} · {e.count} distinct work
                      items
                    </button>
                  ))}
                </div>
              </details>
            </>
          ) : (
            <>
              <p className="wl-reconciliation" role="status">
                {data.integrity.reconciled
                  ? `${data.integrity.accounted} of ${data.integrity.total} work items accounted for`
                  : 'Reconciliation requires investigation'}
              </p>
              <p className="wl-note">
                Each work item appears exactly once. Financial decisions and missing evidence remain
                unresolved after management review.
              </p>
              <div className="wl-state">{data.current_state.map(node)}</div>
            </>
          )}
          {!data.items.length && <p>No work items are saved in this session.</p>}
          <footer>
            <span>
              {data.provenance} · Session {sid.slice(0, 8)}
              {data.read_only ? ' · Retained session' : ''}
            </span>
            <details>
              <summary>Counting, authority and integrity</summary>
              <p>{data.methodology}</p>
              <p>
                {data.integrity.unclassified} unclassified cases.{' '}
                {data.integrity.diagnostics.length} history or evidence diagnostics.
              </p>
              {data.integrity.diagnostics.length > 0 && (
                <pre>{JSON.stringify(data.integrity.diagnostics, null, 2)}</pre>
              )}
            </details>
          </footer>
        </>
      )}
      <dialog
        ref={dialog}
        className="wl-drawer"
        aria-label="Lifecycle evidence drill-down"
        onCancel={(event) => {
          // React owns visibility. Native close notifications are queued and may
          // arrive after another case set opens; they must not clear that selection.
          event.preventDefault();
          setSelected(null);
        }}
      >
        {selected && data && (
          <>
            <header>
              <div>
                <span className="mw-eyebrow">SAVED EVIDENCE · READ ONLY</span>
                <h2>{selected.label}</h2>
                <p>
                  {selectedDocs ? selected.document_ids?.length : selected.item_ids.length}{' '}
                  {selectedDocs ? 'source documents' : 'distinct work items'}
                </p>
              </div>
              <button onClick={() => setSelected(null)}>Close lifecycle details</button>
            </header>
            <div className="wl-search">
              <label>
                Search contributing {selectedDocs ? 'documents' : 'cases'}
                <input
                  type="search"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(0);
                  }}
                />
              </label>
              {!selectedDocs && (
                <label>
                  Current case status
                  <select
                    value={status}
                    onChange={(e) => {
                      setStatus(e.target.value);
                      setPage(0);
                    }}
                  >
                    <option value="all">All statuses</option>
                    {[...new Set(cases.map((i) => i.status))].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            <p>
              {selectedDocs ? docs.length : filtered.length} matches. Showing at most 15 per page.
            </p>
            {selectedDocs
              ? docs.slice(page * 15, page * 15 + 15).map((d) => (
                  <article key={d.id}>
                    <h3>{d.filename}</h3>
                    <p>
                      {d.id} · {d.customer_id ?? 'Unassigned customer'}
                    </p>
                    {docLink(d)}
                    <details>
                      <summary>Linked work items ({d.item_ids.length})</summary>
                      {d.item_ids.map((id) => (
                        <button
                          key={id}
                          onClick={() => {
                            setSelected(null);
                            onOpen(id);
                          }}
                        >
                          Open work item {id}
                        </button>
                      ))}
                      {!d.item_ids.length && <p>No persisted work-item relationship.</p>}
                    </details>
                    <small>Immutable source hash: {d.hash}</small>
                  </article>
                ))
              : filtered.slice(page * 15, page * 15 + 15).map((i) => (
                  <article key={i.id}>
                    <header>
                      <div>
                        <h3>
                          {i.customer_name || i.customer_id} · {i.issue}
                        </h3>
                        <p>
                          {i.id} · {i.status}
                        </p>
                      </div>
                      <button
                        onClick={() => {
                          setSelected(null);
                          onOpen(i.id);
                        }}
                      >
                        Open original work item
                      </button>
                    </header>
                    <dl>
                      <div>
                        <dt>Case owner</dt>
                        <dd>{i.case_owner || 'Not recorded'}</dd>
                      </div>
                      <div>
                        <dt>Reviewer</dt>
                        <dd>{i.reviewer || 'No recorded review'}</dd>
                      </div>
                      <div>
                        <dt>Current decision owner</dt>
                        <dd>{i.decision_owner || 'Not recorded'}</dd>
                      </div>
                      <div>
                        <dt>Management oversight</dt>
                        <dd>{i.oversight_status}</dd>
                      </div>
                    </dl>
                    <details>
                      <summary>Supporting source documents ({i.document_ids.length})</summary>
                      {data.documents.filter((d) => i.document_ids.includes(d.id)).map(docLink)}
                    </details>
                    <details>
                      <summary>Automated result &amp; Maya review provenance</summary>
                      <pre>
                        {JSON.stringify(
                          {
                            automated_check: i.automated_result ?? 'Not recorded',
                            human_review: i.review ?? 'Not recorded',
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                    <details>
                      <summary>Actual case activity &amp; Sarah escalation history</summary>
                      {data.events
                        .filter((e) => i.event_ids.includes(e.id))
                        .map((e) => (
                          <div className="wl-event" key={e.id}>
                            <strong>{e.type.replaceAll('_', ' ')}</strong>
                            <p>
                              {stamp(e.at)} · {e.actor} · {e.actor_kind}
                              {e.simulated_activity ? ' · Simulated fixture activity' : ''}
                            </p>
                            <p>
                              {e.before ?? 'No prior state'} → {e.after ?? 'No case status change'}
                            </p>
                            <p>{e.rationale}</p>
                            <small>
                              Event {e.id}
                              {selected.event_ids.includes(e.id)
                                ? ' · supports selected stage/transition'
                                : ''}
                            </small>
                          </div>
                        ))}
                    </details>
                    {i.corrective_action_ids.length > 0 && (
                      <details>
                        <summary>Linked internal corrective actions</summary>
                        {data.corrective_actions
                          .filter((a) => i.corrective_action_ids.includes(a.id))
                          .map((a) => (
                            <div key={a.id}>
                              <strong>
                                {a.title} · {a.status}
                              </strong>
                              <p>
                                {a.owner} · {a.outcome}
                              </p>
                              <p>{a.provenance}</p>
                            </div>
                          ))}
                      </details>
                    )}
                  </article>
                ))}
            {pages > 1 && (
              <nav aria-label="Lifecycle drill-down pagination">
                <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous cases
                </button>
                <span>
                  Page {page + 1} of {pages}
                </span>
                <button disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
                  Next cases
                </button>
              </nav>
            )}
            {!selectedDocs && (
              <details>
                <summary>Selected stage or transition audit references</summary>
                <pre>
                  {JSON.stringify(
                    { item_ids: selected.item_ids, event_ids: selected.event_ids },
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
            <p>
              Navigation is read-only. No billing, approval or financial authorization is performed.
            </p>
          </>
        )}
      </dialog>
    </section>
  );
}
