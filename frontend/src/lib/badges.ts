import { AlertTriangle, CheckCircle, CopyX, GitPullRequest, HelpCircle, ShieldAlert, type LucideIcon } from 'lucide-react';
import { Classification, IncidentStatus } from '../types';

const NEUTRAL = 'bg-ink-800/70 text-ink-200 border-ink-700';

/** One hue per root-cause class. Used for badges, the stream rail and the breakdown bar. */
export interface ClassTone {
  badge: string;
  /** solid swatch for bars/rails */
  swatch: string;
}

export function classificationTone(cls: Classification | null | undefined): ClassTone {
  switch (cls) {
    case 'code_defect':
      return { badge: 'bg-fuchsia-500/10 text-fuchsia-200 border-fuchsia-400/30', swatch: 'bg-fuchsia-400' };
    case 'config_regression':
      return { badge: 'bg-amber-500/10 text-amber-200 border-amber-400/30', swatch: 'bg-amber-400' };
    case 'dependency':
      return { badge: 'bg-cyan-500/10 text-cyan-200 border-cyan-400/30', swatch: 'bg-cyan-400' };
    case 'resource':
      return { badge: 'bg-orange-500/10 text-orange-200 border-orange-400/30', swatch: 'bg-orange-500' };
    case 'insufficient_evidence':
      return { badge: 'bg-ink-700/40 text-ink-200 border-ink-600', swatch: 'bg-ink-500' };
    default:
      return { badge: NEUTRAL, swatch: 'bg-ink-600' };
  }
}

export function classificationBadge(cls: Classification | null | undefined): string {
  return classificationTone(cls).badge;
}

export interface StatusBadge {
  label: string;
  className: string;
  icon: LucideIcon;
  /** text colour for compact (icon + label, no chip) rendering */
  text: string;
}

export function statusBadge(status: IncidentStatus): StatusBadge {
  switch (status) {
    case 'VERIFIED':
      return { label: 'Verified fix', className: 'bg-signal-400/10 text-signal-300 border-signal-400/30', text: 'text-signal-300', icon: CheckCircle };
    case 'PROPOSED':
      return { label: 'PR proposed', className: 'bg-fuchsia-500/10 text-fuchsia-200 border-fuchsia-400/30', text: 'text-fuchsia-200', icon: GitPullRequest };
    case 'NEEDS_HUMAN':
      return { label: 'Needs human', className: 'bg-amber-500/10 text-amber-200 border-amber-400/30', text: 'text-amber-300', icon: AlertTriangle };
    case 'NOTIFIED':
      return { label: 'Notified SRE', className: 'bg-cyan-500/10 text-cyan-200 border-cyan-400/30', text: 'text-cyan-300', icon: ShieldAlert };
    case 'DUPLICATE_SKIPPED':
      return { label: 'Duplicate skipped', className: NEUTRAL, text: 'text-ink-300', icon: CopyX };
    default:
      return { label: status || 'Unknown', className: NEUTRAL, text: 'text-ink-300', icon: HelpCircle };
  }
}

export function severityBadge(sev?: string | null): string {
  switch (sev) {
    case 'sev1':
      return 'bg-red-500/15 text-red-200 border-red-400/50';
    case 'sev2':
      return 'bg-orange-500/10 text-orange-200 border-orange-400/40';
    case 'sev3':
      return 'bg-amber-500/10 text-amber-200 border-amber-400/30';
    default:
      return NEUTRAL;
  }
}

/** Colour of the left rail on a stream row: severity first, then neutral. */
export function severityRail(sev?: string | null): string {
  switch (sev) {
    case 'sev1':
      return 'bg-red-500';
    case 'sev2':
      return 'bg-orange-500';
    case 'sev3':
      return 'bg-amber-400';
    case 'sev4':
      return 'bg-ink-500';
    default:
      return 'bg-ink-700';
  }
}

export function confidenceTone(percent: number | null): { text: string; bar: string } {
  if (percent === null) return { text: 'text-ink-400', bar: 'bg-ink-600' };
  if (percent >= 70) return { text: 'text-signal-300', bar: 'bg-signal-400' };
  if (percent >= 50) return { text: 'text-amber-300', bar: 'bg-amber-400' };
  return { text: 'text-ink-300', bar: 'bg-ink-500' };
}

export const SOURCE_LABEL: Record<string, string> = {
  fixture: 'Fixture replay',
  simulated: 'Simulated',
  dynamodb: 'Live',
};

export const CLASSIFICATION_ORDER: Classification[] = [
  'code_defect',
  'config_regression',
  'dependency',
  'resource',
  'insufficient_evidence',
];
