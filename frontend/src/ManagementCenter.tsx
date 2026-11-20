import { useState } from 'react';
import { api } from './api';

type Row = {
  customer_id: string;
  expected_cad?: string;
  billed_cad?: string;
  difference_cad?: string;
};
type Issue = {
  unknown_exposure_accounts?: string[];
  id: string;
  title: string;
  priority: number;
  customer_ids: string[];
  references: string[];
  comparisons: Row[];
  potential_exposure_cad: string | null;
  evidence_status: string;
  next_action: string;
};
type Action = {
  provenance?: { kind: string; label?: string };
  id: string;
  issue_id: string;
  version: number;
  owner: string;
  status: string;
  priority: number;
  target_date: string;
  rationale: string;
  closure_criteria: string;
  history: {
    version: number;
    timestamp: string;
    reviewer: string;
    status: string;
    rationale: string;
  }[];
};
export type Center = {
  issues: Issue[];
  actions: Action[];
  revision: string;
  measurement_required: string[];
  caveat: string;
  observed: Record<string, number | string | null>;
};
const money = (v: string | null | undefined) =>
  v == null
    ? 'Unknown exposure'
    : new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' }).format(Number(v));
const statuses = [
  'Proposed',
  'Assigned',
  'Investigating',
  'Awaiting Evidence',
  'Ready for Review',
  'Closed — Verified',
  'Closed — No Change Required',
];
export default function ManagementCenter({
  center,
  root,
  cases,
  reload,
  readOnly = false,
}: {
  center: Center;
  root: string | null;
  cases: { reference_id: string; run_id: string; finding_id: string }[];
  reload: () => void;
  readOnly?: boolean;
}) {
  const [selected, setSelected] = useState<Issue | null>(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const [sources, setSources] = useState<Record<string, unknown>[] | null>(null);
  async function evidence(issue: Issue) {
    try {
      setError('');
      const matching = cases.filter((c) => issue.references.includes(c.reference_id));
      const data = await Promise.all(
        matching.map((c) =>
          api<Record<string, unknown>[]>(`/runs/${c.run_id}/findings/${c.finding_id}/evidence`),
        ),
      );
      setSources(data.flat());
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !root) return;
    const form = new FormData(event.currentTarget);
    const old = center.actions.find((a) => a.issue_id === selected.id);
    setBusy(true);
    try {
      await api('/enterprise/actions', {
        method: 'POST',
        body: JSON.stringify({
          root_run_id: root,
          issue_id: selected.id,
          expected_revision: center.revision,
          expected_version: old?.version ?? 0,
          owner: form.get('owner'),
          priority: Number(form.get('priority')),
          target_date: form.get('target_date'),
          rationale: form.get('rationale'),
          closure_criteria: form.get('closure_criteria'),
          status: form.get('status'),
          closure_references: form.get('closure_support') ? selected.references : [],
        }),
      });
      setSelected(null);
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const shared = center.issues.find((i) => i.id.startsWith('shared:'));
  const old = selected && center.actions.find((a) => a.issue_id === selected.id);
  return (
    <div className="management-command">
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {shared && (
        <section className="panel shared-insight">
          <span className="eyebrow">VERIFIED DISCREPANCY · SUSPECTED SHARED CAUSE</span>
          <h2>
            Shared Pricing Discrepancy —{' '}
            {shared.customer_ids.length === 3 ? 'Three' : shared.customer_ids.length} Accounts
            Affected
          </h2>
          <p>
            {shared.customer_ids.join(' · ')} ·{' '}
            {String(
              (shared.comparisons[0] as Row & { pricing_template?: string })?.pricing_template ??
                'Shared pricing template',
            )}
          </p>
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Documented monthly amount</th>
                <th>Invoiced amount</th>
                <th>Potential difference</th>
              </tr>
            </thead>
            <tbody>
              {shared.comparisons.map((r) => (
                <tr key={r.customer_id}>
                  <th>{r.customer_id}</th>
                  <td>{money(r.expected_cad)}</td>
                  <td>{money(r.billed_cad)}</td>
                  <td>{money(r.difference_cad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            <strong>Combined potential discrepancy: {money(shared.potential_exposure_cad)}</strong>
          </p>
          <p>
            A common configuration defect is a hypothesis, not a proven root cause. No invoice has
            been corrected and no cash collection is established.
          </p>
          <button onClick={() => void evidence(shared)}>Inspect shared pricing evidence</button>
        </section>
      )}
      <section className="panel">
        <h2>What Needs Your Attention</h2>
        <p>Recommended priorities · no external assignment or correction has occurred.</p>
        <div className="priority-grid">
          {center.issues.map((issue) => {
            const action = center.actions.find((a) => a.issue_id === issue.id);
            return (
              <article className="priority-card" key={issue.id}>
                <span className="eyebrow">PRIORITY {action?.priority ?? issue.priority}</span>
                <h3>{issue.title}</h3>
                <p>
                  <strong>{issue.customer_ids.join(', ')}</strong> ·{' '}
                  {money(issue.potential_exposure_cad)}
                </p>
                <p>
                  {issue.evidence_status}
                  {!!issue.unknown_exposure_accounts?.length &&
                    ` · Unknown exposure: ${issue.unknown_exposure_accounts.join(', ')}`}
                </p>
                <p>{issue.next_action}</p>
                <p>
                  {action
                    ? `${action.status} · ${action.owner} · review ${action.target_date}`
                    : 'Proposed · owner not assigned'}
                </p>
                <button
                  disabled={readOnly}
                  onClick={() => {
                    setSelected(issue);
                    setError('');
                  }}
                >
                  Record management action
                </button>
                <button className="plain" onClick={() => void evidence(issue)}>
                  Open supporting evidence
                </button>
              </article>
            );
          })}
        </div>
        {!center.issues.length && (
          <p>
            No saved current issues. Prepare a simulated demo in Advanced Settings or review Maya’s
            saved investigation.
          </p>
        )}
      </section>
      {selected && (
        <section className="panel" aria-label="Management action editor">
          <h2>{selected.title}</h2>
          <form key={selected.id + String(old?.version)} onSubmit={(e) => void save(e)}>
            <label>
              Internal owner or team
              <input name="owner" required maxLength={200} defaultValue={old?.owner} />
            </label>
            <label>
              Priority
              <select
                aria-label="Priority"
                name="priority"
                defaultValue={old?.priority ?? selected.priority}
              >
                {[1, 2, 3].map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <label>
              Target review date
              <input type="date" name="target_date" required defaultValue={old?.target_date} />
            </label>
            <label>
              Status
              <select aria-label="Status" name="status" defaultValue={old?.status ?? 'Proposed'}>
                {statuses.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label>
              Decision rationale
              <textarea
                name="rationale"
                required
                minLength={5}
                maxLength={1000}
                defaultValue={old?.rationale}
              />
            </label>
            <label>
              Expected verification or closure criteria
              <textarea
                name="closure_criteria"
                required
                minLength={5}
                maxLength={1000}
                defaultValue={old?.closure_criteria}
              />
            </label>
            <label>
              <input type="checkbox" name="closure_support" />I inspected the linked original source
              references supporting administrative task closure. This does not establish a billing
              correction.
            </label>
            <p>
              {center.caveat} Reviewer attribution is recorded from the configured local operator,
              not the persona selector.
            </p>
            <button disabled={busy}>Save human management decision</button>
            <button type="button" className="plain" onClick={() => setSelected(null)}>
              Cancel
            </button>
          </form>
        </section>
      )}
      {sources && (
        <section className="panel">
          <h2>Supporting contracts and invoice records</h2>
          <button className="plain" onClick={() => setSources(null)}>
            Close evidence
          </button>
          {sources.map((s, i) => (
            <details open key={i}>
              <summary>{String(s.document_id)}</summary>
              <pre className="source-text">
                {String(s.text ?? JSON.stringify(s.record, null, 2))}
              </pre>
            </details>
          ))}
        </section>
      )}
      <section className="panel">
        <h2>Corrective Actions</h2>
        <p>
          Internal task tracking only. Closed tasks never reduce financial exposure automatically.
        </p>
        {center.actions.map((a) => (
          <article key={a.id}>
            <h3>
              {a.owner} · {a.status}
            </h3>
            <p className="small muted">
              {a.provenance?.kind === 'simulated_demo_action'
                ? 'Simulated Demo Data · proposed fixture action, not a human decision or external assignment'
                : 'Actual local human management record · reviewer attribution in audit history'}
            </p>
            <p>
              Priority {a.priority} · target {a.target_date} · {a.rationale}
            </p>
            <details>
              <summary>Decision audit history · version {a.version}</summary>
              {a.history.map((h) => (
                <p key={h.version}>
                  {h.timestamp} · {h.reviewer} · {h.status} · {h.rationale}
                </p>
              ))}
            </details>
          </article>
        ))}
        {!center.actions.length && <p>No human management actions recorded.</p>}
      </section>
      <section className="panel">
        <h2>Operational Impact</h2>
        <span className="eyebrow">OBSERVED · PERSISTED APPLICATION DATA</span>
        <dl className="impact-grid">
          {Object.entries(center.observed).map(([k, v]) => (
            <div key={k}>
              <dt>{k.replaceAll('_', ' ')}</dt>
              <dd>{v == null ? 'Not yet measured' : k.endsWith('_cad') ? money(String(v)) : v}</dd>
            </div>
          ))}
        </dl>
        <h3>Pilot measurement required</h3>
        <p>
          {center.measurement_required.join(' · ')}: Not yet measured. A pilot must capture
          timestamped human effort, baselines and source-backed correction outcomes.
        </p>
        <p>
          Scenario projections belong to Robert’s assumptions calculator; they are not observed
          savings.
        </p>
      </section>
    </div>
  );
}

export function PrepareDemo({
  onNavigate,
  disabled,
}: {
  onNavigate: (id: string, persona: 'maya' | 'sarah' | 'robert') => void;
  disabled: boolean;
}) {
  const [confirm, setConfirm] = useState(false),
    [id, setId] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  async function prepare() {
    setBusy(true);
    try {
      const result = await api<{ id: string }>('/admin/prepare-demo', {
        method: 'POST',
        body: JSON.stringify({ confirmation: 'PREPARE SIMULATED DEMO' }),
      });
      setId(result.id);
      setConfirm(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel admin-panel">
      <span className="eyebrow">SIMULATED DEMONSTRATION · NO OPENAI USAGE</span>
      <h2>Prepare Full Demo</h2>
      <p>
        Prepare one shared April 2026 scenario for Maya, Sarah and Robert using deterministic Python
        and original fixture evidence. Genuine paid investigations remain separate.
      </p>
      <button disabled={disabled || busy} onClick={() => setConfirm(true)}>
        Prepare Full Demo
      </button>
      {confirm && (
        <div role="dialog" aria-modal="true" aria-label="Confirm simulated demo preparation">
          <h3>Prepare Simulated Demo Data?</h3>
          <p>
            This creates or reuses a separate fixture-backed investigation with simulated review
            annotations, unresolved exceptions and shared management/executive context. No OpenAI
            requests, real human approvals or financial changes occur. Existing investigations,
            journals and decisions are retained; nothing is deleted or silently completed. Repeat
            preparation reuses the same scenario for unchanged source data. Archive-only Reset Demo
            remains a separate operation.
          </p>
          <button disabled={busy} onClick={() => void prepare()}>
            Confirm preparation — no API usage
          </button>
          <button className="plain" onClick={() => setConfirm(false)}>
            Cancel
          </button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {id && (
        <div className="notice">
          <strong>Demo Scenario: April 2026 · Prepared · Simulated</strong>
          <div className="demo-navigation">
            <button onClick={() => onNavigate(id, 'maya')}>Start Full Demo</button>
            <button onClick={() => onNavigate(id, 'maya')}>View Maya’s Results</button>
            <button onClick={() => onNavigate(id, 'sarah')}>Jump to Sarah</button>
            <button onClick={() => onNavigate(id, 'robert')}>Jump to Robert</button>
          </div>
        </div>
      )}
    </section>
  );
}
