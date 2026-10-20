import React, { useState, useEffect, useCallback } from 'react';
import { fetchIncidents, fetchStats } from './api';
import { Incident, Stats } from './types';
import { Header } from './components/Header';
import { StatsCards } from './components/StatsCards';
import { ArchitectureBanner } from './components/ArchitectureBanner';
import { IncidentList } from './components/IncidentList';
import { IncidentDetailModal } from './components/IncidentDetailModal';
import { TriggerSimulationModal } from './components/TriggerSimulationModal';
import { EvalsModal } from './components/EvalsModal';
import { AgentCoreDrawer } from './components/AgentCoreDrawer';

export const App: React.FC = () => {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [isTriggerOpen, setIsTriggerOpen] = useState(false);
  const [isEvalsOpen, setIsEvalsOpen] = useState(false);
  const [isAgentCoreOpen, setIsAgentCoreOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [incidentsData, statsData] = await Promise.all([
        fetchIncidents(),
        fetchStats(),
      ]);
      setIncidents(incidentsData);
      setStats(statsData);
    } catch (error) {
      console.error('Error fetching dashboard data:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Periodic polling when autoRefresh is enabled
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      loadData();
    }, 10000);
    return () => clearInterval(interval);
  }, [autoRefresh, loadData]);

  const handleSimulationSuccess = (newIncident: Incident) => {
    setIncidents((prev) => [newIncident, ...prev.filter((i) => i.incident_id !== newIncident.incident_id)]);
    setSelectedIncident(newIncident);
    fetchStats().then(setStats).catch(console.error);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Header
        onTriggerSimulation={() => setIsTriggerOpen(true)}
        onOpenEvals={() => setIsEvalsOpen(true)}
        onOpenAgentCore={() => setIsAgentCoreOpen(true)}
        onRefresh={loadData}
        isLoading={isLoading}
        autoRefresh={autoRefresh}
        setAutoRefresh={setAutoRefresh}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* KPI Summary Cards */}
        <StatsCards stats={stats} onOpenAgentCore={() => setIsAgentCoreOpen(true)} />

        {/* Pipeline Architecture Banner */}
        <ArchitectureBanner />

        {/* Live Incident Stream */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold tracking-wide text-white uppercase">
                Live Incident Stream &amp; Audit Trail
              </h2>
              <p className="text-xs text-slate-400">
                Real-time alarms filtered, deduplicated, and analyzed with grounded evidence
              </p>
            </div>
            <span className="text-xs text-slate-500 font-mono">
              {incidents.length} incidents recorded
            </span>
          </div>

          <IncidentList
            incidents={incidents}
            onSelectIncident={setSelectedIncident}
            isLoading={isLoading && incidents.length === 0}
          />
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/80 py-6 text-center text-xs text-slate-500">
        <p>
          OpsPilot — Autonomous SRE Monitoring &amp; Remediation Agent • Built with AWS Strands Agents SDK &amp; Amazon Bedrock AgentCore
        </p>
      </footer>

      {/* Modals & Overlays */}
      <IncidentDetailModal
        incident={selectedIncident}
        onClose={() => setSelectedIncident(null)}
      />

      <TriggerSimulationModal
        isOpen={isTriggerOpen}
        onClose={() => setIsTriggerOpen(false)}
        onSimulationSuccess={handleSimulationSuccess}
      />

      <EvalsModal
        isOpen={isEvalsOpen}
        onClose={() => setIsEvalsOpen(false)}
      />

      <AgentCoreDrawer
        isOpen={isAgentCoreOpen}
        onClose={() => setIsAgentCoreOpen(false)}
      />
    </div>
  );
};
