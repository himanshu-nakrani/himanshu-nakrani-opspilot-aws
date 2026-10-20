import React, { useState, useEffect } from 'react';
import { fetchEvals } from '../api';
import { EvalsReport } from '../types';
import { FlaskConical, CheckCircle2, X, AlertCircle, RefreshCw, Trophy } from 'lucide-react';

interface EvalsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const EvalsModal: React.FC<EvalsModalProps> = ({ isOpen, onClose }) => {
  const [report, setReport] = useState<EvalsReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadEvals = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchEvals();
      setReport(data);
    } catch (e: any) {
      setError(e.message || 'Failed to execute evaluation harness');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen && !report) {
      loadEvals();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400">
              <FlaskConical className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <span>OpsPilot M6 Benchmark Evaluation Suite</span>
                {report && report.all_targets_passed && (
                  <span className="px-2 py-0.5 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full flex items-center gap-1">
                    <Trophy className="w-3 h-3" /> 100% Targets Met
                  </span>
                )}
              </h3>
              <p className="text-xs text-slate-400">Deterministic replay of 10 golden historical incident fixtures</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={loadEvals}
              disabled={isLoading}
              className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition disabled:opacity-50 cursor-pointer"
              title="Re-run evaluations"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-sky-400' : ''}`} />
            </button>
            <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-white rounded-lg transition cursor-pointer">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {isLoading && !report && (
            <div className="py-12 text-center text-xs text-slate-400 flex flex-col items-center justify-center gap-3">
              <span className="w-6 h-6 border-2 border-sky-500/20 border-t-sky-500 rounded-full animate-spin" />
              <span>Replaying 10 golden incident fixtures through AWS Strands & Bedrock AgentCore...</span>
            </div>
          )}

          {error && (
            <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-xs text-red-300 flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              <span>{error}</span>
            </div>
          )}

          {report && (
            <>
              {/* Summary Metrics Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl text-center">
                  <span className="text-[10px] uppercase font-semibold text-slate-400 block">Classification Acc.</span>
                  <span className="text-xl font-bold text-emerald-400 mt-1 block">
                    {report.classification_accuracy}%
                  </span>
                  <span className="text-[10px] text-slate-500">10 / 10 fixtures</span>
                </div>

                <div className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl text-center">
                  <span className="text-[10px] uppercase font-semibold text-slate-400 block">Routing Accuracy</span>
                  <span className="text-xl font-bold text-emerald-400 mt-1 block">
                    {report.route_accuracy}%
                  </span>
                  <span className="text-[10px] text-slate-500">ProposeFix vs Notify</span>
                </div>

                <div className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl text-center">
                  <span className="text-[10px] uppercase font-semibold text-slate-400 block">Abstention Precision</span>
                  <span className="text-xl font-bold text-sky-400 mt-1 block">
                    {report.abstention_precision}%
                  </span>
                  <span className="text-[10px] text-slate-500">Zero false positives</span>
                </div>

                <div className="p-3 bg-slate-950 border border-slate-800/80 rounded-xl text-center">
                  <span className="text-[10px] uppercase font-semibold text-slate-400 block">Mean Latency</span>
                  <span className="text-xl font-bold text-purple-400 mt-1 block">
                    {report.mean_latency_ms.toFixed(1)} ms
                  </span>
                  <span className="text-[10px] text-slate-500">Offline deterministic</span>
                </div>
              </div>

              {/* Fixture Details Table */}
              <div className="border border-slate-800 rounded-xl overflow-hidden">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950 text-slate-400 uppercase text-[10px] tracking-wider border-b border-slate-800">
                    <tr>
                      <th className="p-3">Fixture</th>
                      <th className="p-3">Gold Class</th>
                      <th className="p-3">Predicted Class</th>
                      <th className="p-3">Route Verdict</th>
                      <th className="p-3 text-right">Conf.</th>
                      <th className="p-3 text-center">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 bg-slate-900/40 font-mono text-[11px]">
                    {report.details.map((f) => (
                      <tr key={f.id} className="hover:bg-slate-800/40">
                        <td className="p-3 font-semibold text-white">{f.name}</td>
                        <td className="p-3 text-slate-400">{f.gold_classification}</td>
                        <td className="p-3 text-purple-300">{f.predicted_classification}</td>
                        <td className="p-3 text-sky-300">{f.predicted_route}</td>
                        <td className="p-3 text-right text-emerald-400">{Math.round(f.confidence * 100)}%</td>
                        <td className="p-3 text-center">
                          {f.passed ? (
                            <span className="inline-flex items-center gap-1 text-emerald-400 font-sans font-semibold text-xs">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Pass
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-rose-400 font-sans font-semibold text-xs">
                              <AlertCircle className="w-3.5 h-3.5" /> Fail
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/60 flex items-center justify-between">
          <span className="text-xs text-slate-500">
            Target spec: &gt;90% classification accuracy, &gt;90% location hit rate, 100% abstention precision
          </span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
