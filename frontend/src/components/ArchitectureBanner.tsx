import React from 'react';
import { Radio, Filter, Cpu, GitFork, Ticket, Wrench, ShieldCheck, Bell } from 'lucide-react';

export const ArchitectureBanner: React.FC = () => {
  const steps = [
    { id: '1', title: 'Alarm Trigger', subtitle: 'CloudWatch Logs', icon: Radio, color: 'text-rose-400 bg-rose-500/10 border-rose-500/20' },
    { id: '2', title: 'Dedup Ingest', subtitle: '15-min Window', icon: Filter, color: 'text-amber-400 bg-amber-500/10 border-amber-500/20' },
    { id: '3', title: 'Collect Context', subtitle: 'Logs & Commits', icon: Cpu, color: 'text-sky-400 bg-sky-500/10 border-sky-500/20' },
    { id: '4', title: 'Strands RCA', subtitle: 'AgentCore Runtime', icon: GitFork, color: 'text-purple-400 bg-purple-500/10 border-purple-500/20' },
    { id: '5', title: 'Jira Ticket', subtitle: 'ADF Format', icon: Ticket, color: 'text-blue-400 bg-blue-500/10 border-blue-500/20' },
    { id: '6', title: 'Patch PR', subtitle: 'Limits Guardrail', icon: Wrench, color: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
    { id: '7', title: 'CodeBuild Verify', subtitle: '2-Phase Test', icon: ShieldCheck, color: 'text-teal-400 bg-teal-500/10 border-teal-500/20' },
    { id: '8', title: 'Slack & SNS', subtitle: 'Block Kit Alert', icon: Bell, color: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20' },
  ];

  return (
    <section className="bg-slate-900/30 border border-slate-800/80 rounded-2xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-white uppercase flex items-center gap-2">
            <span>Autonomous SRE Pipeline Architecture</span>
            <span className="px-2 py-0.5 text-[10px] font-normal lowercase tracking-normal bg-slate-800 text-slate-300 rounded border border-slate-700">
              AWS Step Functions Standard Workflow
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            End-to-end telemetry flow from CloudWatch Alarm ingestion to grounded remediation
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {steps.map((step, idx) => {
          const Icon = step.icon;
          return (
            <div
              key={step.id}
              className="relative bg-slate-900/60 border border-slate-800/90 rounded-xl p-3 flex flex-col items-center text-center group hover:border-slate-700 transition"
            >
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center border ${step.color} mb-2`}>
                <Icon className="w-4 h-4" />
              </div>
              <span className="text-xs font-semibold text-slate-200 leading-tight">{step.title}</span>
              <span className="text-[10px] text-slate-400 mt-0.5">{step.subtitle}</span>

              {idx < steps.length - 1 && (
                <div className="hidden lg:block absolute -right-2 top-1/2 -translate-y-1/2 z-10 text-slate-600 pointer-events-none">
                  →
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
};
