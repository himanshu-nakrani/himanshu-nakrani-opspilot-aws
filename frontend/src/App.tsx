import React, { useEffect, useState } from 'react';
import { Incident } from './types';
import { useDashboardData } from './hooks/useDashboardData';
import { Header } from './components/Header';
import { StatsCards } from './components/StatsCards';
import { ArchitectureBanner } from './components/ArchitectureBanner';
import { IncidentBreakdown } from './components/IncidentBreakdown';
import { IncidentList } from './components/IncidentList';
import { TicketsPage } from './components/TicketsPage';
import { IncidentDetailModal } from './components/IncidentDetailModal';
import { TriggerSimulationModal } from './components/TriggerSimulationModal';
import { EvalsModal } from './components/EvalsModal';
import { AgentCoreDrawer } from './components/AgentCoreDrawer';
import { AgentRunsModal } from './components/AgentRunsModal';
import { ErrorBoundary } from './components/ErrorBoundary';

type Overlay = { kind: 'incident'; incident: Incident } | { kind: 'trigger' } | { kind: 'evals' } | { kind: 'agentcore' } | { kind: 'runs' } | null;

function usePage(): [string, (path: string) => void] {
  const [path, setPath] = useState(() => window.location.pathname);
  useEffect(() => {
    const sync = () => setPath(window.location.pathname);
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);
  const navigate = (next: string) => {
    if (window.location.pathname !== next) window.history.pushState({}, '', next);
    setPath(next);
  };
  return [path, navigate];
}

export const App: React.FC = () => {
  const [path, navigate] = usePage();
  const page = path === '/tickets' ? 'tickets' : 'incidents';

  useEffect(() => {
    document.title = page === 'tickets' ? 'Tickets · OpsPilot' : 'Incidents · OpsPilot';
  }, [page]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [filterClass, setFilterClass] = useState<string>('all');
  const data = useDashboardData(autoRefresh);
  const close = () => setOverlay(null);

  const handleSimulationSuccess = (newIncident: Incident) => {
    data.upsertIncident(newIncident);
    data.reloadStats();
    setOverlay({ kind: 'incident', incident: newIncident });
  };

  const handleBatchComplete = (incidents: Incident[]) => {
    incidents.forEach((i) => data.upsertIncident(i));
    data.reloadStats();
  };

  return (
    <div className="min-h-screen flex flex-col bg-ink-950">
      <a
        href={page === 'tickets' ? '#tickets-heading' : '#incident-stream-heading'}
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:px-3 focus:py-2 focus:rounded-md focus:bg-ink-50 focus:text-ink-950 focus:text-xs"
      >
        {page === 'tickets' ? 'Skip to tickets' : 'Skip to incidents'}
      </a>

      <Header
        page={page}
        onNavigate={navigate}
        onTriggerSimulation={() => setOverlay({ kind: 'trigger' })}
        onOpenEvals={() => setOverlay({ kind: 'evals' })}
        onOpenAgentCore={() => setOverlay({ kind: 'agentcore' })}
        onOpenRuns={() => setOverlay({ kind: 'runs' })}
        onRefresh={data.refresh}
        isRefreshing={data.isManualRefreshing}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
        lastUpdated={data.lastUpdated}
        hasError={!!data.error}
      />

      <main className="flex-1 w-full max-w-[1440px] mx-auto px-4 sm:px-6 py-6 space-y-6">
        {page === 'incidents' && <StatsCards stats={data.stats} />}

        {page === 'tickets' ? (
          <TicketsPage
            onOpenIncident={(incidentId) => {
              const incident = data.incidents.find((item) => item.incident_id === incidentId);
              if (incident) setOverlay({ kind: 'incident', incident });
            }}
          />
        ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px] items-start">
          <section aria-labelledby="incident-stream-heading" className="min-w-0 space-y-3">
            <div className="flex items-baseline justify-between gap-3">
              <div>
                <h2 id="incident-stream-heading" tabIndex={-1} className="text-[15px] font-semibold tracking-[-0.015em] text-ink-50 focus:outline-hidden">
                  Incident stream
                </h2>
              </div>
            </div>

            <IncidentList
              incidents={data.incidents}
              onSelectIncident={(incident) => setOverlay({ kind: 'incident', incident })}
              isLoading={data.isInitialLoading}
              error={data.error}
              onRetry={data.refresh}
              filterClass={filterClass}
              onFilterClassChange={setFilterClass}
            />
          </section>

          <aside className="grid gap-6 sm:grid-cols-2 xl:grid-cols-1 rounded-lg border border-ink-800 bg-ink-900/60 p-5 sm:[&>*+*]:border-l sm:[&>*+*]:pl-6 xl:[&>*+*]:border-l-0 xl:[&>*+*]:pl-0 xl:[&>*+*]:border-t xl:[&>*+*]:pt-6 [&>*+*]:border-ink-800 [&>*+*]:border-t [&>*+*]:pt-6 sm:[&>*+*]:border-t-0 sm:[&>*+*]:pt-0">
            <IncidentBreakdown incidents={data.incidents} activeClass={filterClass} onSelectClass={setFilterClass} />
            <ArchitectureBanner />
          </aside>
        </div>
        )}
      </main>

      <footer className="border-t border-ink-800 bg-ink-950">
        <div className="px-4 sm:px-6 h-9 flex items-center gap-4 font-mono text-2xs text-ink-400 overflow-x-auto whitespace-nowrap scrollbar-none">
          <button
            type="button"
            onClick={() => setOverlay({ kind: 'agentcore' })}
            className="inline-flex items-center gap-1.5 hover:text-ink-100 transition-colors focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-signal-400 rounded-xs"
            title="Inspect Strands SDK and AgentCore configuration"
          >
            <span className={`w-1.5 h-1.5 rounded-full ${data.stats?.strands_sdk_version ? 'bg-ok-400' : 'bg-ink-600'}`} aria-hidden="true" />
            Strands {data.stats?.strands_sdk_version ?? '…'}
          </button>
          <span className="text-ink-700" aria-hidden="true">|</span>
          <span>AgentCore</span>
          <span className="tnum">{data.stats ? `${data.stats.agentcore_policies_active.length} policies` : '…'}</span>
          <span className="tnum">{data.stats ? `${data.stats.agentcore_gateway_tools.length} gateway tools` : '…'}</span>
          <span className="ml-auto hidden sm:inline text-ink-500">
            OpsPilot · proof of concept · <kbd className="px-1 rounded-xs border border-ink-700 text-ink-300">/</kbd> search
          </span>
        </div>
      </footer>

      <IncidentDetailModal
        incident={overlay?.kind === 'incident' ? overlay.incident : null}
        onClose={close}
        onUpdated={(incident) => {
          data.upsertIncident(incident);
          data.reloadStats();
          setOverlay({ kind: 'incident', incident });
        }}
      />
      <TriggerSimulationModal
        isOpen={overlay?.kind === 'trigger'}
        onClose={close}
        onSimulationSuccess={handleSimulationSuccess}
        onBatchComplete={handleBatchComplete}
      />
      <EvalsModal isOpen={overlay?.kind === 'evals'} onClose={close} />
      <AgentRunsModal isOpen={overlay?.kind === 'runs'} onClose={close} />
      <AgentCoreDrawer isOpen={overlay?.kind === 'agentcore'} onClose={close} stats={data.stats} />
    </div>
  );
};

export const Root: React.FC = () => (
  <ErrorBoundary label="OpsPilot dashboard">
    <App />
  </ErrorBoundary>
);
