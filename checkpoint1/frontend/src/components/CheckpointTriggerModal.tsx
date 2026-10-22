import React, { useState } from 'react';
import { Radio, Zap } from 'lucide-react';
import { Incident } from '../types';
import { CHECKPOINT_DEMO_INCIDENTS } from '../data/checkpointDemo';
import { Modal } from './Modal';
import { btn } from '../ui/styles';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onPreviewIncident: (incident: Incident) => void;
}

/** Simulates the M1 trigger UX without calling the backend. */
export const CheckpointTriggerModal: React.FC<Props> = ({ isOpen, onClose, onPreviewIncident }) => {
  const [phase, setPhase] = useState<'idle' | 'wiring'>('idle');

  const preview = () => {
    setPhase('wiring');
    window.setTimeout(() => {
      const sample = CHECKPOINT_DEMO_INCIDENTS[0];
      onPreviewIncident({
        ...sample,
        incident_id: `OPS-PREVIEW-${Date.now().toString(36).slice(-4).toUpperCase()}`,
        detected_at: new Date().toISOString(),
        source: 'simulated',
      });
      setPhase('idle');
    }, 1400);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Simulate incident" size="md">
      <div className="space-y-4">
        <div className="flex gap-3 rounded-md border border-ink-800 bg-ink-950/60 p-3">
          <Radio className="w-5 h-5 text-signal-300 shrink-0" aria-hidden="true" />
          <div className="text-xs text-ink-300 leading-relaxed">
            <p className="font-medium text-ink-100">EventBridge ingest — wiring in progress</p>
            <p className="mt-1 text-ink-400">
              Checkpoint 2 connects this button to live sample_service faults and DynamoDB dedup. For now, preview how
              a new incident appears in the stream.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={preview}
          disabled={phase === 'wiring'}
          className={btn.primary}
        >
          <Zap className="w-3.5 h-3.5" aria-hidden="true" />
          {phase === 'wiring' ? 'Queuing RCA…' : 'Preview sample incident'}
        </button>
      </div>
    </Modal>
  );
};
