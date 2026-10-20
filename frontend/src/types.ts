export interface EvidenceItem {
  kind: 'log_line' | 'stack_frame' | 'commit' | 'metric';
  ref: string;
  claim: string;
}

export interface SuspectedLocation {
  file: string;
  line: number;
  function?: string;
  commit?: string;
}

export interface Incident {
  incident_id: string;
  service?: string;
  detected_at?: string;
  status: string;
  classification: 'code_defect' | 'config_regression' | 'dependency' | 'resource' | 'insufficient_evidence';
  severity?: 'sev1' | 'sev2' | 'sev3' | 'sev4';
  confidence: number;
  summary?: string;
  suspected_location?: SuspectedLocation;
  evidence?: EvidenceItem[];
  ruled_out?: string[];
  suggested_fix_strategy?: string;
  ticket_key?: string;
  ticket_url?: string;
  pr_branch?: string;
  pr_url?: string;
  patch_diff?: string;
}

export interface Stats {
  total_incidents: number;
  mean_confidence: number;
  total_prs_opened: number;
  verification_pass_rate: number;
  agent_framework?: string;
  agentcore_policies_active?: string[];
  agentcore_gateway_tools?: string[];
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
  passed: boolean;
}

export interface EvalsReport {
  total_fixtures: number;
  classification_accuracy: number;
  route_accuracy: number;
  location_hit_rate: number;
  abstention_precision: number;
  evidence_ref_validity_rate: number;
  mean_tokens: number;
  mean_latency_ms: number;
  all_targets_passed: boolean;
  details: FixtureEvalDetail[];
}

export interface TriggerResponse {
  status: string;
  incident_id: string;
  summary: string;
  incident: Incident;
}
