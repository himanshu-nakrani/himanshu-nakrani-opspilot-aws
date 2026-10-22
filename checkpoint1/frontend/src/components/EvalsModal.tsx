import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertOctagon, CheckCircle2, FlaskConical, Loader2, RotateCcw, XCircle } from 'lucide-react';
import { EvalsReport } from '../types';
import { errorMessage, fetchEvals, isAbortError } from '../api';
import { formatPercent, humanize } from '../lib/format';
import { Modal } from './Modal';
import { ErrorBoundary } from './ErrorBoundary';

interface EvalsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const EvalsModal: React.FC<EvalsModalProps> = ({ isOpen, onClose }) => {
  const [report, setReport] = useState<EvalsReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setIsLoading(true);
    setError(null);
    try {
      setReport(await fetchEvals(controller.signal));
    } catch (e) {
      if (!isAbortError(e)) setError(errorMessage(e, 'Failed to run evals'));
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    if (!report) run();
    return () => controllerRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, run]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      icon={<FlaskConical className="w-5 h-5 text-ink-300 mt-0.5" aria-hidden="true" />}
      title="M6 benchmark evals"
      description="Replays the golden fixtures through the RCA agent and router."
      footer={
        <>
          <span className="text-xs text-ink-400">Results come from the offline scripted model, not a live Bedrock run.</span>
          <button
            type="button"
            onClick={run}
            disabled={isLoading}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-ink-800 hover:bg-ink-700 text-ink-100 border border-ink-700 disabled:opacity-60 flex items-center gap-1.5"
          >
            <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
            Re-run
          </button>
        </>
      }
    >
      <div aria-live="polite">
        {isLoading && (
          <p role="status" className="flex items-center gap-2 text-sm text-ink-300">
            <Loader2 className="w-4 h-4 motion-safe:animate-spin" aria-hidden="true" />
            Running fixtures…
          </p>
        )}
        {error && !isLoading && (
          <p role="alert" className="flex items-start gap-2 text-sm text-red-200 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
            <AlertOctagon className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
            {error}
          </p>
        )}
      </div>
      {report && !isLoading && (
        <ErrorBoundary inline label="Evals report">
          <EvalsReportView report={report} />
        </ErrorBoundary>
      )}
    </Modal>
  );
};

const Metric: React.FC<{ label: string; value: number; target?: number; detail: string }> = ({ label, value, target, detail }) => {
  const met = target === undefined ? null : value >= target;
  return (
    <div className="p-4 rounded-lg bg-ink-950/50 border border-ink-800">
      <h3 className="text-xs uppercase tracking-wider text-ink-300">{label}</h3>
      <p className={`text-2xl font-bold mt-1 ${met === false ? 'text-red-300' : 'text-ink-50'}`}>{formatPercent(round1(value))}</p>
      <p className="text-xs text-ink-400 mt-1">
        {detail}
        {target !== undefined && ` · target ≥ ${target}%`}
      </p>
    </div>
  );
};

const round1 = (n: number) => Math.round(n * 10) / 10;

export const EvalsReportView: React.FC<{ report: EvalsReport }> = ({ report }) => {
  const { targets } = report;
  return (
    <div className="space-y-6">
      <div
        className={`flex flex-wrap items-center gap-3 p-3 rounded-lg border text-sm ${
          report.all_targets_passed
            ? 'bg-ok-500/10 border-ok-500/30 text-ok-300'
            : 'bg-red-500/10 border-red-500/30 text-red-200'
        }`}
      >
        {report.all_targets_passed ? (
          <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
        ) : (
          <XCircle className="w-4 h-4" aria-hidden="true" />
        )}
        <span>
          {report.passed_fixtures} / {report.total_fixtures} fixtures passed ·{' '}
          {report.all_targets_passed ? 'all targets met' : 'one or more targets missed'}
        </span>
        <span className="ml-auto text-xs font-mono">
          mean {Math.round(report.mean_tokens)} tokens · {report.mean_latency_ms.toFixed(1)} ms
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Metric
          label="Classification"
          value={report.classification_accuracy}
          target={targets.classification_accuracy}
          detail={`${report.classification_correct} / ${report.total_fixtures} correct`}
        />
        <Metric
          label="Location hit rate"
          value={report.location_hit_rate}
          target={targets.location_hit_rate}
          detail={report.location_total ? `${report.location_hits} / ${report.location_total} within ±2 lines` : 'no location fixtures'}
        />
        <Metric
          label="Abstention precision"
          value={report.abstention_precision}
          target={targets.abstention_precision}
          detail={report.abstention_total ? `${report.abstention_hits} / ${report.abstention_total} abstained` : 'no abstention fixtures'}
        />
        <Metric
          label="Evidence ref validity"
          value={report.evidence_ref_validity_rate}
          target={targets.evidence_ref_validity_rate}
          detail="cited refs found in bundle"
        />
      </div>

      <div className="overflow-x-auto rounded-lg border border-ink-800">
        <table className="w-full text-xs">
          <caption className="sr-only">Per-fixture results</caption>
          <thead className="bg-ink-900 text-ink-300 text-left">
            <tr>
              <th scope="col" className="p-2.5 font-semibold">Fixture</th>
              <th scope="col" className="p-2.5 font-semibold">Expected</th>
              <th scope="col" className="p-2.5 font-semibold">Predicted</th>
              <th scope="col" className="p-2.5 font-semibold">Route</th>
              <th scope="col" className="p-2.5 font-semibold text-right">Conf.</th>
              <th scope="col" className="p-2.5 font-semibold text-right">Latency</th>
              <th scope="col" className="p-2.5 font-semibold">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-800">
            {report.details.map((d) => (
              <tr key={d.id} className="text-ink-200">
                <th scope="row" className="p-2.5 font-normal text-left">
                  <span className="block">{d.name}</span>
                  <span className="block font-mono text-ink-400">{d.id}</span>
                </th>
                <td className="p-2.5">{humanize(d.gold_classification)}</td>
                <td className={`p-2.5 ${d.predicted_classification === d.gold_classification ? '' : 'text-red-300'}`}>
                  {humanize(d.predicted_classification)}
                </td>
                <td className={`p-2.5 font-mono ${d.predicted_route === d.gold_route ? '' : 'text-red-300'}`}>
                  {d.predicted_route}
                  {d.predicted_route !== d.gold_route && <span className="text-ink-400"> (expected {d.gold_route})</span>}
                </td>
                <td className="p-2.5 text-right font-mono">{Math.round(d.confidence * 100)}%</td>
                <td className="p-2.5 text-right font-mono">{d.latency_ms.toFixed(1)} ms</td>
                <td className="p-2.5">
                  {d.passed ? (
                    <span className="inline-flex items-center gap-1 text-ok-300">
                      <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" /> Pass
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-red-300">
                      <XCircle className="w-3.5 h-3.5" aria-hidden="true" /> Fail
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
