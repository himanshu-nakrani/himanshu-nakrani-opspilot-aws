import React from 'react';
import { Stats } from '../types';
import { AlertCircle, Target, GitPullRequest, CheckCircle2, ShieldCheck } from 'lucide-react';
import { formatRatio } from '../lib/format';

interface StatsCardsProps {
  stats: Stats | null;
  onOpenAgentCore: () => void;
}

const card = 'bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 flex flex-col justify-between transition';

const StatCard: React.FC<{
  label: string;
  value: React.ReactNode;
  valueClass: string;
  icon: React.ReactNode;
  footnote: React.ReactNode;
}> = ({ label, value, valueClass, icon, footnote }) => (
  <div className={`${card} hover:border-slate-700`}>
    <div>
      <div className="flex items-center justify-between text-slate-300">
        <h3 className="text-xs font-semibold uppercase tracking-wider">{label}</h3>
        {icon}
      </div>
      <div className={`text-2xl font-bold mt-2 ${valueClass}`}>{value}</div>
    </div>
    <p className="text-xs text-slate-400 mt-2">{footnote}</p>
  </div>
);

export const StatsCards: React.FC<StatsCardsProps> = ({ stats, onOpenAgentCore }) => {
  const policyCount = stats?.agentcore_policies_active.length;
  const verifyFootnote = !stats
    ? 'Loading…'
    : stats.verification_pass_rate === null
      ? 'No fix PRs yet'
      : `${stats.verified_prs} of ${stats.total_prs_opened} fix PRs verified`;

  return (
    <section aria-label="Key metrics" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      <StatCard
        label="Total Incidents"
        value={stats ? stats.total_incidents : '--'}
        valueClass="text-white"
        icon={<AlertCircle className="w-4 h-4 text-slate-400" aria-hidden="true" />}
        footnote="Dedup window: 15 min"
      />
      <StatCard
        label="Mean RCA Confidence"
        value={stats ? formatRatio(stats.mean_confidence) : '--'}
        valueClass="text-emerald-400"
        icon={<Target className="w-4 h-4 text-emerald-400" aria-hidden="true" />}
        footnote="Fix route requires ≥ 0.60"
      />
      <StatCard
        label="Fix PRs Opened"
        value={stats ? stats.total_prs_opened : '--'}
        valueClass="text-purple-300"
        icon={<GitPullRequest className="w-4 h-4 text-purple-400" aria-hidden="true" />}
        footnote="opspilot/* branches"
      />
      <StatCard
        label="Verification Pass Rate"
        value={stats ? formatRatio(stats.verification_pass_rate) : '--'}
        valueClass="text-sky-300"
        icon={<CheckCircle2 className="w-4 h-4 text-sky-400" aria-hidden="true" />}
        footnote={verifyFootnote}
      />

      <button
        type="button"
        onClick={onOpenAgentCore}
        className={`${card} text-left bg-gradient-to-br from-purple-950/20 to-slate-900/50 border-purple-500/20 hover:border-purple-500/40 group focus-visible:outline focus-visible:outline-2 focus-visible:outline-purple-400`}
      >
        <div className="w-full">
          <div className="flex items-center justify-between text-purple-200">
            <span className="text-xs font-semibold uppercase tracking-wider">Agent Framework</span>
            <ShieldCheck className="w-4 h-4 text-purple-400" aria-hidden="true" />
          </div>
          <div className="text-sm font-bold text-purple-100 mt-2 leading-tight">
            {stats?.agent_framework ?? 'Strands + AgentCore'}
          </div>
        </div>
        <span className="flex items-center gap-1.5 text-xs text-purple-300 mt-2">
          <span>{policyCount === undefined ? '…' : `${policyCount} policies`}</span>
          <span aria-hidden="true">•</span>
          <span className="underline decoration-dotted">Inspect details</span>
        </span>
      </button>
    </section>
  );
};
