// Shapes returned by dashboard/app.py. Keep in sync with tests/test_dashboard.py::test_*_contract.

export type Classification =
  | 'code_defect'
  | 'config_regression'
  | 'dependency'
  | 'resource'
  | 'insufficient_evidence';

export type IncidentStatus =
  | 'VERIFIED'
  | 'PROPOSED'
  | 'PR_OPENED'
  | 'AWAITING_CHOICE'
  | 'APPLY_MYSELF'
  | 'NEEDS_HUMAN'
  | 'NOTIFIED'
  | 'DUPLICATE_SKIPPED'
  | 'RECORDED'
  | (string & {});

export type IncidentSource = 'fixture' | 'simulated' | 'dynamodb';

export interface EvidenceItem {
  kind: 'log_line' | 'stack_frame' | 'commit' | 'metric' | (string & {});
  ref: string;
  claim: string;
}

export interface SuspectedLocation {
  file: string;
  line: number;
  function?: string | null;
  commit?: string | null;
}

export interface Incident {
  incident_id: string;
  service?: string | null;
  detected_at?: string | null;
  status: IncidentStatus;
  /** null when the source record has no classification */
  classification: Classification | null;
  severity?: 'sev1' | 'sev2' | 'sev3' | 'sev4' | null;
  /** 0..1, null when unknown */
  confidence: number | null;
  summary?: string | null;
  suspected_location?: SuspectedLocation | null;
  evidence?: EvidenceItem[] | null;
  ruled_out?: string[] | null;
  suggested_fix_strategy?: string | null;
  ticket_key?: string | null;
  ticket_url?: string | null;
  pr_branch?: string | null;
  pr_url?: string | null;
  patch_diff?: string | null;
  /** true when Raise PR can open a pull request for this diff */
  can_raise_pr?: boolean;
  source?: IncidentSource;
  /** set when the dashboard ran the RCA agent itself and kept its trace */
  agent_run_id?: string | null;
}

export type SpanKind = 'cycle' | 'model' | 'tool' | 'step';

export interface TraceSpan {
  id: string;
  parent_id: string | null;
  depth: number;
  kind: SpanKind;
  name: string;
  /** offset from the first span, ms */
  start_ms: number | null;
  duration_ms: number | null;
  status: 'ok' | 'error' | 'incomplete' | (string & {});
  policy_status?: string;
  input: string | null;
  output: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  model_latency_ms: number | null;
}

export interface AgentRunSummary {
  run_id: string;
  incident_id: string;
  started_at: string | null;
  duration_ms: number;
  status: 'completed' | 'failed' | 'no_rca_submitted' | (string & {});
  error: string | null;
  model: string | null;
  /** true when the scripted offline model ran: token counts and model latencies are fixed stand-ins */
  offline_model: boolean;
  cycles: number | null;
  tool_calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  policy_violations: number;
  route: string | null;
  classification: Classification | null;
  confidence: number | null;
}

export interface AgentRun extends AgentRunSummary {
  spans: TraceSpan[];
  policy_audit: Record<string, unknown>[];
}

export interface Stats {
  total_incidents: number;
  mean_confidence: number | null;
  total_prs_opened: number;
  verified_prs: number;
  /** null when no fix PRs exist */
  verification_pass_rate: number | null;
  agent_framework: string;
  strands_sdk_version: string | null;
  agentcore_policies_active: string[];
  agentcore_gateway_tools: string[];
}

export interface FixtureEvalDetail {
  id: string;
  name: string;
  gold_classification: string;
  predicted_classification: string;
  gold_route: string;
  predicted_route: string;
  confidence: number;
  tokens: number;
  latency_ms: number;
  location_hit: boolean | null;
  abstention_correct: boolean | null;
  passed: boolean;
}

export interface EvalTargets {
  classification_accuracy: number;
  location_hit_rate: number;
  abstention_precision: number;
  evidence_ref_validity_rate: number;
}

export interface EvalsReport {
  total_fixtures: number;
  passed_fixtures: number;
  classification_correct: number;
  route_correct: number;
  location_hits: number;
  location_total: number;
  abstention_hits: number;
  abstention_total: number;
  classification_accuracy: number;
  route_accuracy: number;
  location_hit_rate: number;
  abstention_precision: number;
  evidence_ref_validity_rate: number;
  mean_tokens: number;
  mean_latency_ms: number;
  targets: EvalTargets;
  all_targets_passed: boolean;
  details: FixtureEvalDetail[];
}

export interface Scenario {
  id: string;
  label: string;
  description: string;
  classification: Classification;
  severity: 'sev1' | 'sev2' | 'sev3' | 'sev4';
  /** true when the scenario sends real requests to sample_service */
  live_probe: boolean;
  expected_outcome: IncidentStatus;
}

export type TicketView = 'open' | 'in_progress' | 'resolved' | 'all';

export type TicketSource = 'opscenter' | 'dashboard';

export interface Ticket {
  key: string;
  title: string;
  status: string;
  severity?: string | null;
  priority?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  incident_id?: string | null;
  url?: string | null;
  source: TicketSource;
  classification?: Classification | null;
  category?: string | null;
}

export interface TicketList {
  view: TicketView;
  opscenter_error?: string | null;
  counts: Record<TicketView, number>;
  tickets: Ticket[];
  recorded: Ticket[];
}

export interface TriggerResponse {
  status: string;
  simulated: boolean;
  scenario?: string;
  live_probe?: boolean;
  ingest_mode: 'live' | 'offline';
  ingest_status: string;
  failed_calls: number;
  incident_id: string;
  summary: string;
  message: string;
  incident: Incident;
}
