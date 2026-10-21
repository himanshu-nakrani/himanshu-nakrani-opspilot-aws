import React, { useEffect, useState } from 'react';
import { AlertOctagon, Loader2, Play, Siren } from 'lucide-react';
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
}

type Phase = 'idle' | 'running' | 'done' | 'error';

export const TriggerSimulationModal: React.FC<TriggerSimulationModalProps> = ({ isOpen, onClose, onSimulationSuccess }) => {
  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<TriggerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>('null_order');

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

  const inc = result?.incident;
  const footer = (
    <>
      <span className="text-xs text-ink-400">Demo only: the RCA shown is a canned example and no real ticket or PR is created.</span>
      <div className="flex gap-2">
        {phase === 'done' && inc ? (
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
            disabled={phase === 'running'}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-red-500/15 hover:bg-red-500/25 text-red-200 border border-red-500/40 disabled:opacity-60 flex items-center gap-1.5"
          >
            {phase === 'running' ? (
              <Loader2 className="w-3.5 h-3.5 motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <Play className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            {phase === 'running' ? 'Running…' : phase === 'error' ? 'Try again' : 'Run simulation'}
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
      description="Pick a failure to inject. The alarm is ingested and a canned RCA is attached."
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
                      <span>{sc.expected_outcome === 'PROPOSED' ? 'opens fix PR' : 'notifies SRE'}</span>
                      {sc.live_probe && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="text-ink-300">live traffic</span>
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
            Calling the sample service and ingesting the alarm…
          </p>
        )}
        {phase === 'error' && (
          <p role="alert" className="flex items-start gap-2 text-sm text-red-200 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
            <AlertOctagon className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
            {error}
          </p>
        )}
        {phase === 'done' && result && inc && (
          <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-xs font-mono bg-ink-950 border border-ink-800 rounded-lg p-4">
            <dt className="text-ink-400">Traffic</dt>
            <dd className="text-ink-200">{result.live_probe === false ? 'Synthetic alarm, no requests sent' : `${result.failed_calls} / 5 requests returned 5xx`}</dd>
            <dt className="text-ink-400">Ingest</dt>
            <dd className="text-ink-200">
              {result.ingest_status} ({result.ingest_mode === 'offline' ? 'offline, no AWS credentials' : 'live'})
            </dd>
            <dt className="text-ink-400">Incident</dt>
            <dd className="text-ink-200 break-all">{result.incident_id}</dd>
            <dt className="text-ink-400">Status</dt>
            <dd className="text-ink-200">{inc.status}</dd>
            <dt className="text-ink-400">Summary</dt>
            <dd className="text-ink-200 font-sans">{result.summary}</dd>
          </dl>
        )}
      </div>
    </Modal>
  );
};
