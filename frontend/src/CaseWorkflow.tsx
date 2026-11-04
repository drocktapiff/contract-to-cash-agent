import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { Finding, Run, AuthorityRecord, CollaborativeOutcome } from './types';

export function CollaborationSummary({ run, onOpen }: { run: Run; onOpen: (child: Run) => void }) {
  const [outcome, setOutcome] = useState<CollaborativeOutcome | null>(null);
  const [error, setError] = useState('');
  const parent = run.continuation?.parent_run_id ?? run.id;
  useEffect(() => {
    if (run.mode !== 'live') return;
    api<CollaborativeOutcome>(`/runs/${parent}/outcome`)
      .then(setOutcome)
      .catch((e) => setError(e.message));
  }, [parent, run.last_event_sequence, run.status]);
  if (!outcome?.human_contributions.length)
    return error ? (
      <p className="notice error">Collaboration history could not load: {error}</p>
    ) : null;
  return (
    <section className="collaboration-summary panel">
      <span className="eyebrow">HUMAN + AI</span>
      <h3>What your contribution enabled</h3>
      <div className="collaboration-columns">
        <div>
          <h4>AI found</h4>
          {outcome.original_findings.map((f) => (
            <p key={f.finding_id}>
              {f.customer_ids.join(', ')} ·{' '}
              {f.recommendation?.problem ??
                f.model_hypothesis ??
                'Saved finding — inspect its original evidence.'}
            </p>
          ))}
        </div>
        <div>
          <h4>You contributed</h4>
          {outcome.human_contributions.map((r) => (
            <div key={r.id} className="contribution">
              <strong>
                {r.action === 'resolve'
                  ? 'Documented resolution'
                  : r.action === 'escalate'
                    ? 'Clarification requested'
                    : 'Hypothesis dismissed'}
              </strong>
              <p>{r.rationale}</p>
              {r.clarification_owner && (
                <p>
                  Requested from {r.clarification_owner}: {r.missing_information}
                </p>
              )}
              <small>
                {r.reviewer} · {new Date(r.created_at).toLocaleString()}
              </small>
            </div>
          ))}
        </div>
        <div>
          <h4>AI after intervention</h4>
          {outcome.continued_investigations.length ? (
            outcome.continued_investigations.map((child) => (
              <div key={child.run_id} className="contribution">
                <p>
                  {child.customers_compared.length} account(s) compared ·{' '}
                  {child.findings.filter((f) => f.evidence_verified).length} evidence-verified
                  finding(s)
                </p>
                <p>
                  {child.ready_for_review
                    ? 'Ready for separate human review'
                    : child.status === 'completed'
                      ? 'Scoped investigation completed. Saved human decisions remain in its history.'
                      : `Saved state: ${child.status}. Completion is not implied.`}
                </p>
                <button
                  className="secondary"
                  onClick={() =>
                    void api<Run>(`/runs/${child.run_id}`)
                      .then(onOpen)
                      .catch((e) => setError(e.message))
                  }
                >
                  Open continued investigation →
                </button>
              </div>
            ))
          ) : (
            <p>No continuation has been authorized. The agent has not resumed.</p>
          )}
        </div>
      </div>
      <p className="muted small">{outcome.disclaimer}</p>
    </section>
  );
}

export default function CaseWorkflow({
  run,
  finding,
  stale,
  onUpdated,
  onContinue,
}: {
  run: Run;
  finding: Finding;
  stale: boolean;
  onUpdated: (run: Run) => void;
  onContinue: (run: Run) => void;
}) {
  const [authority, setAuthority] = useState<AuthorityRecord[]>([]),
    [evidenceId, setEvidenceId] = useState('');
  const [action, setAction] = useState<'resolve' | 'escalate' | 'dismiss' | ''>('');
  const [rationale, setRationale] = useState(''),
    [owner, setOwner] = useState(''),
    [missing, setMissing] = useState('');
  const [continuations, setContinuations] = useState<
    CollaborativeOutcome['continued_investigations']
  >([]);
  const [continuationsLoaded, setContinuationsLoaded] = useState(false);
  const [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [confirming, setConfirming] = useState(false),
    [paid, setPaid] = useState(false);
  const request = useRef({ fingerprint: '', key: '' });
  const continuationKey = useRef(crypto.randomUUID());
  const history = (run.interventions ?? []).filter((r) => r.finding_id === finding.finding_id);
  const latest = history.at(-1);
  const conflict = (finding.comparisons ?? [finding.comparison]).some(
    (r) => r?.status === 'conflict',
  );
  const available =
    run.mode === 'live' &&
    !['queued', 'running'].includes(run.status) &&
    !stale &&
    finding.state !== 'retracted' &&
    !finding.requires_revalidation;
  const final = latest?.action === 'resolve' || latest?.action === 'dismiss';
  const existingContinuation = continuations.find((child) =>
    ['queued', 'running', 'completed'].includes(child.status),
  );
  useEffect(() => {
    if (run.mode !== 'live' || latest?.action !== 'resolve') return;
    setContinuationsLoaded(false);
    api<CollaborativeOutcome>(`/runs/${run.id}/outcome`)
      .then((result) => {
        setContinuations(
          result.continued_investigations.filter((child) => child.intervention_id === latest.id),
        );
        setContinuationsLoaded(true);
      })
      .catch((e) => setError(e.message));
  }, [run.id, latest?.id]);
  const selected = authority.find((r) => r.evidence_id === evidenceId);
  useEffect(() => {
    if (run.mode !== 'live') return;
    api<AuthorityRecord[]>('/resolution-evidence')
      .then((items) =>
        setAuthority(
          items.filter((r) => finding.customer_ids.includes(r.payload.assertion.customer_id)),
        ),
      )
      .catch((e) => setError(e.message));
  }, [run.id, finding.finding_id]);
  async function save() {
    const fields = {
      action,
      rationale,
      expected_version: finding.version,
      expected_revision: finding.data_revision,
      expected_workflow_version: latest?.workflow_version ?? 0,
      ...(action === 'resolve'
        ? {
            evidence_id: evidenceId,
            governing_amendment_id: selected?.payload.assertion.governing_amendment_id,
          }
        : {}),
      ...(action === 'escalate'
        ? { clarification_owner: owner, missing_information: missing }
        : {}),
    };
    const fingerprint = JSON.stringify(fields);
    if (request.current.fingerprint !== fingerprint)
      request.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    setError('');
    try {
      const saved = await api<{ run: Run }>(
        `/runs/${run.id}/findings/${encodeURIComponent(finding.finding_id)}/interventions`,
        {
          method: 'POST',
          body: JSON.stringify({ ...fields, idempotency_key: request.current.key }),
        },
      );
      onUpdated(saved.run);
      setAction('');
      setRationale('');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function continueRun() {
    if (!latest || !paid) return;
    setBusy(true);
    setError('');
    try {
      const child = await api<Run>(`/runs/${run.id}/continue`, {
        method: 'POST',
        body: JSON.stringify({
          idempotency_key: continuationKey.current,
          intervention_id: latest.id,
          acknowledge_paid: true,
        }),
      });
      onContinue(child);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="decision-section human-workflow">
      <h3>Your decision is needed</h3>
      <p className="muted">
        The agent can examine records. You provide missing business authority, request
        clarification, or challenge its interpretation. Nothing here changes a bill or approves an
        export.
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {history.map((record) => (
        <div className="decision-record" key={record.id}>
          <strong>
            {record.action === 'resolve'
              ? 'Resolution saved with evidence'
              : record.action === 'escalate'
                ? record.id === latest?.id
                  ? 'Awaiting clarification'
                  : 'Clarification request saved'
                : 'Finding dismissed'}
          </strong>
          <p>{record.rationale}</p>
          {record.clarification_owner && (
            <p>
              Who: {record.clarification_owner}
              <br />
              Missing: {record.missing_information}
            </p>
          )}
          <small>
            {record.reviewer} · {new Date(record.created_at).toLocaleString()}
          </small>
          {record.evidence_id && (
            <p className="small break">Supporting record: {record.evidence_id}</p>
          )}
        </div>
      ))}
      {available && !final && (
        <>
          <div className="decision-choices">
            {conflict && (
              <button
                className={action === 'resolve' ? 'primary' : 'secondary'}
                onClick={() => setAction('resolve')}
              >
                Resolve with evidence
              </button>
            )}
            <button
              className={action === 'escalate' ? 'primary' : 'secondary'}
              onClick={() => setAction('escalate')}
            >
              Escalate for clarification
            </button>
            <button
              className={action === 'dismiss' ? 'danger selected' : 'danger'}
              onClick={() => setAction('dismiss')}
            >
              Dismiss finding
            </button>
          </div>
          {action && (
            <div className="guided-action">
              {action === 'resolve' && (
                <>
                  <label>
                    Authoritative supporting record
                    <select
                      aria-label="Authoritative supporting record"
                      value={evidenceId}
                      onChange={(e) => setEvidenceId(e.target.value)}
                    >
                      <option value="">Choose a registered record</option>
                      {authority.map((r) => (
                        <option key={r.evidence_id} value={r.evidence_id}>
                          {r.payload.assertion.issuer} · governing{' '}
                          {r.payload.assertion.governing_amendment_id}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!authority.length && (
                    <p className="notice">
                      Ask your administrator to verify and register the original written
                      confirmation and its issuer's authority. A selection or explanation alone
                      cannot establish precedence. Until then, escalate for clarification.
                    </p>
                  )}
                  {selected && (
                    <div className="authority-preview">
                      <h4>Source and authority</h4>
                      <p>{selected.payload.assertion.source_reference}</p>
                      <p>{selected.payload.assertion.issuer_authority}</p>
                      <p className="source-text">{selected.payload.assertion.confirmation_text}</p>
                      <p>
                        Governing: {selected.payload.assertion.governing_amendment_id}. Superseded
                        for this comparison:{' '}
                        {selected.payload.assertion.superseded_amendment_ids.join(', ')}.
                      </p>
                      <details>
                        <summary>Read original written confirmation</summary>
                        <p className="source-text">{selected.payload.original_document_text}</p>
                        <p className="small break">
                          Original SHA-256: {selected.payload.original_document_sha256}
                        </p>
                      </details>
                      <small>
                        Source and authority attested by {selected.payload.verified_by}. Ledgerline
                        does not independently authenticate the issuer or legal authority.
                      </small>
                    </div>
                  )}
                </>
              )}
              {action === 'escalate' && (
                <>
                  <label>
                    Who should provide clarification?
                    <input
                      value={owner}
                      maxLength={200}
                      onChange={(e) => setOwner(e.target.value)}
                      placeholder="Department or responsible colleague"
                    />
                  </label>
                  <label>
                    What information is missing?
                    <textarea
                      value={missing}
                      maxLength={1000}
                      onChange={(e) => setMissing(e.target.value)}
                    />
                  </label>
                </>
              )}
              <label>
                Explain your decision
                <textarea
                  value={rationale}
                  minLength={5}
                  maxLength={1000}
                  onChange={(e) => setRationale(e.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={
                  busy ||
                  rationale.trim().length < 5 ||
                  (action === 'resolve' && !selected) ||
                  (action === 'escalate' && (!owner.trim() || !missing.trim()))
                }
                onClick={() => void save()}
              >
                {busy
                  ? 'Saving…'
                  : action === 'resolve'
                    ? 'Save documented resolution'
                    : action === 'escalate'
                      ? 'Save clarification request'
                      : 'Confirm dismissal'}
              </button>
            </div>
          )}
        </>
      )}
      {available && latest?.action === 'resolve' && (
        <div className="continuation-card">
          <h4>
            {existingContinuation
              ? 'Your continued investigation is saved'
              : 'Ready for the agent to take another look'}
          </h4>
          {existingContinuation ? (
            <button
              className="primary"
              onClick={() =>
                void api<Run>(`/runs/${existingContinuation.run_id}`)
                  .then(onContinue)
                  .catch((e) => setError(e.message))
              }
            >
              Open continued investigation
            </button>
          ) : (
            <>
              <p>
                Your evidence is saved. Continue only this customer in a new bounded investigation;
                the original history stays intact. This does not authorize an export or financial
                correction.
              </p>
              {continuations.length >= 3 ? (
                <p className="notice">
                  Three attempts are retained. No further continuation is available for this
                  resolution.
                </p>
              ) : (
                <button
                  className="primary"
                  disabled={!continuationsLoaded}
                  onClick={() => {
                    setConfirming(true);
                    setPaid(false);
                  }}
                >
                  Continue investigation
                </button>
              )}
            </>
          )}
        </div>
      )}
      {confirming && (
        <div className="paid-confirmation">
          <h4>Authorize one paid continuation</h4>
          <p>
            Maximum 3 minutes · $1 estimated API cost · 35 tools · 40 model requests. Current
            administrator-confirmed pricing is required. Attempts are rate limited and capped at
            three per resolution.
          </p>
          <label className="check">
            <input type="checkbox" checked={paid} onChange={(e) => setPaid(e.target.checked)} />I
            authorize this paid continuation.
          </label>
          <button className="primary" disabled={busy || !paid} onClick={() => void continueRun()}>
            Begin authorized continuation
          </button>
          <button className="plain" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      )}
      {latest?.action === 'escalate' && (
        <p className="notice">
          Waiting for the requested information. No dependent calculation or paid continuation has
          started. Return with registered supporting evidence when available.
        </p>
      )}
      {latest?.action === 'dismiss' && (
        <p className="notice">
          The original hypothesis and evidence are retained. No investigation was continued.
        </p>
      )}
      {!available && (
        <p className="muted small">
          Decisions require a settled, current live investigation. Recorded evidence remains
          read-only.
        </p>
      )}
    </section>
  );
}
