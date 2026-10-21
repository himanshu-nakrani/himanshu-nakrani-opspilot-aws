import React, { useState } from 'react';
import { Incident } from './types';
import { useDashboardData } from './hooks/useDashboardData';
import { Header } from './components/Header';
import { StatsCards } from './components/StatsCards';
import { ArchitectureBanner } from './components/ArchitectureBanner';
import { IncidentBreakdown } from './components/IncidentBreakdown';
import { IncidentList } from './components/IncidentList';
import { IncidentDetailModal } from './components/IncidentDetailModal';
import { TriggerSimulationModal } from './components/TriggerSimulationModal';
import { EvalsModal } from './components/EvalsModal';
import { AgentCoreDrawer } from './components/AgentCoreDrawer';
import { ErrorBoundary } from './components/ErrorBoundary';

type Overlay = { kind: 'incident'; incident: Incident } | { kind: 'trigger' } | { kind: 'evals' } | { kind: 'agentcore' } | null;

export const App: React.FC = () => {
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

  return (
    <div className="min-h-screen flex flex-col bg-ink-950 bg-grid">
      <a
        href="#incident-stream-heading"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:px-3 focus:py-2 focus:rounded-md focus:bg-signal-400 focus:text-ink-950 focus:text-xs"
      >
        Skip to incidents
      </a>

      <Header
        onTriggerSimulation={() => setOverlay({ kind: 'trigger' })}
        onOpenEvals={() => setOverlay({ kind: 'evals' })}
        onOpenAgentCore={() => setOverlay({ kind: 'agentcore' })}
        onRefresh={data.refresh}
        isRefreshing={data.isManualRefreshing}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
        lastUpdated={data.lastUpdated}
        hasError={!!data.error}
      />

      <main className="flex-1 w-full max-w-[1440px] mx-auto px-4 sm:px-6 py-6 space-y-6">
        <StatsCards stats={data.stats} onOpenAgentCore={() => setOverlay({ kind: 'agentcore' })} />

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px] items-start">
          <section aria-labelledby="incident-stream-heading" className="min-w-0 space-y-3">
            <div className="flex items-baseline justify-between gap-3">
              <div>
                <h2 id="incident-stream-heading" tabIndex={-1} className="text-xl font-semibold tracking-[-0.025em] text-ink-50 focus:outline-none">
                  Incident stream
                </h2>
                <p className="text-xs text-ink-400">Deduplicated alarms, each analysed with cited evidence. Select one for the full audit trail.</p>
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

          <aside className="xl:sticky xl:top-20 grid gap-6 sm:grid-cols-2 xl:grid-cols-1 rounded-lg border border-ink-800 bg-ink-900 p-5 [&>*+*]:sm:border-l [&>*+*]:sm:pl-6 [&>*+*]:xl:border-l-0 [&>*+*]:xl:pl-0 [&>*+*]:xl:border-t [&>*+*]:xl:pt-6 [&>*+*]:border-ink-800 [&>*+*]:border-t [&>*+*]:pt-6 [&>*+*]:sm:border-t-0 [&>*+*]:sm:pt-0">
            <IncidentBreakdown incidents={data.incidents} activeClass={filterClass} onSelectClass={setFilterClass} />
            <ArchitectureBanner />
          </aside>
        </div>
      </main>

      <footer className="border-t border-ink-800 px-4 sm:px-6 py-4 flex flex-wrap items-center justify-between gap-2 text-2xs text-ink-500">
        <p>OpsPilot — autonomous SRE monitoring &amp; remediation agent · proof of concept</p>
        <p className="font-mono">
          Press <kbd className="px-1 rounded border border-ink-700 text-ink-400">/</kbd> to search
        </p>
      </footer>

      <IncidentDetailModal incident={overlay?.kind === 'incident' ? overlay.incident : null} onClose={close} />
      <TriggerSimulationModal
        isOpen={overlay?.kind === 'trigger'}
        onClose={close}
        onSimulationSuccess={handleSimulationSuccess}
      />
      <EvalsModal isOpen={overlay?.kind === 'evals'} onClose={close} />
      <AgentCoreDrawer isOpen={overlay?.kind === 'agentcore'} onClose={close} stats={data.stats} />
    </div>
  );
};

export const Root: React.FC = () => (
  <ErrorBoundary label="OpsPilot dashboard">
    <App />
  </ErrorBoundary>
);
