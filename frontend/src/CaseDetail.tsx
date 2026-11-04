import { useEffect, useState } from 'react';
import type { Evidence, Finding, Review, Run } from './types';
import { api } from './api';
import { businessTitle, exportAllowed, findingCategory, statusLabel } from './mapping.mjs';

const money = (value: unknown) =>
  value == null
    ? 'Not determined'
    : new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' }).format(Number(value));
export default function CaseDetail({
  run,
  finding,
  review,
  onClose,
  onDecision,
  onExport,
  busy,
  stale,
}: {
  run: Run;
  finding: Finding;
  review?: Review;
  onClose: () => void;
  onDecision: (decision: string, rationale: string) => Promise<void>;
  onExport: () => Promise<void>;
  busy: boolean;
  stale: boolean;
}) {
  const [sources, setSources] = useState<Evidence[]>([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [rationale, setRationale] = useState('');
  const category = findingCategory(finding),
    conflict = category === 'Signed terms conflict',
    duplicate = category === 'Possible duplicate';
  const pending = review?.status === 'pending',
    verified = finding.state === 'verified' && finding.evidence_verified;
  const canDecide =
    finding.state !== 'retracted' &&
    !finding.requires_revalidation &&
    pending &&
    run.mode === 'live' &&
    !['running', 'queued'].includes(run.status) &&
    !stale;
  useEffect(() => {
    let active = true;
    setLoading(true);
    setSources([]);
    api<Evidence[]>(`/runs/${run.id}/findings/${encodeURIComponent(finding.finding_id)}/evidence`)
      .then((data) => {
        if (active) setSources(data);
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [run.id, finding.finding_id, finding.version, finding.data_revision]);
  useEffect(() => {
    const old = document.activeElement as HTMLElement | null;
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key === 'Tab') {
        const controls = [
          ...document.querySelectorAll<HTMLElement>(
            '.case-drawer button:not(:disabled),.case-drawer textarea,.case-drawer summary',
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
    document.querySelector<HTMLElement>('.case-close')?.focus();
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = '';
      old?.focus();
    };
  }, []);
  return (
    <div className="drawer-shade" onClick={onClose}>
      <aside
        className="case-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawer-heading">
          <span className="eyebrow">YOUR REVIEW</span>
          <button className="case-close plain" onClick={onClose} aria-label="Close item">
            Close ×
          </button>
        </div>
        <h2 id="case-title">{businessTitle(finding)}</h2>
        <p className="muted">{finding.customer_ids.join(' · ')}</p>
        <div className="badge-row">
          <span className={'badge ' + finding.state}>{statusLabel(finding.state)}</span>
          {review && <span className={'badge ' + review.status}>{statusLabel(review.status)}</span>}
        </div>
        <section className="judgment-note">
          <h3>
            {conflict
              ? 'Why the agent cannot choose a term'
              : duplicate
                ? 'Why this needs reconciliation'
                : 'What the evidence supports'}
          </h3>
          <p>
            {conflict
              ? 'The recorded signed terms conflict. Choosing one would require human interpretation. No expected charge or billing difference has been selected.'
              : duplicate
                ? 'Multiple invoice records do not establish that multiple charges were collected. The original invoices need reconciliation; their sum is not confirmed duplicate exposure.'
                : verified
                  ? 'The retrieved sources support a calculated billing difference. Your approval authorizes only the requested review or evidence export.'
                  : 'This is a proposed interpretation. It has not completed evidence verification.'}
          </p>
        </section>
        <h3>Agent assessment</h3>
        <p className="assessment">
          {finding.model_hypothesis ??
            'No model recommendation has been submitted. The deterministic conflict check requires clarification of the signed terms.'}
        </p>
        <small className="muted">
          A hypothesis for your judgment, not a legal conclusion or billing instruction.
        </small>
        <h3>Agreed amount and invoice comparison</h3>
        <div className="comparison-list">
          {(finding.comparisons ?? (finding.comparison ? [finding.comparison] : [])).map((row) => (
            <div key={row.customer_id}>
              <strong>{row.customer_id}</strong>
              <dl>
                <dt>Expected from terms</dt>
                <dd>{money(row.expected_cad)}</dd>
                <dt>Recorded invoice</dt>
                <dd>{money(row.billed_cad)}</dd>
                <dt>Calculated difference</dt>
                <dd>{money(row.difference_cad)}</dd>
              </dl>
            </div>
          ))}
        </div>
        <h3>Original supporting records</h3>
        <p className="muted small">
          All retrieved contract and amendment sources are included, including contrary terms.
          Missing source text is never reconstructed.
        </p>
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        {loading ? (
          <p role="status">Retrieving the saved records…</p>
        ) : sources.length ? (
          sources.map((source) => (
            <details
              className="source"
              key={source.document_id}
              open={conflict && source.kind !== 'invoice'}
            >
              <summary>
                {source.kind === 'invoice' ? 'Invoice record' : 'Contract / amendment'}{' '}
                <span>{source.document_id}</span>
              </summary>
              {source.text ? (
                <p className="source-text">{source.text}</p>
              ) : (
                <dl className="invoice-record">
                  <dt>Invoice</dt>
                  <dd>{String(source.record?.invoice_id ?? source.document_id)}</dd>
                  <dt>Billing period</dt>
                  <dd>{String(source.record?.period ?? 'Not recorded')}</dd>
                  <dt>Billed amount</dt>
                  <dd>{money(source.record?.billed_amount)}</dd>
                  <dt>Recorded quantity</dt>
                  <dd>{String(source.record?.usage_quantity ?? 'Not recorded')}</dd>
                </dl>
              )}
              {source.redacted && (
                <p className="small muted">
                  Sanitized recording. The displayed source may include redactions.
                </p>
              )}
            </details>
          ))
        ) : (
          <p className="notice">
            No original source text was retrieved for this item. Citation IDs alone are not evidence
            verification.
          </p>
        )}
        <section className="decision-section">
          <h3>Your decision</h3>
          <p className="muted">
            {review?.action === 'export'
              ? 'This request can authorize an evidence package only.'
              : 'This request is for review only. It cannot authorize an export or a financial correction.'}{' '}
            Pending review is not approval.
          </p>
          {stale && (
            <p className="notice error">
              These source records changed. A new investigation is required before a decision or
              export.
            </p>
          )}
          {canDecide ? (
            <>
              <label>
                Decision rationale
                <textarea
                  value={rationale}
                  onChange={(event) => setRationale(event.target.value)}
                  minLength={5}
                  maxLength={1000}
                  placeholder="What did you conclude from the original records?"
                />
              </label>
              <div className="decision-actions">
                {verified && (
                  <button
                    className="primary"
                    disabled={busy || rationale.trim().length < 5}
                    onClick={() => void onDecision('approved', rationale)}
                  >
                    {review?.action === 'export'
                      ? 'Approve evidence export'
                      : 'Approve review only'}
                  </button>
                )}
                <button
                  className="secondary"
                  disabled={busy || rationale.trim().length < 5}
                  onClick={() => void onDecision('needs_information', rationale)}
                >
                  Request clarification
                </button>
                <button
                  className="danger"
                  disabled={busy || rationale.trim().length < 5}
                  onClick={() => void onDecision('rejected', rationale)}
                >
                  Reject hypothesis
                </button>
              </div>
              <p className="small muted">
                Clarification is saved for this version. It does not choose a contract term or
                resume the agent. Updated records require a new review.
              </p>
            </>
          ) : (
            <p className="small muted">
              {run.mode === 'recorded'
                ? 'Recorded investigation — decisions are read-only.'
                : review?.status === 'pending'
                  ? 'Decisions are available after the review settles.'
                  : review
                    ? 'The decision for this version has been recorded.'
                    : 'The agent has not requested a supported decision for this item.'}
            </p>
          )}
          {review?.decision && (
            <div className="decision-record">
              <strong>{statusLabel(review.decision.decision)}</strong>
              <p>
                {review.decision.rationale ??
                  'No rationale was captured by this historical version.'}
              </p>
              <small>
                {review.decision.reviewer} · {new Date(review.decision.decided_at).toLocaleString()}
              </small>
            </div>
          )}
          {exportAllowed(run, finding, review) && !stale && (
            <button className="secondary" onClick={() => void onExport()} disabled={busy}>
              Download approved evidence package
            </button>
          )}
        </section>
        <details className="technical">
          <summary>View Technical Details</summary>
          <p>
            Finding: {finding.finding_id} · Version {finding.version}
          </p>
          <p>Evidence verification: {finding.evidence_verified ? 'checked' : 'not complete'}</p>
          <p className="break">Revision: {finding.data_revision}</p>
          <p>Citations: {finding.evidence_ids.join(', ')}</p>
          {sources.map(
            (source) =>
              source.sha256 && (
                <p className="break" key={source.document_id}>
                  {source.document_id} ·{' '}
                  {source.redacted ? 'Original hash before redaction' : 'SHA-256'}: {source.sha256}
                </p>
              ),
          )}
          <p>
            Report event {run.report_event_sequence} / journal event {run.last_event_sequence}
          </p>
        </details>
      </aside>
    </div>
  );
}
