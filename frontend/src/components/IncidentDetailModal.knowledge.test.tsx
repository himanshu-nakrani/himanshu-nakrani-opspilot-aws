import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { Incident } from '../types';
import { IncidentDetailModal } from './IncidentDetailModal';

afterEach(cleanup);

const incident = {
  incident_id: 'inc-kb-1',
  service: 'sample-service',
  status: 'PR_OPENED',
  classification: 'code_defect',
  confidence: 0.9,
  summary: 'Missing order raises AttributeError',
  pr_url: 'https://codecommit.example/pr/15',
  pr_branch: 'opspilot/OPS-15',
  knowledge: {
    status: 'waiting',
    body: 'Return 404 when the order is missing.',
    error: null,
  },
} as Incident;

describe('reconstructed agent trace', () => {
  it('shows the saved RCA steps when no live session was stored', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(
      <IncidentDetailModal
        incident={{
          incident_id: '59dbcf8b',
          service: 'sample-service',
          status: 'NOTIFIED',
          classification: 'code_defect',
          confidence: 0.98,
          summary: "Unhandled KeyError 'SPRING50' in checkout().",
          evidence: [{ kind: 'log_line', ref: 'log-1', claim: "GET /checkout returned 500." }],
          suggested_fix_strategy: 'Return 400 for an unknown coupon.',
          source: 'dynamodb',
        }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText('Reconstructed from the saved RCA. The live agent session was not stored.')).toBeTruthy();
    expect(screen.getByText(/Model call — code defect, 98%/)).toBeTruthy();
    expect(screen.getByText(/log line log-1/)).toBeTruthy();
    expect(screen.getByText(/Submitted RCA/)).toBeTruthy();
    expect(screen.queryByText('No agent trace was recorded for this incident.')).toBeNull();
    vi.unstubAllGlobals();
  });
});

describe('knowledge base preview', () => {
  it('shows the document that will be ingested on the pull request', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    render(<IncidentDetailModal incident={incident} onClose={() => {}} />);
    expect(screen.getByRole('heading', { name: 'Knowledge base' })).toBeTruthy();
    expect(screen.getByText('Waiting for merge')).toBeTruthy();
    expect(screen.getByText('Return 404 when the order is missing.')).toBeTruthy();
    vi.unstubAllGlobals();
  });
});
