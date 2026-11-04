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

// Business copy is a projection of real event types/tool selections, never a timer.
export function businessActivity(event) {
  const tool = event.tool;
  if (event.type === 'tool.requested') {
    return (
      {
        screen_customers: 'Checking customer invoices across the billing period.',
        list_customers: 'Identifying the customer accounts to review.',
        get_contract: 'Reviewing contractual terms.',
        get_customer_evidence: 'Reviewing agreements and supporting billing records.',
        get_document: 'Reading an original contract or amendment.',
        get_amendments: 'Comparing contract amendments.',
        get_invoices: 'Checking customer invoices.',
        calculate_expected: 'Calculating charges from the agreed terms.',
        compare_invoices: 'Investigating a possible billing difference.',
        summarize_pattern: 'Looking for pricing patterns across customers.',
        submit_finding: 'Preparing a finding for review.',
        request_human_review: 'Preparing an item for your judgment.',
        recommend_next_action: 'Preparing an evidence-grounded suggested next step.',
      }[tool] ?? null
    );
  }
  return (
    {
      'investigation.started': 'Your billing review has started.',
      'screening.completed': 'Structured invoice screening has finished.',
      'evidence.retrieved': 'Supporting records have been retrieved.',
      'evidence.updated': 'Source records changed. Earlier conclusions need to be checked again.',
      'finding.proposed': 'An item needs further judgment before it can be verified.',
      'finding.verified': 'A finding is supported by the retrieved evidence.',
      'finding.retracted': 'An earlier finding has been withdrawn.',
      'human_review.requested': 'An item is ready for a human decision.',
      'human_review.decided': 'Your review decision has been saved.',
      'human_resolution.resolve':
        'Your documented resolution has been saved. Continuation still needs authorization.',
      'human_resolution.escalate':
        'Your clarification request has been saved. The dependent work is waiting.',
      'human_resolution.dismiss':
        'Your dismissal has been saved. The original evidence is retained.',
      'continuation.authorized': 'You authorized a separate investigation of the affected case.',
      'guidance.prepared':
        'An evidence-based procedural next step has been saved. No model request was made.',
      'recommendation.created': 'The agent saved a suggested next step for your judgment.',
      'tool.failed': 'A check could not finish. Affected conclusions remain unverified.',
      'api.failed': 'The investigation service could not complete a request.',
      'investigation.error': 'The review was interrupted. Saved work is retained.',
    }[event.type] ??
    (event.type === 'investigation.completed'
      ? 'The review has stopped. Saved findings are available.'
      : null)
  );
}
export function businessTitle(finding) {
  if (finding.state === 'retracted') return 'An earlier billing finding was withdrawn';
  const category = findingCategory(finding);
  return (
    {
      'Signed terms conflict': 'Signed amendments disagree',
      'Possible duplicate': 'Invoice records need reconciliation',
      'Missing invoice': 'An expected invoice is missing',
      'Shared pricing pattern': 'Several customers share a pricing discrepancy',
      'Potential customer credit': 'A customer may have been overcharged',
      'Potential receivable': 'Billing may be below the agreed amount',
    }[category] ?? 'A billing item needs further investigation'
  );
}
export function needsAttention(finding, reviews, interventions = []) {
  if (finding.state === 'retracted') return false;
  const human = interventions.filter((r) => r.finding_id === finding.finding_id).at(-1);
  if (human) return human.action !== 'dismiss';
  const review = reviews.find((r) => r.finding_id === finding.finding_id);
  return (
    finding.state !== 'retracted' &&
    (review?.status === 'pending' || (finding.state === 'proposed' && !review))
  );
}
export function stopExplanation(run) {
  if (run.status === 'completed')
    return 'The review finished. Evidence-backed findings and decisions are saved.';
  if (run.status === 'running' || run.status === 'queued')
    return 'The agent is investigating. You retain every review and export decision.';
  return (
    {
      tool_call_limit:
        'The review reached its allowed work limit. Completed findings are saved; some work may remain.',
      time_limit:
        'The review reached its time limit. Completed findings are saved; some work may remain.',
      estimated_cost_limit:
        'The review reached its estimated spending limit. Completed findings are saved.',
      api_failure:
        'The investigation service could not finish. Retained findings remain available for review.',
      server_restart_no_resume:
        'The server stopped during this review. Work is retained; it has not restarted automatically.',
    }[run.reason] ??
    'This review did not finish all required work. Saved findings remain available; completion is not implied.'
  );
}

export function businessTimeline(events) {
  const result = [];
  for (const event of events) {
    const text = businessActivity(event);
    if (!text) continue;
    if (result.at(-1)?.text === text) result[result.length - 1] = { event, text };
    else result.push({ event, text });
  }
  return result;
}

export function humanActionLabel(action) {
  return (
    { resolve: 'Resolution documented', escalate: 'Awaiting clarification', dismiss: 'Dismissed' }[
      action
    ] ?? null
  );
}
