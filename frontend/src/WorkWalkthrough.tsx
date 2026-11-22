import { useEffect, useRef, useState } from 'react';
import { api } from './api';

type Scenario = { key: string; label: string; work_item_id: string | null };
type Story = {
  item: {
    work_item_id: string;
    customer_id: string;
    customer_name?: string;
    status: string;
    version: number;
    supporting_facts: Record<string, unknown>;
  };
  business: { title: string; why_it_matters: string; next_action: string };
  documents: {
    document_id: string;
    file_hash: string;
    document_type: string;
    errors: string[];
    facts: { field: string; value: string; spans: { page: number; text: string }[] }[];
  }[];
  manual_steps: { title: string; description: string; file_hash?: string; document_id?: string }[];
  manual_label: string;
  manual_role: string;
  processing_label: string;
  recorded: boolean;
  recorded_operation_id: string | null;
  can_process: boolean;
  financial_comparison: Record<string, string> | null;
  validation: {
    at: string;
    details: {
      evidence_current: boolean;
      automation_eligible: boolean;
      eligibility_reason: string;
      financial_comparison: Record<string, string> | null;
    };
  } | null;
  processing_events: {
    id: string;
    type: string;
    at: string;
    rationale: string;
    after: string | null;
  }[];
  outcome: {
    lifecycle_label?: string;
    status: string;
    administratively_completed: boolean;
    waiting_on: string | null;
  };
};
export default function WorkWalkthrough({
  sid,
  scenarios,
  onClose,
  onProcess,
  onRemaining,
  revision,
  disabled,
  initialItem,
  completedOperationId,
}: {
  completedOperationId?: string;
  initialItem?: string | null;
  sid: string;
  scenarios: Scenario[];
  onClose: () => void;
  onProcess: (item: Story['item']) => void;
  onRemaining: () => void;
  revision: unknown;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState(initialItem ? 'selected' : (scenarios[0]?.key ?? '')),
    [story, setStory] = useState<Story | null>(null),
    [step, setStep] = useState(0),
    [manual, setManual] = useState(0),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false),
    [requested, setRequested] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    opener = useRef(document.activeElement as HTMLElement | null);
  useEffect(() => {
    dialog.current?.showModal();
    return () => {
      if (opener.current?.isConnected && opener.current !== document.body) opener.current.focus();
      else document.querySelector<HTMLButtonElement>('.mw-queue-heading button')?.focus();
    };
  }, []);
  const initialScenarios = useRef(scenarios).current;
  const choices = initialItem
    ? [
        { key: 'selected', label: 'Selected work item', work_item_id: initialItem },
        ...initialScenarios,
      ]
    : initialScenarios;
  const wid = choices.find((s) => s.key === selected)?.work_item_id;
  useEffect(() => {
    let current = true;
    setError('');
    setLoading(true);
    if (!wid) {
      setStory(null);
      setLoading(false);
      return;
    }
    void api<Story>(`/document-workspace/sessions/${sid}/walkthrough/${wid}`)
      .then((s) => {
        if (current) setStory(s);
      })
      .catch((e) => current && setError((e as Error).message))
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
    };
  }, [sid, wid, revision]);
  function choose(key: string) {
    setSelected(key);
    setStep(0);
    setManual(0);
    setStory(null);
    setRequested(false);
  }
  const currentOperation = requested && completedOperationId === story?.recorded_operation_id;
  const pdf = (hash: string) => `/api/document-workspace/sessions/${sid}/evidence/${hash}`;
  return (
    <dialog
      className="mw-walkthrough"
      ref={dialog}
      aria-labelledby="walk-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="mw-detail-top">
        <div>
          <span className="mw-eyebrow">SAME DOCUMENTS · OBSERVABLE OUTCOMES</span>
          <h2 id="walk-title">Show Me the Work</h2>
        </div>
        <button onClick={onClose} aria-label="Close walkthrough">
          Close ×
        </button>
      </div>
      <p className="mw-walk-lead">
        A real case, from traditional cross-referencing to an auditable workflow result.
      </p>
      <div className="mw-scenario">
        <label htmlFor="walk-scenario">Choose a real case</label>
        <select id="walk-scenario" value={selected} onChange={(e) => choose(e.target.value)}>
          {choices.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
              {s.work_item_id ? '' : ' — unavailable'}
            </option>
          ))}
        </select>
      </div>
      <nav className="mw-steps" aria-label="Walkthrough steps">
        {[
          'Before Ledgerline',
          'Understand the documents',
          'Process the work',
          'Business outcome',
        ].map((label, i) => (
          <button
            key={label}
            aria-current={step === i ? 'step' : undefined}
            onClick={() => setStep(i)}
          >
            <span>{i + 1}</span>
            {label}
          </button>
        ))}
      </nav>
      {error && (
        <p role="alert" className="mw-alert">
          {error}
        </p>
      )}
      {loading && <p role="status">Retrieving saved source evidence and actual workflow events…</p>}
      {!loading && !wid && (
        <p>
          No supported work item is available for this scenario in this session. Choose another
          case.
        </p>
      )}
      {story && (
        <>
          <div className="mw-case-banner">
            <strong>{story.business.title}</strong>
            <span>
              {story.item.customer_name ?? story.item.customer_id} · {story.item.customer_id}
            </span>
            {story.recorded && (
              <small>
                {currentOperation
                  ? 'Recorded result of the requested operation'
                  : 'Recorded replay — historical processing; no new mutation'}
              </small>
            )}
          </div>
          {step === 0 && (
            <section className="mw-walk-panel">
              <span className="mw-eyebrow">TRADITIONAL {story.manual_role.toUpperCase()}</span>
              <h3>Before Ledgerline</h3>
              <p>{story.manual_label}. Presenter clicks are not measured professional labor.</p>
              <div className="mw-manual">
                <span className="mw-step-count">
                  Task {manual + 1} of {story.manual_steps.length}
                </span>
                <h3>{story.manual_steps[manual].title}</h3>
                <p>{story.manual_steps[manual].description}</p>
                {story.manual_steps[manual].file_hash && (
                  <a
                    className="mw-pdf"
                    href={pdf(story.manual_steps[manual].file_hash!)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open {story.manual_steps[manual].document_id} ↗
                  </a>
                )}
                <div className="mw-command-row">
                  <button disabled={manual === 0} onClick={() => setManual((v) => v - 1)}>
                    Previous manual task
                  </button>
                  <button
                    disabled={manual === story.manual_steps.length - 1}
                    onClick={() => setManual((v) => v + 1)}
                  >
                    Next manual task
                  </button>
                </div>
              </div>
            </section>
          )}
          {step === 1 && (
            <section className="mw-walk-panel">
              <h3>What the documents actually say</h3>
              <p>
                Extracted facts are separate from Python-calculated comparisons. Signed conflicts
                and unknown amounts remain unresolved.
              </p>
              <div className="mw-document-cards">
                {story.documents.map((d) => (
                  <article key={d.file_hash}>
                    <span className="mw-eyebrow">EXTRACTED · {d.document_type}</span>
                    <a href={pdf(d.file_hash)} target="_blank" rel="noopener noreferrer">
                      {d.document_id} ↗
                    </a>
                    <dl>
                      {d.facts.map((f) => (
                        <div key={f.field}>
                          <dt>{f.field}</dt>
                          <dd>{f.value}</dd>
                          {f.spans[0] && (
                            <small>
                              Page {f.spans[0].page} · “{f.spans[0].text}”
                            </small>
                          )}
                        </div>
                      ))}
                    </dl>
                  </article>
                ))}
              </div>
              <h4>Deterministic financial comparison</h4>
              {story.financial_comparison ? (
                <dl className="mw-financial">
                  {Object.entries(story.financial_comparison)
                    .filter(([k]) => k !== 'currency')
                    .map(([k, v]) => (
                      <div key={k}>
                        <dt>{k.replaceAll('_', ' ')}</dt>
                        <dd>
                          {story.financial_comparison!.currency} {v}
                        </dd>
                      </div>
                    ))}
                </dl>
              ) : (
                <p className="mw-unknown">
                  The current evidence does not establish a quantifiable authoritative amount.
                  Unknown is not zero.
                </p>
              )}
              <p>Potential differences are not authorized corrections or recovered revenue.</p>
            </section>
          )}
          {step === 2 && (
            <section className="mw-walk-panel">
              <h3>
                {story.recorded ? 'Inspect the recorded work' : 'Watch Ledgerline perform the work'}
              </h3>
              <p>{story.processing_label}.</p>
              {!story.recorded ? (
                <>
                  <p>
                    No processing outcome is being simulated. The button invokes the existing
                    evidence-bound administrative operation.
                  </p>
                  <button
                    className="mw-primary"
                    disabled={disabled || !story.can_process || loading}
                    onClick={() => {
                      setRequested(true);
                      onProcess(story.item);
                    }}
                  >
                    Process This Work Item
                  </button>
                  {!story.can_process && (
                    <p>
                      This item is read-only or already handed off. No new processing is permitted.
                    </p>
                  )}
                </>
              ) : (
                <>
                  <p className="mw-recorded">
                    {currentOperation
                      ? 'Actual operation completed; the records below are its saved evidence.'
                      : 'Recorded replay. Opening this walkthrough does not execute the work again.'}
                  </p>
                  {story.validation ? (
                    <ol className="mw-proof">
                      <li>
                        <strong>Source evidence checked</strong>
                        <p>
                          {story.validation.details.evidence_current
                            ? 'The session PDFs were re-extracted and reconciled.'
                            : 'Missing, changed or contradictory evidence prevented unsupported completion.'}
                        </p>
                      </li>
                      <li>
                        <strong>Business rule evaluated</strong>
                        <p>
                          {story.validation.details.automation_eligible
                            ? 'Evidence supported a permitted administrative check.'
                            : 'Human authority or additional evidence was required.'}{' '}
                          {story.validation.details.eligibility_reason}
                        </p>
                      </li>
                    </ol>
                  ) : (
                    <p>
                      Detailed validation proof was not recorded for this earlier operation. Only
                      the actual available workflow events are shown.
                    </p>
                  )}
                  {story.validation?.details.financial_comparison && (
                    <>
                      <h4>Recorded Python comparison</h4>
                      <small>
                        As recorded {new Date(story.validation.at).toLocaleString()}; not a new
                        calculation.
                      </small>
                      <dl className="mw-financial">
                        {Object.entries(story.validation.details.financial_comparison)
                          .filter(([k]) => k !== 'currency')
                          .map(([k, v]) => (
                            <div key={k}>
                              <dt>{k.replaceAll('_', ' ')}</dt>
                              <dd>
                                {story.validation!.details.financial_comparison!.currency} {v}
                              </dd>
                            </div>
                          ))}
                      </dl>
                    </>
                  )}
                  <h4>Actual recorded workflow</h4>
                  <ol className="mw-proof">
                    {story.processing_events
                      .filter((e) =>
                        [
                          'evidence_validation_recorded',
                          'routine_processing_completed',
                          'administratively_closed',
                          'escalated',
                          'awaiting_evidence',
                          'human_review_requested',
                          'automatic_disposition_applied',
                        ].includes(e.type),
                      )
                      .map((e) => (
                        <li key={e.id}>
                          <strong>
                            {
                              {
                                evidence_validation_recorded: 'Evidence revalidated',
                                routine_processing_completed: 'Supported check performed',
                                administratively_closed: 'Administrative completion recorded',
                                escalated: 'Referred to Sarah',
                                awaiting_evidence: 'Missing evidence requested',
                                human_review_requested: 'Human review requested',
                                automatic_disposition_applied: 'Workflow disposition recorded',
                              }[e.type]
                            }
                          </strong>
                          <time>{new Date(e.at).toLocaleString()}</time>
                          <p>
                            {e.rationale}
                            {e.after ? ` · ${e.after}` : ''}
                          </p>
                        </li>
                      ))}
                  </ol>
                </>
              )}
            </section>
          )}
          {step === 3 && (
            <section className="mw-walk-panel">
              <h3>
                {story.recorded
                  ? 'Here is the business outcome'
                  : 'This case has not been processed yet'}
              </h3>
              {story.recorded ? (
                <>
                  <div className="mw-outcome">
                    <strong>
                      {story.outcome.administratively_completed
                        ? (story.outcome.lifecycle_label ??
                          'Legacy automated closure — no recorded human review')
                        : `Work remains open: ${story.outcome.status}`}
                    </strong>
                    <p>
                      {story.outcome.waiting_on
                        ? `Waiting on ${story.outcome.waiting_on}.`
                        : 'Maya retains case ownership.'}{' '}
                      No financial or contractual decision was executed.
                    </p>
                  </div>
                  <h4>What Ledgerline verified</h4>
                  <p>
                    {story.validation?.details.evidence_current
                      ? 'The stored source records were re-extracted and checked under supported deterministic rules.'
                      : 'Current evidence did not establish a supported automatic outcome; inspect the recorded limitations.'}
                  </p>
                  <p>{story.business.why_it_matters}</p>
                  <h4>Original supporting records</h4>
                  {story.documents.map((d) => (
                    <p key={d.file_hash}>
                      <a href={pdf(d.file_hash)} target="_blank" rel="noopener noreferrer">
                        {d.document_id} ↗
                      </a>
                    </p>
                  ))}
                  <button className="mw-primary" disabled={disabled} onClick={onRemaining}>
                    Process All Remaining Work
                  </button>
                  <p>
                    Rechecks the actual remaining queue. Completed checks and prior handoffs are not
                    counted or executed again.
                  </p>
                </>
              ) : (
                <p>
                  Go to Process the work to run the supported operation, or leave this case
                  unchanged.
                </p>
              )}
            </section>
          )}
          <div className="mw-walk-footer">
            <button disabled={step === 0} onClick={() => setStep((v) => v - 1)}>
              Back
            </button>
            <span>{step + 1} / 4</span>
            {step < 3 ? (
              <button className="mw-primary" onClick={() => setStep((v) => v + 1)}>
                Continue
              </button>
            ) : (
              <button onClick={onClose}>Return to work queue</button>
            )}
          </div>
        </>
      )}
    </dialog>
  );
}
