import { AlertTriangle, CheckCircle, CopyX, GitPullRequest, HelpCircle, ShieldAlert, type LucideIcon } from 'lucide-react';
import { Classification, IncidentStatus } from '../types';

const NEUTRAL = 'bg-slate-800 text-slate-300 border-slate-700';

export function classificationBadge(cls: Classification | null | undefined): string {
  switch (cls) {
    case 'code_defect':
      return 'bg-purple-500/10 text-purple-300 border-purple-500/30';
    case 'config_regression':
      return 'bg-amber-500/10 text-amber-300 border-amber-500/30';
    case 'dependency':
      return 'bg-blue-500/10 text-blue-300 border-blue-500/30';
    case 'resource':
      return 'bg-rose-500/10 text-rose-300 border-rose-500/30';
    case 'insufficient_evidence':
      return 'bg-slate-500/10 text-slate-300 border-slate-500/30';
    default:
      return NEUTRAL;
  }
}

export interface StatusBadge {
  label: string;
  className: string;
  icon: LucideIcon;
}

export function statusBadge(status: IncidentStatus): StatusBadge {
  switch (status) {
    case 'VERIFIED':
      return { label: 'Verified fix', className: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30', icon: CheckCircle };
    case 'PROPOSED':
      return { label: 'PR proposed', className: 'bg-purple-500/10 text-purple-300 border-purple-500/30', icon: GitPullRequest };
    case 'NEEDS_HUMAN':
      return { label: 'Needs human', className: 'bg-amber-500/10 text-amber-300 border-amber-500/30', icon: AlertTriangle };
    case 'NOTIFIED':
      return { label: 'Notified SRE', className: 'bg-blue-500/10 text-blue-300 border-blue-500/30', icon: ShieldAlert };
    case 'DUPLICATE_SKIPPED':
      return { label: 'Duplicate skipped', className: NEUTRAL, icon: CopyX };
    default:
      return { label: status || 'Unknown', className: NEUTRAL, icon: HelpCircle };
  }
}

export function severityBadge(sev?: string | null): string {
  switch (sev) {
    case 'sev1':
      return 'bg-red-500/15 text-red-300 border-red-500/40';
    case 'sev2':
      return 'bg-orange-500/10 text-orange-300 border-orange-500/30';
    case 'sev3':
      return 'bg-amber-500/10 text-amber-300 border-amber-500/30';
    default:
      return NEUTRAL;
  }
}

export function confidenceTone(percent: number | null): { text: string; bar: string } {
  if (percent === null) return { text: 'text-slate-400', bar: 'bg-slate-600' };
  if (percent >= 70) return { text: 'text-emerald-400', bar: 'bg-emerald-500' };
  if (percent >= 50) return { text: 'text-amber-400', bar: 'bg-amber-500' };
  return { text: 'text-slate-300', bar: 'bg-slate-500' };
}

export const SOURCE_LABEL: Record<string, string> = {
  fixture: 'Fixture replay',
  simulated: 'Simulated',
  dynamodb: 'Live',
};
