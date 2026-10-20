import React, { useEffect, useState } from 'react';
import { ExternalLink, FileCode, GitBranch, ListChecks, Ticket } from 'lucide-react';
import { Incident } from '../types';
import { errorMessage, fetchIncident, isAbortError } from '../api';
import { classificationBadge, confidenceTone, severityBadge, SOURCE_LABEL, statusBadge } from '../lib/badges';
import { formatTimestamp, humanize } from '../lib/format';
import { Modal } from './Modal';

interface IncidentDetailModalProps {
  incident: Incident | null;
  onClose: () => void;
}

const sectionTitle = 'text-xs font-semibold uppercase tracking-wider text-slate-300 mb-2';

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-slate-300 font-semibold';
  if (line.startsWith('+')) return 'text-emerald-300 bg-emerald-500/10';
  if (line.startsWith('-')) return 'text-red-300 bg-red-500/10';
  if (line.startsWith('@@')) return 'text-sky-300';
  return 'text-slate-300';
}

export const IncidentDetailModal: React.FC<IncidentDetailModalProps> = ({ incident: initial, onClose }) => {
  const [incident, setIncident] = useState<Incident | null>(initial);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  // Show the list copy immediately, then load the current record so status/PR fields are fresh.
  useEffect(() => {
    setIncident(initial);
    setRefreshError(null);
    if (!initial) return;
    const controller = new AbortController();
    fetchIncident(initial.incident_id, controller.signal)
      .then(setIncident)
      .catch((e) => {
        if (!isAbortError(e)) setRefreshError(errorMessage(e));
      });
    return () => controller.abort();
  }, [initial]);

  if (!incident) return null;

  const status = statusBadge(incident.status);
  const StatusIcon = status.icon;
  const pct = incident.confidence === null || incident.confidence === undefined ? null : Math.round(incident.confidence * 100);
  const tone = confidenceTone(pct);
  const evidence = incident.evidence ?? [];
  const loc = incident.suspected_location;

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={<span className="font-mono">{incident.incident_id}</span>}
      description={
        <>
          {incident.service ?? 'unknown service'} ·{' '}
          <time dateTime={incident.detected_at ?? undefined}>{formatTimestamp(incident.detected_at)}</time>
          {incident.source && incident.source !== 'dynamodb' && <> · {SOURCE_LABEL[incident.source]}</>}
        </>
      }
    >
      {refreshError && (
        <p role="status" className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-lg p-2">
          Could not load the latest version of this incident; showing cached data. {refreshError}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className={`px-2 py-0.5 text-xs rounded-md border ${classificationBadge(incident.classification)}`}>
          {humanize(incident.classification)}
        </span>
        <span className={`px-2 py-0.5 text-xs rounded-md border flex items-center gap-1 ${status.className}`}>
          <StatusIcon className="w-3.5 h-3.5" aria-hidden="true" />
          {status.label}
        </span>
        {incident.severity && (
          <span className={`px-2 py-0.5 text-xs rounded-md border uppercase ${severityBadge(incident.severity)}`}>
            {incident.severity}
          </span>
        )}
        <span className={`ml-auto text-sm font-semibold ${tone.text}`}>Confidence {pct === null ? 'n/a' : `${pct}%`}</span>
      </div>

      <section>
        <h3 className={sectionTitle}>Root-cause summary</h3>
        <p className="text-sm text-slate-200 leading-relaxed">{incident.summary || 'No summary available.'}</p>
      </section>

      <div className="grid md:grid-cols-2 gap-4">
        <section className="p-4 rounded-xl bg-slate-950/50 border border-slate-800">
          <h3 className={sectionTitle}>
            <FileCode className="inline w-3.5 h-3.5 mr-1" aria-hidden="true" />
            Suspected location
          </h3>
          {loc ? (
            <p className="font-mono text-xs text-slate-200 break-all">
              {loc.file}:{loc.line}
              {loc.function && <span className="text-slate-400"> in {loc.function}()</span>}
            </p>
          ) : (
            <p className="text-xs text-slate-400">Not identified.</p>
          )}
        </section>
        <section className="p-4 rounded-xl bg-slate-950/50 border border-slate-800">
          <h3 className={sectionTitle}>Suggested fix strategy</h3>
          <p className="text-xs text-slate-200">{incident.suggested_fix_strategy || 'None proposed.'}</p>
        </section>
      </div>

      <section>
        <h3 className={sectionTitle}>
          <ListChecks className="inline w-3.5 h-3.5 mr-1" aria-hidden="true" />
          Evidence cited ({evidence.length})
        </h3>
        {evidence.length > 0 ? (
          <ul className="space-y-2">
            {evidence.map((ev, i) => (
              <li key={`${ev.ref}-${i}`} className="p-3 rounded-lg bg-slate-950/50 border border-slate-800 text-xs">
                <div className="flex flex-wrap gap-2 text-slate-400 font-mono">
                  <span className="uppercase">{humanize(ev.kind)}</span>
                  <span className="break-all">{ev.ref}</span>
                </div>
                <p className="text-slate-200 mt-1">{ev.claim}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-400">No evidence items recorded.</p>
        )}
        {incident.ruled_out && incident.ruled_out.length > 0 && (
          <div className="mt-3">
            <h4 className="text-xs text-slate-300 mb-1">Ruled out</h4>
            <ul className="list-disc pl-5 text-xs text-slate-300 space-y-0.5">
              {incident.ruled_out.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {incident.patch_diff && (
        <section>
          <h3 className={sectionTitle}>Proposed patch</h3>
          <pre className="text-xs font-mono rounded-xl bg-slate-950 border border-slate-800 p-3 overflow-x-auto">
            {incident.patch_diff.split('\n').map((line, idx) => (
              <div key={idx} className={`px-1 ${diffLineClass(line)}`}>
                {line || ' '}
              </div>
            ))}
          </pre>
        </section>
      )}

      {(incident.ticket_key || incident.pr_branch) && (
        <section className="flex flex-wrap gap-3 text-xs">
          {incident.ticket_key && (
            <LinkOrLabel url={incident.ticket_url} icon={<Ticket className="w-3.5 h-3.5" aria-hidden="true" />}>
              {incident.ticket_key}
            </LinkOrLabel>
          )}
          {incident.pr_branch && (
            <LinkOrLabel url={incident.pr_url} icon={<GitBranch className="w-3.5 h-3.5" aria-hidden="true" />}>
              {incident.pr_branch}
            </LinkOrLabel>
          )}
          {!incident.ticket_url && !incident.pr_url && (
            <span className="text-slate-400 self-center">No ticket or PR was created for this {incident.source === 'dynamodb' ? 'incident' : 'demo record'}.</span>
          )}
        </section>
      )}
    </Modal>
  );
};

const LinkOrLabel: React.FC<{ url?: string | null; icon: React.ReactNode; children: React.ReactNode }> = ({ url, icon, children }) => {
  const cls = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/60 font-mono text-slate-200';
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className={`${cls} hover:bg-slate-700`}>
      {icon}
      {children}
      <ExternalLink className="w-3 h-3" aria-hidden="true" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  ) : (
    <span className={cls}>
      {icon}
      {children}
    </span>
  );
};
