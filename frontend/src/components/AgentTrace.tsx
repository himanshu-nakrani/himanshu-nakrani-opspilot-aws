import React, { useEffect, useMemo, useState } from 'react';
import { AlertOctagon, Bot, ChevronRight, CornerDownRight, Loader2, Repeat, Wrench } from 'lucide-react';
import { AgentRun, SpanKind, TraceSpan } from '../types';
import { errorMessage, fetchRun, isAbortError } from '../api';
import { humanize } from '../lib/format';
import { chip, focusRing } from '../ui/styles';

/** Duration with a unit that suits its size. */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—';
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

/** Waterfall geometry: left offset and width as % of the whole trace. */
export function spanGeometry(span: TraceSpan, totalMs: number): { left: number; width: number } {
  if (!totalMs || span.start_ms === null) return { left: 0, width: 0 };
  const left = Math.min(100, Math.max(0, (span.start_ms / totalMs) * 100));
  const width = Math.max(0.6, Math.min(100 - left, ((span.duration_ms ?? 0) / totalMs) * 100));
  return { left, width };
}

export function traceExtent(spans: TraceSpan[]): number {
  return spans.reduce((max, s) => Math.max(max, (s.start_ms ?? 0) + (s.duration_ms ?? 0)), 0);
}

const KIND_ICON: Record<SpanKind, React.FC<{ className?: string }>> = {
  cycle: Repeat,
  model: Bot,
  tool: Wrench,
  step: CornerDownRight,
};

const KIND_BAR: Record<SpanKind, string> = {
  cycle: 'bg-ink-600',
  model: 'bg-signal-500',
  tool: 'bg-ink-200',
  step: 'bg-ink-700',
};

function spanLabel(span: TraceSpan): string {
  if (span.kind === 'step' && span.name === 'Recursive call') return 'Next cycle';
  return span.name;
}

export const RunStatusChip: React.FC<{ status: string }> = ({ status }) => {
  const cls =
    status === 'completed'
      ? 'text-ok-300 border-ok-500/30 bg-ok-500/10'
      : status === 'failed'
        ? 'text-red-300 border-red-500/30 bg-red-500/10'
        : 'text-amber-300 border-amber-500/30 bg-amber-500/10';
  return <span className={`${chip} ${cls}`}>{status === 'no_rca_submitted' ? 'No RCA submitted' : humanize(status)}</span>;
};

export const OfflineNote: React.FC = () => (
  <p className="text-2xs text-ink-400 leading-relaxed">
    Ran on the offline scripted model, not Bedrock. Span timings are measured; token counts and model latencies are fixed
    stand-ins from that model.
  </p>
);

interface AgentTraceProps {
  runId: string;
  /** compact hides the run header (used inside the incident view) */
  compact?: boolean;
}

/** Loads one agent run and renders its span waterfall with an inspector for the selected span. */
export const AgentTrace: React.FC<AgentTraceProps> = ({ runId, compact = false }) => {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setRun(null);
    setError(null);
    setSelected(null);
    fetchRun(runId, controller.signal)
      .then((r) => {
        setRun(r);
        // Open on the first tool call: that is usually what people come to look at.
        setSelected(r.spans.find((s) => s.kind === 'tool')?.id ?? r.spans[0]?.id ?? null);
      })
      .catch((e) => {
        if (!isAbortError(e)) setError(errorMessage(e));
      });
    return () => controller.abort();
  }, [runId]);

  const total = useMemo(() => (run ? traceExtent(run.spans) : 0), [run]);

  if (error) {
    return (
      <p role="alert" className="flex items-center gap-2 text-xs text-red-300">
        <AlertOctagon className="w-3.5 h-3.5" aria-hidden="true" /> {error}
      </p>
    );
  }
  if (!run) {
    return (
      <p className="flex items-center gap-2 text-xs text-ink-400" role="status">
        <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" /> Loading trace…
      </p>
    );
  }

  const active = run.spans.find((s) => s.id === selected) ?? null;

  return (
    <div className="space-y-3">
      {!compact && <RunMetrics run={run} />}

      <div className="rounded-lg border border-ink-800 overflow-hidden">
        <div className="grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)_4.5rem] gap-3 px-3 py-1.5 bg-ink-950/60 border-b border-ink-800 text-2xs uppercase tracking-[0.1em] text-ink-400">
          <span>Span</span>
          <span className="flex justify-between font-mono normal-case tracking-normal">
            <span>0</span>
            <span>{formatMs(total)}</span>
          </span>
          <span className="text-right">Duration</span>
        </div>
        <ol role="listbox" aria-label="Trace spans" className="divide-y divide-ink-850">
          {run.spans.map((span) => {
            const Icon = KIND_ICON[span.kind] ?? CornerDownRight;
            const { left, width } = spanGeometry(span, total);
            const isActive = span.id === selected;
            const failed = span.status === 'error';
            return (
              <li key={span.id} role="option" aria-selected={isActive}>
                <button
                  type="button"
                  onClick={() => setSelected(span.id)}
                  className={`w-full grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)_4.5rem] gap-3 items-center px-3 py-1.5 text-left text-xs transition-colors ${
                    isActive ? 'bg-ink-850' : 'hover:bg-ink-900'
                  } ${focusRing}`}
                >
                  <span className="flex items-center gap-1.5 min-w-0" style={{ paddingLeft: `${span.depth * 14}px` }}>
                    <Icon className={`w-3.5 h-3.5 shrink-0 ${failed ? 'text-red-300' : 'text-ink-400'}`} aria-hidden="true" />
                    <span
                      className={`truncate ${span.kind === 'tool' ? 'font-mono text-ink-100' : span.kind === 'cycle' ? 'text-ink-200 font-medium' : 'text-ink-300'}`}
                    >
                      {spanLabel(span)}
                    </span>
                    {failed && <span className={`${chip} text-red-300 border-red-500/30`}>{span.policy_status ? humanize(span.policy_status) : 'error'}</span>}
                  </span>
                  <span className="relative h-2 rounded-sm bg-ink-900" aria-hidden="true">
                    <span
                      className={`absolute inset-y-0 rounded-sm ${failed ? 'bg-red-400' : KIND_BAR[span.kind] ?? 'bg-ink-600'}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                    />
                  </span>
                  <span className="text-right font-mono tabular-nums text-ink-300">{formatMs(span.duration_ms)}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>

      {active && <SpanInspector span={active} />}
      {run.offline_model && compact && <OfflineNote />}
    </div>
  );
};

export const RunMetrics: React.FC<{ run: AgentRun }> = ({ run }) => {
  const items: [string, string][] = [
    ['Wall time', formatMs(run.duration_ms)],
    ['Cycles', run.cycles === null ? '—' : String(run.cycles)],
    ['Tool calls', String(run.tool_calls)],
    ['Tokens in / out', run.input_tokens === null ? '—' : `${run.input_tokens} / ${run.output_tokens ?? '—'}`],
    ['Policy blocks', String(run.policy_violations)],
  ];
  return (
    <div className="space-y-2">
      <dl className="grid grid-cols-2 sm:grid-cols-5 gap-px rounded-lg overflow-hidden border border-ink-800 bg-ink-800">
        {items.map(([k, v]) => (
          <div key={k} className="bg-ink-900 px-3 py-2">
            <dt className="text-2xs uppercase tracking-[0.1em] text-ink-400">{k}</dt>
            <dd className="mt-0.5 font-mono tabular-nums text-sm text-ink-50">{v}</dd>
          </div>
        ))}
      </dl>
      {run.error && <p className="text-xs text-red-300 font-mono">{run.error}</p>}
      {run.offline_model && <OfflineNote />}
    </div>
  );
};

const SpanInspector: React.FC<{ span: TraceSpan }> = ({ span }) => {
  const facts: [string, string][] = [
    ['Kind', humanize(span.kind)],
    ['Starts at', span.start_ms === null ? '—' : `+${formatMs(span.start_ms)}`],
    ['Duration', formatMs(span.duration_ms)],
  ];
  if (span.kind === 'model') {
    facts.push(['Tokens in / out', span.input_tokens === null ? '—' : `${span.input_tokens} / ${span.output_tokens ?? '—'}`]);
    facts.push(['Model latency', formatMs(span.model_latency_ms)]);
  }
  if (span.policy_status) facts.push(['Gateway', humanize(span.policy_status)]);
  return (
    <section aria-label={`Span ${spanLabel(span)}`} className="rounded-lg border border-ink-800 bg-ink-950/50 p-3 space-y-3">
      <header className="flex items-center gap-1.5 text-xs text-ink-100">
        <ChevronRight className="w-3.5 h-3.5 text-ink-400" aria-hidden="true" />
        <span className={span.kind === 'tool' ? 'font-mono' : ''}>{spanLabel(span)}</span>
      </header>
      <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
        {facts.map(([k, v]) => (
          <div key={k} className="flex gap-1.5">
            <dt className="text-ink-400">{k}</dt>
            <dd className="font-mono tabular-nums text-ink-200">{v}</dd>
          </div>
        ))}
      </dl>
      {span.input && <Payload label={span.kind === 'tool' ? 'Arguments' : 'Input'} body={span.input} />}
      {span.output && <Payload label={span.kind === 'model' ? 'Model output' : span.kind === 'tool' ? 'Result' : 'Output'} body={span.output} />}
      {!span.input && !span.output && <p className="text-2xs text-ink-400">No payload recorded for this span.</p>}
    </section>
  );
};

const Payload: React.FC<{ label: string; body: string }> = ({ label, body }) => (
  <div>
    <div className="text-2xs uppercase tracking-[0.1em] text-ink-400 mb-1">{label}</div>
    <pre className="max-h-56 overflow-auto rounded-md bg-ink-950 border border-ink-850 p-2 text-2xs font-mono text-ink-200 whitespace-pre-wrap break-words">
      {body}
    </pre>
  </div>
);
