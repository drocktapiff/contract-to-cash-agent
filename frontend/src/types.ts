export type Session = {
  authenticated: boolean;
  local_passwordless: boolean;
  identity_verified: boolean;
  csrf_token: string | null;
  reviewer: string | null;
  mode: 'operator' | 'recorded';
};
export type Health = {
  status: string;
  mode: 'operator' | 'recorded';
  api_key_configured: boolean;
  operator_configured: boolean;
  dataset_ready: boolean;
  launch_available: boolean;
  message: string;
};
export type Dataset = {
  period: string;
  customer_count: number | null;
  invoice_count: number | null;
  data_revision: string | null;
  message: string;
};
export type Comparison = {
  customer_id: string;
  status: string;
  expected_cad?: string;
  billed_cad?: string;
  difference_cad?: string | null;
  financial_category?: string;
  invoice_amounts_cad?: string[];
};
export type Finding = {
  finding_id: string;
  customer_ids: string[];
  state: string;
  version: number;
  evidence_ids: string[];
  evidence_verified: boolean;
  comparisons?: Comparison[];
  comparison?: Comparison;
  pattern?: {
    shared_pattern_verified: boolean;
    total_difference_cad: string | null;
    root_cause: string;
  };
  model_hypothesis?: string;
  data_revision: string;
  origin: string;
  requires_revalidation?: boolean;
};
export type Decision = {
  reviewer: string;
  decided_at: string;
  rationale?: string;
  decision: string;
  scope: string;
};
export type Review = {
  finding_id: string;
  finding_version: number;
  action: 'review' | 'export';
  status: string;
  data_revision: string;
  decision?: Decision;
};
export type Metrics = {
  cost_accounting_complete?: boolean;
  human_review_requests?: number;
  human_interventions?: number;
  duration_seconds?: number;
  agent_tool_calls?: number;
  api_requests?: number;
  input_tokens?: number;
  output_tokens?: number;
  cached_input_tokens?: number;
  estimated_api_cost_usd?: string;
  usage_priced_cost_usd?: string | null;
  actual_billed_cost_usd?: string | null;
  tool_failures?: number;
};
export type Run = {
  id: string;
  mode: 'live' | 'recorded';
  status: string;
  reason: string;
  created_at: string;
  period: string;
  model: string;
  data_revision: string | null;
  report_event_sequence: number;
  last_event_sequence: number;
  screening_complete: boolean;
  customers_compared: string[];
  customers_with_retrieved_documents: string[];
  findings: Finding[];
  reviews: Review[];
  candidates: Comparison[];
  financial_totals: { additional_receivables_cad?: string; potential_credits_cad?: string };
  metrics: Metrics;
};
export type Activity = {
  sequence: number;
  timestamp: string;
  type: string;
  actor: string;
  summary: string;
  decision?: string | null;
  reviewer?: string | null;
  rationale?: string | null;
  data_revision?: string | null;
  finding_version?: number | null;
  tool?: string | null;
  customer_ids: string[];
  finding_id?: string | null;
};
export type Evidence = {
  redacted?: boolean;
  document_id: string;
  customer_id?: string;
  sha256?: string;
  text?: string;
  kind?: string;
  record?: Record<string, unknown>;
};
