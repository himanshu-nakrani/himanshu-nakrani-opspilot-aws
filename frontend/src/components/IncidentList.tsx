import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertOctagon, ChevronRight, Search, X } from 'lucide-react';
import { Incident } from '../types';
import { classificationTone, confidenceTone, severityBadge, severityRail, SOURCE_LABEL, statusBadge } from '../lib/badges';
import { formatRelative, formatTimestamp, humanize } from '../lib/format';
import { btn, chip, focusRing } from '../ui/styles';

interface IncidentListProps {
  incidents: Incident[];
  onSelectIncident: (incident: Incident) => void;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  /** classification filter, lifted so the breakdown panel can drive it */
  filterClass: string;
  onFilterClassChange: (cls: string) => void;
}

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'code_defect', label: 'Code defect' },
  { id: 'config_regression', label: 'Config' },
  { id: 'dependency', label: 'Dependency' },
  { id: 'resource', label: 'Resource' },
  { id: 'insufficient_evidence', label: 'Insufficient' },
] as const;

type SortKey = 'newest' | 'confidence';

const SkeletonRow: React.FC<{ i: number }> = ({ i }) => (
  <li className="flex gap-4 px-4 py-4" aria-hidden="true">
    <div className="flex-1 space-y-2.5">
      <div className="h-3 w-40 rounded bg-ink-800 motion-safe:animate-pulse" style={{ animationDelay: `${i * 120}ms` }} />
      <div className="h-3 w-4/5 rounded bg-ink-800/70 motion-safe:animate-pulse" style={{ animationDelay: `${i * 120 + 60}ms` }} />
    </div>
    <div className="h-3 w-16 rounded bg-ink-800 motion-safe:animate-pulse" />
  </li>
);

export const IncidentList: React.FC<IncidentListProps> = ({
  incidents,
  onSelectIncident,
  isLoading,
  error,
  onRetry,
  filterClass,
  onFilterClassChange,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [sort, setSort] = useState<SortKey>('newest');
  const searchRef = useRef<HTMLInputElement>(null);

  // "/" focuses search, like most ops consoles.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      e.preventDefault();
      searchRef.current?.focus();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const counts = useMemo(() => {
    const m: Record<string, number> = { all: incidents.length };
    for (const inc of incidents) if (inc.classification) m[inc.classification] = (m[inc.classification] ?? 0) + 1;
    return m;
  }, [incidents]);

  const filtered = useMemo(() => {
    const q = searchTerm.trim().toLowerCase();
    const rows = incidents.filter((inc) => {
      const matchesSearch =
        !q ||
        inc.incident_id.toLowerCase().includes(q) ||
        (inc.summary ?? '').toLowerCase().includes(q) ||
        (inc.service ?? '').toLowerCase().includes(q);
      const matchesClass = filterClass === 'all' || inc.classification === filterClass;
      return matchesSearch && matchesClass;
    });
    if (sort === 'confidence') {
      return [...rows].sort((a, b) => (b.confidence ?? -1) - (a.confidence ?? -1));
    }
    const ts = (i: Incident) => {
      const t = i.detected_at ? new Date(i.detected_at).getTime() : NaN;
      return Number.isNaN(t) ? -Infinity : t;
    };
    return [...rows].sort((a, b) => ts(b) - ts(a));
  }, [incidents, searchTerm, filterClass, sort]);

  const hasFilter = searchTerm.trim() !== '' || filterClass !== 'all';

  return (
    <div className="rounded-lg border border-ink-800 bg-ink-900 overflow-hidden">
      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 border-b border-red-500/30 bg-red-500/10 text-xs text-red-200"
        >
          <span className="flex items-center gap-2">
            <AlertOctagon className="w-4 h-4 shrink-0" aria-hidden="true" />
            {incidents.length > 0 ? `Showing last loaded data. ${error}` : error}
          </span>
          <button type="button" onClick={onRetry} className={btn.secondary}>
            Retry
          </button>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex flex-col gap-3 px-3 sm:px-4 py-3 border-b border-ink-800 xl:flex-row xl:items-center">
        <div className="relative flex-1 min-w-0 xl:max-w-sm">
          <label htmlFor="incident-search" className="sr-only">
            Search incidents
          </label>
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-400" aria-hidden="true" />
          <input
            ref={searchRef}
            id="incident-search"
            type="search"
            placeholder="Search ID, summary, service"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full h-8 bg-ink-950 border border-ink-700 rounded-md pl-8 pr-9 text-[13px] text-ink-50 placeholder-ink-500 focus:outline-none focus:border-signal-400/70 focus:ring-1 focus:ring-signal-400/40 [&::-webkit-search-cancel-button]:hidden"
          />
          {searchTerm ? (
            <button
              type="button"
              onClick={() => setSearchTerm('')}
              aria-label="Clear search"
              className={`absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded text-ink-400 hover:text-ink-50 ${focusRing}`}
            >
              <X className="w-3.5 h-3.5" aria-hidden="true" />
            </button>
          ) : (
            <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 hidden sm:block px-1.5 rounded border border-ink-700 font-mono text-2xs text-ink-500">
              /
            </kbd>
          )}
        </div>

        <div className="flex items-center gap-3 min-w-0 xl:ml-auto">
          <div
            role="group"
            aria-label="Filter by classification"
            className="flex gap-1 overflow-x-auto -mx-1 px-1 pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {FILTERS.map((f) => {
              const active = filterClass === f.id;
              const n = counts[f.id] ?? 0;
              return (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onFilterClassChange(f.id)}
                  className={`shrink-0 h-7 px-2 inline-flex items-center gap-1.5 text-xs rounded-md border transition-colors duration-150 ${focusRing} ${
                    active
                      ? 'bg-ink-50 text-ink-950 border-ink-50 font-medium'
                      : 'bg-transparent text-ink-300 border-ink-800 hover:text-ink-50 hover:border-ink-600'
                  }`}
                >
                  {f.id !== 'all' && (
                    <span
                      className={`w-1.5 h-1.5 rounded-sm ${classificationTone(f.id as Incident['classification']).swatch}`}
                      aria-hidden="true"
                    />
                  )}
                  {f.label}
                  <span className={`font-mono text-2xs tnum ${active ? 'text-ink-600' : 'text-ink-500'}`}>{n}</span>
                </button>
              );
            })}
          </div>

          <label className="shrink-0 flex items-center gap-1.5 text-2xs text-ink-400">
            <span className="sr-only sm:not-sr-only">Sort</span>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className={`h-7 rounded-md border border-ink-800 bg-ink-950 px-1.5 text-xs text-ink-200 ${focusRing}`}
            >
              <option value="newest">Newest</option>
              <option value="confidence">Confidence</option>
            </select>
          </label>
        </div>
      </div>

      {isLoading && (
        <>
          <p className="sr-only" role="status">
            Loading incidents…
          </p>
          <ul className="divide-y divide-ink-800">
            {[0, 1, 2, 3].map((i) => (
              <SkeletonRow key={i} i={i} />
            ))}
          </ul>
        </>
      )}

      {!isLoading && filtered.length === 0 && !(error && incidents.length === 0) && (
        <div className="px-6 py-16 text-center">
          <p className="text-[13px] text-ink-200">
            {hasFilter ? 'No incidents match this search or filter.' : 'No incidents recorded yet.'}
          </p>
          <p className="mt-1 text-xs text-ink-400">
            {hasFilter ? (
              <button
                type="button"
                onClick={() => {
                  setSearchTerm('');
                  onFilterClassChange('all');
                }}
                className={`underline decoration-ink-600 underline-offset-2 hover:text-ink-100 ${focusRing}`}
              >
                Clear filters
              </button>
            ) : (
              'Use “Simulate incident” to create one.'
            )}
          </p>
        </div>
      )}

      {!isLoading && filtered.length > 0 && (
        <ul className="divide-y divide-ink-800">
          {filtered.map((inc) => {
            const status = statusBadge(inc.status);
            const StatusIcon = status.icon;
            const pct = inc.confidence === null || inc.confidence === undefined ? null : Math.round(inc.confidence * 100);
            const tone = confidenceTone(pct);
            const cls = classificationTone(inc.classification);
            return (
              <li key={inc.incident_id}>
                <button
                  type="button"
                  onClick={() => onSelectIncident(inc)}
                  className="relative w-full text-left pl-5 pr-3 sm:pr-4 py-3.5 hover:bg-ink-850 transition-colors duration-150 flex items-start gap-4 group focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-signal-400"
                >
                  <span className={`absolute left-0 top-0 bottom-0 w-[3px] ${severityRail(inc.severity)}`} aria-hidden="true" />

                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="font-mono text-xs text-ink-100">{inc.incident_id}</span>
                      {inc.severity && <span className={`${chip} uppercase font-mono ${severityBadge(inc.severity)}`}>{inc.severity}</span>}
                      <span className={`${chip} ${cls.badge}`}>{humanize(inc.classification)}</span>
                      <span className={`inline-flex items-center gap-1 text-2xs ${status.text}`}>
                        <StatusIcon className="w-3 h-3" aria-hidden="true" />
                        {status.label}
                      </span>
                      {inc.source && inc.source !== 'dynamodb' && (
                        <span className={`${chip} border-dashed border-ink-600 text-ink-400`}>{SOURCE_LABEL[inc.source]}</span>
                      )}
                    </div>
                    <p className="mt-1.5 text-[13px] leading-snug text-ink-100 line-clamp-2">{inc.summary || 'No summary available.'}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-400">
                      <span className="font-mono">{inc.service ?? 'unknown service'}</span>
                      <time dateTime={inc.detected_at ?? undefined} title={formatTimestamp(inc.detected_at)}>
                        {formatRelative(inc.detected_at) || formatTimestamp(inc.detected_at)}
                      </time>
                      {inc.ticket_key && <span className="font-mono text-ink-300">{inc.ticket_key}</span>}
                    </div>
                  </div>

                  <div className="w-16 sm:w-24 shrink-0 text-right pt-0.5">
                    <span className="sr-only">Confidence</span>
                    <span className={`block font-mono text-sm tnum ${tone.text}`}>{pct === null ? 'n/a' : `${pct}%`}</span>
                    <div
                      role="progressbar"
                      aria-label="RCA confidence"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={pct ?? undefined}
                      aria-valuetext={pct === null ? 'unknown' : `${pct}%`}
                      className="mt-1.5 h-[3px] bg-ink-800 rounded-sm overflow-hidden"
                    >
                      <div className={`h-full ${tone.bar}`} style={{ width: `${pct ?? 0}%` }} />
                    </div>
                    <span className="hidden sm:block mt-1 text-2xs text-ink-500">confidence</span>
                  </div>
                  <ChevronRight
                    className="hidden sm:block w-4 h-4 text-ink-600 group-hover:text-ink-200 self-center transition-colors"
                    aria-hidden="true"
                  />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {!isLoading && incidents.length > 0 && (
        <div className="px-4 py-2 border-t border-ink-800 font-mono text-2xs text-ink-500 tnum" aria-live="polite">
          {filtered.length === incidents.length ? `${incidents.length} incidents` : `${filtered.length} of ${incidents.length} incidents`}
        </div>
      )}
    </div>
  );
};
