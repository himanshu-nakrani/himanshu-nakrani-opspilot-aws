import React from 'react';
import { Incident } from '../types';
import { X, ExternalLink, GitPullRequest, Ticket, Code2, ShieldAlert, Cpu, Sparkles, CheckCircle2 } from 'lucide-react';

interface IncidentDetailModalProps {
  incident: Incident | null;
  onClose: () => void;
}

export const IncidentDetailModal: React.FC<IncidentDetailModalProps> = ({ incident, onClose }) => {
  if (!incident) return null;

  const confPercent = Math.round((incident.confidence || 0) * 100);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="p-5 border-b border-slate-800 flex items-start justify-between gap-4 bg-slate-900/60">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-1.5">
              <span className="font-mono text-base font-bold text-white">{incident.incident_id}</span>
              <span className="px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider rounded-md bg-purple-500/10 text-purple-300 border border-purple-500/20">
                {incident.classification.replace('_', ' ')}
              </span>
              {incident.severity && (
                <span className="px-2 py-0.5 text-xs font-mono uppercase rounded-md bg-red-500/10 text-red-400 border border-red-500/20">
                  {incident.severity}
                </span>
              )}
              <span className="px-2.5 py-0.5 text-xs font-medium rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                {incident.status}
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Service: <span className="font-mono text-slate-300">{incident.service || 'sample-service'}</span> •
              Detected: <span className="text-slate-300">{incident.detected_at || 'Just now'}</span>
            </p>
          </div>

          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Strands & AgentCore Runtime Banner */}
          <div className="p-3.5 rounded-xl bg-gradient-to-r from-purple-950/30 to-indigo-950/20 border border-purple-500/20 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Cpu className="w-4 h-4 text-purple-400" />
              <div>
                <span className="text-xs font-semibold text-purple-200">AWS Strands Agents SDK + Bedrock AgentCore</span>
                <p className="text-[11px] text-purple-400/80">Multi-turn tool execution with automatic evidence grounding verification</p>
              </div>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-slate-400 block uppercase">Confidence</span>
              <span className="font-mono text-sm font-bold text-emerald-400">{confPercent}%</span>
            </div>
          </div>

          {/* RCA Summary */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
              Root Cause Analysis Summary
            </h3>
            <div className="p-4 bg-slate-950 border border-slate-800/80 rounded-xl text-xs text-slate-200 leading-relaxed font-mono">
              {incident.summary || 'No summary available.'}
            </div>
          </div>

          {/* Suspected Code Location & Fix Strategy */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Code2 className="w-3.5 h-3.5 text-sky-400" />
                Suspected Location
              </h3>
              <div className="p-3.5 bg-slate-950 border border-slate-800/80 rounded-xl text-xs font-mono text-sky-300">
                {incident.suspected_location ? (
                  <div>
                    <div className="font-bold text-white">{incident.suspected_location.file}</div>
                    <div className="text-slate-400 mt-1">Line: <span className="text-sky-400">{incident.suspected_location.line}</span></div>
                    {incident.suspected_location.function && (
                      <div className="text-slate-400">Function: <span className="text-purple-400">{incident.suspected_location.function}()</span></div>
                    )}
                  </div>
                ) : (
                  <span className="text-slate-500 italic">No specific code location pinpointed (abstention route)</span>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                Suggested Fix Strategy
              </h3>
              <div className="p-3.5 bg-slate-950 border border-slate-800/80 rounded-xl text-xs text-slate-300 leading-relaxed">
                {incident.suggested_fix_strategy || 'Gather additional telemetry and consult system logs.'}
              </div>
            </div>
          </div>

          {/* Grounded Evidence Breakdown */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
                Grounded Evidence Breakdown
              </span>
              <span className="text-[10px] text-slate-500 lowercase">
                {incident.evidence?.length || 0} citations validated
              </span>
            </h3>

            <div className="space-y-2">
              {incident.evidence && incident.evidence.length > 0 ? (
                incident.evidence.map((ev, i) => (
                  <div
                    key={i}
                    className="p-3 bg-slate-950/80 border border-slate-800/80 rounded-xl text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                  >
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 font-mono text-[10px] uppercase rounded bg-slate-800 text-slate-300 border border-slate-700">
                        {ev.kind}
                      </span>
                      <span className="font-mono text-emerald-400 text-[11px]">{ev.ref}</span>
                    </div>
                    <span className="text-slate-300 text-xs">{ev.claim}</span>
                  </div>
                ))
              ) : (
                <div className="p-4 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-500 italic">
                  No verified evidence items recorded.
                </div>
              )}
            </div>
          </div>

          {/* Unified Patch Diff Viewer */}
          {incident.patch_diff && (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <GitPullRequest className="w-3.5 h-3.5 text-purple-400" />
                  Proposed Fix Unified Diff
                </span>
                <span className="text-[10px] text-purple-400 font-mono">AgentCore limits: max 3 files / 80 lines</span>
              </h3>
              <div className="bg-slate-950 border border-slate-800 rounded-xl p-4 overflow-x-auto text-[11px] font-mono leading-relaxed">
                {incident.patch_diff.split('\n').map((line, idx) => {
                  let lineClass = 'text-slate-400';
                  if (line.startsWith('+') && !line.startsWith('+++')) {
                    lineClass = 'text-emerald-400 bg-emerald-500/10 px-1 rounded';
                  } else if (line.startsWith('-') && !line.startsWith('---')) {
                    lineClass = 'text-rose-400 bg-rose-500/10 px-1 rounded';
                  } else if (line.startsWith('@@')) {
                    lineClass = 'text-sky-400 font-bold';
                  }
                  return (
                    <div key={idx} className={lineClass}>
                      {line}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer / Action Links */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/60 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {incident.ticket_key && (
              <a
                href={incident.ticket_url || '#'}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-500/10 hover:bg-blue-500/20 text-blue-300 border border-blue-500/30 transition flex items-center gap-1.5"
              >
                <Ticket className="w-3.5 h-3.5" />
                Jira: {incident.ticket_key}
                <ExternalLink className="w-3 h-3 text-blue-400" />
              </a>
            )}

            {incident.pr_branch && (
              <a
                href={incident.pr_url || '#'}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30 transition flex items-center gap-1.5"
              >
                <GitPullRequest className="w-3.5 h-3.5" />
                PR: {incident.pr_branch}
                <ExternalLink className="w-3 h-3 text-purple-400" />
              </a>
            )}
          </div>

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
