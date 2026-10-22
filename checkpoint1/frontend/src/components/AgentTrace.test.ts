import { describe, expect, it } from 'vitest';
import { formatMs, spanGeometry, traceExtent } from './AgentTrace';
import { TraceSpan } from '../types';

const span = (start: number | null, dur: number | null): TraceSpan => ({
  id: 'x', parent_id: null, depth: 0, kind: 'tool', name: 't', start_ms: start, duration_ms: dur, status: 'ok',
  input: null, output: null, input_tokens: null, output_tokens: null, model_latency_ms: null,
});

describe('trace waterfall', () => {
  it('measures the trace extent from start + duration', () => {
    expect(traceExtent([span(0, 10), span(40, 20), span(5, 1)])).toBe(60);
  });
  it('positions bars as a share of the trace and keeps tiny spans visible', () => {
    expect(spanGeometry(span(30, 30), 60)).toEqual({ left: 50, width: 50 });
    expect(spanGeometry(span(0, 0), 60).width).toBeGreaterThan(0);
    expect(spanGeometry(span(null, 5), 60)).toEqual({ left: 0, width: 0 });
  });
  it('formats durations', () => {
    expect(formatMs(0.42)).toBe('0.42 ms');
    expect(formatMs(3.25)).toBe('3.3 ms');
    expect(formatMs(250)).toBe('250 ms');
    expect(formatMs(1500)).toBe('1.50 s');
    expect(formatMs(null)).toBe('—');
  });
});
