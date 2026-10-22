import { Incident, Stats } from '../types';

/** Offline sample data for Checkpoint 1 demos (no backend required). */
export const CHECKPOINT_DEMO_INCIDENTS: Incident[] = [
  {
    incident_id: 'OPS-CP1-001',
    service: 'sample-service',
    detected_at: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    status: 'RECORDED',
    classification: 'code_defect',
    severity: 'sev2',
    confidence: 0.78,
    summary:
      'Unhandled KeyError on missing order_id in checkout handler. Stack frame points to planted sample bug in order lookup.',
    suspected_location: {
      file: 'sample_service/handler.py',
      line: 42,
      function: 'get_order',
      commit: 'a1b2c3d',
    },
    evidence: [
      {
        kind: 'log_line',
        ref: 'log-0142',
        claim: 'KeyError: order_id not found in request payload',
      },
      {
        kind: 'stack_frame',
        ref: 'sample_service/handler.py:42',
        claim: 'Exception raised inside get_order before DynamoDB read',
      },
      {
        kind: 'commit',
        ref: 'a1b2c3d',
        claim: 'Recent deploy introduced stricter order validation',
      },
    ],
    ruled_out: ['config_regression — env vars present in task definition'],
    suggested_fix_strategy: 'Guard missing order_id and return 400 with structured error body.',
    source: 'fixture',
    agent_run_id: 'run-cp1-demo-001',
  },
  {
    incident_id: 'OPS-CP1-002',
    service: 'sample-service',
    detected_at: new Date(Date.now() - 1000 * 60 * 52).toISOString(),
    status: 'NEEDS_HUMAN',
    classification: 'insufficient_evidence',
    severity: 'sev3',
    confidence: 0.41,
    summary:
      'Alarm fired on error rate but log sample is noisy. RCA abstained — ticket route only until grounding improves.',
    evidence: [
      {
        kind: 'log_line',
        ref: 'log-0098',
        claim: 'Elevated 5xx without matching stack trace in window',
      },
    ],
    ruled_out: ['code_defect — no grounded stack frame'],
    suggested_fix_strategy: null,
    ticket_key: 'OI-DRAFT-12',
    source: 'simulated',
  },
  {
    incident_id: 'OPS-CP1-003',
    service: 'sample-service',
    detected_at: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
    status: 'RECORDED',
    classification: 'code_defect',
    severity: 'sev2',
    confidence: 0.66,
    summary: 'Ingest received CloudWatch alarm; context collector attached logs. Strands RCA run queued.',
    suspected_location: {
      file: 'sample_service/handler.py',
      line: 38,
      function: 'handle_checkout',
    },
    evidence: [
      {
        kind: 'metric',
        ref: 'Errors/sample-service',
        claim: 'Metric filter crossed threshold 3 times in 5 minutes',
      },
    ],
    source: 'simulated',
  },
];

export const CHECKPOINT_DEMO_STATS: Stats = {
  total_incidents: CHECKPOINT_DEMO_INCIDENTS.length,
  mean_confidence: 0.62,
  total_prs_opened: 0,
  verified_prs: 0,
  verification_pass_rate: null,
  agent_framework: 'Strands Agents SDK',
  strands_sdk_version: '0.3.x',
  agentcore_policies_active: ['Evidence grounding', 'Abstention on weak refs'],
  agentcore_gateway_tools: ['query_logs', 'get_file'],
};
