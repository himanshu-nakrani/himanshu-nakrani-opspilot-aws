import React from 'react';
import { FileCode, Lock } from 'lucide-react';
import { Incident } from '../types';
import { classificationBadge, confidenceTone, severityBadge, SOURCE_LABEL, statusBadge } from '../lib/badges';
import { formatTimestamp, humanize } from '../lib/format';
import { badge, eyebrow } from '../ui/styles';
import { Modal } from './Modal';

interface Props {
  incident: Incident | null;
  onClose: () => void;
}

const sectionTitle = `${eyebrow} mb-2 flex items-center gap-1.5`;

/** Read-only RCA view for Checkpoint 1 — fix automation deliberately stubbed. */
export const CheckpointIncidentDetailModal: React.FC<Props> = ({ incident, onClose }) => {
  if (!incident) return null;

  const status = statusBadge(incident.status);
  const StatusIcon = status.icon;
  const pct = incident.confidence === null ? null : Math.round(incident.confidence * 100);
  const tone = confidenceTone(pct);

  return (
  <Modal isOpen onClose={onClose} title={incident.incident_id} size="lg">
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          {incident.classification && (
            <span className={`${badge} ${classificationBadge(incident.classification)}`}>
              {humanize(incident.classification)}
            </span>
          )}
          <span className={`${badge} ${status.className}`}>
            <StatusIcon className="w-3.5 h-3.5" aria-hidden="true" />
            {status.label}
          </span>
          {incident.severity && (
            <span className={`${badge} uppercase ${severityBadge(incident.severity)}`}>{incident.severity}</span>
          )}
          <span className={`ml-auto text-sm font-semibold ${tone.text}`}>
            Confidence {pct === null ? 'n/a' : `${pct}%`}
          </span>
          {incident.source && incident.source !== 'dynamodb' && (
            <span className={`${badge} text-ink-400 border-ink-800`}>{SOURCE_LABEL[incident.source]}</span>
          )}
        </div>

        {incident.detected_at && (
          <p className="text-xs text-ink-400 font-mono tnum">{formatTimestamp(incident.detected_at)}</p>
        )}

        {incident.summary && (
          <section>
            <h3 className={sectionTitle}>Summary</h3>
            <p className="text-sm text-ink-200 leading-relaxed">{incident.summary}</p>
          </section>
        )}

        {incident.suspected_location && (
          <section>
            <h3 className={sectionTitle}>
              <FileCode className="w-3.5 h-3.5" aria-hidden="true" />
              Suspected location
            </h3>
            <p className="font-mono text-sm text-signal-200">
              {incident.suspected_location.file}:{incident.suspected_location.line}
              {incident.suspected_location.function ? ` · ${incident.suspected_location.function}` : ''}
            </p>
          </section>
        )}

        {incident.evidence && incident.evidence.length > 0 && (
          <section>
            <h3 className={sectionTitle}>Grounded evidence</h3>
            <ul className="space-y-2">
              {incident.evidence.map((item) => (
                <li
                  key={`${item.kind}-${item.ref}`}
                  className="rounded-md border border-ink-800 bg-ink-950/50 px-3 py-2 text-xs"
                >
                  <span className="font-mono text-2xs text-ink-500 uppercase">{item.kind}</span>
                  <span className="mx-2 text-ink-600">·</span>
                  <span className="font-mono text-ink-300">{item.ref}</span>
                  <p className="mt-1 text-ink-200">{item.claim}</p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {incident.suggested_fix_strategy && (
          <section>
            <h3 className={sectionTitle}>Suggested fix strategy</h3>
            <p className="text-sm text-ink-200">{incident.suggested_fix_strategy}</p>
          </section>
        )}

        {incident.ruled_out && incident.ruled_out.length > 0 && (
          <section>
            <h3 className={sectionTitle}>Ruled out</h3>
            <ul className="list-disc pl-5 text-xs text-ink-400 space-y-1">
              {incident.ruled_out.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
        )}

        <section
          aria-labelledby="fix-wip-heading"
          className="rounded-lg border border-dashed border-ink-700 bg-ink-900/40 px-4 py-4"
        >
          <div className="flex items-center gap-2 text-ink-300">
            <Lock className="w-4 h-4 text-ink-500" aria-hidden="true" />
            <h3 id="fix-wip-heading" className="text-sm font-medium text-ink-200">
              Fix automation — Checkpoint 2
            </h3>
          </div>
          <p className="mt-2 text-xs text-ink-400 leading-relaxed">
            Patch diff viewer, Raise PR, CodeBuild verification, and deploy tracking ship in the full build. Status
            here: <span className="text-ink-200">{humanize(incident.status)}</span>
            {incident.ticket_key ? ` · draft ticket ${incident.ticket_key}` : ''}.
          </p>
        </section>
      </div>
  </Modal>
  );
};
