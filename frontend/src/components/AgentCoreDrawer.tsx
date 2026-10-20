import React from 'react';
import { X, Shield, Cpu, Database, Terminal, CheckCircle2 } from 'lucide-react';

interface AgentCoreDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AgentCoreDrawer: React.FC<AgentCoreDrawerProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-slate-950/60 backdrop-blur-sm animate-fade-in flex justify-end">
      <div className="w-full max-w-md bg-slate-900 border-l border-slate-800 h-full flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-900/80">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white">AWS Strands & Bedrock AgentCore</h3>
              <p className="text-[11px] text-purple-400/80">Agentic Architecture Inspector</p>
            </div>
          </div>

          <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-white rounded-lg transition cursor-pointer">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto space-y-6 flex-1 text-xs">
          {/* Strands SDK Overview */}
          <div className="space-y-2">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5 text-purple-400" />
              AWS Strands Agents SDK (strands-agents)
            </h4>
            <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2 text-slate-300 font-mono text-[11px]">
              <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-1.5">
                <span>Version</span>
                <span className="text-purple-300">strands-agents v1.61.1</span>
              </div>
              <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-1.5">
                <span>Loop Abstraction</span>
                <span className="text-emerald-400 font-sans">strands.Agent</span>
              </div>
              <div className="flex items-center justify-between text-slate-400 border-b border-slate-800 pb-1.5">
                <span>Tool Decorator</span>
                <span className="text-sky-400 font-sans">@strands.tool</span>
              </div>
              <div className="flex items-center justify-between text-slate-400">
                <span>Model Backend</span>
                <span className="text-amber-300 font-sans">BedrockModel / Offline</span>
              </div>
            </div>
          </div>

          {/* AgentCore Gateway Tools */}
          <div className="space-y-2">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-sky-400" />
              AgentCore Gateway (MCP Compatible)
            </h4>
            <div className="space-y-1.5">
              {[
                { name: 'query_logs', desc: 'Search logs in incident context bundle' },
                { name: 'get_file', desc: 'Retrieve repository source file lines' },
                { name: 'get_commit_diff', desc: 'Inspect git commit unified diff' },
                { name: 'submit_rca', desc: 'Submit structured RCA with grounding check' },
              ].map((t) => (
                <div key={t.name} className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80 flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-sky-400 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-mono text-white text-[11px] font-bold">{t.name}</span>
                    <p className="text-slate-400 text-[10px]">{t.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* AgentCore Policies */}
          <div className="space-y-2">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-emerald-400" />
              AgentCore Safety Policies & Guardrails
            </h4>
            <div className="space-y-2 text-slate-300">
              <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80">
                <span className="font-bold text-white block text-[11px]">Blast Radius Policy</span>
                <p className="text-slate-400 text-[10px] mt-0.5">
                  Max 3 files modified, max 80 lines changed per patch.
                </p>
              </div>

              <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80">
                <span className="font-bold text-white block text-[11px]">Protected Paths Policy</span>
                <p className="text-slate-400 text-[10px] mt-0.5">
                  Modifications strictly blocked for CI (.github/), IaC (infra/), contracts, and package manifests.
                </p>
              </div>

              <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80">
                <span className="font-bold text-white block text-[11px]">Evidence Grounding Policy</span>
                <p className="text-slate-400 text-[10px] mt-0.5">
                  Every evidence reference must resolve to a valid log line id, stack frame, or commit. Unverifiable citations drop confidence to &le;0.40.
                </p>
              </div>

              <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800/80">
                <span className="font-bold text-white block text-[11px]">Abstention Policy</span>
                <p className="text-slate-400 text-[10px] mt-0.5">
                  When diagnostic evidence is weak or absent, enforces classification="insufficient_evidence" with confidence &le;0.40.
                </p>
              </div>
            </div>
          </div>

          {/* AgentCore Telemetry */}
          <div className="space-y-2">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Database className="w-3.5 h-3.5 text-amber-400" />
              AgentCore Observability & Metrics
            </h4>
            <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl space-y-1 font-mono text-[10px] text-slate-400">
              <div>Namespace: <span className="text-amber-300">OpsPilot/AgentCore</span></div>
              <div>Metrics: ExecutionDurationMs, ToolInvocations, PolicyViolations, ConfidenceScore</div>
              <div>EMF Format: Embedded Metric Format extracted by CloudWatch Agent</div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/80 text-right">
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
