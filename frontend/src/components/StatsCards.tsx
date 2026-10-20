import React from 'react';
import { Stats } from '../types';
import { AlertCircle, Target, GitPullRequest, CheckCircle2, ShieldCheck } from 'lucide-react';

interface StatsCardsProps {
  stats: Stats | null;
  onOpenAgentCore: () => void;
}

export const StatsCards: React.FC<StatsCardsProps> = ({ stats, onOpenAgentCore }) => {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      {/* 1. Total Incidents */}
      <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 flex flex-col justify-between hover:border-slate-700 transition">
        <div>
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Incidents</span>
            <AlertCircle className="w-4 h-4 text-slate-500" />
          </div>
          <div className="text-2xl font-bold text-white mt-2">
            {stats ? stats.total_incidents : '--'}
          </div>
        </div>
        <span className="text-[11px] text-slate-500 mt-2">Dedup window: 15-min</span>
      </div>

      {/* 2. Mean Confidence */}
      <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 flex flex-col justify-between hover:border-slate-700 transition">
        <div>
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Mean RCA Confidence</span>
            <Target className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-emerald-400 mt-2">
            {stats ? `${Math.round(stats.mean_confidence * 100)}%` : '--%'}
          </div>
        </div>
        <span className="text-[11px] text-slate-500 mt-2">Evidence-grounded (min 0.60 fix)</span>
      </div>

      {/* 3. Total PRs Opened */}
      <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 flex flex-col justify-between hover:border-slate-700 transition">
        <div>
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Fix PRs Opened</span>
            <GitPullRequest className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-bold text-purple-400 mt-2">
            {stats ? stats.total_prs_opened : '--'}
          </div>
        </div>
        <span className="text-[11px] text-slate-500 mt-2">opspilot/* branch refs</span>
      </div>

      {/* 4. Verification Pass Rate */}
      <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 flex flex-col justify-between hover:border-slate-700 transition">
        <div>
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Verification Pass Rate</span>
            <CheckCircle2 className="w-4 h-4 text-sky-400" />
          </div>
          <div className="text-2xl font-bold text-sky-400 mt-2">
            {stats ? `${Math.round(stats.verification_pass_rate * 100)}%` : '100%'}
          </div>
        </div>
        <span className="text-[11px] text-slate-500 mt-2">CodeBuild 2-phase verify</span>
      </div>

      {/* 5. Agent Architecture */}
      <div
        onClick={onOpenAgentCore}
        className="bg-gradient-to-br from-purple-950/20 to-slate-900/50 border border-purple-500/20 hover:border-purple-500/40 rounded-xl p-4 flex flex-col justify-between transition cursor-pointer group"
      >
        <div>
          <div className="flex items-center justify-between text-purple-300">
            <span className="text-xs font-semibold uppercase tracking-wider">Agent Framework</span>
            <ShieldCheck className="w-4 h-4 text-purple-400 group-hover:scale-110 transition" />
          </div>
          <div className="text-sm font-bold text-purple-200 mt-2 leading-tight">
            AWS Strands + AgentCore
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-purple-400/80 mt-2 group-hover:text-purple-300">
          <span>5 active policies</span>
          <span>•</span>
          <span className="underline decoration-dotted">Inspect details →</span>
        </div>
      </div>
    </section>
  );
};
