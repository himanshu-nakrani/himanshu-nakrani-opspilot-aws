import { AgentRun, AgentRunSummary, EvalsReport, Incident, Scenario, Stats, TriggerResponse } from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(`Cannot reach the OpsPilot API (${path}). Is the dashboard server running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(`${path} failed: ${res.status} ${detail}`.trim(), res.status);
  }
  return (await res.json()) as T;
}

export const fetchIncidents = (signal?: AbortSignal) => request<Incident[]>('/incidents', { signal });

export const fetchIncident = (incidentId: string, signal?: AbortSignal) =>
  request<Incident>(`/incidents/${encodeURIComponent(incidentId)}`, { signal });

export const fetchRuns = (signal?: AbortSignal) => request<AgentRunSummary[]>('/runs', { signal });

export const fetchRun = (runId: string, signal?: AbortSignal) =>
  request<AgentRun>(`/runs/${encodeURIComponent(runId)}`, { signal });

export const fetchStats = (signal?: AbortSignal) => request<Stats>('/stats', { signal });

export const fetchScenarios = (signal?: AbortSignal) => request<Scenario[]>('/scenarios', { signal });

export const triggerSimulation = (scenario?: string) =>
  request<TriggerResponse>('/trigger', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(scenario ? { scenario } : {}),
  });

export const fetchEvals = (signal?: AbortSignal) => request<EvalsReport>('/evals', { signal });

export function errorMessage(e: unknown, fallback = 'Something went wrong'): string {
  if (e instanceof Error && e.message) return e.message;
  if (typeof e === 'string' && e) return e;
  return fallback;
}

export function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError';
}
