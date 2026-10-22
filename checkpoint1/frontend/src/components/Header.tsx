import React from 'react';
import { Play, FlaskConical, RefreshCw, Cpu, Activity } from 'lucide-react';
import { btn, focusRing } from '../ui/styles';
import { formatRelative } from '../lib/format';

interface HeaderProps {
  page: 'incidents' | 'tickets';
  onNavigate: (path: string) => void;
  onTriggerSimulation: () => void;
  onOpenEvals: () => void;
  onOpenAgentCore: () => void;
  onOpenRuns: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  autoRefresh: boolean;
  setAutoRefresh: (val: boolean) => void;
  lastUpdated?: Date | null;
  hasError?: boolean;
}

/** Heartbeat glyph used as the product mark (matches the favicon). */
const Mark: React.FC = () => (
  <svg viewBox="0 0 100 100" className="w-7 h-7 shrink-0" aria-hidden="true">
    <rect width="100" height="100" rx="22" className="fill-ink-50" />
    <path
      d="M14 56h18l8-22 14 40 10-26 6 8h16"
      fill="none"
      className="stroke-ink-950"
      strokeWidth="9"
      strokeLinejoin="round"
      strokeLinecap="round"
    />
  </svg>
);


const SectionNav: React.FC<{ page: string; onNavigate: (path: string) => void; className: string }> = ({
  page,
  onNavigate,
  className,
}) => (
<nav aria-label="Dashboard sections" className={className}>
    {(
      [
        ['/', 'Incidents', 'incidents'],
        ['/tickets', 'Tickets', 'tickets'],
      ] as const
    ).map(([path, label, id]) => {
      const active = page === id;
      return (
        <a
          key={path}
          href={path}
          aria-current={active ? 'page' : undefined}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
            e.preventDefault();
            onNavigate(path);
          }}
          className={`h-7 px-2 inline-flex items-center rounded-md text-xs ${focusRing} ${
            active ? 'bg-ink-800 text-ink-50' : 'text-ink-400 hover:text-ink-100 hover:bg-ink-900'
          }`}
        >
          {label}
        </a>
      );
    })}
  </nav>
);

export const Header: React.FC<HeaderProps> = ({
  page,
  onNavigate,
  onTriggerSimulation,
  onOpenEvals,
  onOpenAgentCore,
  onOpenRuns,
  onRefresh,
  isRefreshing,
  autoRefresh,
  setAutoRefresh,
  lastUpdated,
  hasError,
}) => {
  const live = autoRefresh && !hasError;
  const statusText = hasError
    ? 'Connection issue'
    : autoRefresh
      ? 'Demo · 15s'
      : 'Paused';

  return (
    <header className="sticky top-0 z-30 border-b border-ink-800 bg-ink-950/95 supports-[backdrop-filter]:bg-ink-950/85 supports-[backdrop-filter]:backdrop-blur">
      <div className="px-4 sm:px-6 h-14 flex items-center gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <Mark />
          <h1 className="text-[15px] font-semibold tracking-[-0.02em] text-ink-50">
            OpsPilot
          </h1>
          <SectionNav page={page} onNavigate={onNavigate} className="hidden sm:flex items-center gap-1 ml-2" />
          <span className="hidden md:inline px-1.5 py-px rounded border border-amber-500/40 font-mono text-2xs text-amber-200/90 bg-amber-500/10">
            Checkpoint 1
          </span>
        </div>

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          {/* Live status: doubles as the auto-refresh switch */}
          <button
            type="button"
            role="switch"
            aria-checked={autoRefresh}
            onClick={() => setAutoRefresh(!autoRefresh)}
            title={autoRefresh ? 'Pause auto-refresh (polls every 10s)' : 'Resume auto-refresh (polls every 10s)'}
            className={`h-8 px-2.5 inline-flex items-center gap-2 rounded-md border text-xs transition-colors duration-150 ${focusRing} ${
              hasError
                ? 'border-red-500/40 text-red-200 bg-red-500/10'
                : autoRefresh
                  ? 'border-ink-700 text-ink-100 hover:bg-ink-800'
                  : 'border-ink-700 text-ink-400 hover:bg-ink-800'
            }`}
          >
            <span className="relative flex w-2 h-2" aria-hidden="true">
              <span
                className={`w-2 h-2 rounded-full ${
                  hasError ? 'bg-red-400' : live ? 'bg-ok-400 motion-safe:animate-pulse-dot' : 'bg-ink-500'
                }`}
              />
            </span>
            <span className="hidden sm:inline font-mono text-2xs tracking-wide">{statusText}</span>
            <span className="sm:hidden sr-only">{statusText}</span>
            {lastUpdated && (
              <span className="hidden lg:inline font-mono text-2xs text-ink-400 tnum">
                {formatRelative(lastUpdated.toISOString())}
              </span>
            )}
            <span className="sr-only">Auto-refresh</span>
          </button>

          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-label="Refresh incidents and stats"
            title="Refresh incidents and stats"
            className={btn.ghost}
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'motion-safe:animate-spin text-ink-50' : ''}`} aria-hidden="true" />
          </button>

          <span className="hidden sm:block w-px h-5 bg-ink-800 mx-1" aria-hidden="true" />

          <button
            type="button"
            onClick={onOpenRuns}
            className={`${btn.secondary} max-md:w-8 max-md:px-0 max-md:justify-center`}
            title="Agent runs and traces: model calls, tool calls, timings"
            aria-label="Agent runs"
          >
            <Activity className="w-3.5 h-3.5 text-ink-300" aria-hidden="true" />
            <span className="hidden md:inline">Agent runs</span>
          </button>

          <button
            type="button"
            onClick={onOpenAgentCore}
            className={`${btn.secondary} hidden lg:inline-flex`}
            title="Inspect Strands SDK and AgentCore configuration"
          >
            <Cpu className="w-3.5 h-3.5 text-ink-300" aria-hidden="true" />
            Agent runtime
          </button>

          <button
            type="button"
            onClick={onOpenEvals}
            className={`${btn.secondary} max-sm:w-8 max-sm:px-0 max-sm:justify-center`}
            title="Replay the golden M6 benchmark fixtures"
            aria-label="Run M6 evals"
          >
            <FlaskConical className="w-3.5 h-3.5 text-ink-300" aria-hidden="true" />
            <span className="hidden sm:inline">Run M6 evals</span>
          </button>

          <button
            type="button"
            onClick={onTriggerSimulation}
            className={btn.primary}
            title="Send 5 failing requests to sample_service and ingest the resulting alarm (simulated)"
          >
            <Play className="w-3.5 h-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">Simulate incident</span>
            <span className="sm:hidden">Simulate</span>
          </button>
        </div>
      </div>
      <div className="sm:hidden px-4 pb-2 -mt-1">
        <SectionNav page={page} onNavigate={onNavigate} className="flex items-center gap-1" />
      </div>
    </header>
  );
};
