import React from 'react';
import { Zap, Play, FlaskConical, RefreshCw, Cpu } from 'lucide-react';

interface HeaderProps {
  onTriggerSimulation: () => void;
  onOpenEvals: () => void;
  onOpenAgentCore: () => void;
  onRefresh: () => void;
  isLoading: boolean;
  autoRefresh: boolean;
  setAutoRefresh: (val: boolean) => void;
}

export const Header: React.FC<HeaderProps> = ({
  onTriggerSimulation,
  onOpenEvals,
  onOpenAgentCore,
  onRefresh,
  isLoading,
  autoRefresh,
  setAutoRefresh,
}) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur-md sticky top-0 z-30">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-bold text-xl shadow-lg shadow-emerald-950/50">
            <Zap className="w-5 h-5 text-emerald-400 fill-emerald-400/20" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg tracking-tight text-white">OpsPilot</span>
              <span className="px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                AWS POC
              </span>
              <button
                onClick={onOpenAgentCore}
                className="px-2 py-0.5 text-[10px] font-mono font-medium rounded-full bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30 transition flex items-center gap-1 cursor-pointer"
                title="Inspect AWS Strands & Bedrock AgentCore Runtime"
              >
                <Cpu className="w-2.5 h-2.5" />
                Strands + AgentCore
              </button>
            </div>
            <p className="text-xs text-slate-400 hidden sm:block">
              Autonomous SRE Incident Monitoring & Remediating Agent
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <label className="hidden md:flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer mr-1">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-emerald-500 focus:ring-0 cursor-pointer"
            />
            <span>Auto (10s)</span>
          </label>

          <button
            onClick={onTriggerSimulation}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 transition flex items-center gap-1.5 shadow-sm hover:shadow-red-950 cursor-pointer"
            title="Simulate 5 unhandled 500s on sample_service and trigger EventBridge alarm"
          >
            <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
            <Play className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Simulate Incident</span>
            <span className="sm:hidden">Simulate</span>
          </button>

          <button
            onClick={onOpenEvals}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition flex items-center gap-1.5 cursor-pointer"
            title="Replay 10 Golden M6 Benchmark Fixtures"
          >
            <FlaskConical className="w-3.5 h-3.5 text-sky-400" />
            <span className="hidden sm:inline">Run M6 Evals</span>
            <span className="sm:hidden">Evals</span>
          </button>

          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition disabled:opacity-50 cursor-pointer"
            title="Refresh incident list"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-emerald-400' : ''}`} />
          </button>
        </div>
      </div>
    </header>
  );
};
