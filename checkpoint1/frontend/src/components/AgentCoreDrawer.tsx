import React from 'react';
import { Cpu, Shield, Terminal, Wrench } from 'lucide-react';
import { Stats } from '../types';
import { Modal } from './Modal';

interface AgentCoreDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  stats: Stats | null;
}

// Descriptions only; which policies/tools are active comes from /api/stats.
const POLICY_INFO: Record<string, { title: string; desc: string }> = {
  blast_radius_files: { title: 'Blast radius (files)', desc: 'Caps how many files a proposed patch may touch.' },
  blast_radius_lines: { title: 'Blast radius (lines)', desc: 'Caps how many lines a proposed patch may change.' },
  protected_paths: { title: 'Protected paths', desc: 'Rejects patches to infra, CI and secrets paths.' },
  evidence_grounding: { title: 'Evidence grounding', desc: 'Every cited ref must exist in the context bundle.' },
  abstention_policy: { title: 'Abstention', desc: 'Low-confidence RCAs route to a human instead of a PR.' },
};

const TOOL_INFO: Record<string, string> = {
  query_logs: 'Search logs in the incident context bundle',
  get_file: 'Retrieve repository source file lines',
  get_commit_diff: 'Inspect a commit unified diff',
  submit_rca: 'Submit the structured RCA',
};

const h3 = 'text-xs font-semibold uppercase tracking-wider text-ink-300 flex items-center gap-1.5 mb-2';

export const AgentCoreDrawer: React.FC<AgentCoreDrawerProps> = ({ isOpen, onClose, stats }) => (
  <Modal
    isOpen={isOpen}
    onClose={onClose}
    variant="drawer"
    icon={<Cpu className="w-5 h-5 text-fuchsia-400 mt-0.5" aria-hidden="true" />}
    title="Strands & Bedrock AgentCore"
    description={stats?.agent_framework ?? 'Agent architecture'}
  >
    {!stats ? (
      <p role="status" className="text-sm text-ink-300">
        Loading agent configuration…
      </p>
    ) : (
      <>
        <section>
          <h3 className={h3}>
            <Terminal className="w-3.5 h-3.5 text-fuchsia-400" aria-hidden="true" />
            Strands Agents SDK
          </h3>
          <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 text-xs font-mono p-3.5 rounded-lg bg-ink-950 border border-ink-800">
            <dt className="text-ink-400">Installed version</dt>
            <dd className="text-fuchsia-200 text-right">{stats.strands_sdk_version ?? 'not installed'}</dd>
            <dt className="text-ink-400">Model backend</dt>
            <dd className="text-ink-200 text-right">Bedrock / offline scripted</dd>
          </dl>
        </section>

        <section>
          <h3 className={h3}>
            <Wrench className="w-3.5 h-3.5 text-ink-400" aria-hidden="true" />
            Gateway tools ({stats.agentcore_gateway_tools.length})
          </h3>
          <ul className="space-y-1.5">
            {stats.agentcore_gateway_tools.map((t) => (
              <li key={t} className="p-2.5 rounded-lg bg-ink-950 border border-ink-800 text-xs">
                <span className="font-mono text-ink-50 font-semibold">{t}</span>
                {TOOL_INFO[t] && <p className="text-ink-400 mt-0.5">{TOOL_INFO[t]}</p>}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h3 className={h3}>
            <Shield className="w-3.5 h-3.5 text-ink-400" aria-hidden="true" />
            Policies ({stats.agentcore_policies_active.length})
          </h3>
          <ul className="space-y-1.5">
            {stats.agentcore_policies_active.map((p) => (
              <li key={p} className="p-2.5 rounded-lg bg-ink-950 border border-ink-800 text-xs">
                <span className="text-ink-50 font-semibold">{POLICY_INFO[p]?.title ?? p}</span>
                <p className="text-ink-400 mt-0.5">{POLICY_INFO[p]?.desc ?? <span className="font-mono">{p}</span>}</p>
              </li>
            ))}
          </ul>
        </section>
      </>
    )}
  </Modal>
);
