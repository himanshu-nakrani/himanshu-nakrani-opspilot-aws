import React from 'react';
import { Zap, Play, FlaskConical, RefreshCw, Cpu } from 'lucide-react';

interface HeaderProps {
  onTriggerSimulation: () => void;
  onOpenEvals: () => void;
  onOpenAgentCore: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  autoRefresh: boolean;
  setAutoRefresh: (val: boolean) => void;
}

const focusRing = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400';

export const Header: React.FC<HeaderProps> = ({
  onTriggerSimulation,
  onOpenEvals,
  onOpenAgentCore,
  onRefresh,
  isRefreshing,
  autoRefresh,
  setAutoRefresh,
}) => (
  <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur-md sticky top-0 z-30">
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-emerald-500/20 to-emerald-600/10 border border-emerald-500/30 flex items-center justify-center">
          <Zap className="w-5 h-5 text-emerald-400 fill-emerald-400/20" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="font-bold text-lg tracking-tight text-white">OpsPilot</h1>
            <span className="px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
              AWS POC
            </span>
            <button
              type="button"
              onClick={onOpenAgentCore}
              className={`hidden sm:flex px-2 py-0.5 text-[11px] font-mono font-medium rounded-full bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30 transition items-center gap-1 ${focusRing}`}
            >
              <Cpu className="w-3 h-3" aria-hidden="true" />
              Strands + AgentCore
            </button>
          </div>
          <p className="text-xs text-slate-400 hidden sm:block truncate">Autonomous SRE incident monitoring &amp; remediation</p>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">
        <label className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer mr-1">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
            className="rounded bg-slate-800 border-slate-600 text-emerald-500 focus:ring-2 focus:ring-emerald-400"
          />
          <span className="hidden md:inline">Auto-refresh (10s)</span>
          <span className="md:hidden">Auto</span>
        </label>

        <button
          type="button"
          onClick={onTriggerSimulation}
          className={`px-3 py-1.5 text-xs font-semibold rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/30 transition flex items-center gap-1.5 ${focusRing}`}
          title="Send 5 failing requests to sample_service and ingest the resulting alarm (simulated)"
        >
          <Play className="w-3.5 h-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">Simulate Incident</span>
          <span className="sm:hidden">Simulate</span>
        </button>

        <button
          type="button"
          onClick={onOpenEvals}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition flex items-center gap-1.5 ${focusRing}`}
          title="Replay the golden M6 benchmark fixtures"
        >
          <FlaskConical className="w-3.5 h-3.5 text-sky-400" aria-hidden="true" />
          <span className="hidden sm:inline">Run M6 Evals</span>
          <span className="sm:hidden">Evals</span>
        </button>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          aria-label="Refresh incidents and stats"
          title="Refresh incidents and stats"
          className={`p-2 text-slate-300 hover:text-white rounded-lg hover:bg-slate-800 transition disabled:opacity-60 ${focusRing}`}
        >
          <RefreshCw
            className={`w-4 h-4 ${isRefreshing ? 'motion-safe:animate-spin text-emerald-400' : ''}`}
            aria-hidden="true"
          />
        </button>
      </div>
    </div>
  </header>
);
