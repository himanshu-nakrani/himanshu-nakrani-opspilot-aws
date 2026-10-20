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
  source?: IncidentSource;
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

export interface TriggerResponse {
  status: string;
  simulated: boolean;
  ingest_mode: 'live' | 'offline';
  ingest_status: string;
  failed_calls: number;
  incident_id: string;
  summary: string;
  message: string;
  incident: Incident;
}
