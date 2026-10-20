import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EvalsModal } from './EvalsModal';
import evals from '../__fixtures__/evals.json';
import type { EvalsReport } from '../types';

// evals.json is a real /api/evals response captured from dashboard/app.py.
const report = evals as EvalsReport;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('EvalsModal', () => {
  it('renders the real /api/evals payload without crashing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(report), { status: 200 }));
    render(<EvalsModal isOpen onClose={() => {}} />);
    await screen.findByText(`${report.passed_fixtures} / ${report.total_fixtures} fixtures passed`, { exact: false });
    expect(screen.getAllByRole('row')).toHaveLength(report.details.length + 1);
    expect(screen.getAllByText('Pass')).toHaveLength(report.details.filter((d) => d.passed).length);
  });

  it('shows an error instead of a blank page when the API fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'boom' }), { status: 500, statusText: 'Internal Server Error' })
    );
    render(<EvalsModal isOpen onClose={() => {}} />);
    expect((await screen.findByRole("alert")).textContent).toContain("boom");
  });

  it('closes on Escape', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(report), { status: 200 }));
    const onClose = vi.fn();
    render(<EvalsModal isOpen onClose={onClose} />);
    expect(screen.getByRole("dialog").getAttribute("aria-modal")).toBe("true");
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
