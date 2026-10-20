import React, { useState } from 'react';
import { Incident } from '../types';
import { Search, ExternalLink, GitPullRequest, Ticket, Code2, AlertTriangle, CheckCircle, ShieldAlert } from 'lucide-react';

interface IncidentListProps {
  incidents: Incident[];
  onSelectIncident: (incident: Incident) => void;
  isLoading: boolean;
}

export const IncidentList: React.FC<IncidentListProps> = ({ incidents, onSelectIncident, isLoading }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterClass, setFilterClass] = useState<string>('all');

  const filteredIncidents = incidents.filter((inc) => {
    const matchesSearch =
      inc.incident_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (inc.summary || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (inc.service || '').toLowerCase().includes(searchTerm.toLowerCase());

    const matchesClass = filterClass === 'all' || inc.classification === filterClass;
    return matchesSearch && matchesClass;
  });

  const getClassificationBadge = (cls: string) => {
    switch (cls) {
      case 'code_defect':
        return 'bg-purple-500/10 text-purple-400 border-purple-500/20';
      case 'config_regression':
        return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
      case 'dependency':
        return 'bg-blue-500/10 text-blue-400 border-blue-500/20';
      case 'resource':
        return 'bg-rose-500/10 text-rose-400 border-rose-500/20';
      case 'insufficient_evidence':
        return 'bg-slate-500/10 text-slate-400 border-slate-500/20';
      default:
        return 'bg-slate-800 text-slate-300 border-slate-700';
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'VERIFIED':
        return { label: 'Verified Fix', bg: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20', icon: CheckCircle };
      case 'PROPOSED':
        return { label: 'PR Proposed', bg: 'bg-purple-500/10 text-purple-400 border-purple-500/20', icon: GitPullRequest };
      case 'NEEDS_HUMAN':
        return { label: 'Needs Human', bg: 'bg-amber-500/10 text-amber-400 border-amber-500/20', icon: AlertTriangle };
      case 'NOTIFIED':
        return { label: 'Notified SRE', bg: 'bg-blue-500/10 text-blue-400 border-blue-500/20', icon: ShieldAlert };
      default:
        return { label: status, bg: 'bg-slate-800 text-slate-300 border-slate-700', icon: AlertTriangle };
    }
  };

  return (
    <section className="bg-slate-900/40 border border-slate-800/80 rounded-2xl overflow-hidden shadow-sm">
      {/* Search & Filter Toolbar */}
      <div className="p-4 border-b border-slate-800/80 flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="text"
            placeholder="Search by incident ID, summary, or service name..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-900/80 border border-slate-700/80 rounded-xl pl-9 pr-4 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500/60 focus:ring-1 focus:ring-emerald-500/60"
          />
        </div>

        {/* Classification Filter Chips */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0 scrollbar-none">
          {[
            { id: 'all', label: 'All Incidents' },
            { id: 'code_defect', label: 'Code Defect' },
            { id: 'config_regression', label: 'Config' },
            { id: 'dependency', label: 'Dependency' },
            { id: 'resource', label: 'Resource' },
            { id: 'insufficient_evidence', label: 'Abstained' },
          ].map((chip) => (
            <button
              key={chip.id}
              onClick={() => setFilterClass(chip.id)}
              className={`px-2.5 py-1 text-xs font-medium rounded-lg whitespace-nowrap transition cursor-pointer ${
                filterClass === chip.id
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-semibold'
                  : 'bg-slate-900/60 text-slate-400 hover:text-slate-200 border border-slate-800'
              }`}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      {/* Incidents Table / List */}
      <div className="divide-y divide-slate-800/60">
        {isLoading && (
          <div className="p-8 text-center text-xs text-slate-400 flex items-center justify-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
            <span>Loading telemetry and recorded incidents...</span>
          </div>
        )}

        {!isLoading && filteredIncidents.length === 0 && (
          <div className="p-8 text-center text-xs text-slate-400">
            No incidents matched your query.
          </div>
        )}

        {!isLoading &&
          filteredIncidents.map((inc) => {
            const statusConfig = getStatusBadge(inc.status);
            const StatusIcon = statusConfig.icon;
            const confPercent = Math.round((inc.confidence || 0) * 100);

            return (
              <div
                key={inc.incident_id}
                onClick={() => onSelectIncident(inc)}
                className="p-4 hover:bg-slate-800/40 transition cursor-pointer flex flex-col md:flex-row md:items-center justify-between gap-3 group"
              >
                <div className="space-y-1.5 max-w-3xl">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-bold text-white group-hover:text-emerald-300 transition">
                      {inc.incident_id}
                    </span>
                    <span
                      className={`px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase rounded-md border ${getClassificationBadge(
                        inc.classification
                      )}`}
                    >
                      {inc.classification.replace('_', ' ')}
                    </span>
                    <span
                      className={`px-2 py-0.5 text-[10px] font-medium rounded-md border flex items-center gap-1 ${statusConfig.bg}`}
                    >
                      <StatusIcon className="w-3 h-3" />
                      {statusConfig.label}
                    </span>
                    {inc.service && (
                      <span className="text-[11px] text-slate-500 font-mono">
                        {inc.service}
                      </span>
                    )}
                  </div>

                  <p className="text-xs text-slate-300 line-clamp-2 leading-relaxed">
                    {inc.summary || 'Incident recorded; awaiting RCA completion.'}
                  </p>

                  <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500 pt-0.5">
                    {inc.suspected_location && (
                      <span className="flex items-center gap-1 font-mono text-slate-400">
                        <Code2 className="w-3 h-3 text-sky-400" />
                        {inc.suspected_location.file}:{inc.suspected_location.line}
                      </span>
                    )}
                    {inc.ticket_key && (
                      <span className="flex items-center gap-1 font-mono text-blue-400">
                        <Ticket className="w-3 h-3" />
                        {inc.ticket_key}
                      </span>
                    )}
                    {inc.pr_branch && (
                      <span className="flex items-center gap-1 font-mono text-purple-400">
                        <GitPullRequest className="w-3 h-3" />
                        {inc.pr_branch}
                      </span>
                    )}
                    {inc.detected_at && (
                      <span>{new Date(inc.detected_at).toLocaleString()}</span>
                    )}
                  </div>
                </div>

                {/* Confidence Bar & Action */}
                <div className="flex items-center gap-4 self-end md:self-center shrink-0">
                  <div className="w-24 text-right">
                    <div className="flex items-center justify-between text-[10px] mb-1">
                      <span className="text-slate-400">Confidence</span>
                      <span
                        className={`font-mono font-bold ${
                          confPercent >= 70
                            ? 'text-emerald-400'
                            : confPercent >= 50
                            ? 'text-amber-400'
                            : 'text-slate-400'
                        }`}
                      >
                        {confPercent}%
                      </span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          confPercent >= 70
                            ? 'bg-emerald-500'
                            : confPercent >= 50
                            ? 'bg-amber-500'
                            : 'bg-slate-600'
                        }`}
                        style={{ width: `${confPercent}%` }}
                      />
                    </div>
                  </div>

                  <span className="text-slate-600 group-hover:text-slate-300 transition">
                    <ExternalLink className="w-4 h-4" />
                  </span>
                </div>
              </div>
            );
          })}
      </div>
    </section>
  );
};
