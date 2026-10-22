import React, { useEffect, useMemo, useState } from 'react';
import { ExternalLink, Search } from 'lucide-react';
import { fetchTickets, errorMessage, isAbortError } from '../api';
import { classificationBadge, opsSeverity, severityBadge, ticketStatusBadge } from '../lib/badges';
import { formatRelative, formatTimestamp, humanize } from '../lib/format';
import { badge, btn, eyebrow, focusRing } from '../ui/styles';
import { Ticket, TicketList, TicketView } from '../types';

interface TicketsPageProps {
  onOpenIncident: (incidentId: string) => void;
}

const VIEWS: { id: TicketView; label: string }[] = [
  { id: 'open', label: 'Open' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'resolved', label: 'Resolved' },
  { id: 'all', label: 'All' },
];

function matches(ticket: Ticket, query: string): boolean {
  if (!query) return true;
  const hay = [ticket.key, ticket.title, ticket.incident_id, ticket.classification].filter(Boolean).join(' ').toLowerCase();
  return hay.includes(query);
}

export const TicketsPage: React.FC<TicketsPageProps> = ({ onOpenIncident }) => {
  const [view, setView] = useState<TicketView>('open');
  const [data, setData] = useState<TicketList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchTickets(view, controller.signal)
      .then((next) => {
        setData(next);
        setError(null);
      })
      .catch((e) => {
        if (!isAbortError(e)) setError(errorMessage(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [view]);

  const q = query.trim().toLowerCase();
  const tickets = useMemo(() => (data?.tickets ?? []).filter((ticket) => matches(ticket, q)), [data, q]);
  const recorded = useMemo(() => (data?.recorded ?? []).filter((ticket) => matches(ticket, q)), [data, q]);

  return (
    <section aria-labelledby="tickets-heading" className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="tickets-heading" tabIndex={-1} className="text-[15px] font-semibold tracking-[-0.015em] text-ink-50 focus:outline-none">
            Tickets
          </h2>
          <p className="mt-1 text-xs text-ink-400 max-w-xl">
            Systems Manager OpsCenter is the ticket. A live alarm files one OpsItem. The dashboard simulation only stores a label until that happens.
          </p>
        </div>
        <label className="relative w-full sm:w-64">
          <span className="sr-only">Search tickets</span>
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-500" aria-hidden="true" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search tickets"
            className={`w-full h-8 pl-8 pr-2 rounded-md border border-ink-800 bg-ink-950 text-xs text-ink-100 placeholder:text-ink-500 ${focusRing}`}
          />
        </label>
      </div>

      <div role="group" aria-label="Filter tickets" className="flex gap-0.5 p-0.5 rounded-md border border-ink-800 bg-ink-950 w-fit">
        {VIEWS.map((item) => {
          const active = view === item.id;
          const count = data?.counts?.[item.id];
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={active}
              onClick={() => setView(item.id)}
              className={`h-7 px-2.5 inline-flex items-center gap-1.5 text-xs rounded-[5px] border transition-colors ${focusRing} ${
                active ? 'bg-ink-800 text-ink-50 border-ink-700' : 'bg-transparent text-ink-400 border-transparent hover:text-ink-100'
              }`}
            >
              {item.label}
              <span className={`font-mono text-2xs tnum ${active ? 'text-ink-300' : 'text-ink-600'}`}>{count ?? '…'}</span>
            </button>
          );
        })}
      </div>

      {data?.opscenter_error && (
        <p role="status" className="text-xs text-amber-200 bg-amber-500/10 border border-amber-400/30 rounded-md px-3 py-2">
          OpsCenter could not be listed. Ticket labels already on incidents are still shown. {data.opscenter_error}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-red-200 bg-red-500/10 border border-red-500/30 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      <TicketSection
        title="OpsCenter"
        empty={loading ? 'Loading tickets…' : q ? 'No OpsCenter tickets match this search.' : 'No OpsCenter tickets in this view.'}
        tickets={loading ? [] : tickets}
        onOpenIncident={onOpenIncident}
      />

      <TicketSection
        title="Recorded on incidents"
        hint="Ticket ids stored on incidents in this dashboard. A filed OpsItem also appears in the OpsCenter list."
        empty={loading ? '' : q ? 'No recorded tickets match this search.' : 'No ticket labels on the current incidents.'}
        tickets={loading ? [] : recorded}
        onOpenIncident={onOpenIncident}
      />
    </section>
  );
};

const TicketSection: React.FC<{
  title: string;
  hint?: string;
  empty: string;
  tickets: Ticket[];
  onOpenIncident: (incidentId: string) => void;
}> = ({ title, hint, empty, tickets, onOpenIncident }) => (
  <div className="rounded-lg border border-ink-800 bg-ink-900/60">
    <div className="px-4 py-3 border-b border-ink-800">
      <h3 className={eyebrow}>{title}</h3>
      
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
    {tickets.length === 0 ? (
      empty ? <p className="px-4 py-8 text-xs text-ink-400">{empty}</p> : null
    ) : (
      <ul className="divide-y divide-ink-800">
        {tickets.map((ticket) => (
          <TicketRow key={`${ticket.source}-${ticket.key}`} ticket={ticket} onOpenIncident={onOpenIncident} />
        ))}
      </ul>
    )}
  </div>
);

const TicketRow: React.FC<{ ticket: Ticket; onOpenIncident: (incidentId: string) => void }> = ({ ticket, onOpenIncident }) => {
  const status = ticketStatusBadge(ticket.status);
  const StatusIcon = status.icon;
  const sev = opsSeverity(ticket.severity);
  return (
    <li className="px-4 py-3 flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-ink-100">{ticket.key}</span>
          <span className={`${badge} ${status.className}`}>
            <StatusIcon className="w-3.5 h-3.5" aria-hidden="true" />
            {status.label}
          </span>
          {sev && <span className={`${badge} uppercase ${severityBadge(sev)}`}>{sev}</span>}
          {ticket.classification && (
            <span className={`${badge} ${classificationBadge(ticket.classification)}`}>
              {humanize(ticket.classification)}
            </span>
          )}
        </div>
        <p className="text-[13px] text-ink-100 leading-snug">{ticket.title}</p>
        <p className="text-2xs text-ink-500 font-mono">
          {ticket.created_at ? formatTimestamp(ticket.created_at) : 'Unknown time'}
          {ticket.created_at ? ` · ${formatRelative(ticket.created_at)}` : ''}
          {ticket.incident_id ? ` · ${ticket.incident_id}` : ''}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {ticket.incident_id && (
          <button
            type="button"
            onClick={() => onOpenIncident(ticket.incident_id as string)}
            className={btn.secondary}
          >
            Incident
          </button>
        )}
        {ticket.url && (
          <a
            href={ticket.url}
            target="_blank"
            rel="noopener noreferrer"
            className={btn.secondary}
          >
            OpsCenter
            <ExternalLink className="w-3 h-3" aria-hidden="true" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </div>
    </li>
  );
};
