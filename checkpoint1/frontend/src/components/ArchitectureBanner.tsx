import React from 'react';
import { eyebrow } from '../ui/styles';

type StepState = 'done' | 'active' | 'planned';

const STEPS: { title: string; detail: string; state: StepState }[] = [
  { title: 'Alarm trigger', detail: 'CloudWatch Logs', state: 'done' },
  { title: 'Dedup ingest', detail: '15-min window', state: 'done' },
  { title: 'Collect context', detail: 'Logs & commits', state: 'done' },
  { title: 'Strands RCA', detail: 'AgentCore runtime', state: 'done' },
  { title: 'OpsCenter OpsItem', detail: 'SSM, IAM auth', state: 'active' },
  { title: 'Patch PR', detail: 'Limits guardrail', state: 'active' },
  { title: 'CodeBuild verify', detail: '2-phase test', state: 'planned' },
  { title: 'Slack & SNS', detail: 'Block Kit alert', state: 'planned' },
] as const;

const stepStyles = (state: StepState) => {
  if (state === 'done') return 'border-ok-500/40 bg-ok-500/10 text-ok-200';
  if (state === 'active') return 'border-amber-500/40 bg-amber-500/10 text-amber-100';
  return 'border-ink-700 bg-ink-900 text-ink-500';
};

/** Step Functions workflow with checkpoint-aware progress styling. */
export const ArchitectureBanner: React.FC = () => (
  <section aria-labelledby="pipeline-heading">
    <div className="flex items-baseline justify-between gap-2">
      <h2 id="pipeline-heading" className={eyebrow}>
        Autonomous SRE pipeline
      </h2>
      <span className="font-mono text-2xs text-ink-500">Step Functions · Standard</span>
    </div>
    <p className="mt-1 text-xs text-ink-400">Steps 1–4 shipped; 5–6 in progress for Checkpoint 2.</p>

    <ol className="mt-4 relative">
      {STEPS.map((step, idx) => {
        const last = idx === STEPS.length - 1;
        return (
          <li key={step.title} className="relative flex gap-3 pb-3 last:pb-0">
            {!last && <span className="absolute left-[11px] top-6 bottom-0 w-px bg-ink-800" aria-hidden="true" />}
            <span
              className={`relative z-10 w-6 h-6 shrink-0 rounded-md border flex items-center justify-center font-mono text-2xs tnum ${stepStyles(step.state)}`}
              aria-hidden="true"
            >
              {String(idx + 1).padStart(2, '0')}
            </span>
            <div className="min-w-0 pt-[3px] flex flex-1 items-baseline justify-between gap-2">
              <span className={`text-[13px] leading-tight ${step.state === 'planned' ? 'text-ink-500' : 'text-ink-100'}`}>
                {step.title}
              </span>
              <span className="font-mono text-2xs text-ink-400 text-right">{step.detail}</span>
            </div>
          </li>
        );
      })}
    </ol>
  </section>
);
