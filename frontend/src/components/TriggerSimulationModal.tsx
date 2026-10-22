import React, { useEffect, useState } from 'react';
import { AlertOctagon, Layers, Loader2, Play, Siren } from 'lucide-react';
import { Incident, Scenario, TriggerResponse } from '../types';
import { errorMessage, fetchScenarios, triggerSimulation } from '../api';
import { severityBadge } from '../lib/badges';
import { humanize } from '../lib/format';
import { chip } from '../ui/styles';
import { Modal } from './Modal';

interface TriggerSimulationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSimulationSuccess: (incident: Incident) => void;
  /** Called once a "Simulate all" batch finishes, with every incident it produced. */
  onBatchComplete?: (incidents: Incident[]) => void;
}

type Phase = 'idle' | 'running' | 'done' | 'error' | 'batch';

export interface BatchRow {
  scenario: Scenario;
  state: 'pending' | 'running' | 'ok' | 'failed';
  result?: TriggerResponse;
  error?: string;
}

/** Runs every scenario one after another so ingest and the incident store see them in order. */
export async function runBatch(
  scenarios: Scenario[],
  trigger: (id: string) => Promise<TriggerResponse>,
  onUpdate: (rows: BatchRow[]) => void,
): Promise<BatchRow[]> {
  const rows: BatchRow[] = scenarios.map((scenario) => ({ scenario, state: 'pending' }));
  onUpdate([...rows]);
  for (let i = 0; i < rows.length; i++) {
    rows[i] = { ...rows[i], state: 'running' };
    onUpdate([...rows]);
    try {
      const result = await trigger(rows[i].scenario.id);
      rows[i] = { ...rows[i], state: 'ok', result };
    } catch (e) {
      rows[i] = { ...rows[i], state: 'failed', error: errorMessage(e, 'Simulation failed') };
    }
    onUpdate([...rows]);
  }
  return rows;
}

export const TriggerSimulationModal: React.FC<TriggerSimulationModalProps> = ({ isOpen, onClose, onSimulationSuccess, onBatchComplete }) => {
  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<TriggerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>('null_order');
  const [batch, setBatch] = useState<BatchRow[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);

  useEffect(() => {
    if (!isOpen || scenarios.length) return;
    const ctrl = new AbortController();
    fetchScenarios(ctrl.signal)
      .then((list) => {
        setScenarios(list);
        if (list.length && !list.some((x) => x.id === selected)) setSelected(list[0].id);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setScenarioError(errorMessage(e, 'Could not load scenarios'));
      });
    return () => ctrl.abort();
  }, [isOpen, scenarios.length, selected]);

  useEffect(() => {
    if (isOpen) {
      setPhase('idle');
      setResult(null);
      setError(null);
      setBatch([]);
    }
  }, [isOpen]);

  const run = async () => {
    setPhase('running');
    setError(null);
    try {
      const res = await triggerSimulation(selected);
      setResult(res);
      setPhase('done');
    } catch (e) {
      setError(errorMessage(e, 'Simulation failed'));
      setPhase('error');
    }
  };

  const runAll = async () => {
    if (!scenarios.length) return;
    setPhase('batch');
    setError(null);
    setBatchRunning(true);
    const rows = await runBatch(scenarios, (id) => triggerSimulation(id), setBatch);
    setBatchRunning(false);
    const made = rows.flatMap((r) => (r.result?.incident ? [r.result.incident] : []));
    if (made.length) onBatchComplete?.(made);
  };

  const batchDone = batch.filter((r) => r.state === 'ok' || r.state === 'failed').length;
  const batchFailed = batch.filter((r) => r.state === 'failed').length;
  const busy = phase === 'running' || batchRunning;

  const inc = result?.incident;
  const footer = (
    <>
      <span className="text-xs text-ink-400">The incident appears here after EventBridge starts the pipeline.</span>
      <div className="flex gap-2">
        {(phase === 'idle' || phase === 'error') && (
          <button
            type="button"
            onClick={runAll}
            disabled={busy || !scenarios.length}
            title={scenarios.length ? `Run all ${scenarios.length} scenarios in sequence` : 'Scenarios are still loading'}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-ink-900 hover:bg-ink-850 text-ink-100 border border-ink-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            <Layers className="w-3.5 h-3.5" aria-hidden="true" />
            Simulate all{scenarios.length ? ` (${scenarios.length})` : ''}
          </button>
        )}
        {phase === 'batch' ? (
          <button
            type="button"
            onClick={onClose}
            disabled={batchRunning}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-signal-500/15 hover:bg-signal-500/25 text-signal-200 border border-signal-500/40 disabled:opacity-60 flex items-center gap-1.5"
          >
            {batchRunning && <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />}
            {batchRunning ? `Running ${Math.min(batchDone + 1, batch.length)} / ${batch.length}…` : 'Done'}
          </button>
        ) : phase === 'done' && inc ? (
          <button
            type="button"
            onClick={() => onSimulationSuccess(inc)}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-signal-500/15 hover:bg-signal-500/25 text-signal-200 border border-signal-500/40"
          >
            View incident
          </button>
        ) : (
          <button
            type="button"
            onClick={run}
            disabled={busy}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-red-500/15 hover:bg-red-500/25 text-red-200 border border-red-500/40 disabled:opacity-60 flex items-center gap-1.5"
          >
            {phase === 'running' ? (
              <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <Play className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            {phase === 'running' ? 'Running…' : phase === 'error' ? 'Try again' : phase === 'done' ? 'Run again' : 'Run simulation'}
          </button>
        )}
      </div>
    </>
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="md"
      icon={<Siren className="w-5 h-5 text-red-400 mt-0.5" aria-hidden="true" />}
      title="Simulate incident"
      description="Pick a failure. The sample service writes it to CloudWatch, and EventBridge starts the pipeline."
      footer={footer}
    >
      <div aria-live="polite" className="space-y-3">
        {(phase === 'idle' || phase === 'error') && (
          <fieldset>
            <legend className="sr-only">Scenario</legend>
            {scenarioError && <p className="text-xs text-ink-400 mb-2">{scenarioError}. The default scenario will run.</p>}
            <div className="grid gap-1.5 sm:grid-cols-2 max-h-[46vh] overflow-y-auto pr-1">
              {scenarios.map((sc) => {
                const on = sc.id === selected;
                return (
                  <label
                    key={sc.id}
                    className={`relative flex flex-col gap-1 rounded-md border px-3 py-2.5 cursor-pointer transition-colors duration-100 has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-signal-400 ${
                      on ? 'border-ink-400 bg-ink-850' : 'border-ink-800 hover:border-ink-700 hover:bg-ink-900'
                    }`}
                  >
                    <input type="radio" name="scenario" value={sc.id} checked={on} onChange={() => setSelected(sc.id)} className="sr-only" />
                    <span className="flex items-center gap-2">
                      <span className={`${chip} uppercase font-mono tracking-wide ${severityBadge(sc.severity)}`}>{sc.severity}</span>
                      <span className="text-[13px] text-ink-50 truncate">{sc.label}</span>
                    </span>
                    <span className="text-2xs leading-snug text-ink-400">{sc.description}</span>
                    <span className="flex items-center gap-1.5 font-mono text-2xs text-ink-500">
                      <span className="capitalize">{humanize(sc.classification)}</span>
                      <span aria-hidden="true">·</span>
                      <span className="text-ink-300">live service</span>
                      {sc.alarm_name && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="truncate">{sc.alarm_name}</span>
                        </>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          </fieldset>
        )}
        {phase === 'running' && (
          <p role="status" className="text-sm text-ink-300">
            Calling the sample service so CloudWatch can raise the alarm…
          </p>
        )}
        {phase === 'error' && (
          <p role="alert" className="flex items-start gap-2 text-sm text-red-200 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
            <AlertOctagon className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
            {error}
          </p>
        )}
        {phase === 'batch' && (
          <div className="space-y-2">
            <p role="status" className="text-xs text-ink-300 font-mono">
              {batchRunning
                ? `Simulating ${batchDone} of ${batch.length} done…`
                : `${batch.length - batchFailed} of ${batch.length} scenarios simulated${batchFailed ? `, ${batchFailed} failed` : ''}.`}
            </p>
            <div className="h-1 rounded-full bg-ink-850 overflow-hidden" aria-hidden="true">
              <div className="h-full bg-ink-300 transition-[width] duration-200" style={{ width: `${batch.length ? (batchDone / batch.length) * 100 : 0}%` }} />
            </div>
            <ul className="divide-y divide-ink-800 border border-ink-800 rounded-lg max-h-[46vh] overflow-y-auto">
              {batch.map((row) => {
                const ri = row.result?.incident;
                return (
                  <li key={row.scenario.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                    <span className={`${chip} uppercase font-mono tracking-wide ${severityBadge(row.scenario.severity)}`}>{row.scenario.severity}</span>
                    <span className="text-ink-100 truncate flex-1">{row.scenario.label}</span>
                    <span className="font-mono text-2xs text-ink-400 shrink-0">
                      {row.state === 'pending' && 'queued'}
                      {row.state === 'running' && (
                        <span className="inline-flex items-center gap-1 text-ink-200">
                          <Loader2 className="w-3 h-3 motion-safe:animate-spin" aria-hidden="true" />
                          running
                        </span>
                      )}
                      {row.state === 'failed' && <span className="text-red-300" title={row.error}>failed</span>}
                      {row.state === 'ok' && (ri ? ri.status : 'sent')}
                    </span>
                    {row.state === 'ok' && ri && !batchRunning && (
                      <button
                        type="button"
                        onClick={() => onSimulationSuccess(ri)}
                        className="shrink-0 text-2xs font-semibold text-signal-300 hover:text-signal-200 underline-offset-2 hover:underline"
                      >
                        View
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {phase === 'done' && result && (
          <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-xs font-mono bg-ink-950 border border-ink-800 rounded-lg p-4">
            <dt className="text-ink-400">Request</dt>
            <dd className="text-ink-200 break-all">{result.probe || 'sample service'}</dd>
            <dt className="text-ink-400">Alarm</dt>
            <dd className="text-ink-200 break-all">{result.alarm_name || 'CloudWatch'}</dd>
            <dt className="text-ink-400">Service</dt>
            <dd className="text-ink-200">{result.http_status ?? 'no HTTP status'}</dd>
            <dt className="text-ink-400">Next</dt>
            <dd className="text-ink-200 font-sans">{result.message}</dd>
            {inc && (
              <>
                <dt className="text-ink-400">Incident</dt>
                <dd className="text-ink-200 break-all">{inc.incident_id}</dd>
              </>
            )}
          </dl>
        )}
      </div>
    </Modal>
  );
};
