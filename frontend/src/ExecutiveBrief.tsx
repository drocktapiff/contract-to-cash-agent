import type { ReactNode } from 'react';
type Claim = { text: string; citations: string[] };
export type Brief = Record<
  | 'executive_assessment'
  | 'maya_demonstrated'
  | 'sarah_changed'
  | 'financial_opportunity'
  | 'risks_missing_evidence',
  Claim[]
>;
export default function ExecutiveBrief({
  brief,
  stance,
  recommendations,
  analysis,
  onReference,
  financial,
  scenario,
}: {
  brief: Brief;
  stance?: string;
  recommendations: Claim[];
  analysis: {
    id: string;
    root_run_id: string;
    input_revision: string;
    created_at: string;
    status: string;
    current?: boolean;
    provenance?: { label: string };
  };
  onReference: (ref: string) => void;
  financial: ReactNode;
  scenario: ReactNode;
}) {
  const sections = [
    ['executive_assessment', 'Executive Assessment'],
    ['maya_demonstrated', 'What Maya Demonstrated'],
    ['sarah_changed', 'What Sarah Changed'],
    ['financial_opportunity', 'Financial Opportunity'],
    ['risks_missing_evidence', 'Risks & Missing Evidence'],
  ] as const;
  function claims(items: Claim[]) {
    return items.map((claim, i) => (
      <article key={i}>
        <p>{claim.text}</p>
        <div className="citation-buttons">
          {claim.citations.map((ref, j) => (
            <button className="plain" key={ref} onClick={() => onReference(ref)}>
              Brief evidence {j + 1} ↗
            </button>
          ))}
        </div>
      </article>
    ));
  }
  return (
    <section className="panel executive-brief" aria-label="Executive Decision Brief">
      <span className="eyebrow">GROUNDED EXECUTIVE ADVISOR · ADVISORY ONLY</span>
      <h2>Executive Decision Brief</h2>
      <p className="small muted">
        {analysis.provenance?.label ?? 'Saved analysis — provenance from retained journal'} ·{' '}
        {new Date(analysis.created_at).toLocaleString()} · scenario {analysis.root_run_id}
      </p>
      <details>
        <summary>Analysis source revision and audit identity</summary>
        <p className="break">
          Analysis {analysis.id} · revision {analysis.input_revision} · {analysis.status} ·{' '}
          {analysis.current === false
            ? 'Stale inputs — regenerate before deciding'
            : 'Current source check'}
        </p>
      </details>
      {(analysis.status !== 'completed' || analysis.current === false) && (
        <p className="notice error">
          Historical or incomplete interpretation. No new strategic decision is authorized by this
          brief.
        </p>
      )}
      {sections.map(([key, title]) => (
        <section key={key}>
          <h3>{title}</h3>
          {key === 'financial_opportunity' && (
            <div className="brief-deterministic">
              <strong>Authoritative Python snapshot, not model arithmetic</strong>
              {financial}
              {scenario}
              <p>
                Receivables are not collected cash; credits are not savings. Projections are
                assumptions, not measured returns. Model prose cannot change these amounts.
              </p>
            </div>
          )}
          {claims(brief[key])}
        </section>
      ))}
      <section>
        <h3>AI Recommendation</h3>
        <p className="notice">
          <strong>{stance?.replaceAll('_', ' ')}</strong> · Advisory recommendation, never
          investment approval.
        </p>
        {claims(recommendations)}
      </section>
      <p>
        Executive Decision is recorded separately by the human below. No spending, deployment,
        organizational or export authority is exercised.
      </p>
    </section>
  );
}
