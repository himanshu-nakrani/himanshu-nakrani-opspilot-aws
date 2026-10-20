import React, { useState } from 'react';
import { triggerSimulation } from '../api';
import { Incident } from '../types';
import { Play, CheckCircle, X, Terminal } from 'lucide-react';

interface TriggerSimulationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSimulationSuccess: (incident: Incident) => void;
}

export const TriggerSimulationModal: React.FC<TriggerSimulationModalProps> = ({
  isOpen,
  onClose,
  onSimulationSuccess,
}) => {
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [result, setResult] = useState<Incident | null>(null);

  if (!isOpen) return null;

  const handleRun = async () => {
    setIsRunning(true);
    setResult(null);
    setLogs([
      '⚡ [1/4] Sending 5 requests to GET /orders/999 on sample-service...',
      '❌ [2/4] AttributeError: \'NoneType\' object has no attribute \'total\' (HTTP 500)',
      '📊 [3/4] Metric Filter matched: Traceback/AttributeError > threshold 5',
      '⏰ [4/4] EventBridge Alarm State Change -> ALARM. Checking DynamoDB 15-min dedup window...',
    ]);

    try {
      const res = await triggerSimulation();
      setLogs((prev) => [
        ...prev,
        `✅ Incident recorded: ${res.incident_id}`,
        `🔍 RCA Analysis: ${res.incident.classification} (${Math.round(res.incident.confidence * 100)}% confidence)`,
        `🎫 Jira ticket: ${res.incident.ticket_key || 'OPS-101'}`,
        `🌿 Fix PR branch: ${res.incident.pr_branch || 'opspilot/OPS-101'}`,
      ]);
      setResult(res.incident);
      onSimulationSuccess(res.incident);
    } catch (e: any) {
      setLogs((prev) => [...prev, `❌ Simulation error: ${e.message}`]);
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center justify-center text-red-400">
              <Play className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">Simulate Production Incident (M1)</h3>
              <p className="text-xs text-slate-400">Trigger planted bug, metric filter, alarm, and full RCA flow</p>
            </div>
          </div>

          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-white rounded-lg transition cursor-pointer">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          <p className="text-xs text-slate-300 leading-relaxed">
            This will dispatch 5 unhandled HTTP 500 requests to <code className="px-1.5 py-0.5 rounded bg-slate-800 text-sky-300 font-mono">GET /orders/999</code> on the sample service, causing the CloudWatch metric filter to fire, transition the alarm to <span className="text-red-400 font-semibold">ALARM</span>, check DynamoDB 15-minute deduplication, run the Strands Agent on Bedrock AgentCore, and propose a fix.
          </p>

          {/* Console / Terminal logs */}
          <div className="bg-slate-950 border border-slate-800/80 rounded-xl p-4 font-mono text-xs space-y-1.5 min-h-[160px] max-h-[220px] overflow-y-auto">
            <div className="text-slate-500 flex items-center gap-1.5 pb-1 border-b border-slate-900">
              <Terminal className="w-3.5 h-3.5 text-slate-400" />
              <span>OpsPilot Execution Terminal</span>
            </div>
            {logs.length === 0 ? (
              <div className="text-slate-600 italic pt-4 text-center">Click "Execute Simulation" below to begin...</div>
            ) : (
              logs.map((log, idx) => (
                <div key={idx} className="text-slate-300 leading-relaxed">
                  {log}
                </div>
              ))
            )}
          </div>

          {result && (
            <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle className="w-5 h-5 text-emerald-400" />
                <div>
                  <span className="text-xs font-bold text-emerald-300">Simulation Finished Successfully</span>
                  <p className="text-[11px] text-emerald-400/80">{result.incident_id} processed by AWS Strands Agent</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200 transition cursor-pointer"
              >
                View in Dashboard
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/60 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 text-xs font-medium rounded-lg text-slate-400 hover:text-white transition cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={handleRun}
            disabled={isRunning}
            className="px-4 py-2 text-xs font-semibold rounded-lg bg-red-600 hover:bg-red-500 text-white transition disabled:opacity-50 flex items-center gap-1.5 cursor-pointer shadow-lg shadow-red-950"
          >
            {isRunning ? (
              <>
                <span className="w-3 h-3 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                <span>Simulating...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Execute Simulation</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
