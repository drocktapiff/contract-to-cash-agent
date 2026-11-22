import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import './management-center.css';
import OperationalActivity from './OperationalActivity';
import WorkLifecycle from './WorkLifecycle';
type Case = {
  review?: { decision: string };
  work_item_id: string;
  customer_id: string;
  customer_name?: string;
  category: string;
  status: string;
  priority: string;
  version: number;
  source_documents: string[];
  supporting_facts: Record<string, { document_id: string }>;
  age: { seconds: number; since: string };
  business: {
    title: string;
    case_owner: string;
    current_decision_owner: string;
    waiting_on: string | null;
    impact_text: string;
  };
  oversight?: { reason: string; requested_at: string; requested_by: string; item_note?: string };
  management: { review_status: string; coordination_owner: string; required_next_action?: string };
  evidence_status: string;
  event_history: { type?: string; at: string; rationale?: string }[];
};
type ActionRecord = {
  id: string;
  version: number;
  title: string;
  description: string;
  originating_insight: string;
  provenance: string;
  related_ids: string[];
  document_ids: string[];
  owner: string;
  priority: string;
  due_date: string | null;
  status: string;
  acceptance_criteria: string;
  outcome: string;
  event_history: {
    type: string;
    actor: string;
    at: string;
    rationale: string;
    details: Record<string, unknown>;
  }[];
};
type Group = {
  id: string;
  title: string;
  source: string;
  case_ids: string[];
  observation: string;
  hypothesis: string;
  count: number;
};
type Overview = {
  session_id: string;
  read_only: boolean;
  cases: Case[];
  work_items: Case[];
  metrics: Record<string, number>;
  charts: {
    categories: Record<string, number>;
    decision_owners: Record<string, number>;
    workload: Record<string, number>;
    flow: Record<string, number>;
  };
  groups: Group[];
  exposure: Record<string, string | number>;
  aging_groups: Record<string, string[]>;
  operations: {
    id: string;
    status: string;
    duration_seconds: number | null;
    examined: number | null;
    completed: number;
    case_ids: string[];
  }[];
  telemetry: { human_interaction_count: number; processing_duration_seconds: number };
  corrective_actions: ActionRecord[];
  checked_at: string;
  changed_source_cases: number;
};
type Insight = {
  title: string;
  pattern: string;
  interpretation: string;
  case_ids: string[];
  document_ids: string[];
  evidence: {
    id: string;
    case_id: string;
    document_id: string;
    file_hash: string;
    page: number;
    text: string;
  }[];
  observed_evidence: {
    case_id: string;
    customer_id: string;
    category: string;
    financial: Record<string, string> | null;
  }[];
  root_cause_hypothesis: string;
  alternative_explanations: string[];
  missing_evidence: string[];
  recommended_action: string;
  priority: string;
  basis: string;
};
type Analysis = {
  provider: string;
  model: string;
  scope: string;
  category: string | null;
  id: string;
  session_id: string;
  status: string;
  reason: string;
  created_at: string;
  current: boolean;
  case_ids: string[];
  input_revision: string;
  result: { insights: Insight[]; limitations: string[] } | null;
  metrics: {
    duration_seconds: number;
    api_requests: number;
    input_tokens: number;
    output_tokens: number;
    estimated_api_cost_usd: string;
    cost_accounting_complete: boolean;
    usage_priced_cost_usd: string | null;
  } | null;
  provenance: { kind: string; label: string };
  failure_diagnostic?: { message: string };
  usage_unknown?: boolean;
};
type Preview = {
  revision: string;
  case_ids: string[];
  scope: string;
  category: string | null;
  estimated_evidence_pass_usd: string | null;
  maximum_cost_usd: string;
  model: string;
  maximum_seconds: number;
  max_responses: number;
  max_tool_calls: number;
  availability: {
    available: boolean;
    reasons: { code: string; message: string }[];
    next_eligible_at: string | null;
  };
  pricing: { ready: boolean };
};
const TEAMS = [
  'Revenue Operations',
  'Billing Operations',
  'Contract Administration',
  'Finance coordination',
];
const ACTIONS: Record<string, string> = {
  auto: 'Auto Complete Selected',
  prioritize: 'Prioritize',
  assign: 'Assign coordination',
  return: 'Return to Maya',
  evidence: 'Request additional evidence',
  finance: 'Coordinate financial review',
  complete: 'Complete management review',
};
const VIEWS = [
  'All Management Handoffs',
  'Needs My Attention',
  'Awaiting Finance',
  'Awaiting Evidence',
  'Returned to Maya',
  'Management Actions Completed',
];
const clean = (s: string) => s.replaceAll('_', ' ').replace(/^./, (x) => x.toUpperCase());
function Chart({
  title,
  values,
  onSelect,
}: {
  title: string;
  values: Record<string, number>;
  onSelect: (key: string) => void;
}) {
  const max = Math.max(1, ...Object.values(values));
  return (
    <section className="mc-chart">
      <h3>{title}</h3>
      <div>
        {Object.entries(values).map(([label, value]) => (
          <button
            key={label}
            onClick={() => onSelect(label)}
            aria-label={`${title}: ${clean(label)}, ${value}. View supporting work`}
          >
            <span>{clean(label)}</span>
            <strong>{value}</strong>
            <meter min={0} max={max} value={value}>
              {value}
            </meter>
          </button>
        ))}
      </div>
    </section>
  );
}
export default function ManagementInbox({
  sid,
  revision,
  onOpen,
  onChanged,
  readOnly = false,
  reviewer = 'Local operator',
}: {
  sid: string;
  revision: unknown;
  onOpen: (id: string) => void;
  onChanged?: () => void;
  readOnly?: boolean;
  reviewer?: string;
}) {
  const [data, setData] = useState<Overview | null>(null),
    [tab, setTab] = useState('Overview'),
    [view, setView] = useState(VIEWS[0]),
    [drill, setDrill] = useState<string[] | null>(null),
    [page, setPage] = useState(0),
    [selected, setSelected] = useState<Record<string, number>>({}),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true);
  const [actor, setActor] = useState(reviewer),
    [rationale, setRationale] = useState(''),
    [required, setRequired] = useState(''),
    [owner, setOwner] = useState(TEAMS[0]),
    [priority, setPriority] = useState('High'),
    [ack, setAck] = useState(false),
    [command, setCommand] = useState<string | null>(null),
    [captured, setCaptured] = useState<{ id: string; version: number }[]>([]),
    [result, setResult] = useState<{
      per_item: { id: string; outcome: string; reason?: string }[];
      blocked: number;
    } | null>(null);
  const [analyses, setAnalyses] = useState<Analysis[]>([]),
    [scope, setScope] = useState('all'),
    [category, setCategory] = useState(''),
    [preview, setPreview] = useState<Preview | null>(null),
    [previewBusy, setPreviewBusy] = useState(false),
    [paidAck, setPaidAck] = useState(false),
    [paidRationale, setPaidRationale] = useState(''),
    [paidOpen, setPaidOpen] = useState(false),
    [trace, setTrace] = useState<unknown[] | null>(null),
    [sla, setSla] = useState(48);
  const [actionForm, setActionForm] = useState<{
      origin: string;
      ids: string[];
      record?: ActionRecord;
    } | null>(null),
    [actionTitle, setActionTitle] = useState(''),
    [description, setDescription] = useState(''),
    [criteria, setCriteria] = useState(''),
    [due, setDue] = useState(''),
    [actionStatus, setActionStatus] = useState('Proposed'),
    [outcome, setOutcome] = useState(''),
    [actionDocs, setActionDocs] = useState<string[]>([]);
  const modal = useRef<HTMLDialogElement>(null),
    correctiveModal = useRef<HTMLDialogElement>(null),
    paidModal = useRef<HTMLDialogElement>(null),
    header = useRef<HTMLInputElement>(null),
    pending = useRef<{ key: string; body: object } | null>(null),
    paidPending = useRef<{ key: string; body: object } | null>(null);
  const [insightId, setInsightId] = useState<string | null>(null);
  const disabled = readOnly || !!data?.read_only || busy;
  async function load() {
    const [overview, records] = await Promise.all([
      api<Overview>(`/document-workspace/sessions/${sid}/management`),
      api<Analysis[]>(`/document-workspace/sessions/${sid}/management/analyses`),
    ]);
    setData(overview);
    setAnalyses(records);
    return overview;
  }
  useEffect(() => {
    let live = true;
    setLoading(true);
    setSelected({});
    setDrill(null);
    setError('');
    void load()
      .catch((e) => live && setError((e as Error).message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [sid, revision]);
  const running = analyses.some((a) =>
    ['queued', 'running', 'gathering_evidence', 'validating'].includes(a.status),
  );
  useEffect(() => {
    if (!running) return;
    let active = true;
    let timer: number;
    async function poll() {
      try {
        await load();
      } catch (e) {
        if (active) setError((e as Error).message);
      }
      if (active) timer = window.setTimeout(() => void poll(), 1500);
    }
    timer = window.setTimeout(() => void poll(), 1500);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [running, sid]);
  useEffect(() => {
    if (command) modal.current?.showModal();
    else modal.current?.close();
  }, [command]);
  useEffect(() => {
    if (actionForm) correctiveModal.current?.showModal();
    else correctiveModal.current?.close();
  }, [actionForm]);
  useEffect(() => {
    if (paidOpen) paidModal.current?.showModal();
    else paidModal.current?.close();
  }, [paidOpen]);
  const filtered = (drill ? (data?.work_items ?? []) : (data?.cases ?? [])).filter(
    (w) =>
      (!drill || drill.includes(w.work_item_id)) &&
      (view === VIEWS[0] ||
        (view === 'Needs My Attention' &&
          w.status === 'Escalated' &&
          !['Completed', 'Returned to Maya'].includes(w.management.review_status)) ||
        (view === 'Awaiting Finance' && w.status === 'Awaiting Financial Review') ||
        (view === 'Awaiting Evidence' &&
          (w.status === 'Awaiting Evidence' ||
            w.management.review_status === 'Awaiting Evidence')) ||
        (view === 'Returned to Maya' && w.management.review_status === 'Returned to Maya') ||
        (view === 'Management Actions Completed' && w.management.review_status === 'Completed')),
  );
  const visible = filtered.slice(page * 15, (page + 1) * 15),
    count = Object.keys(selected).length,
    allVisible = visible.length > 0 && visible.every((w) => w.work_item_id in selected);
  useEffect(() => {
    if (header.current)
      header.current.indeterminate = !allVisible && visible.some((w) => w.work_item_id in selected);
  });
  function selectMany(rows: Case[]) {
    setSelected((prev) => ({
      ...prev,
      ...Object.fromEntries(
        rows
          .filter((w) => w.oversight || w.status === 'Escalated')
          .map((w) => [w.work_item_id, w.version]),
      ),
    }));
  }
  function openCommand(action: string, rows?: Case[]) {
    setCaptured(
      rows
        ? rows.map((w) => ({ id: w.work_item_id, version: w.version }))
        : Object.entries(selected).map(([id, version]) => ({ id, version })),
    );
    setRationale('');
    setRequired('');
    setAck(false);
    setCommand(action);
    setInsightId(null);
    setError('');
  }
  function selectChart(ids: string[]) {
    setDrill(ids);
    setView(VIEWS[0]);
    setTab('Escalations');
    setPage(0);
  }
  async function submitCommand() {
    if (!command) return;
    setBusy(true);
    setError('');
    const fields = {
      expected_session: sid,
      actor,
      rationale,
      confirmation: 'ADMINISTRATIVE WORKFLOW ONLY',
      selected: captured,
      action: command,
      insight_id: insightId,
      priority,
      owner,
      required_next_action: required,
    };
    const key = JSON.stringify(fields);
    if (pending.current?.key !== key)
      pending.current = {
        key,
        body: { ...fields, operation_id: crypto.randomUUID().replaceAll('-', '') },
      };
    try {
      const r = await api<{
        per_item: { id: string; outcome: string; reason?: string }[];
        blocked: number;
      }>(`/document-workspace/sessions/${sid}/management/commands`, {
        method: 'POST',
        body: JSON.stringify(pending.current.body),
      });
      setResult(r);
      setNotice(
        r.blocked
          ? 'Some cases were blocked. Inspect individual results.'
          : 'Management coordination recorded; underlying approvals remain outstanding.',
      );
      setCommand(null);
      setSelected({});
      await load();
      onChanged?.();
      pending.current = null;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function openCorrective(origin: string, ids: string[], title: string, record?: ActionRecord) {
    setActionForm({ origin, ids, record });
    setActionTitle(record?.title ?? title);
    setDescription(
      record?.description ??
        'Investigate the source-backed operational pattern and verify the required process change.',
    );
    setCriteria(
      record?.acceptance_criteria ??
        'Document the verified cause, alternatives and evidence-backed next steps; obtain separate financial or contractual authorization where needed.',
    );
    setOwner(record?.owner ?? TEAMS[0]);
    setPriority(record?.priority ?? 'High');
    setDue(record?.due_date ?? '');
    setActionStatus(record?.status ?? 'Proposed');
    setOutcome(record?.outcome ?? '');
    setActionDocs(
      record?.document_ids ??
        Array.from(
          new Set(
            (data?.cases ?? [])
              .filter((w) => ids.includes(w.work_item_id))
              .flatMap((w) => w.source_documents),
          ),
        ),
    );
    setAck(false);
    setRationale('');
    setError('');
  }
  async function saveCorrective() {
    if (!actionForm) return;
    setBusy(true);
    setError('');
    const fields = {
      expected_session: sid,
      actor,
      rationale,
      confirmation: 'ADMINISTRATIVE WORKFLOW ONLY',
      action_id: actionForm.record?.id ?? null,
      action_version: actionForm.record?.version ?? null,
      title: actionTitle,
      description,
      origin_insight: actionForm.origin,
      related_ids: actionForm.ids,
      document_ids: actionDocs,
      owner,
      priority,
      due_date: due || null,
      status: actionStatus,
      acceptance_criteria: criteria,
      outcome,
    };
    const key = JSON.stringify(fields);
    if (pending.current?.key !== key)
      pending.current = {
        key,
        body: { ...fields, operation_id: crypto.randomUUID().replaceAll('-', '') },
      };
    try {
      await api(`/document-workspace/sessions/${sid}/management/corrective`, {
        method: 'POST',
        body: JSON.stringify(pending.current.body),
      });
      setActionForm(null);
      setNotice(
        'Internal corrective action saved. Related financial and contract cases were not closed.',
      );
      setTab('Corrective Actions');
      await load();
      pending.current = null;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function proposeAnalysis() {
    setPreviewBusy(true);
    setError('');
    setPaidAck(false);
    setPaidRationale('');
    setPreview(null);
    try {
      const p = await api<Preview>(
        `/document-workspace/sessions/${sid}/management/analysis-preview`,
        {
          method: 'POST',
          body: JSON.stringify({
            scope,
            case_ids: scope === 'selected' ? Object.keys(selected) : [],
            category: scope === 'category' ? category : null,
          }),
        },
      );
      setPreview(p);
      setPaidOpen(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreviewBusy(false);
    }
  }
  async function launch() {
    if (!preview) return;
    setBusy(true);
    setError('');
    const fields = {
      expected_session: sid,
      actor,
      rationale: paidRationale,
      confirmation: 'ADMINISTRATIVE WORKFLOW ONLY',
      acknowledge_paid: true,
      expected_revision: preview.revision,
      scope: preview.scope,
      category: preview.category,
      case_ids: preview.case_ids,
    };
    const key = JSON.stringify(fields);
    if (paidPending.current?.key !== key)
      paidPending.current = {
        key,
        body: { ...fields, operation_id: crypto.randomUUID().replaceAll('-', '') },
      };
    try {
      await api(`/document-workspace/sessions/${sid}/management/analyses`, {
        method: 'POST',
        body: JSON.stringify(paidPending.current.body),
      });
      setPaidOpen(false);
      setNotice(
        'Explicitly authorized bounded analysis requested. No automatic retry will be made.',
      );
      await load();
      paidPending.current = null;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="mc-center" aria-label="Sarah’s management inbox">
      <div className="mc-heading">
        <div>
          <span className="mw-eyebrow">SARAH CHEN · DIRECTOR OF REVENUE OPERATIONS</span>
          <h1>Management Command Center</h1>
          <p>Team performance, evidence-backed priorities and accountable follow-through.</p>
        </div>
        <span className="mc-session">Shared session · {sid.slice(0, 8)}</span>
      </div>
      <nav className="mc-tabs" aria-label="Management navigation">
        {['Overview', 'Escalations', 'Management Intelligence', 'Corrective Actions'].map((t) => (
          <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>
      {error && (
        <p role="alert" className="mw-alert">
          {error}
        </p>
      )}
      <p role="status" className="mc-notice">
        {notice || (loading ? 'Gathering saved team evidence…' : '')}
      </p>
      {data && (
        <>
          <details className="mp-evidence-status">
            <summary>
              {data.changed_source_cases
                ? `${data.changed_source_cases} cases need source verification`
                : 'Source evidence verified'}{' '}
              · {new Date(data.checked_at).toLocaleTimeString()}
            </summary>
            <p>
              {data.metrics.handoffs} oversight cases. Source evidence checked{' '}
              {new Date(data.checked_at).toLocaleString()}.{' '}
              {data.changed_source_cases
                ? 'Some handoffs have changed or missing PDFs; saved facts are historical.'
                : 'Current source PDFs verified for all handoffs.'}
            </p>
          </details>
          {data.changed_source_cases > 0 && (
            <p className="mw-alert">
              {data.changed_source_cases} handoffs have changed or missing sources. Saved facts are
              historical; inspect source integrity before acting.
            </p>
          )}
          {(readOnly || data.read_only) && (
            <p className="mw-alert">
              Retained session · Management history and analyses are read-only.
            </p>
          )}
          {tab === 'Overview' && (
            <>
              <WorkLifecycle sid={sid} revision={revision} onOpen={onOpen} />
              <details className="mc-activity-time">
                <summary>Activity Over Time</summary>
                <OperationalActivity
                  sid={sid}
                  revision={revision}
                  onOpen={onOpen}
                  onCases={selectChart}
                />
              </details>
              <details className="mp-advanced mp-operational">
                <summary>Operational metrics &amp; exposure</summary>
                <section className="mc-metrics" aria-label="Management performance metrics">
                  {[
                    ['Total work items', 'total'],
                    ['Completed work items', 'completed'],
                    ['Legacy automated closures', 'legacy_closed'],
                    ['Outstanding work', 'outstanding'],
                    ['Management handoffs', 'handoffs'],
                    ['Sarah’s direct attention', 'sarah_direct'],
                    ['Awaiting Finance', 'awaiting_finance'],
                    ['Awaiting Evidence', 'awaiting_evidence'],
                    ['Management reviews completed', 'management_reviews_completed'],
                  ].map(([label, k]) => (
                    <article key={k}>
                      <span>{label}</span>
                      <strong data-testid={'management-' + k}>{data.metrics[k]}</strong>
                    </article>
                  ))}
                  <article>
                    <span>Automation preparation rate</span>
                    <strong>
                      {new Intl.NumberFormat('en-CA', {
                        style: 'percent',
                        maximumFractionDigits: 1,
                      }).format(data.metrics.automation_rate)}
                    </strong>
                    <small>Prepared checks / all work; review remains separate</small>
                  </article>
                </section>
                <div className="mc-charts">
                  <Chart
                    title="Workload distribution"
                    values={data.charts.workload}
                    onSelect={(key) => {
                      const ids = data.work_items
                        .filter((w) =>
                          key === 'Outstanding'
                            ? w.status !== 'Closed'
                            : key === 'Legacy automatic closure'
                              ? w.status === 'Closed' && !w.review
                              : w.status === 'Closed' && w.review?.decision === 'approve',
                        )
                        .map((w) => w.work_item_id);
                      selectChart(ids);
                    }}
                  />
                  <Chart
                    title="Escalations by category"
                    values={data.charts.categories}
                    onSelect={(key) =>
                      selectChart(
                        data.cases.filter((w) => w.category === key).map((w) => w.work_item_id),
                      )
                    }
                  />
                  <Chart
                    title="Current decision ownership"
                    values={data.charts.decision_owners}
                    onSelect={(key) =>
                      selectChart(
                        data.cases
                          .filter((w) =>
                            key === 'Finance'
                              ? w.status === 'Awaiting Financial Review'
                              : key === 'Evidence / contract authority'
                                ? w.status === 'Awaiting Evidence'
                                : key === 'Maya'
                                  ? w.management.review_status === 'Returned to Maya'
                                  : w.status === 'Escalated' &&
                                    w.management.review_status !== 'Returned to Maya',
                          )
                          .map((w) => w.work_item_id),
                      )
                    }
                  />
                  <Chart
                    title="Operational flow — outcome branches"
                    values={Object.fromEntries(
                      Object.entries(data.charts.flow).filter(([k]) => k !== 'Incoming'),
                    )}
                    onSelect={(key) =>
                      selectChart(
                        data.work_items
                          .filter((w) =>
                            key === 'Completed'
                              ? w.status === 'Closed'
                              : key === 'Outstanding with oversight'
                                ? w.status !== 'Closed' && !!w.oversight
                                : w.status !== 'Closed' && !w.oversight,
                          )
                          .map((w) => w.work_item_id),
                      )
                    }
                  />
                  <Chart
                    title="Actual state aging"
                    values={Object.fromEntries(
                      Object.entries(data.aging_groups).map(([k, v]) => [k, v.length]),
                    )}
                    onSelect={(key) => selectChart(data.aging_groups[key])}
                  />
                  <section className="mc-chart">
                    <h3>Processing performance</h3>
                    <p>Measured system duration, not employee labor.</p>
                    <strong>{data.telemetry.processing_duration_seconds.toFixed(3)} seconds</strong>
                    <p>
                      {data.operations.length} saved operations · {data.metrics.completed} completed
                      work items
                    </p>
                    <small>Human labor: Not Measured</small>
                    <details>
                      <summary>Measured operation records</summary>
                      {data.operations.map((o) => (
                        <button key={o.id} onClick={() => selectChart(o.case_ids)}>
                          {o.status} · {o.duration_seconds ?? 'Not measured'} seconds ·{' '}
                          {o.completed} checks
                        </button>
                      ))}
                    </details>
                    <label>
                      Prospective SLA target (hours; assumption)
                      <input
                        type="number"
                        min={1}
                        max={720}
                        value={sla}
                        onChange={(e) =>
                          setSla(Math.max(1, Math.min(720, Number(e.target.value) || 1)))
                        }
                      />
                    </label>
                    <p>
                      {data.cases.filter((w) => w.age.seconds > sla * 3600).length} cases exceed
                      this assumed target. No fabricated historical aging.
                    </p>
                  </section>
                </div>
                <section className="mc-exposure">
                  <h3>Potential financial exposure — separate categories</h3>
                  <dl>
                    {[
                      ['Potential underbilling', 'potential_underbilling'],
                      ['Potential overbilling', 'potential_overbilling'],
                      ['Proposed credits', 'proposed_credits'],
                      ['Payment review balances', 'payment_review_balances'],
                    ].map(([label, k]) => (
                      <div key={k}>
                        <dt>{label}</dt>
                        <dd>CAD {data.exposure[k]}</dd>
                      </div>
                    ))}
                    <div>
                      <dt>Unknown customer/contract scopes</dt>
                      <dd>{data.exposure.unknown_customer_contracts}</dd>
                    </div>
                  </dl>
                  <p>{data.exposure.limitations}</p>
                </section>
              </details>
              <section className="mc-rule">
                <span className="mw-eyebrow">FREE · NO PROVIDER REQUESTS</span>
                <h3>Rule-based operational overview</h3>
                <div className="mc-insights">
                  {data.groups.map((g) => (
                    <article key={g.id}>
                      <h4>{g.title}</h4>
                      <p>
                        {g.count} actual cases. {g.observation}
                      </p>
                      <p>{g.hypothesis}</p>
                      <button onClick={() => selectChart(g.case_ids)}>
                        Inspect supporting cases
                      </button>
                      <button
                        disabled={disabled}
                        onClick={() =>
                          openCorrective(g.id, g.case_ids, 'Investigate ' + g.title.toLowerCase())
                        }
                      >
                        Create corrective action
                      </button>
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
          {tab === 'Escalations' && (
            <section aria-label="Management escalation queue">
              <div className="mc-queue-tools">
                <select
                  aria-label="Management queue view"
                  value={view}
                  onChange={(e) => {
                    setView(e.target.value);
                    setPage(0);
                    setDrill(null);
                  }}
                >
                  {VIEWS.map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
                <button
                  onClick={() => {
                    setDrill(null);
                    setView(VIEWS[0]);
                  }}
                >
                  Clear chart filter
                </button>
                <button disabled={disabled} onClick={() => selectMany(filtered)}>
                  Select All Matching
                </button>
                <span>{filtered.length} matching cases</span>
              </div>
              {count > 0 && (
                <div
                  className="mc-selection"
                  role="region"
                  aria-label="Selected management actions"
                >
                  <strong role="status">{count} Management Cases Selected</strong>
                  <div>
                    {Object.entries(ACTIONS).map(([key, label]) => (
                      <button
                        key={key}
                        className={key === 'auto' ? 'mw-primary' : ''}
                        disabled={disabled}
                        onClick={() => openCommand(key)}
                      >
                        {label}
                      </button>
                    ))}
                    <button onClick={() => setSelected({})}>Clear Selection</button>
                  </div>
                </div>
              )}
              {result && (
                <details open>
                  <summary>Recorded management outcomes</summary>
                  <p>
                    {result.blocked
                      ? 'Some cases were blocked; inspect their reasons.'
                      : 'Permitted coordination recorded; underlying cases remain independently governed.'}
                  </p>
                  {result.per_item.map((r) => (
                    <p key={r.id}>
                      {r.id} · {clean(r.outcome)} {r.reason}
                    </p>
                  ))}
                </details>
              )}
              <div className="mw-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>
                        <input
                          ref={header}
                          type="checkbox"
                          aria-label="Select All Management Cases"
                          checked={allVisible}
                          disabled={
                            disabled ||
                            !visible.some((w) => w.oversight || w.status === 'Escalated')
                          }
                          onChange={(e) => {
                            if (e.target.checked) selectMany(visible);
                            else
                              setSelected((prev) =>
                                Object.fromEntries(
                                  Object.entries(prev).filter(
                                    ([id]) => !visible.some((w) => w.work_item_id === id),
                                  ),
                                ),
                              );
                          }}
                        />
                      </th>
                      {[
                        'Customer / issue',
                        'Priority / potential impact',
                        'Owners / waiting',
                        'Reason / age',
                        'Status / next step',
                        'Actions',
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
                            aria-label={'Select management ' + w.work_item_id}
                            checked={w.work_item_id in selected}
                            disabled={disabled || !(w.oversight || w.status === 'Escalated')}
                            onChange={(e) => {
                              if (e.target.checked) selectMany([w]);
                              else
                                setSelected((p) =>
                                  Object.fromEntries(
                                    Object.entries(p).filter(([id]) => id !== w.work_item_id),
                                  ),
                                );
                            }}
                          />
                        </td>
                        <td>
                          <strong>{w.customer_name ?? w.customer_id}</strong>
                          <p>{w.business.title}</p>
                          <small>{w.work_item_id}</small>
                        </td>
                        <td>
                          {w.priority}
                          <p>{w.business.impact_text}</p>
                        </td>
                        <td>
                          Case: {w.business.case_owner}
                          <p>Decision: {w.business.current_decision_owner}</p>
                          <small>
                            Waiting on: {w.business.waiting_on ?? 'Management coordination'}
                          </small>
                          <p>Coordinator: {w.management.coordination_owner}</p>
                        </td>
                        <td>
                          {w.oversight?.reason ?? 'Retained escalation'}
                          <small className="mc-age">{w.evidence_status}</small>
                          <small className="mc-age">
                            {Math.floor(w.age.seconds / 60)} minutes in current state
                          </small>
                        </td>
                        <td>
                          {w.status}
                          <p>Management: {w.management.review_status}</p>
                          <small>
                            {w.management.required_next_action ??
                              'Review evidence and coordinate the next authorized decision.'}
                          </small>
                        </td>
                        <td>
                          <button onClick={() => onOpen(w.work_item_id)}>
                            View case &amp; full history
                          </button>
                          <button
                            disabled={disabled || !(w.oversight || w.status === 'Escalated')}
                            onClick={() => openCommand('auto', [w])}
                          >
                            Manage case
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mw-table-footer">
                <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                  Previous management page
                </button>
                <span>
                  {Math.min(page * 15 + 15, filtered.length)} of {filtered.length}
                </span>
                <button
                  disabled={(page + 1) * 15 >= filtered.length}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next management page
                </button>
              </div>
              {!filtered.length && <p>No cases match this management view.</p>}
            </section>
          )}
          {tab === 'Management Intelligence' && (
            <section className="mc-intelligence">
              <span className="mw-eyebrow">ADVISORY ONLY · EXPLICIT PAID AUTHORIZATION</span>
              <h3>Management Intelligence</h3>
              <p>
                Reason across the actual workload to identify hypotheses, bottlenecks and management
                priorities. Python supplies facts and financial calculations.
              </p>
              <div className="mc-analysis-controls">
                <label>
                  Analysis scope
                  <select value={scope} onChange={(e) => setScope(e.target.value)}>
                    <option value="all">All current management handoffs</option>
                    <option value="selected">Selected cases ({count})</option>
                    <option value="category">Specific exception category</option>
                  </select>
                </label>
                {scope === 'category' && (
                  <select
                    aria-label="Analysis exception category"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    <option value="">Choose category</option>
                    {Object.keys(data.charts.categories).map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                )}
                <button
                  className="mw-primary"
                  disabled={disabled || running || previewBusy}
                  onClick={() => void proposeAnalysis()}
                >
                  {previewBusy ? 'Gathering supporting evidence…' : 'Analyze Team Performance'}
                </button>
              </div>
              {!analyses.length && (
                <p>
                  No recorded live AI analysis exists for this session. Use the free rule-based
                  operational overview on Overview, or explicitly authorize analysis.
                </p>
              )}
              {analyses.map((a) => (
                <article className="mc-analysis" key={a.id}>
                  <div className="mw-detail-top">
                    <h4>
                      {a.status === 'completed' ? 'Recorded analysis · ' : ''}
                      {a.provenance.label}
                    </h4>
                    <span>{clean(a.status)}</span>
                  </div>
                  <small>
                    {a.provider} · {a.model} · {new Date(a.created_at).toLocaleString()} · {a.scope}{' '}
                    {a.category} · {a.case_ids.length} scoped cases
                  </small>
                  <p>
                    {a.current
                      ? 'Scope matches current saved evidence.'
                      : 'Historical / stale scope. Interpretations are not current authority.'}
                  </p>
                  {a.failure_diagnostic && <p role="alert">{a.failure_diagnostic.message}</p>}
                  {[
                    'queued',
                    'running',
                    'validating',
                    'interrupted',
                    'incomplete',
                    'failed',
                  ].includes(a.status) && (
                    <p role="status">
                      {
                        {
                          queued: 'Paid authorization retained; waiting for the worker.',
                          running: 'Analysis running — actual bounded provider workflow.',
                          validating: 'Validating results against the authorized evidence.',
                          interrupted: 'Interrupted; no automatic model retry.',
                          incomplete: 'Incomplete analysis; no validated insight published.',
                          failed: 'Analysis failed; no result inferred.',
                        }[a.status]
                      }
                    </p>
                  )}
                  <p>
                    Usage:{' '}
                    {a.metrics
                      ? a.metrics.cost_accounting_complete
                        ? `${a.metrics.api_requests} API requests · ${a.metrics.input_tokens} input / ${a.metrics.output_tokens} output tokens · ${a.metrics.duration_seconds} seconds`
                        : `${a.metrics.api_requests} attempted API requests · Token usage incomplete / unknown (${a.metrics.input_tokens} input / ${a.metrics.output_tokens} output reported before failure)`
                      : 'Unknown / not reported'}{' '}
                    · Cost:{' '}
                    {a.metrics?.cost_accounting_complete
                      ? `USD ${a.metrics.usage_priced_cost_usd ?? a.metrics.estimated_api_cost_usd} estimated from usage; billed cost unverified`
                      : 'Unknown or incomplete; not zero'}
                  </p>
                  <div className="mc-insights">
                    {a.status === 'completed' &&
                      a.result?.insights.map((i, index) => (
                        <article key={index}>
                          <span className="mw-eyebrow">
                            MODEL INTERPRETATION · NOT FINANCIAL AUTHORITY
                          </span>
                          <h4>{i.title}</h4>
                          <p>
                            <strong>Observed pattern:</strong> {clean(i.pattern)}
                          </p>
                          <p>{i.interpretation}</p>
                          <details>
                            <summary>
                              Verified source facts and calculations ({i.observed_evidence.length}{' '}
                              linked cases)
                            </summary>
                            {i.observed_evidence.map((f) => (
                              <p key={f.case_id}>
                                <button onClick={() => onOpen(f.case_id)}>
                                  {f.customer_id} · {f.case_id}
                                </button>
                                {f.financial
                                  ? Object.entries(f.financial).map(([k, v]) => (
                                      <span className="mc-fact" key={k}>
                                        {clean(k)}: {v}
                                      </span>
                                    ))
                                  : 'Financial exposure unknown'}
                              </p>
                            ))}
                          </details>
                          <p>
                            <strong>Root-cause hypothesis:</strong> {i.root_cause_hypothesis}
                          </p>
                          <p>
                            <strong>Alternatives:</strong> {i.alternative_explanations.join(' · ')}
                          </p>
                          <p>
                            <strong>Missing evidence:</strong> {i.missing_evidence.join(' · ')}
                          </p>
                          <p>
                            <strong>Recommended management action:</strong> {i.recommended_action}
                          </p>
                          <details>
                            <summary>Source references and limitations</summary>
                            {i.evidence.map((ref) => (
                              <p key={ref.id}>
                                <a
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  href={`/api/document-workspace/sessions/${sid}/evidence/${ref.file_hash}`}
                                >
                                  {ref.document_id} · page {ref.page} ↗
                                </a>{' '}
                                “{ref.text}”
                              </p>
                            ))}
                            <p>{a.result!.limitations.join(' · ')}</p>
                          </details>
                          <button
                            disabled={disabled || !a.current}
                            onClick={() =>
                              openCorrective(a.id + ':' + index, i.case_ids, i.recommended_action)
                            }
                          >
                            Accept &amp; Create corrective action
                          </button>
                          <button
                            disabled={disabled || !a.current}
                            onClick={() => {
                              setNotice(
                                'Dismissal requires a recorded management rationale. Select the supporting cases to record it.',
                              );
                              setSelected(
                                Object.fromEntries(
                                  data.cases
                                    .filter((w) => i.case_ids.includes(w.work_item_id))
                                    .map((w) => [w.work_item_id, w.version]),
                                ),
                              );
                              openCommand(
                                'dismiss_insight',
                                data.cases.filter((w) => i.case_ids.includes(w.work_item_id)),
                              );
                              setInsightId(a.id + ':' + index);
                            }}
                          >
                            Dismiss recommendation
                          </button>
                        </article>
                      ))}
                  </div>
                  <details>
                    <summary>Actual model and tool traces</summary>
                    <button
                      onClick={() =>
                        void api<unknown[]>(
                          `/document-workspace/sessions/${sid}/management/analyses/${a.id}/trace`,
                        )
                          .then(setTrace)
                          .catch((e) => setError((e as Error).message))
                      }
                    >
                      Retrieve retained trace
                    </button>
                    {trace && <pre>{JSON.stringify(trace, null, 2)}</pre>}
                  </details>
                </article>
              ))}
            </section>
          )}
          {tab === 'Corrective Actions' && (
            <section>
              <h3>Internal corrective actions</h3>
              <p>
                Tracked operational improvement, separate from financial or contractual
                authorization.
              </p>
              {!data.corrective_actions.length && (
                <p>
                  No corrective action recorded. Create one from an evidence-backed rule group or
                  validated current insight.
                </p>
              )}
              <div className="mc-insights">
                {data.corrective_actions.map((a) => (
                  <article key={a.id}>
                    <span className="mw-eyebrow">{a.status}</span>
                    <small>{a.provenance}</small>
                    <h4>{a.title}</h4>
                    <p>{a.description}</p>
                    <p>
                      Coordination owner: {a.owner} · {a.priority} · Due:{' '}
                      {a.due_date ?? 'Not selected'}
                    </p>
                    <p>Acceptance criteria: {a.acceptance_criteria}</p>
                    <p>Outcome: {a.outcome || 'Not yet recorded'}</p>
                    <details>
                      <summary>Action audit history</summary>
                      {a.event_history.map((e, index) => (
                        <div key={index}>
                          {clean(e.type)} · {e.actor} · {new Date(e.at).toLocaleString()} ·{' '}
                          {e.rationale}
                          <details>
                            <summary>Before / after action record</summary>
                            <pre>{JSON.stringify(e.details, null, 2)}</pre>
                          </details>
                        </div>
                      ))}
                    </details>
                    <button onClick={() => selectChart(a.related_ids)}>
                      Inspect related cases
                    </button>
                    <button
                      disabled={disabled}
                      onClick={() =>
                        openCorrective(a.originating_insight, a.related_ids, a.title, a)
                      }
                    >
                      Update action &amp; outcome
                    </button>
                  </article>
                ))}
              </div>
            </section>
          )}
          <p className="mc-boundary">
            No budget, credit, invoice, export or contract authorization is granted here. Persona
            selection is not authentication or RBAC. Human labor savings: Not Measured.
          </p>
        </>
      )}
      <dialog
        ref={modal}
        className="mw-confirm"
        aria-labelledby="mc-command-title"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setCommand(null);
        }}
      >
        {command && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submitCommand();
            }}
          >
            <h2 id="mc-command-title">{ACTIONS[command] ?? 'Record insight decision'}</h2>
            <p>
              {captured.length} selected cases. This is internal coordination only; the underlying
              financial or contractual case will remain open where required.
            </p>
            <label>
              Reviewer attribution
              <input required value={actor} onChange={(e) => setActor(e.target.value)} />
            </label>
            <label htmlFor="mc-rationale">Rationale</label>
            <textarea
              id="mc-rationale"
              required
              minLength={5}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
            <label htmlFor="mc-next">Required next action / management closure criteria</label>
            <textarea
              id="mc-next"
              required
              minLength={5}
              value={required}
              onChange={(e) => setRequired(e.target.value)}
            />
            <label>
              Coordination owner
              <select value={owner} onChange={(e) => setOwner(e.target.value)}>
                {TEAMS.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <label>
              Operational priority
              <select value={priority} onChange={(e) => setPriority(e.target.value)}>
                {['High', 'Normal', 'Low'].map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="mw-checkbox">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I
              confirm internal management coordination only; no financial or contractual approval.
            </label>
            {error && (
              <p role="alert" className="mw-alert">
                {error}
              </p>
            )}
            <button
              className="mw-primary"
              disabled={busy || !ack || rationale.trim().length < 5 || required.trim().length < 5}
            >
              Confirm management action
            </button>
            <button type="button" disabled={busy} onClick={() => setCommand(null)}>
              Cancel
            </button>
          </form>
        )}
      </dialog>
      <dialog
        ref={correctiveModal}
        className="mw-confirm"
        aria-labelledby="mc-corrective-title"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setActionForm(null);
        }}
      >
        {actionForm && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void saveCorrective();
            }}
          >
            <h2 id="mc-corrective-title">
              {actionForm.record ? 'Update corrective action' : 'Create corrective action'}
            </h2>
            <p>
              Internal operational task. Creating or completing it does not change or close the
              related source cases.
            </p>
            <label>
              Action title
              <input
                required
                value={actionTitle}
                onChange={(e) => setActionTitle(e.target.value)}
              />
            </label>
            <label htmlFor="mc-description">Description</label>
            <textarea
              id="mc-description"
              required
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <label htmlFor="mc-criteria">Acceptance criteria</label>
            <textarea
              id="mc-criteria"
              required
              value={criteria}
              onChange={(e) => setCriteria(e.target.value)}
            />
            <label>
              Coordination owner
              <select value={owner} onChange={(e) => setOwner(e.target.value)}>
                {TEAMS.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <label>
              Priority
              <select value={priority} onChange={(e) => setPriority(e.target.value)}>
                {['High', 'Normal', 'Low'].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </label>
            <label>
              Due date (explicit, optional)
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </label>
            <label>
              Corrective action status
              <select value={actionStatus} onChange={(e) => setActionStatus(e.target.value)}>
                {[
                  'Proposed',
                  'Approved for Internal Investigation',
                  'In Progress',
                  'Awaiting Evidence',
                  'Completed',
                  'Dismissed',
                ].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label htmlFor="mc-outcome">Outcome</label>
            <textarea
              id="mc-outcome"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            />
            <label>
              Reviewer attribution
              <input required value={actor} onChange={(e) => setActor(e.target.value)} />
            </label>
            <label htmlFor="mc-action-rationale">Rationale</label>
            <textarea
              id="mc-action-rationale"
              required
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
            <details>
              <summary>Bound supporting case and document references</summary>
              <p>{actionForm.ids.join(', ')}</p>
              {actionDocs.map((d) => (
                <p key={d}>{d}</p>
              ))}
            </details>
            <label className="mw-checkbox">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I
              confirm this internal action; it does not approve a financial or contractual change.
            </label>
            {error && (
              <p role="alert" className="mw-alert">
                {error}
              </p>
            )}
            <button
              className="mw-primary"
              disabled={
                busy ||
                !ack ||
                rationale.trim().length < 5 ||
                (actionStatus === 'Completed' && outcome.trim().length < 5)
              }
            >
              Save corrective action
            </button>
            <button type="button" disabled={busy} onClick={() => setActionForm(null)}>
              Cancel
            </button>
          </form>
        )}
      </dialog>
      <dialog
        ref={paidModal}
        className="mw-confirm"
        aria-labelledby="mc-paid-title"
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setPaidOpen(false);
        }}
      >
        {preview && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void launch();
            }}
          >
            <span className="mw-eyebrow">PAID OPENAI REQUEST · ADVISORY ONLY</span>
            <h2 id="mc-paid-title">Authorize Team Performance Analysis</h2>
            <p>
              Scope: {preview.case_ids.length} current cases · {preview.scope} {preview.category}
            </p>
            <p>
              Model: {preview.model}. Estimated evidence pass:{' '}
              {preview.estimated_evidence_pass_usd
                ? `USD ${preview.estimated_evidence_pass_usd}`
                : 'Unavailable until current pricing is confirmed'}
              . Maximum local estimated budget: USD {preview.maximum_cost_usd}.
            </p>
            <p>
              Estimate uses source bytes/framing and output reserve, not a billing guarantee.
              Limits: {preview.maximum_seconds} seconds, {preview.max_tool_calls} tool calls,{' '}
              {preview.max_responses} responses. Unknown usage is never reported as zero.
            </p>
            {!preview.availability.available && (
              <div className="mw-alert">
                {preview.availability.reasons.map((r) => (
                  <p key={r.code}>{r.message}</p>
                ))}
                <a href="/legacy#advanced">Review administrator pricing / API setup in Legacy</a>
              </div>
            )}
            <label>
              Reviewer attribution
              <input required value={actor} onChange={(e) => setActor(e.target.value)} />
            </label>
            <label htmlFor="mc-paid-rationale">Analysis rationale</label>
            <textarea
              id="mc-paid-rationale"
              required
              value={paidRationale}
              onChange={(e) => setPaidRationale(e.target.value)}
            />
            <label className="mw-checkbox">
              <input
                type="checkbox"
                checked={paidAck}
                onChange={(e) => setPaidAck(e.target.checked)}
              />
              I explicitly authorize this paid OpenAI analysis of the displayed scope.
            </label>
            {error && (
              <p role="alert" className="mw-alert">
                {error}
              </p>
            )}
            <button
              className="mw-primary"
              disabled={
                busy ||
                !preview.availability.available ||
                !paidAck ||
                paidRationale.trim().length < 5
              }
            >
              Begin authorized management analysis
            </button>
            <button type="button" disabled={busy} onClick={() => setPaidOpen(false)}>
              Cancel
            </button>
          </form>
        )}
      </dialog>
    </section>
  );
}
