import React from 'react';
import { Stats } from '../types';
import { formatRatio } from '../lib/format';
import { eyebrow } from '../ui/styles';

interface StatsCardsProps {
  stats: Stats | null;
  checkpointMode?: boolean;
}

const Cell: React.FC<{
  label: string;
  value: React.ReactNode;
  unit?: string;
  footnote: React.ReactNode;
  emphasis?: boolean;
  index: number;
}> = ({ label, value, unit, footnote, emphasis, index }) => (
  <div
    className="px-4 sm:px-5 py-4 motion-safe:animate-rise-in"
    style={{ animationDelay: `${40 + index * index * 12 + index * 30}ms` }}
  >
    <dt className={eyebrow}>{label}</dt>
    <dd className="mt-2">
      <span
        className={`tnum text-[32px] leading-none font-light tracking-[-0.04em] ${
          emphasis ? 'text-ok-300' : 'text-ink-50'
        }`}
      >
        {value}
      </span>
      {unit && <span className="ml-1 text-xs text-ink-400">{unit}</span>}
    </dd>
    <p className="mt-2.5 text-2xs text-ink-400">{footnote}</p>
  </div>
);

/** Key metrics as one instrument strip rather than a row of identical cards. */
export const StatsCards: React.FC<StatsCardsProps> = ({ stats, checkpointMode }) => {
  const verifyFootnote = !stats
    ? 'Loading…'
    : checkpointMode
      ? 'M5 — CodeBuild verify not wired yet'
      : stats.verification_pass_rate === null
        ? 'No fix PRs yet'
        : `${stats.verified_prs} of ${stats.total_prs_opened} fix PRs verified`;

  const pct = (v: number | null | undefined) => {
    const s = formatRatio(v);
    return s.endsWith('%') ? s.slice(0, -1) : s;
  };

  return (
    <section aria-label="Key metrics" className="rounded-lg border border-ink-800 bg-ink-900/60">
      <dl className="grid grid-cols-2 lg:grid-cols-4 [&>*]:border-ink-800 [&>*:nth-child(odd)]:border-r lg:[&>*]:border-r lg:[&>*:last-child]:border-r-0 [&>*:nth-child(-n+2)]:border-b lg:[&>*]:border-b-0">
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
          footnote="Fix route requires ≥ 0.60"
        />
        <Cell
          index={2}
          label="Fix PRs opened"
          value={stats ? stats.total_prs_opened : '—'}
          footnote={
            checkpointMode ? (
              'M4 patch agent — in progress'
            ) : (
              <span className="font-mono">opspilot/* branches</span>
            )
          }
        />
        <Cell
          index={3}
          label="Verification pass rate"
          value={stats ? pct(stats.verification_pass_rate) : '—'}
          unit={stats && stats.verification_pass_rate !== null ? '%' : undefined}
          footnote={verifyFootnote}
        />

      </dl>
    </section>
  );
};
