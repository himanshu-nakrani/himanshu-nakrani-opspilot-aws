import React from 'react';
import { eyebrow } from '../ui/styles';

const STEPS = [
  { title: 'Alarm trigger', detail: 'CloudWatch Logs' },
  { title: 'Dedup ingest', detail: '15-min window' },
  { title: 'Collect context', detail: 'Logs & commits' },
  { title: 'Strands RCA', detail: 'AgentCore runtime' },
  { title: 'OpsCenter OpsItem', detail: 'SSM, IAM auth' },
  { title: 'Patch PR', detail: 'Limits guardrail' },
  { title: 'CodeBuild verify', detail: '2-phase test' },
  { title: 'Slack & SNS', detail: 'Block Kit alert' },
] as const;

/** The Step Functions workflow as a compact numbered rail. */
export const ArchitectureBanner: React.FC = () => (
  <section aria-labelledby="pipeline-heading">
    <div className="flex items-baseline justify-between gap-2">
      <h2 id="pipeline-heading" className={eyebrow}>
        Autonomous SRE pipeline
      </h2>
      <span className="font-mono text-2xs text-ink-500">Step Functions · Standard</span>
    </div>
    <p className="mt-1 text-xs text-ink-400">CloudWatch alarm to grounded, verified remediation.</p>

    <ol className="mt-4 relative">
      {STEPS.map((step, idx) => {
        const last = idx === STEPS.length - 1;
        return (
          <li key={step.title} className="relative flex gap-3 pb-3 last:pb-0">
            {!last && <span className="absolute left-[11px] top-6 bottom-0 w-px bg-ink-800" aria-hidden="true" />}
            <span
              className={`relative z-10 w-6 h-6 shrink-0 rounded-md border flex items-center justify-center font-mono text-2xs tnum ${
                'border-ink-700 bg-ink-900 text-ink-400'
              }`}
              aria-hidden="true"
            >
              {String(idx + 1).padStart(2, '0')}
            </span>
            <div className="min-w-0 pt-[3px] flex flex-1 items-baseline justify-between gap-2">
              <span className="text-[13px] text-ink-100 leading-tight">{step.title}</span>
              <span className="font-mono text-2xs text-ink-400 text-right">{step.detail}</span>
            </div>
          </li>
        );
      })}
    </ol>
  </section>
);
