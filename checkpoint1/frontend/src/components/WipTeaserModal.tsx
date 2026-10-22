import React from 'react';
import { Construction } from 'lucide-react';
import { Modal } from './Modal';
import { btn } from '../ui/styles';

interface WipTeaserModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  body: string;
  checkpointTarget: string;
}

export const WipTeaserModal: React.FC<WipTeaserModalProps> = ({
  isOpen,
  onClose,
  title,
  body,
  checkpointTarget,
}) => (
  <Modal isOpen={isOpen} onClose={onClose} title={title} size="md">
    <div className="flex gap-3">
      <Construction className="w-5 h-5 text-amber-300 shrink-0" aria-hidden="true" />
      <div className="space-y-3">
        <p className="text-sm text-ink-200 leading-relaxed">{body}</p>
        <p className="text-xs font-mono text-ink-400 border border-dashed border-ink-700 rounded-md px-3 py-2">
          Target: {checkpointTarget}
        </p>
        <button type="button" onClick={onClose} className={btn.primary}>
          Got it
        </button>
      </div>
    </div>
  </Modal>
);
