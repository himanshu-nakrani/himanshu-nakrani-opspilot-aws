import React, { useEffect, useState } from 'react';
import { AlertOctagon, Loader2, Play, Siren } from 'lucide-react';
import { Incident, TriggerResponse } from '../types';
import { errorMessage, triggerSimulation } from '../api';
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
      const res = await triggerSimulation();
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
      <span className="text-xs text-slate-400">Demo only: the RCA shown is a canned example and no real ticket or PR is created.</span>
      <div className="flex gap-2">
        {phase === 'done' && inc ? (
          <button
            type="button"
            onClick={() => onSimulationSuccess(inc)}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-200 border border-emerald-500/40"
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
      description="Sends 5 requests to /orders/999 on sample_service and ingests the resulting CloudWatch alarm."
      footer={footer}
    >
      <div aria-live="polite" className="space-y-3">
        {phase === 'idle' && <p className="text-sm text-slate-300">Nothing has been sent yet.</p>}
        {phase === 'running' && (
          <p role="status" className="text-sm text-slate-300">
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
          <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-2 text-xs font-mono bg-slate-950 border border-slate-800 rounded-xl p-4">
            <dt className="text-slate-400">5xx responses</dt>
            <dd className="text-slate-200">{result.failed_calls} / 5</dd>
            <dt className="text-slate-400">Ingest</dt>
            <dd className="text-slate-200">
              {result.ingest_status} ({result.ingest_mode === 'offline' ? 'offline, no AWS credentials' : 'live'})
            </dd>
            <dt className="text-slate-400">Incident</dt>
            <dd className="text-slate-200 break-all">{result.incident_id}</dd>
            <dt className="text-slate-400">Status</dt>
            <dd className="text-slate-200">{inc.status}</dd>
            <dt className="text-slate-400">Summary</dt>
            <dd className="text-slate-200 font-sans">{result.summary}</dd>
          </dl>
        )}
      </div>
    </Modal>
  );
};
