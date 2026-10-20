import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage, fetchIncidents, fetchStats, isAbortError } from '../api';
import { Incident, Stats } from '../types';

const POLL_MS = 10_000;

export interface DashboardData {
  incidents: Incident[];
  stats: Stats | null;
  /** true only until the first successful load */
  isInitialLoading: boolean;
  /** true while a user-initiated refresh is in flight */
  isManualRefreshing: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refresh: () => void;
  upsertIncident: (incident: Incident) => void;
  reloadStats: () => void;
}

/**
 * Loads incidents + stats, then polls while autoRefresh is on.
 * - single-flight: a poll never overlaps a running request
 * - aborts in-flight requests on unmount
 * - pauses while the tab is hidden, refreshes when it becomes visible
 * - keeps the last good data on error and exposes the error separately
 */
export function useDashboardData(autoRefresh: boolean): DashboardData {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [isManualRefreshing, setIsManualRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const inFlight = useRef<AbortController | null>(null);

  const load = useCallback(async (manual: boolean) => {
    if (inFlight.current) {
      if (!manual) return; // background poll: skip, a request is already running
      inFlight.current.abort();
    }
    const controller = new AbortController();
    inFlight.current = controller;
    setIsFetching(true);
    if (manual) setIsManualRefreshing(true);
    try {
      const [incidentsData, statsData] = await Promise.all([
        fetchIncidents(controller.signal),
        fetchStats(controller.signal),
      ]);
      setIncidents(incidentsData);
      setStats(statsData);
      setError(null);
      setHasLoaded(true);
      setLastUpdated(new Date());
    } catch (e) {
      if (!isAbortError(e)) setError(errorMessage(e, 'Failed to load dashboard data'));
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
        setIsFetching(false);
        setIsManualRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    load(true);
    return () => inFlight.current?.abort();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const tick = () => {
      if (document.visibilityState === 'visible') load(false);
    };
    const id = window.setInterval(tick, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') load(false);
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [autoRefresh, load]);

  const upsertIncident = useCallback((incident: Incident) => {
    setIncidents((prev) => [incident, ...prev.filter((i) => i.incident_id !== incident.incident_id)]);
  }, []);

  const reloadStats = useCallback(() => {
    fetchStats()
      .then(setStats)
      .catch((e) => setError(errorMessage(e, 'Failed to refresh stats')));
  }, []);

  return {
    incidents,
    stats,
    isInitialLoading: !hasLoaded && isFetching && !error,
    isManualRefreshing,
    error,
    lastUpdated,
    refresh: () => load(true),
    upsertIncident,
    reloadStats,
  };
}
