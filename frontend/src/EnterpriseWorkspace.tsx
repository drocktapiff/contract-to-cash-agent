import { useEffect, useRef, useState } from 'react';
import { api } from './api';

type Ref = { kind: string; body: Record<string, unknown>; run_id?: string };
type Claim = { text: string; citations: string[] };
type Analysis = {
  id: string;
  kind: string;
  root_run_id: string;
  status: string;
  reason: string;
  created_at: string;
  input_revision: string;
  current?: boolean;
  result: null | {
    observations: Claim[];
    hypotheses: Claim[];
    recommendations: Claim[];
    limitations: string[];
    stance: string;
  };
  activity?: { sequence: number; type: string; tool?: string; timestamp: string }[];
  references?: Record<string, Ref>;
  metrics?: Record<string, unknown>;
};
type Case = {
  reference_id: string;
  run_id: string;
  finding_id: string;
  customer_ids: string[];
  state: string;
  evidence_verified: boolean;
  comparisons: Record<string, unknown>[];
  comparison?: Record<string, unknown>;
};
type Scenario = {
  version: number;
  assumptions: {
    traditional_employment_cad: string;
    redesigned_employment_cad: string;
    annual_software_cad: string;
    implementation_total_cad: string;
    teams: number;
    assumed_workload_reduction_percent: string | null;
    basis: string;
  };
  outputs: Record<string, string | null>;
};
type Decision = {
  id: string;
  root_run_id: string;
  kind: string;
  analysis_id: string;
  recommendation_index: number;
  action: string;
  rationale: string;
  owner?: string;
  created_at: string;
  persona: { name: string };
  reviewer: string;
  scope: string;
};
type Overview = {
  epoch: string;
  active: boolean;
  operational: {
    root_run_id: string | null;
    scope: string;
    metrics: {
      customers_screened: number;
      screened_candidates_without_findings?: number;
      findings_verified: number;
      outstanding_exceptions: number;
      resolved_cases: number;
      unresolved_cases: number;
      human_contributions: number;
      execution_seconds: string | null;
      estimated_api_cost_usd: string | null;
      cost_accounting_complete?: boolean;
    };
    financial: {
      potential_receivables_cad: string | null;
      potential_credits_cad: string | null;
      unresolved_quantifiable_exposure_cad: string | null;
      unquantified_cases: number;
    };
    cases: Case[];
    patterns: Record<string, unknown>[];
    runs: { id: string; status: string; reason: string }[];
    limitations: string[];
  };
  scenario: Scenario;
  analyses: Analysis[];
  decisions: Decision[];
  analysis_revisions: Record<string, string>;
};
const currency = (value: unknown, code = 'CAD') =>
  value == null
    ? 'Not established'
    : new Intl.NumberFormat('en-CA', { style: 'currency', currency: code }).format(Number(value));
const apiCost = (value: unknown) =>
  value == null
    ? 'Not established'
    : new Intl.NumberFormat('en-CA', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 4,
        maximumFractionDigits: 6,
      }).format(Number(value));
const title = (action: string) =>
  ({
    prioritize: 'Prioritize systemic issue',
    follow_up: 'Create internal follow-up',
    assign_owner: 'Record investigation owner',
    request_investigation: 'Request additional investigation',
    dismiss: 'Dismiss unsupported recommendation',
    approve_pilot: 'Approve proposed expansion pilot',
    request_validation: 'Request additional validation',
    defer: 'Defer expansion',
  })[action] ?? action;

export function ResetDemo({ onReset, recorded }: { onReset: () => void; recorded: boolean }) {
  const [scope, setScope] = useState<{
      epoch: string;
      investigations: number;
      analyses: number;
      enterprise_decisions: number;
      will_archive: string;
      will_preserve: string;
      active: boolean;
    } | null>(null),
    [error, setError] = useState(''),
    [confirmation, setConfirmation] = useState(''),
    [busy, setBusy] = useState(false);
  async function preview() {
    try {
      setError('');
      setScope(await api('/admin/reset'));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function archive() {
    if (!scope) return;
    setBusy(true);
    try {
      await api('/admin/reset', {
        method: 'POST',
        body: JSON.stringify({
          expected_epoch: scope.epoch,
          acknowledge_archive: true,
          confirmation,
        }),
      });
      onReset();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel admin-panel">
      <h2>Reset Demo</h2>
      <p>
        Start all three personas with an empty active workspace. Prior history is archived by
        default; no permanent deletion is available and no AI request is made.
      </p>
      <button className="secondary" disabled={recorded} onClick={() => void preview()}>
        Review reset scope
      </button>
      {scope && (
        <div className="reset-preview">
          <p>
            <strong>
              {scope.investigations} investigations · {scope.analyses} analyses ·{' '}
              {scope.enterprise_decisions} management/executive decisions
            </strong>
          </p>
          <p>{scope.will_archive}</p>
          <p>Preserved: {scope.will_preserve}</p>
          {scope.active && (
            <p className="notice">Work is active. Reset is unavailable until it settles.</p>
          )}
          <label>
            Type ARCHIVE DEMO HISTORY
            <input
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="off"
            />
          </label>
          <button
            className="danger"
            disabled={busy || scope.active || confirmation !== 'ARCHIVE DEMO HISTORY'}
            onClick={() => void archive()}
          >
            Archive history and reset all personas
          </button>
          <button
            className="plain"
            onClick={() => {
              setScope(null);
              setConfirmation('');
            }}
          >
            Cancel
          </button>
        </div>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default function EnterpriseWorkspace({
  persona,
  runId,
  pricingReady,
  recorded,
  onOperational,
}: {
  persona: 'sarah' | 'robert';
  runId: string;
  pricingReady: boolean;
  recorded: boolean;
  onOperational: (runId?: string) => void;
}) {
  const kind = persona === 'sarah' ? 'management' : 'executive';
  const [overview, setOverview] = useState<Overview | null>(null),
    [error, setError] = useState(''),
    [selectedId, setSelectedId] = useState(''),
    [detail, setDetail] = useState<Analysis | null>(null),
    [confirm, setConfirm] = useState(false),
    [paid, setPaid] = useState(false),
    [busy, setBusy] = useState(false),
    [reference, setReference] = useState<string | null>(null),
    [scenario, setScenario] = useState<Scenario['assumptions'] | null>(null),
    [evidence, setEvidence] = useState<Record<string, unknown>[]>([]);
  const [action, setAction] = useState(persona === 'sarah' ? 'prioritize' : 'request_validation'),
    [owner, setOwner] = useState(''),
    [rationale, setRationale] = useState(''),
    [support, setSupport] = useState(false),
    [recommendation, setRecommendation] = useState(0);
  const working = !!detail && ['queued', 'running'].includes(detail.status);
  const launchKey = useRef(crypto.randomUUID()),
    decisionKey = useRef({ fingerprint: '', key: '' });
  async function load() {
    try {
      const next = await api<Overview>(
        '/enterprise' + (runId ? '?root_run_id=' + encodeURIComponent(runId) : ''),
      );
      setOverview(next);
      setScenario((prev) => prev ?? next.scenario.assumptions);
      setSelectedId(
        (prev) =>
          prev ||
          next.analyses.find(
            (a) => a.kind === kind && a.root_run_id === next.operational.root_run_id,
          )?.id ||
          '',
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, [runId, kind]);
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    const poll = () =>
      void api<Analysis>('/enterprise/analyses/' + selectedId)
        .then((a) => {
          if (active) setDetail(a);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    poll();
    const timer = setInterval(poll, 1200);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedId]);
  useEffect(() => {
    if (!overview?.active && !working) return;
    const timer = setInterval(() => void load(), 2500);
    return () => clearInterval(timer);
  }, [overview?.active, working]);
  useEffect(() => {
    if (detail && !['queued', 'running'].includes(detail.status)) void load();
  }, [detail?.status]);
  async function launch() {
    if (!overview || !paid) return;
    setBusy(true);
    setError('');
    try {
      const a = await api<Analysis>('/enterprise/analyses', {
        method: 'POST',
        body: JSON.stringify({
          idempotency_key: launchKey.current,
          acknowledge_paid: true,
          kind,
          root_run_id: overview.operational.root_run_id,
          expected_revision: overview.analysis_revisions[kind],
        }),
      });
      setSelectedId(a.id);
      setDetail(a);
      setConfirm(false);
    } catch (e) {
      setError((e as Error).message);
      await load();
    } finally {
      setBusy(false);
    }
  }
  async function saveScenario() {
    if (!overview || !scenario) return;
    setBusy(true);
    setError('');
    try {
      const saved = await api<Scenario>('/enterprise/scenario', {
        method: 'PUT',
        body: JSON.stringify({
          expected_epoch: overview.epoch,
          expected_version: overview.scenario.version,
          scenario,
        }),
      });
      setOverview({ ...overview, scenario: saved });
      setScenario(saved.assumptions);
      await load();
      if (selectedId) setDetail(await api('/enterprise/analyses/' + selectedId));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function decide() {
    if (!detail?.result) return;
    const body = {
      expected_revision: detail.input_revision,
      recommendation_index: recommendation,
      action,
      rationale,
      owner: owner || null,
      supporting_references: detail.result.recommendations[recommendation].citations,
    };
    const fingerprint = JSON.stringify(body);
    if (decisionKey.current.fingerprint !== fingerprint)
      decisionKey.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    setError('');
    try {
      await api(`/enterprise/analyses/${detail.id}/decisions`, {
        method: 'POST',
        body: JSON.stringify({ ...body, idempotency_key: decisionKey.current.key }),
      });
      setRationale('');
      setSupport(false);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function inspect(c: Case) {
    try {
      setEvidence(
        await api(`/runs/${c.run_id}/findings/${encodeURIComponent(c.finding_id)}/evidence`),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (!overview)
    return (
      <section className="empty panel">
        <h1>Opening your {kind} workspace…</h1>
        {error && <p role="alert">{error}</p>}
      </section>
    );
  const op = overview.operational,
    metrics = op.metrics,
    financial = op.financial,
    result = detail?.result;
  const savedDecision = overview.decisions.find(
    (d) => d.analysis_id === detail?.id && d.recommendation_index === recommendation,
  );
  const canAnalyze =
    !working &&
    !!op.root_run_id &&
    !!op.cases.length &&
    !overview.active &&
    pricingReady &&
    !recorded;
  const available = overview.analyses.filter(
    (a) => a.kind === kind && a.root_run_id === op.root_run_id,
  );
  const ref = reference && detail?.references?.[reference];
  return (
    <section className={'enterprise-workspace ' + persona}>
      <div className="page-heading">
        <span className="eyebrow">
          {persona === 'sarah' ? 'SARAH · MANAGEMENT PRIORITIES' : 'ROBERT · FINANCIAL STRATEGY'}
        </span>
        <h1>
          {persona === 'sarah' ? 'See the pattern. Set the priority.' : 'Should this pilot grow?'}
        </h1>
        <p>
          {persona === 'sarah'
            ? 'AI helps you connect the operational findings. You decide what the department should investigate next.'
            : 'Use observed results and explicit assumptions to decide what deserves further investment.'}
        </p>
      </div>
      <div className="persona-boundary">
        Fictional demo persona · local operator authority is unchanged. These are single-operator
        prototype records, not measured departmental performance.
      </div>
      {error && (
        <p className="notice error" role="alert">
          {error}
          <button className="plain" onClick={() => void load()}>
            Refresh shared results
          </button>
        </p>
      )}
      <section className="enterprise-overview panel">
        <span className="eyebrow">FROM MAYA'S SAVED WORK</span>
        {persona === 'sarah' ? (
          <div className="enterprise-metrics">
            <div>
              <strong>{metrics.customers_screened}</strong>
              <span>Accounts compared / screened</span>
            </div>
            <div>
              <strong>{metrics.findings_verified}</strong>
              <span>Evidence-verified findings</span>
            </div>
            <div>
              <strong>{metrics.outstanding_exceptions}</strong>
              <span>Items needing attention</span>
            </div>
          </div>
        ) : (
          <div className="enterprise-metrics financial">
            <div>
              <strong>{currency(financial.potential_receivables_cad)}</strong>
              <span>Potential additional receivables</span>
            </div>
            <div>
              <strong>{currency(financial.potential_credits_cad)}</strong>
              <span>Potential customer credits</span>
            </div>
          </div>
        )}
        <p className="muted">
          {metrics.resolved_cases} reviewed or dismissed items · {metrics.unresolved_cases}{' '}
          unresolved items · {metrics.human_contributions} recorded human contributions
        </p>
        <p className="muted small">
          {financial.unquantified_cases} case(s) have no supported financial exposure.{' '}
          {persona === 'robert' && (
            <>
              Known outstanding differences:{' '}
              {currency(financial.unresolved_quantifiable_exposure_cad)}.{' '}
            </>
          )}
          Potential receivables are not collected revenue. Credits are not savings.
        </p>
        <p className="muted small">
          Recorded investigation duration: {metrics.execution_seconds ?? 'not established'} seconds.{' '}
          {persona === 'robert' && (
            <>
              Investigation API estimate: {apiCost(metrics.estimated_api_cost_usd)}; actual billed
              cost is unknown.
            </>
          )}
        </p>
        {!!metrics.screened_candidates_without_findings && (
          <p className="notice small">
            {metrics.screened_candidates_without_findings} additional structured screening
            candidates have no saved investigated finding. They are not verified exposure.
          </p>
        )}
        <div className="workflow-strip">
          {op.runs.map((r) => (
            <span key={r.id}>
              {r.status === 'completed' ? '✓' : '◷'} {r.status} review
            </span>
          ))}
          {!op.runs.length && (
            <p>No saved billing review yet. Start with Maya; results are never prefilled.</p>
          )}
        </div>
        <button className="plain" onClick={() => onOperational(op.root_run_id ?? undefined)}>
          Open the originating billing review →
        </button>
      </section>
      <section className="panel analysis-launch">
        <div>
          <span className="eyebrow">YOUR NEXT DECISION</span>
          <h2>
            {persona === 'sarah'
              ? 'Connect the cases into an operational priority.'
              : 'Evaluate the next step.'}
          </h2>
          <p>
            {persona === 'sarah'
              ? 'Ask AI to interpret this review’s evidence, recurring discrepancies and unresolved work.'
              : 'Ask AI to weigh observed results, Sarah’s saved decisions and your last saved financial assumptions.'}
          </p>
        </div>
        <button
          className="primary"
          disabled={!canAnalyze || busy}
          onClick={() => {
            launchKey.current = crypto.randomUUID();
            setConfirm(true);
            setPaid(false);
          }}
        >
          {persona === 'sarah'
            ? 'Analyze Department Performance'
            : 'Evaluate AI Expansion Opportunity'}
        </button>
        {!canAnalyze && (
          <p className="small muted">
            A saved current billing review, idle workspace, server API configuration and fresh
            administrator pricing are required. Recorded mode is read-only.
          </p>
        )}
      </section>
      {confirm && (
        <section
          className="paid-confirmation panel"
          role="dialog"
          aria-label="Authorize enterprise analysis"
        >
          <h2>Authorize one paid {kind} analysis</h2>
          <p>
            Uses only this review's saved evidence
            {persona === 'robert' ? ', management context and illustrative scenario' : ''}. Up to 3
            minutes, 35 tools, 40 model requests and US$1 estimated cost. No financial correction,
            external assignment or strategic decision is automatic.
          </p>
          <label className="checkbox">
            <input type="checkbox" checked={paid} onChange={(e) => setPaid(e.target.checked)} />I
            authorize this paid analysis.
          </label>
          <button className="primary" disabled={!paid || busy} onClick={() => void launch()}>
            Begin authorized analysis
          </button>
          <button className="plain" onClick={() => setConfirm(false)}>
            Cancel
          </button>
        </section>
      )}
      {persona === 'robert' && scenario && (
        <section className="panel scenario-panel">
          <span className="eyebrow">ILLUSTRATIVE FINANCIAL SCENARIO · CAD</span>
          <h2>Model the operating design.</h2>
          <p>
            Compare a Billing Analyst + Contract Administrator with an AI-augmented Revenue
            Operations Specialist. These editable assumptions are not measured staffing savings.
          </p>
          <div className="scenario-grid">
            <div>
              {(
                [
                  ['traditional_employment_cad', 'Traditional employment / team / year'],
                  ['redesigned_employment_cad', 'Redesigned employment / team / year'],
                  ['annual_software_cad', 'AI and software / team / year'],
                  ['implementation_total_cad', 'One-time implementation / all teams'],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    inputMode="decimal"
                    value={scenario[key]}
                    onChange={(e) => setScenario({ ...scenario, [key]: e.target.value })}
                  />
                </label>
              ))}
              <label>
                Comparable teams
                <input
                  type="number"
                  min={1}
                  max={10000}
                  value={scenario.teams}
                  onChange={(e) => setScenario({ ...scenario, teams: Number(e.target.value) })}
                />
              </label>
              <label>
                Assumed workload reduction % (optional)
                <input
                  inputMode="decimal"
                  value={scenario.assumed_workload_reduction_percent ?? ''}
                  onChange={(e) =>
                    setScenario({
                      ...scenario,
                      assumed_workload_reduction_percent: e.target.value || null,
                    })
                  }
                />
              </label>
              <p className="small muted">
                Workload reduction is an assumption only; it does not discount employment costs
                again.
              </p>
              <button
                className="secondary"
                disabled={busy || recorded || overview.active}
                onClick={() => void saveScenario()}
              >
                Calculate and save scenario
              </button>
            </div>
            <div className="scenario-results">
              <span className="eyebrow">LAST SAVED SCENARIO · NOT REALIZED BENEFITS</span>
              <h3>{currency(overview.scenario.outputs.recurring_annual_net_benefit_cad)}</h3>
              <p>Potential recurring annual net benefit</p>
              <dl>
                <dt>Previous recurring annual cost</dt>
                <dd>{currency(overview.scenario.outputs.previous_recurring_annual_cad)}</dd>
                <dt>Redesigned recurring annual cost</dt>
                <dd>{currency(overview.scenario.outputs.redesigned_recurring_annual_cad)}</dd>
                <dt>Recurring cost reduction</dt>
                <dd>
                  {overview.scenario.outputs.operating_cost_reduction_percent ?? 'Not defined'}%
                </dd>
                <dt>Implementation, once</dt>
                <dd>{currency(overview.scenario.outputs.implementation_total_cad)}</dd>
                <dt>First-year net benefit</dt>
                <dd>{currency(overview.scenario.outputs.first_year_net_benefit_cad)}</dd>
                <dt>Illustrative payback</dt>
                <dd>
                  {overview.scenario.outputs.payback_months == null
                    ? 'No positive recurring benefit'
                    : overview.scenario.outputs.payback_months + ' months'}
                </dd>
              </dl>
              <p className="small muted">
                Uniform monthly benefit assumed for payback. Python calculates every financial
                output. Unsaved edits do not alter the displayed results.
              </p>
            </div>
          </div>
        </section>
      )}
      {persona === 'robert' && (
        <section className="management-bridge panel">
          <span className="eyebrow">SARAH'S MANAGEMENT INPUT</span>
          <h2>Priorities before projections.</h2>
          {overview.decisions
            .filter(
              (d) =>
                d.kind === 'management' &&
                overview.analyses.find((a) => a.id === d.analysis_id)?.root_run_id ===
                  op.root_run_id,
            )
            .map((d) => (
              <div className="decision-record" key={d.id}>
                <strong>{title(d.action)}</strong>
                <p>{d.rationale}</p>
                {d.owner && <p>Internal owner recorded: {d.owner}</p>}
                <small>
                  {d.persona.name} · {new Date(d.created_at).toLocaleString()} · no assignment was
                  transmitted
                </small>
              </div>
            ))}
          {!overview.decisions.some(
            (d) => d.kind === 'management' && d.root_run_id === op.root_run_id,
          ) && (
            <p>
              No management decision has been recorded. The executive analysis must disclose this
              evidence gap.
            </p>
          )}
        </section>
      )}
      <section className="panel enterprise-analysis">
        <div className="section-heading">
          <h2>Analysis &amp; your judgment</h2>
          <select
            aria-label="Saved enterprise analysis"
            value={selectedId}
            onChange={(e) => {
              setSelectedId(e.target.value);
              setRecommendation(0);
              setReference(null);
              setRationale('');
              setSupport(false);
            }}
          >
            <option value="">Choose a saved analysis</option>
            {available.map((a) => (
              <option key={a.id} value={a.id}>
                {new Date(a.created_at).toLocaleString()} · {a.status}
              </option>
            ))}
          </select>
        </div>
        {!detail && (
          <p>
            No AI analysis has been generated here. Saved operational records above remain the
            source of truth.
          </p>
        )}
        {working && (
          <div className="analysis-working" role="status">
            <h3>AI is examining the saved inputs.</h3>
            <p>No progress percentage or discovery is inferred.</p>
            <ol>
              {detail?.activity
                ?.filter(
                  (e) =>
                    e.type === 'tool.requested' ||
                    e.type === 'analysis.saved' ||
                    e.type === 'api.failed',
                )
                .map((e) => (
                  <li key={e.sequence}>
                    {e.type === 'analysis.saved'
                      ? 'Analysis was saved'
                      : e.type === 'api.failed'
                        ? 'A model request failed'
                        : `Selected ${e.tool === 'get_analysis_overview' ? 'the observed performance overview' : e.tool === 'get_analysis_reference' ? 'a supporting input' : 'the recommendation report'}`}
                  </li>
                ))}
            </ol>
          </div>
        )}
        {detail && !working && detail.status !== 'completed' && (
          <p className="notice">
            This analysis is {detail.status}. Saved work may be incomplete. No decision is
            enabled.{' '}
          </p>
        )}
        {detail && detail.current === false && (
          <p className="notice error">
            Inputs changed. This is historical analysis; authorize a fresh analysis before deciding.
          </p>
        )}
        {result && (
          <>
            {persona === 'robert' && (
              <p className="notice">
                AI suggested stance: {result.stance.replaceAll('_', ' ')}. This is a recommendation,
                not approval.
              </p>
            )}
            <p className="small muted">
              AI interpretation of cited inputs. Suggested causes and actions are hypotheses, not
              verified financial facts.
            </p>
            {(['observations', 'hypotheses', 'recommendations'] as const).map((category) => (
              <section className="analysis-claims" key={category}>
                <h3>
                  {category === 'observations'
                    ? 'Observed evidence — AI interpretation'
                    : category === 'hypotheses'
                      ? 'Hypotheses to test'
                      : 'Suggested next actions'}
                </h3>
                {result[category].map((claim, i) => (
                  <article key={i}>
                    <p>{claim.text}</p>
                    <div className="citation-buttons">
                      {claim.citations.map((ref, j) => (
                        <button className="plain" key={ref} onClick={() => setReference(ref)}>
                          Supporting input {j + 1} ↗
                        </button>
                      ))}
                    </div>
                  </article>
                ))}
              </section>
            ))}
            <details>
              <summary>Limitations to consider</summary>
              <ul>
                {result.limitations.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </details>
            {reference && ref && (
              <section className="reference-panel">
                <h3>Supporting input · {ref.kind.replaceAll('_', ' ')}</h3>
                <p className="break small muted">{reference}</p>
                <ReferenceBody value={ref.body} />
                <button className="plain" onClick={() => setReference(null)}>
                  Close supporting input
                </button>
              </section>
            )}
            <section className="enterprise-human-decision">
              <h3>
                {persona === 'sarah'
                  ? 'Set a management priority'
                  : 'Record the strategic decision'}
              </h3>
              <p>
                Internal demonstration record only. No email, ticket, budget allocation, workforce
                change, billing correction or export approval is executed.
              </p>
              <label>
                Recommendation
                <select
                  aria-label="Recommendation to decide"
                  value={recommendation}
                  onChange={(e) => {
                    setRecommendation(Number(e.target.value));
                    setSupport(false);
                  }}
                >
                  {result.recommendations.map((r, i) => (
                    <option key={i} value={i}>
                      {r.text.slice(0, 110)}
                    </option>
                  ))}
                </select>
              </label>
              {savedDecision ? (
                <div className="decision-record">
                  <strong>{title(savedDecision.action)}</strong>
                  <p>{savedDecision.rationale}</p>
                  {savedDecision.owner && <p>Internal owner: {savedDecision.owner}</p>}
                  <small>
                    {savedDecision.persona.name} · local operator: {savedDecision.reviewer} ·{' '}
                    {new Date(savedDecision.created_at).toLocaleString()}
                  </small>
                </div>
              ) : (
                <>
                  <label>
                    Decision
                    <select
                      aria-label="Decision action"
                      value={action}
                      onChange={(e) => setAction(e.target.value)}
                    >
                      {(persona === 'sarah'
                        ? [
                            'prioritize',
                            'follow_up',
                            'assign_owner',
                            'request_investigation',
                            'dismiss',
                          ]
                        : ['approve_pilot', 'request_validation', 'defer']
                      ).map((a) => (
                        <option key={a} value={a}>
                          {title(a)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {persona === 'sarah' && (
                    <label>
                      Internal investigation owner
                      <input
                        value={owner}
                        maxLength={200}
                        onChange={(e) => setOwner(e.target.value)}
                        placeholder="Name or department — nothing will be sent"
                      />
                    </label>
                  )}
                  <label>
                    Decision rationale
                    <textarea
                      value={rationale}
                      maxLength={1000}
                      onChange={(e) => setRationale(e.target.value)}
                    />
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={support}
                      onChange={(e) => setSupport(e.target.checked)}
                    />
                    I considered this recommendation's cited supporting inputs.
                  </label>
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      !support ||
                      rationale.trim().length < 5 ||
                      detail?.status !== 'completed' ||
                      !detail.current ||
                      recorded ||
                      (['follow_up', 'assign_owner', 'request_investigation'].includes(action) &&
                        !owner.trim())
                    }
                    onClick={() => void decide()}
                  >
                    {persona === 'sarah' ? 'Save management decision' : 'Save strategic decision'}
                  </button>
                </>
              )}
            </section>
          </>
        )}
        {detail && (
          <details className="technical">
            <summary>View Technical Activity</summary>
            <p className="break">
              Analysis {detail.id} · snapshot {detail.input_revision} · {detail.status} ·{' '}
              {detail.reason}
            </p>
            <ol>
              {detail.activity?.map((e) => (
                <li key={e.sequence}>
                  {new Date(e.timestamp).toLocaleTimeString()} · {e.type} {e.tool ?? ''}
                </li>
              ))}
            </ol>
          </details>
        )}
      </section>
      <details className="panel department-evidence">
        <summary>Inspect affected accounts and source evidence</summary>
        {op.cases.map((c) => (
          <article key={c.reference_id}>
            <h3>
              {c.customer_ids.join(', ')} · {c.state.replaceAll('_', ' ')}
            </h3>
            <p>
              {c.evidence_verified
                ? 'Original evidence checked'
                : 'Interpretation or source verification remains unresolved'}
            </p>
            <button className="secondary" onClick={() => void inspect(c)}>
              Read original supporting documents
            </button>
            <button className="plain" onClick={() => onOperational(c.run_id)}>
              Open operational case →
            </button>
          </article>
        ))}
        {evidence.map((source, i) => (
          <details className="source" key={i}>
            <summary>{String(source.document_id)}</summary>
            {source.text ? (
              <p className="source-text">{String(source.text)}</p>
            ) : (
              <ReferenceBody value={(source.record ?? source) as Record<string, unknown>} />
            )}
          </details>
        ))}
      </details>
      <details className="panel">
        <summary>Measurement scope and limitations</summary>
        <p>{op.scope}</p>
        <p>
          Recorded investigation duration: {metrics.execution_seconds ?? 'not available'} seconds.
          Estimated investigation API cost: {apiCost(metrics.estimated_api_cost_usd)}.{' '}
          {metrics.cost_accounting_complete === false
            ? 'Cost accounting is incomplete; actual billed cost is unknown.'
            : 'Actual billed cost remains unknown.'}
        </p>
        <ul>
          {op.limitations.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
function ReferenceBody({ value }: { value: Record<string, unknown> }) {
  return (
    <div className="reference-content">
      {Object.entries(value).map(([key, v]) => (
        <div key={key}>
          <strong>{key.replaceAll('_', ' ')}</strong>
          {typeof v === 'object' && v !== null ? (
            <details>
              <summary>View saved supporting detail</summary>
              {Array.isArray(v) ? (
                v.map((row, i) => (
                  <div key={i}>
                    {typeof row === 'object' && row !== null ? (
                      <ReferenceBody value={row as Record<string, unknown>} />
                    ) : (
                      <p>{String(row)}</p>
                    )}
                  </div>
                ))
              ) : (
                <ReferenceBody value={v as Record<string, unknown>} />
              )}
            </details>
          ) : (
            <p className="break source-text">{v == null ? 'Not established' : String(v)}</p>
          )}
        </div>
      ))}
    </div>
  );
}
