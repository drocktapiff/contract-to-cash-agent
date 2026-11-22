import { useEffect, useRef, useState } from 'react';
import { api } from './api';
export type ReviewChoice = { id: string; version: number };
type Preview = {
  selected: number;
  eligible: number;
  excluded: number;
  changed_evidence: number;
  previously_rejected: number;
  individual_review_required: number;
  read_only: boolean;
  methodology: string;
  items: {
    id: string;
    version: number;
    eligible: boolean;
    reason: string | null;
    status: string;
    evidence_hashes: string[];
    automated_result: {
      event_id: string;
      operation_id: string;
      finding: string;
      mechanism: string;
      financial_comparison: Record<string, string> | null;
    } | null;
    documents: { document_id: string; file_hash: string; fields: Record<string, string> }[];
  }[];
};
export default function HumanReviewPanel({
  sid,
  choices,
  bulk,
  reviewer,
  onClose,
  onComplete,
  readOnly = false,
}: {
  sid: string;
  choices: ReviewChoice[];
  bulk: boolean;
  reviewer: string;
  onClose: () => void;
  onComplete: () => Promise<void>;
  readOnly?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    pending = useRef<{ key: string; body: object } | null>(null);
  const [data, setData] = useState<Preview | null>(null),
    [error, setError] = useState(''),
    [actor, setActor] = useState(reviewer),
    [rationale, setRationale] = useState(''),
    [ack, setAck] = useState(false),
    [decision, setDecision] = useState('approve'),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState<{
      approved: number;
      rejected: number;
      excluded: number;
      failed: number;
      per_item: { id: string; outcome: string; reason?: string }[];
    } | null>(null);
  useEffect(() => {
    dialog.current?.showModal();
    let active = true;
    void api<Preview>(`/document-workspace/sessions/${sid}/review-preview`, {
      method: 'POST',
      body: JSON.stringify({
        operation_id: crypto.randomUUID().replaceAll('-', ''),
        actor: reviewer,
        rationale: 'Preview current human review eligibility; no decision.',
        confirmation: 'ADMINISTRATIVE WORKFLOW ONLY',
        expected_session: sid,
        selected: choices,
      }),
    })
      .then((v) => {
        if (active) setData(v);
      })
      .catch((e) => active && setError((e as Error).message));
    return () => {
      active = false;
    };
  }, [sid]);
  async function submit() {
    if (!data) return;
    setBusy(true);
    setError('');
    const fields = {
      expected_session: sid,
      actor,
      rationale,
      confirmation: 'ADMINISTRATIVE WORKFLOW ONLY',
      selected: choices.map((c) => ({
        ...c,
        evidence_hashes: data.items.find((i) => i.id === c.id)?.evidence_hashes ?? [],
      })),
      decision,
      attestation: bulk ? 'bulk' : 'individual',
      acknowledge_review: true,
    };
    const key = JSON.stringify(fields);
    if (pending.current?.key !== key)
      pending.current = {
        key,
        body: { ...fields, operation_id: crypto.randomUUID().replaceAll('-', '') },
      };
    try {
      const answer = await api<NonNullable<typeof result>>(
        `/document-workspace/sessions/${sid}/human-reviews`,
        { method: 'POST', body: JSON.stringify(pending.current.body) },
      );
      setResult(answer);
      await onComplete();
      pending.current = null;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="mw-confirm hr-review"
      aria-labelledby="hr-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <span className="mw-eyebrow">MANDATORY HUMAN VERIFICATION · ADMINISTRATIVE ONLY</span>
        <h2 id="hr-title">{bulk ? 'Review All' : 'Review Automated Result'}</h2>
        {!data && !error && <p role="status">Revalidating original PDFs and prepared results…</p>}
        {data && (
          <>
            <div className="hr-summary">
              <strong>{data.selected} selected</strong>
              <span>{data.eligible} eligible for approval</span>
              <span>{data.excluded} excluded</span>
              <span>{data.changed_evidence} evidence changes / integrity exclusions</span>
              <span>{data.previously_rejected} previously rejected</span>
              <span>{data.individual_review_required} require individual investigation</span>
            </div>
            <p>
              {bulk
                ? 'This is a bulk attestation of the listed low-risk checks. It does not claim you individually inspected each case.'
                : 'Inspect the automated finding, calculations and original evidence before deciding.'}{' '}
              No financial correction, credit, cash movement or contractual authority is authorized.
            </p>
            <div className="hr-evidence">
              {data.items.map((row) => (
                <details key={row.id} open={!bulk}>
                  <summary>
                    {row.id} · {row.eligible ? 'Eligible low-risk check' : row.reason}
                  </summary>
                  <h3>Automated finding</h3>
                  <p>{row.automated_result?.finding ?? 'No supported prepared result'}</p>
                  <p>{row.automated_result?.mechanism}</p>
                  <h4>Calculation</h4>
                  {row.automated_result?.financial_comparison ? (
                    <dl>
                      {Object.entries(row.automated_result.financial_comparison).map(([k, v]) => (
                        <div key={k}>
                          <dt>{k.replaceAll('_', ' ')}</dt>
                          <dd>{v}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p>No quantifiable comparison; never assume unknown is zero.</p>
                  )}
                  <h4>Original evidence</h4>
                  {row.evidence_hashes.map((hash) => (
                    <p key={hash}>
                      <a
                        target="_blank"
                        rel="noopener noreferrer"
                        href={`/api/document-workspace/sessions/${sid}/evidence/${hash}`}
                      >
                        Open review source PDF ↗
                      </a>
                      <small>{hash}</small>
                    </p>
                  ))}
                  {row.documents.map((doc) => (
                    <details key={doc.file_hash}>
                      <summary>Extracted fields · {doc.document_id}</summary>
                      <dl>
                        {Object.entries(doc.fields).map(([k, v]) => (
                          <div key={k}>
                            <dt>{k}</dt>
                            <dd>{v}</dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  ))}
                  <small>
                    Captured work version {choices.find((c) => c.id === row.id)?.version}.
                    Preparation event {row.automated_result?.event_id}; operation{' '}
                    {row.automated_result?.operation_id}.
                  </small>
                </details>
              ))}
            </div>
            {!bulk && (
              <label>
                Review decision
                <select
                  aria-label="Review decision"
                  value={decision}
                  onChange={(e) => setDecision(e.target.value)}
                >
                  <option value="approve">Approve &amp; Close</option>
                  <option value="reject">Reject Automated Result</option>
                  <option value="evidence">Request Additional Evidence</option>
                  <option value="escalate">Escalate to Sarah</option>
                </select>
              </label>
            )}
            <label>
              Review actor attribution
              <input required value={actor} onChange={(e) => setActor(e.target.value)} />
            </label>
            <label htmlFor="hr-rationale">Review rationale</label>
            <textarea
              id="hr-rationale"
              required
              minLength={5}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
            <label className="mw-checkbox">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              {bulk
                ? 'I explicitly attest these eligible low-risk automated checks as a bulk review; I am not claiming individual inspection.'
                : 'I acknowledge reviewing the presented automated finding and supporting evidence status before recording this decision.'}
            </label>
            {data.read_only && (
              <p className="mw-alert">Retained session: review history is read-only.</p>
            )}
            {!result && (
              <button
                className="mw-primary"
                disabled={
                  busy ||
                  readOnly ||
                  data.read_only ||
                  !ack ||
                  rationale.trim().length < 5 ||
                  !actor.trim() ||
                  (decision === 'approve' && !data.eligible)
                }
              >
                {bulk
                  ? 'Confirm Bulk Review'
                  : decision === 'approve'
                    ? 'Approve & Close'
                    : 'Record Review Decision'}
              </button>
            )}
          </>
        )}
        {error && (
          <p role="alert" className="mw-alert">
            {error}
          </p>
        )}
        {result && (
          <section role="status">
            <h3>Recorded review results</h3>
            <p>
              {result.approved} approved · {result.rejected} rejected · {result.excluded} excluded ·{' '}
              {result.failed} failed.
            </p>
            <details>
              <summary>Per-item review outcomes</summary>
              {result.per_item.map((r) => (
                <p key={r.id}>
                  {r.id} · {r.outcome} {r.reason}
                </p>
              ))}
            </details>
          </section>
        )}
        <button type="button" disabled={busy} onClick={onClose}>
          {result ? 'Done' : 'Cancel Review'}
        </button>
      </form>
    </dialog>
  );
}
