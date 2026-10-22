import React, { useEffect, useState } from 'react';
import { Incident } from './types';
import { useDashboardData } from './hooks/useDashboardData';
import { Header } from './components/Header';
import { StatsCards } from './components/StatsCards';
import { ArchitectureBanner } from './components/ArchitectureBanner';
import { BuildProgress } from './components/BuildProgress';
import { CheckpointBanner } from './components/CheckpointBanner';
import { IncidentBreakdown } from './components/IncidentBreakdown';
import { IncidentList } from './components/IncidentList';
import { WipTicketsPage } from './components/WipTicketsPage';
import { CheckpointIncidentDetailModal } from './components/CheckpointIncidentDetailModal';
import { CheckpointTriggerModal } from './components/CheckpointTriggerModal';
import { WipTeaserModal } from './components/WipTeaserModal';
import { ErrorBoundary } from './components/ErrorBoundary';

type Overlay =
  | { kind: 'incident'; incident: Incident }
  | { kind: 'trigger' }
  | { kind: 'evals' }
  | { kind: 'agentcore' }
  | { kind: 'runs' }
  | null;

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
    document.title = page === 'tickets' ? 'Tickets · OpsPilot (CP1)' : 'Incidents · OpsPilot (CP1)';
  }, [page]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const [filterClass, setFilterClass] = useState<string>('all');
  const data = useDashboardData(autoRefresh);
  const close = () => setOverlay(null);

  const handlePreviewIncident = (newIncident: Incident) => {
    data.upsertIncident(newIncident);
    data.reloadStats();
    setOverlay({ kind: 'incident', incident: newIncident });
  };

  return (
    <div className="min-h-screen flex flex-col bg-ink-950">
      <a
        href={page === 'tickets' ? '#tickets-wip-heading' : '#incident-stream-heading'}
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
        <CheckpointBanner />

        {page === 'incidents' && <StatsCards stats={data.stats} checkpointMode />}

        {page === 'tickets' ? (
          <WipTicketsPage />
        ) : (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px] items-start">
            <section aria-labelledby="incident-stream-heading" className="min-w-0 space-y-3">
              <div className="flex items-baseline justify-between gap-3">
                <div>
                  <h2
                    id="incident-stream-heading"
                    tabIndex={-1}
                    className="text-[15px] font-semibold tracking-[-0.015em] text-ink-50 focus:outline-none"
                  >
                    Incident stream
                  </h2>
                  <p className="text-xs text-ink-500 mt-0.5">Sample data · live ingest in Checkpoint 2</p>
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

            <aside className="grid gap-6 sm:grid-cols-2 xl:grid-cols-1 rounded-lg border border-ink-800 bg-ink-900/60 p-5 [&>*+*]:sm:border-l [&>*+*]:sm:pl-6 [&>*+*]:xl:border-l-0 [&>*+*]:xl:pl-0 [&>*+*]:xl:border-t [&>*+*]:xl:pt-6 [&>*+*]:border-ink-800 [&>*+*]:border-t [&>*+*]:pt-6 [&>*+*]:sm:border-t-0 [&>*+*]:sm:pt-0">
              <IncidentBreakdown incidents={data.incidents} activeClass={filterClass} onSelectClass={setFilterClass} />
              <BuildProgress />
              <ArchitectureBanner />
            </aside>
          </div>
        )}
      </main>

      <footer className="border-t border-ink-800 bg-ink-950">
        <div className="px-4 sm:px-6 h-9 flex items-center gap-4 font-mono text-2xs text-ink-400 overflow-x-auto whitespace-nowrap [scrollbar-width:none]">
          <span className="text-amber-200/90">Checkpoint 1 build</span>
          <span className="text-ink-700" aria-hidden="true">
            |
          </span>
          <span>Strands {data.stats?.strands_sdk_version ?? '…'}</span>
          <span className="tnum">{data.stats ? `${data.stats.agentcore_policies_active.length} policies (partial)` : '…'}</span>
          <span className="tnum">{data.stats ? `${data.stats.agentcore_gateway_tools.length}/4 gateway tools` : '…'}</span>
          <span className="ml-auto hidden sm:inline text-ink-500">OpsPilot · hackathon WIP</span>
        </div>
      </footer>

      <CheckpointIncidentDetailModal
        incident={overlay?.kind === 'incident' ? overlay.incident : null}
        onClose={close}
      />
      <CheckpointTriggerModal
        isOpen={overlay?.kind === 'trigger'}
        onClose={close}
        onPreviewIncident={handlePreviewIncident}
      />
      <WipTeaserModal
        isOpen={overlay?.kind === 'evals'}
        onClose={close}
        title="M6 eval suite"
        body="Golden fixture replay and target metrics are implemented in the full repo build. This checkpoint focuses on the RCA dashboard experience."
        checkpointTarget="Checkpoint 2 · GET /api/evals"
      />
      <WipTeaserModal
        isOpen={overlay?.kind === 'agentcore'}
        onClose={close}
        title="Agent runtime inspector"
        body="Policy and gateway tool inventory will open in a drawer once the backend stats endpoint is wired for demo day."
        checkpointTarget="Checkpoint 2 · AgentCore drawer"
      />
      <WipTeaserModal
        isOpen={overlay?.kind === 'runs'}
        onClose={close}
        title="Agent runs & traces"
        body="Span-level traces for model and tool calls ship with the full FastAPI backend. Checkpoint 1 shows RCA output only."
        checkpointTarget="Checkpoint 2 · /api/agent-runs"
      />
    </div>
  );
};

export const Root: React.FC = () => (
  <ErrorBoundary label="OpsPilot dashboard (Checkpoint 1)">
    <App />
  </ErrorBoundary>
);
