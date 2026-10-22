import React from 'react';
import { Ticket } from 'lucide-react';
import { eyebrow } from '../ui/styles';

export const WipTicketsPage: React.FC = () => (
  <section
    aria-labelledby="tickets-wip-heading"
    className="rounded-lg border border-dashed border-ink-700 bg-ink-900/40 p-8 text-center max-w-lg mx-auto"
  >
    <Ticket className="w-8 h-8 text-ink-500 mx-auto" aria-hidden="true" />
    <h2 id="tickets-wip-heading" className={`${eyebrow} mt-4`}>
      OpsCenter tickets
    </h2>
    <p className="mt-2 text-sm text-ink-300 leading-relaxed">
      Classifier routes and OpsItem creation are in progress for Checkpoint 1. The full dashboard lists open, in
      progress, and resolved tickets from AWS Systems Manager OpsCenter.
    </p>
    <p className="mt-4 text-xs font-mono text-ink-500">M3 · classifier + OpsCenter API</p>
  </section>
);
