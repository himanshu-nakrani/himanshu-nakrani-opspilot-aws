import { useCallback, useEffect, useState } from 'react';
import { CHECKPOINT_DEMO_INCIDENTS, CHECKPOINT_DEMO_STATS } from '../data/checkpointDemo';
import { Incident, Stats } from '../types';

const POLL_MS = 15_000;

export interface DashboardData {
  incidents: Incident[];
  stats: Stats | null;
  isInitialLoading: boolean;
  isManualRefreshing: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refresh: () => void;
  upsertIncident: (incident: Incident) => void;
  reloadStats: () => void;
}

/** Checkpoint 1: demo incidents with optional slow refresh animation (no API dependency). */
export function useDashboardData(autoRefresh: boolean): DashboardData {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [isManualRefreshing, setIsManualRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const load = useCallback((manual: boolean) => {
    if (manual) setIsManualRefreshing(true);
    window.setTimeout(() => {
      setIncidents((prev) => {
        const seedIds = new Set(CHECKPOINT_DEMO_INCIDENTS.map((item) => item.incident_id));
        const extras = prev.filter((item) => !seedIds.has(item.incident_id));
        const next = [...extras, ...CHECKPOINT_DEMO_INCIDENTS];
        setStats({ ...CHECKPOINT_DEMO_STATS, total_incidents: next.length });
        return next;
      });
      setHasLoaded(true);
      setLastUpdated(new Date());
      setIsManualRefreshing(false);
    }, manual ? 320 : 180);
  }, []);

  useEffect(() => {
    load(true);
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') load(false);
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [autoRefresh, load]);

  const upsertIncident = useCallback((incident: Incident) => {
    setIncidents((prev) => {
      const next = [incident, ...prev.filter((i) => i.incident_id !== incident.incident_id)];
      setStats((s) => (s ? { ...s, total_incidents: next.length } : s));
      return next;
    });
  }, []);

  const reloadStats = useCallback(() => {
    setStats({ ...CHECKPOINT_DEMO_STATS, total_incidents: incidents.length || CHECKPOINT_DEMO_INCIDENTS.length });
  }, [incidents.length]);

  return {
    incidents,
    stats,
    isInitialLoading: !hasLoaded,
    isManualRefreshing,
    error: null,
    lastUpdated,
    refresh: () => load(true),
    upsertIncident,
    reloadStats,
  };
}
