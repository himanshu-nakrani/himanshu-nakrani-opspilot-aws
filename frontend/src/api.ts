import { EvalsReport, Incident, Stats, TriggerResponse } from './types';

const API_BASE = '/api';

export async function fetchIncidents(): Promise<Incident[]> {
  const res = await fetch(`${API_BASE}/incidents`);
  if (!res.ok) {
    throw new Error(`Failed to fetch incidents: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchIncident(incidentId: string): Promise<Incident> {
  const res = await fetch(`${API_BASE}/incidents/${incidentId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch incident ${incidentId}: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${API_BASE}/stats`);
  if (!res.ok) {
    throw new Error(`Failed to fetch stats: ${res.statusText}`);
  }
  return res.json();
}

export async function triggerSimulation(): Promise<TriggerResponse> {
  const res = await fetch(`${API_BASE}/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    throw new Error(`Failed to trigger simulation: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchEvals(): Promise<EvalsReport> {
  const res = await fetch(`${API_BASE}/evals`);
  if (!res.ok) {
    throw new Error(`Failed to fetch evals: ${res.statusText}`);
  }
  return res.json();
}
