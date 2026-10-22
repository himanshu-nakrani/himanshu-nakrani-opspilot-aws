import React from 'react';
import { CheckCircle2, CircleDashed, Loader2 } from 'lucide-react';
import { eyebrow } from '../ui/styles';

type MilestoneState = 'done' | 'active' | 'planned';

const MILESTONES: { id: string; label: string; state: MilestoneState; note: string }[] = [
  { id: 'M0', label: 'Design docs & state machine', state: 'done', note: 'Contracts + ASL checked in' },
  { id: 'M1', label: 'Sample service + alarm path', state: 'done', note: 'Planted fault + metric filter' },
  { id: 'M2', label: 'Context + RCA agent', state: 'done', note: 'Bedrock structured RCA' },
  { id: 'M3', label: 'Classifier + OpsCenter', state: 'active', note: 'Ticket API integration' },
  { id: 'M4', label: 'Patch agent → PR', state: 'active', note: 'CodeCommit branch flow' },
  { id: 'M5', label: 'CodeBuild + notify', state: 'planned', note: 'Verify + Slack/SNS' },
  { id: 'M6', label: 'Offline eval harness', state: 'planned', note: '10 golden fixtures' },
];

const iconFor = (state: MilestoneState) => {
  if (state === 'done') return <CheckCircle2 className="w-4 h-4 text-ok-400" aria-hidden="true" />;
  if (state === 'active') return <Loader2 className="w-4 h-4 text-amber-300 motion-safe:animate-spin" aria-hidden="true" />;
  return <CircleDashed className="w-4 h-4 text-ink-500" aria-hidden="true" />;
};

/** README-aligned milestone rail for checkpoint storytelling. */
export const BuildProgress: React.FC = () => (
  <section aria-labelledby="build-progress-heading" className="rounded-lg border border-ink-800 bg-ink-900/60 p-5">
    <h2 id="build-progress-heading" className={eyebrow}>
      Build progress
    </h2>
    <p className="mt-1 text-xs text-ink-400">What we are shipping between Checkpoint 1 and the full demo.</p>
    <ul className="mt-4 space-y-3">
      {MILESTONES.map((m) => (
        <li key={m.id} className="flex gap-3 items-start">
          <span className="mt-0.5">{iconFor(m.state)}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="font-mono text-2xs text-ink-500">{m.id}</span>
              <span className="text-[13px] text-ink-100">{m.label}</span>
              {m.state === 'active' && (
                <span className="text-2xs uppercase tracking-wide text-amber-200/90 font-mono">In progress</span>
              )}
            </div>
            <p className="text-xs text-ink-400 mt-0.5">{m.note}</p>
          </div>
        </li>
      ))}
    </ul>
  </section>
);
