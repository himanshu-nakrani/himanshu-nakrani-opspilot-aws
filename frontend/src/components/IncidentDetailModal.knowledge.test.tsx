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
