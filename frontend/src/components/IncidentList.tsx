import React, { useMemo, useState } from 'react';
import { AlertOctagon, ChevronRight, Search } from 'lucide-react';
import { Incident } from '../types';
import { classificationBadge, confidenceTone, severityBadge, SOURCE_LABEL, statusBadge } from '../lib/badges';
import { formatTimestamp, humanize } from '../lib/format';

interface IncidentListProps {
  incidents: Incident[];
  onSelectIncident: (incident: Incident) => void;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'code_defect', label: 'Code defect' },
  { id: 'config_regression', label: 'Config regression' },
  { id: 'dependency', label: 'Dependency' },
  { id: 'resource', label: 'Resource' },
  { id: 'insufficient_evidence', label: 'Insufficient evidence' },
] as const;

export const IncidentList: React.FC<IncidentListProps> = ({ incidents, onSelectIncident, isLoading, error, onRetry }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterClass, setFilterClass] = useState<string>('all');

  const filtered = useMemo(() => {
    const q = searchTerm.trim().toLowerCase();
    return incidents.filter((inc) => {
      const matchesSearch =
        !q ||
        inc.incident_id.toLowerCase().includes(q) ||
        (inc.summary ?? '').toLowerCase().includes(q) ||
        (inc.service ?? '').toLowerCase().includes(q);
      const matchesClass = filterClass === 'all' || inc.classification === filterClass;
      return matchesSearch && matchesClass;
    });
  }, [incidents, searchTerm, filterClass]);

  const hasFilter = searchTerm.trim() !== '' || filterClass !== 'all';

  return (
    <div className="space-y-4">
      {error && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-xs text-red-200">
          <span className="flex items-center gap-2">
            <AlertOctagon className="w-4 h-4 shrink-0" aria-hidden="true" />
            {incidents.length > 0 ? `Showing last loaded data. ${error}` : error}
          </span>
          <button type="button" onClick={onRetry} className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 font-medium">
            Retry
          </button>
        </div>
      )}

      <div className="flex flex-col md:flex-row gap-3 md:items-center justify-between">
        <div className="relative flex-1 max-w-md">
          <label htmlFor="incident-search" className="sr-only">
            Search incidents
          </label>
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" aria-hidden="true" />
          <input
            id="incident-search"
            type="search"
            placeholder="Search by incident ID, summary, or service"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-900/80 border border-slate-700 rounded-xl pl-9 pr-4 py-2 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/60"
          />
        </div>

        <div role="group" aria-label="Filter by classification" className="flex flex-wrap gap-1.5">
          {FILTERS.map((chip) => {
            const active = filterClass === chip.id;
            return (
              <button
                key={chip.id}
                type="button"
                aria-pressed={active}
                onClick={() => setFilterClass(chip.id)}
                className={`px-2.5 py-1 text-xs font-medium rounded-lg border transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${
                  active
                    ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
                    : 'bg-slate-900/60 text-slate-300 border-slate-700 hover:text-white hover:border-slate-600'
                }`}
              >
                {chip.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="bg-slate-900/30 border border-slate-800 rounded-xl overflow-hidden">
        {isLoading && (
          <div className="p-8 text-center text-sm text-slate-300" role="status">
            Loading incidents…
          </div>
        )}

        {!isLoading && filtered.length === 0 && !(error && incidents.length === 0) && (
          <div className="p-8 text-center text-sm text-slate-300">
            {hasFilter ? 'No incidents match your search or filter.' : 'No incidents recorded yet. Use “Simulate Incident” to create one.'}
          </div>
        )}

        {!isLoading && filtered.length > 0 && (
          <ul className="divide-y divide-slate-800">
            {filtered.map((inc) => {
              const status = statusBadge(inc.status);
              const StatusIcon = status.icon;
              const pct = inc.confidence === null || inc.confidence === undefined ? null : Math.round(inc.confidence * 100);
              const tone = confidenceTone(pct);
              return (
                <li key={inc.incident_id}>
                  <button
                    type="button"
                    onClick={() => onSelectIncident(inc)}
                    className="w-full text-left p-4 hover:bg-slate-800/40 transition flex items-start gap-4 group focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-emerald-400"
                  >
                    <div className="flex-1 min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-slate-200">{inc.incident_id}</span>
                        <span className={`px-2 py-0.5 text-[11px] rounded-md border ${classificationBadge(inc.classification)}`}>
                          {humanize(inc.classification)}
                        </span>
                        <span className={`px-2 py-0.5 text-[11px] rounded-md border flex items-center gap-1 ${status.className}`}>
                          <StatusIcon className="w-3 h-3" aria-hidden="true" />
                          {status.label}
                        </span>
                        {inc.severity && (
                          <span className={`px-2 py-0.5 text-[11px] rounded-md border uppercase ${severityBadge(inc.severity)}`}>
                            {inc.severity}
                          </span>
                        )}
                        {inc.source && inc.source !== 'dynamodb' && (
                          <span className="px-2 py-0.5 text-[11px] rounded-md border border-dashed border-slate-600 text-slate-300">
                            {SOURCE_LABEL[inc.source]}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-200 line-clamp-2">{inc.summary || 'No summary available.'}</p>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
                        <span>{inc.service ?? 'unknown service'}</span>
                        <time dateTime={inc.detected_at ?? undefined}>{formatTimestamp(inc.detected_at)}</time>
                        {inc.ticket_key && <span className="font-mono">{inc.ticket_key}</span>}
                      </div>
                    </div>

                    <div className="w-28 shrink-0 space-y-1 text-right">
                      <span className="block text-[11px] text-slate-400">Confidence</span>
                      <span className={`block text-sm font-semibold ${tone.text}`}>{pct === null ? 'n/a' : `${pct}%`}</span>
                      <div
                        role="progressbar"
                        aria-label="RCA confidence"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={pct ?? undefined}
                        aria-valuetext={pct === null ? 'unknown' : `${pct}%`}
                        className="h-1.5 bg-slate-800 rounded-full overflow-hidden"
                      >
                        <div className={`h-full ${tone.bar}`} style={{ width: `${pct ?? 0}%` }} />
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-white self-center" aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};
