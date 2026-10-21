import React from 'react';
import { ArrowUpRight } from 'lucide-react';
import { Stats } from '../types';
import { formatRatio } from '../lib/format';
import { eyebrow, focusRing } from '../ui/styles';

interface StatsCardsProps {
  stats: Stats | null;
  onOpenAgentCore: () => void;
}

const Cell: React.FC<{
  label: string;
  value: React.ReactNode;
  unit?: string;
  footnote: React.ReactNode;
  emphasis?: boolean;
  meter?: number | null;
  index: number;
}> = ({ label, value, unit, footnote, emphasis, meter, index }) => (
  <div
    className="px-4 sm:px-5 py-4 motion-safe:animate-rise-in"
    style={{ animationDelay: `${40 + index * index * 12 + index * 30}ms` }}
  >
    <dt className={eyebrow}>{label}</dt>
    <dd className="mt-2">
      <span
        className={`tnum text-[28px] leading-none font-light tracking-[-0.03em] ${
          emphasis ? 'text-signal-300' : 'text-ink-50'
        }`}
      >
        {value}
      </span>
      {unit && <span className="ml-1 text-xs text-ink-400">{unit}</span>}
    </dd>
    {meter !== undefined && (
      <div className="mt-3 h-[3px] bg-ink-800 rounded-sm overflow-hidden" aria-hidden="true">
        <div
          className={`h-full ${emphasis ? 'bg-signal-400' : 'bg-ink-300'}`}
          style={{ width: `${Math.max(0, Math.min(1, meter ?? 0)) * 100}%` }}
        />
      </div>
    )}
    <p className="mt-2 text-2xs text-ink-400">{footnote}</p>
  </div>
);

/** Key metrics as one instrument strip rather than a row of identical cards. */
export const StatsCards: React.FC<StatsCardsProps> = ({ stats, onOpenAgentCore }) => {
  const policyCount = stats?.agentcore_policies_active.length;
  const toolCount = stats?.agentcore_gateway_tools.length;
  const verifyFootnote = !stats
    ? 'Loading…'
    : stats.verification_pass_rate === null
      ? 'No fix PRs yet'
      : `${stats.verified_prs} of ${stats.total_prs_opened} fix PRs verified`;

  const pct = (v: number | null | undefined) => {
    const s = formatRatio(v);
    return s.endsWith('%') ? s.slice(0, -1) : s;
  };

  return (
    <section aria-label="Key metrics" className="rounded-lg border border-ink-800 bg-ink-900">
      <dl className="grid grid-cols-2 lg:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,1.25fr)] divide-ink-800 [&>*]:border-ink-800 [&>*:nth-child(odd)]:border-r lg:[&>*]:border-r lg:[&>*:last-child]:border-r-0 [&>*:nth-child(-n+4)]:border-b lg:[&>*]:border-b-0">
        <Cell
          index={0}
          label="Incidents"
          value={stats ? stats.total_incidents : '—'}
          footnote="Dedup window 15 min"
        />
        <Cell
          index={1}
          label="Mean RCA confidence"
          value={stats ? pct(stats.mean_confidence) : '—'}
          unit={stats && stats.mean_confidence !== null ? '%' : undefined}
          meter={stats ? stats.mean_confidence : null}
          emphasis
          footnote="Fix route requires ≥ 0.60"
        />
        <Cell
          index={2}
          label="Fix PRs opened"
          value={stats ? stats.total_prs_opened : '—'}
          footnote={<span className="font-mono">opspilot/* branches</span>}
        />
        <Cell
          index={3}
          label="Verification pass rate"
          value={stats ? pct(stats.verification_pass_rate) : '—'}
          unit={stats && stats.verification_pass_rate !== null ? '%' : undefined}
          meter={stats ? stats.verification_pass_rate : null}
          footnote={verifyFootnote}
        />

        <div className="col-span-2 lg:col-span-1 motion-safe:animate-rise-in" style={{ animationDelay: '220ms' }}>
          <button
            type="button"
            onClick={onOpenAgentCore}
            className={`group w-full h-full text-left px-4 sm:px-5 py-4 hover:bg-ink-850 transition-colors duration-150 rounded-b-lg lg:rounded-bl-none lg:rounded-r-lg ${focusRing}`}
          >
            <dt className={`${eyebrow} flex items-center justify-between`}>
              Agent framework
              <ArrowUpRight
                className="w-3.5 h-3.5 text-ink-500 group-hover:text-signal-400 transition-colors"
                aria-hidden="true"
              />
            </dt>
            <dd className="mt-2 text-[15px] font-medium tracking-[-0.01em] text-ink-50 leading-snug">
              {stats?.agent_framework ?? 'Strands + AgentCore'}
            </dd>
            <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-2xs text-ink-400 tnum">
              <span>{policyCount === undefined ? '…' : `${policyCount} policies`}</span>
              <span>{toolCount === undefined ? '…' : `${toolCount} gateway tools`}</span>
              <span>{stats ? `SDK ${stats.strands_sdk_version ?? 'not installed'}` : '…'}</span>
            </p>
          </button>
        </div>
      </dl>
    </section>
  );
};
