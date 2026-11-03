// UI presentation only. Authoritative money and finding validation stay in Python.
export const isActive = (status) => status === 'queued' || status === 'running';
export function statusLabel(status) {
  return (
    {
      completed: 'Completed',
      incomplete: 'Incomplete',
      running: 'Investigating',
      queued: 'Queued',
      failed: 'Failed',
      interrupted: 'Interrupted',
      verified: 'Verified',
      proposed: 'Proposed',
      retracted: 'Retracted',
      pending: 'Pending review',
      approved: 'Approved',
      rejected: 'Rejected',
      needs_information: 'Clarification requested',
      invalidated: 'Revision invalidated',
    }[status] ?? status
  );
}
export function findingCategory(f) {
  const rows = f.comparisons ?? (f.comparison ? [f.comparison] : []);
  if (rows.some((r) => r.status === 'conflict')) return 'Signed terms conflict';
  if (rows.some((r) => r.status === 'duplicate_invoice')) return 'Possible duplicate';
  if (rows.some((r) => r.status === 'missing_invoice')) return 'Missing invoice';
  if (f.pattern?.shared_pattern_verified) return 'Shared pricing pattern';
  return rows[0]?.financial_category === 'potential_credit'
    ? 'Potential customer credit'
    : rows[0]?.financial_category === 'additional_receivable'
      ? 'Potential receivable'
      : 'Requires investigation';
}
export function findingAmount(f) {
  if (f.state !== 'verified' || !f.evidence_verified) return null;
  if (f.pattern?.shared_pattern_verified) return f.pattern.total_difference_cad;
  return (f.comparisons ?? [f.comparison])[0]?.difference_cad ?? null;
}
export function exportAllowed(run, f, review) {
  return (
    run.mode === 'live' &&
    !isActive(run.status) &&
    f.state === 'verified' &&
    f.evidence_verified &&
    !f.requires_revalidation &&
    review?.status === 'approved' &&
    review.action === 'export' &&
    review.finding_version === f.version &&
    review.data_revision === f.data_revision &&
    run.data_revision === f.data_revision
  );
}
export function mergeEvents(previous, incoming) {
  const byId = new Map(previous.map((e) => [e.sequence, e]));
  for (const e of incoming) byId.set(e.sequence, e);
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence);
}
export function stageFor(type) {
  if (type === 'screening.completed') return 'Screen';
  if (type === 'evidence.retrieved' || type === 'evidence.updated') return 'Evidence';
  if (type.startsWith('finding.')) return 'Findings';
  if (type.startsWith('human_review.')) return 'Review';
  return 'Investigation';
}
