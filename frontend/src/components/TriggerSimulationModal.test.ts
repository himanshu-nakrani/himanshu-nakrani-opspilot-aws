import { describe, expect, it } from 'vitest';
import { BatchRow, runBatch } from './TriggerSimulationModal';
import { Scenario, TriggerResponse } from '../types';

const sc = (id: string): Scenario =>
  ({ id, label: id, description: '', classification: 'code_defect', severity: 'sev2', live_probe: false, expected_outcome: 'NOTIFIED' }) as unknown as Scenario;

describe('runBatch', () => {
  it('runs every scenario in order and keeps going after a failure', async () => {
    const calls: string[] = [];
    const updates: BatchRow[][] = [];
    const rows = await runBatch(
      [sc('a'), sc('b'), sc('c')],
      async (id) => {
        calls.push(id);
        if (id === 'b') throw new Error('boom');
        return { status: 'ok', incident_id: id } as unknown as TriggerResponse;
      },
      (r) => updates.push(r),
    );
    expect(calls).toEqual(['a', 'b', 'c']);
    expect(rows.map((r) => r.state)).toEqual(['ok', 'failed', 'ok']);
    expect(rows[1].error).toContain('boom');
    expect(updates[0].every((r) => r.state === 'pending')).toBe(true);
    expect(updates.some((u) => u[1].state === 'running' && u[0].state === 'ok')).toBe(true);
  });
});
