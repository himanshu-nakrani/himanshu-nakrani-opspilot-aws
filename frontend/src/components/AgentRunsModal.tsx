import React, { useEffect, useState } from 'react';
import { Activity, AlertOctagon, ArrowLeft, Loader2 } from 'lucide-react';
import { AgentRunSummary } from '../types';
import { errorMessage, fetchRuns, isAbortError } from '../api';
import { formatTimestamp, humanize } from '../lib/format';
import { focusRing } from '../ui/styles';
import { Modal } from './Modal';
import { AgentTrace, formatMs, RunStatusChip } from './AgentTrace';

interface AgentRunsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/** Every RCA agent run this dashboard recorded, with a drill-down into one run's trace. */
export const AgentRunsModal: React.FC<AgentRunsModalProps> = ({ isOpen, onClose }) => {
  const [runs, setRuns] = useState<AgentRunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<AgentRunSummary | null>(null);
  const maxWall = Math.max(1, ...(runs ?? []).map((r) => r.duration_ms ?? 0));

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    setError(null);
    setSelected(null);
    fetchRuns(controller.signal)
      .then(setRuns)
      .catch((e) => {
        if (!isAbortError(e)) setError(errorMessage(e, 'Failed to load agent runs'));
      });
    return () => controller.abort();
  }, [isOpen]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      variant="drawer"
      size="lg"
      icon={<Activity className="w-4 h-4 text-ink-300" aria-hidden="true" />}
      title={selected ? `Run on ${selected.incident_id}` : 'Agent runs'}
      description={
        selected
          ? `${formatTimestamp(selected.started_at ?? '')} · ${selected.model ?? 'unknown model'}`
          : 'RCA agent sessions recorded by this dashboard, newest first'
      }
    >
      {selected ? (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setSelected(null)}
            className={`inline-flex items-center gap-1.5 text-xs text-ink-300 hover:text-ink-50 rounded-sm ${focusRing}`}
          >
            <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" /> All runs
          </button>
          <AgentTrace runId={selected.run_id} />
        </div>
      ) : error ? (
        <p role="alert" className="flex items-center gap-2 text-sm text-red-300">
          <AlertOctagon className="w-4 h-4" aria-hidden="true" /> {error}
        </p>
      ) : !runs ? (
        <p role="status" className="flex items-center gap-2 text-sm text-ink-400">
          <Loader2 className="w-4 h-4 motion-safe:animate-spin" aria-hidden="true" /> Loading runs…
        </p>
      ) : runs.length === 0 ? (
        <p className="text-sm text-ink-400">
          No agent runs recorded yet. Runs appear when the dashboard runs the RCA agent itself, which it does for the
          replayed fixture incidents.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-2xs text-ink-400">Select a run to open its trace.</p>
          <div className="rounded-lg border border-ink-800 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-ink-950/60 text-2xs uppercase tracking-widest text-ink-400">
                <tr>
                  <th scope="col" className="text-left font-medium px-3 py-2">Incident</th>
                  <th scope="col" className="text-left font-medium px-3 py-2">Status</th>
                  <th scope="col" className="text-left font-medium px-3 py-2">Outcome</th>
                  <th scope="col" className="text-right font-medium px-3 py-2">Cycles</th>
                  <th scope="col" className="text-right font-medium px-3 py-2">Tools</th>
                  <th scope="col" className="text-right font-medium px-3 py-2">Blocks</th>
                  <th scope="col" className="text-right font-medium px-3 py-2">Wall time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-850">
                {runs.map((run) => (
                  <tr
                    key={run.run_id}
                    onClick={() => setSelected(run)}
                    className="cursor-pointer hover:bg-ink-900 transition-colors duration-100"
                  >
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelected(run);
                        }}
                        className={`font-mono text-ink-50 hover:underline underline-offset-2 rounded-sm ${focusRing}`}
                      >
                        {run.incident_id}
                      </button>
                      <div className="text-2xs text-ink-400">{run.classification ? humanize(run.classification) : '—'}</div>
                    </td>
                    <td className="px-3 py-2">
                      <RunStatusChip status={run.status} />
                    </td>
                    <td className="px-3 py-2 text-ink-300">{run.route ? humanize(run.route) : '—'}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-200">{run.cycles ?? '—'}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-200">{run.tool_calls}</td>
                    <td className={`px-3 py-2 text-right font-mono tabular-nums ${run.policy_violations ? 'text-red-300' : 'text-ink-400'}`}>
                      {run.policy_violations}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-2">
                        <span className="hidden sm:block w-16 h-1 rounded-full bg-ink-800 overflow-hidden" aria-hidden="true">
                          <span
                            className={`block h-full rounded-full ${run.policy_violations ? 'bg-red-400/80' : 'bg-signal-400/70'}`}
                            style={{ width: `${Math.max(4, ((run.duration_ms ?? 0) / maxWall) * 100)}%` }}
                          />
                        </span>
                        <span className="font-mono tabular-nums text-ink-200 w-14 text-right">{formatMs(run.duration_ms)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-2xs text-ink-400 leading-relaxed">
            Simulated incidents have no run here: their root cause is scripted by the scenario, so the agent does not run.
            {runs.some((r) => r.offline_model) &&
              ' Runs marked by the offline model did not call Bedrock; their token counts are stand-ins.'}
          </p>
        </div>
      )}
    </Modal>
  );
};
