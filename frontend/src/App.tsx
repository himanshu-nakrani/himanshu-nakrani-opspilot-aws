import React, { useState } from 'react';
import { Incident } from './types';
import { useDashboardData } from './hooks/useDashboardData';
import { Header } from './components/Header';
import { StatsCards } from './components/StatsCards';
import { ArchitectureBanner } from './components/ArchitectureBanner';
import { IncidentList } from './components/IncidentList';
import { IncidentDetailModal } from './components/IncidentDetailModal';
import { TriggerSimulationModal } from './components/TriggerSimulationModal';
import { EvalsModal } from './components/EvalsModal';
import { AgentCoreDrawer } from './components/AgentCoreDrawer';
import { ErrorBoundary } from './components/ErrorBoundary';
import { formatRelative } from './lib/format';

type Overlay = { kind: 'incident'; incident: Incident } | { kind: 'trigger' } | { kind: 'evals' } | { kind: 'agentcore' } | null;

export const App: React.FC = () => {
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [overlay, setOverlay] = useState<Overlay>(null);
  const data = useDashboardData(autoRefresh);
  const close = () => setOverlay(null);

  const handleSimulationSuccess = (newIncident: Incident) => {
    data.upsertIncident(newIncident);
    data.reloadStats();
    setOverlay({ kind: 'incident', incident: newIncident });
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        onTriggerSimulation={() => setOverlay({ kind: 'trigger' })}
        onOpenEvals={() => setOverlay({ kind: 'evals' })}
        onOpenAgentCore={() => setOverlay({ kind: 'agentcore' })}
        onRefresh={data.refresh}
        isRefreshing={data.isManualRefreshing}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <StatsCards stats={data.stats} onOpenAgentCore={() => setOverlay({ kind: 'agentcore' })} />

        <ArchitectureBanner />

        <section className="space-y-3" aria-labelledby="incident-stream-heading">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 id="incident-stream-heading" className="text-sm font-semibold tracking-wide text-white uppercase">
                Incident Stream &amp; Audit Trail
              </h2>
              <p className="text-xs text-slate-400">Alarms deduplicated and analyzed with cited evidence</p>
            </div>
            <span className="text-xs text-slate-400 font-mono" aria-live="polite">
              {data.incidents.length} incidents
              {data.lastUpdated && ` · updated ${formatRelative(data.lastUpdated.toISOString())}`}
            </span>
          </div>

          <IncidentList
            incidents={data.incidents}
            onSelectIncident={(incident) => setOverlay({ kind: 'incident', incident })}
            isLoading={data.isInitialLoading}
            error={data.error}
            onRetry={data.refresh}
          />
        </section>
      </main>

      <footer className="border-t border-slate-900 bg-slate-950/80 py-6 text-center text-xs text-slate-400">
        <p>OpsPilot — Autonomous SRE Monitoring &amp; Remediation Agent (proof of concept)</p>
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
