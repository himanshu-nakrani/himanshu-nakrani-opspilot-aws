import React from 'react';
import { Hammer } from 'lucide-react';
/** Top-of-page hackathon checkpoint callout. */
export const CheckpointBanner: React.FC = () => (
  <div
    role="status"
    className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-3"
  >
    <div className="flex items-start gap-2.5 min-w-0">
      <Hammer className="w-4 h-4 text-amber-200 shrink-0 mt-0.5" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-amber-50 tracking-[-0.01em]">
          Hackathon Checkpoint 1 — work in progress
        </p>
        <p className="mt-0.5 text-xs text-amber-100/80 leading-relaxed">
          Dashboard and grounded RCA are live in this build. Sample incidents below are demo data while we wire
          EventBridge ingest, OpsCenter, and the fix PR pipeline for Checkpoint 2.
        </p>
      </div>
    </div>
    <span
      className="shrink-0 self-start sm:self-center text-xs font-mono px-2.5 py-1 rounded-md border border-amber-500/40 text-amber-100/90"
      title="Full product ships from repo root for Checkpoint 2"
    >
      CP2 → full pipeline
    </span>
  </div>
);
