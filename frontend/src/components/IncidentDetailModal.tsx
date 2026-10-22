import React, { useEffect, useState } from 'react';
import { Copy, ExternalLink, FileCode, GitBranch, ListChecks, Ticket } from 'lucide-react';
import { Incident, PrStatus } from '../types';
import { ApiError, chooseFix, errorMessage, fetchIncident, fetchPrStatus, isAbortError } from '../api';
import { classificationBadge, confidenceTone, severityBadge, SOURCE_LABEL, statusBadge } from '../lib/badges';
import { formatTimestamp, humanize } from '../lib/format';
import { badge, btn, eyebrow, focusRing } from '../ui/styles';
import { Modal } from './Modal';
import { AgentTrace } from './AgentTrace';

interface IncidentDetailModalProps {
  incident: Incident | null;
  onClose: () => void;
  onUpdated?: (incident: Incident) => void;
}

const sectionTitle = `${eyebrow} mb-2 flex items-center gap-1.5`;

export interface ReconstructedStep {
  id: string;
  label: string;
  detail: string;
}

/** Steps taken from the stored RCA when the live agent session was not kept. */
export function reconstructedTrace(
  incident: Pick<
    Incident,
    'classification' | 'confidence' | 'summary' | 'evidence' | 'ruled_out' | 'suggested_fix_strategy'
  >,
): ReconstructedStep[] {
  const steps: ReconstructedStep[] = [];
  const pct = incident.confidence == null || Number.isNaN(incident.confidence) ? null : Math.round(incident.confidence * 100);
  const classLabel = incident.classification ? humanize(incident.classification) : '';
  const headline = [classLabel, pct == null ? '' : `${pct}%`].filter(Boolean).join(', ');
  const summary = (incident.summary || '').trim();
  if (headline || summary) {
    steps.push({
      id: 'model',
      label: headline ? `Model call — ${headline}` : 'Model call',
      detail: summary,
    });
  }
  (incident.evidence || []).forEach((ev, i) => {
    steps.push({
      id: `evidence-${i}`,
      label: `${humanize(ev.kind)} ${ev.ref}`.trim(),
      detail: (ev.claim || '').trim(),
    });
  });
  const strategy = (incident.suggested_fix_strategy || '').trim();
  const ruledOut = (incident.ruled_out || []).map((item) => item.trim()).filter(Boolean);
  if (strategy || ruledOut.length > 0) {
    const ruled = ruledOut.length > 0 ? `Ruled out ${ruledOut.join(', ')}.` : '';
    steps.push({
      id: 'submitted',
      label: 'Submitted RCA',
      detail: [strategy, ruled].filter(Boolean).join(' '),
    });
  }
  return steps;
}

const quietButton = btn.secondary;
const signalButton = btn.accent;

/** An http(s) link is a pull request. A branch name such as opspilot/OPS-342 is not. */
export function pullRequestUrl(prUrl: string | null | undefined): string | null {
  const url = typeof prUrl === 'string' ? prUrl.trim() : '';
  return /^https?:\/\//i.test(url) ? url : null;
}

/** Which fix controls the incident screen should show. Raise PR only when a generator exists. */
export function fixChoiceActions(incident: Pick<Incident, 'patch_diff' | 'pr_url' | 'status' | 'can_raise_pr'>): {
  applyMyself: boolean;
  raisePr: boolean;
  copyDiff: boolean;
  trackPr: boolean;
} {
  const hasDiff = Boolean(incident.patch_diff);
  const link = pullRequestUrl(incident.pr_url);
  const prRecorded = Boolean(link) || incident.status === 'VERIFIED';
  return {
    applyMyself: hasDiff && !prRecorded && incident.status !== 'APPLY_MYSELF',
    raisePr: hasDiff && !prRecorded && incident.can_raise_pr === true,
    copyDiff: hasDiff && incident.status === 'APPLY_MYSELF' && !link,
    trackPr: Boolean(link),
  };
}

/** Short status note. Never includes the request path or a missing-PR API error. */
export function prStatusNotice(status: string): string {
  return `Couldn't refresh the pull request status. Last known status: ${prStatusLabel(status)}.`;
}

/** Display label for a status the API already returned. Unknown values stay as returned. */
export function prStatusLabel(status: string): string {
  if (status === 'open') return 'Open';
  if (status === 'merged') return 'Merged';
  if (status === 'closed') return 'Closed';
  if (status === 'opened') return 'Opened';
  return status;
}

export const PIPELINE_VIEW_URL =
  'https://us-east-1.console.aws.amazon.com/codesuite/codepipeline/pipelines/opspilot-sample-service/view?region=us-east-1';

/** Verification is shown only after a real http(s) pull request, and only once a build was started or failed to start. */
export function showTestPanel(incident: Pick<Incident, 'pr_url' | 'test_status' | 'test_error'>): boolean {
  if (!pullRequestUrl(incident.pr_url)) return false;
  return Boolean(incident.test_status || incident.test_error);
}

/** The storefront deploy is shown for a real pull request, including before anyone merges it. */
export function showDeployPanel(incident: Pick<Incident, 'pr_url'>): boolean {
  return Boolean(pullRequestUrl(incident.pr_url));
}

export function testStatusLabel(status: string): string {
  if (status === 'running') return 'Running';
  if (status === 'passed') return 'Passed';
  if (status === 'failed') return 'Failed';
  return status;
}

export function knowledgeStatusLabel(status: string | null | undefined): string {
  if (status === 'ingested') return 'Ingested';
  if (status === 'failed') return 'Ingest failed';
  return 'Waiting for merge';
}

export function deployStatusLabel(status: string): string {
  if (status === 'not_started') return 'Not started';
  if (status === 'in_progress') return 'In progress';
  if (status === 'succeeded') return 'Succeeded';
  if (status === 'failed') return 'Failed';
  return status;
}

function mergePrReading(incident: Incident, body: PrStatus): Incident {
  const next: Incident = { ...incident };
  if (body.test) {
    next.test_status = (body.test.status as Incident['test_status']) ?? null;
    next.test_name = body.test.name ?? null;
    next.test_summary = body.test.summary ?? null;
    next.test_log = body.test.log_excerpt ?? null;
    next.test_error = body.test.error ?? null;
  }
  if (body.deploy) {
    next.deploy_status = body.deploy.status ?? null;
    next.deploy_summary = body.deploy.summary ?? null;
    next.deploy_url = body.deploy.url ?? null;
    next.deploy_error = body.deploy.error ?? null;
    next.deploy_stage = body.deploy.stage ?? null;
  }
  if (body.knowledge) next.knowledge = body.knowledge;
  return next;
}

function prStateClass(status: string, failed: boolean): string {
  if (failed) return 'text-amber-200 bg-amber-500/10 border-amber-500/30';
  if (status === 'open') return 'text-signal-200 bg-signal-500/10 border-signal-500/30';
  if (status === 'merged') return 'text-ok-300 bg-ok-500/10 border-ok-500/30';
  return 'text-ink-200 bg-ink-900 border-ink-700';
}

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-ink-300 font-semibold';
  if (line.startsWith('+')) return 'text-ok-300 bg-ok-500/10';
  if (line.startsWith('-')) return 'text-red-300 bg-red-500/10';
  if (line.startsWith('@@')) return 'text-signal-300';
  return 'text-ink-300';
}

export const IncidentDetailModal: React.FC<IncidentDetailModalProps> = ({ incident: initial, onClose, onUpdated }) => {
  const [incident, setIncident] = useState<Incident | null>(initial);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [choicePending, setChoicePending] = useState<'apply_myself' | 'raise_pr' | null>(null);
  const [choiceError, setChoiceError] = useState<string | null>(null);
  const [prStatus, setPrStatus] = useState<PrStatus | null>(null);
  const [prPending, setPrPending] = useState(false);
  const [prAbsent, setPrAbsent] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  // Show the list copy immediately, then load the current record so status/PR fields are fresh.
  useEffect(() => {
    setIncident(initial);
    setRefreshError(null);
    setChoiceError(null);
    setChoicePending(null);
    setPrStatus(null);
    setPrPending(false);
    setPrAbsent(false);
    setCopied(false);
    setCopyError(null);
    if (!initial) return;
    const controller = new AbortController();
    fetchIncident(initial.incident_id, controller.signal)
      .then(setIncident)
      .catch((e) => {
        if (!isAbortError(e)) setRefreshError(errorMessage(e));
      });
    return () => controller.abort();
  }, [initial]);

  const prUrl = prAbsent ? null : pullRequestUrl(incident?.pr_url);
  const incidentId = incident?.incident_id;

  useEffect(() => {
    if (!prUrl || !incidentId) {
      setPrStatus(null);
      setPrPending(false);
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const pull = () => {
      setPrPending(true);
      fetchPrStatus(incidentId, controller.signal)
        .then((body) => {
          if (cancelled) return;
          setPrAbsent(false);
          setPrStatus(body);
          setIncident((prev) => (prev ? mergePrReading(prev, body) : prev));
          const testRunning = body.test?.status === 'running' && !body.test?.error;
          const deployRunning = body.deploy?.status === 'in_progress' && !body.deploy?.error;
          if (testRunning || deployRunning) timer = setTimeout(pull, 4000);
        })
        .catch((e) => {
          if (cancelled || isAbortError(e)) return;
          if (e instanceof ApiError && e.status === 404) {
            setPrStatus(null);
            setPrAbsent(true);
            return;
          }
          setPrStatus({
            pr_url: prUrl,
            status: 'opened',
            pull_request_status: null,
            is_merged: null,
            error: 'unavailable',
          });
          setIncident((prev) =>
            prev
              ? {
                  ...prev,
                  test_error: prev.test_status || prev.test_error ? 'The verification build could not be read.' : prev.test_error,
                  deploy_error: 'The pipeline could not be read.',
                  deploy_url: prev.deploy_url || PIPELINE_VIEW_URL,
                }
              : prev,
          );
        })
        .finally(() => {
          if (!cancelled) setPrPending(false);
        });
    };
    pull();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [incidentId, prUrl]);

  if (!incident) return null;

  const status = statusBadge(incident.status);
  const StatusIcon = status.icon;
  const pct = incident.confidence === null || incident.confidence === undefined ? null : Math.round(incident.confidence * 100);
  const tone = confidenceTone(pct);
  const evidence = incident.evidence ?? [];
  const traceSteps = incident.agent_run_id ? [] : reconstructedTrace(incident);
  const loc = incident.suspected_location;
  const prLink = prAbsent ? null : pullRequestUrl(incident.pr_url);
  const actions = fixChoiceActions(
    prLink
      ? incident
      : {
          ...incident,
          pr_url: null,
          pr_branch: null,
          status: incident.status === 'PR_OPENED' ? 'AWAITING_CHOICE' : incident.status,
        },
  );

  const choose = (action: 'apply_myself' | 'raise_pr') => {
    setChoicePending(action);
    setChoiceError(null);
    chooseFix(incident.incident_id, action)
      .then((next) => {
        setIncident(next);
        onUpdated?.(next);
      })
      .catch((e) => {
        if (!isAbortError(e)) setChoiceError(errorMessage(e));
      })
      .finally(() => setChoicePending(null));
  };

  const copyDiff = () => {
    if (!incident.patch_diff) return;
    const text = incident.patch_diff;
    setCopyError(null);
    const write = navigator.clipboard?.writeText
      ? navigator.clipboard.writeText(text)
      : Promise.reject(new Error('Clipboard is not available in this browser.'));
    write
      .then(() => setCopied(true))
      .catch((e) => {
        setCopied(false);
        setCopyError(errorMessage(e, 'Could not copy the diff.'));
      });
  };

  const trackPr = () => {
    if (!prLink) return;
    const url = prLink;
    setPrPending(true);
    fetchPrStatus(incident.incident_id)
      .then((body) => {
        setPrAbsent(false);
        setPrStatus(body);
        setIncident((prev) => (prev ? mergePrReading(prev, body) : prev));
      })
      .catch((e) => {
        if (isAbortError(e)) return;
        if (e instanceof ApiError && e.status === 404) {
          setPrStatus(null);
          setPrAbsent(true);
          return;
        }
        setPrStatus({
          pr_url: url,
          status: 'opened',
          pull_request_status: null,
          is_merged: null,
          error: 'unavailable',
        });
      })
      .finally(() => setPrPending(false));
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={<span className="font-mono">{incident.incident_id}</span>}
      description={
        <>
          {incident.service ?? 'unknown service'} ·{' '}
          <time dateTime={incident.detected_at ?? undefined}>{formatTimestamp(incident.detected_at)}</time>
          {incident.source && incident.source !== 'dynamodb' && <> · {SOURCE_LABEL[incident.source]}</>}
        </>
      }
    >
      {refreshError && (
        <p role="status" className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
          Could not load the latest version of this incident; showing cached data. {refreshError}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className={`${badge} ${classificationBadge(incident.classification)}`}>
          {humanize(incident.classification)}
        </span>
        <span className={`${badge} ${status.className}`}>
          <StatusIcon className="w-3.5 h-3.5" aria-hidden="true" />
          {status.label}
        </span>
        {incident.severity && (
          <span className={`${badge} uppercase ${severityBadge(incident.severity)}`}>
            {incident.severity}
          </span>
        )}
        <span className={`ml-auto text-sm font-semibold ${tone.text}`}>Confidence {pct === null ? 'n/a' : `${pct}%`}</span>
      </div>

      <section>
        <h3 className={sectionTitle}>Root-cause summary</h3>
        <p className="text-sm text-ink-200 leading-relaxed">{incident.summary || 'No summary available.'}</p>
      </section>

      <div className="grid md:grid-cols-2 gap-4">
        <section className="p-4 rounded-lg bg-ink-950/50 border border-ink-800">
          <h3 className={sectionTitle}>
            <FileCode className="w-3.5 h-3.5" aria-hidden="true" />
            Suspected location
          </h3>
          {loc ? (
            <p className="font-mono text-xs text-ink-200 break-all">
              {loc.file}:{loc.line}
              {loc.function && <span className="text-ink-400"> in {loc.function}()</span>}
            </p>
          ) : (
            <p className="text-xs text-ink-400">Not identified.</p>
          )}
        </section>
        <section className="p-4 rounded-lg bg-ink-950/50 border border-ink-800">
          <h3 className={sectionTitle}>Suggested fix strategy</h3>
          <p className="text-xs text-ink-200">{incident.suggested_fix_strategy || 'None proposed.'}</p>
        </section>
      </div>

      <section>
        <h3 className={sectionTitle}>
          <ListChecks className="w-3.5 h-3.5" aria-hidden="true" />
          Evidence cited ({evidence.length})
        </h3>
        {evidence.length > 0 ? (
          <ul className="space-y-2">
            {evidence.map((ev, i) => (
              <li key={`${ev.ref}-${i}`} className="p-3 rounded-lg bg-ink-950/50 border border-ink-800 text-xs">
                <div className="flex flex-wrap gap-2 text-ink-400 font-mono">
                  <span className="uppercase">{humanize(ev.kind)}</span>
                  <span className="break-all">{ev.ref}</span>
                </div>
                <p className="text-ink-200 mt-1">{ev.claim}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-ink-400">No evidence items recorded.</p>
        )}
        {incident.ruled_out && incident.ruled_out.length > 0 && (
          <div className="mt-3">
            <h4 className="text-xs text-ink-300 mb-1">Ruled out</h4>
            <ul className="list-disc pl-5 text-xs text-ink-300 space-y-0.5">
              {incident.ruled_out.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {incident.human_ending && !prLink && (
        <section className="rounded-lg border border-ink-700 bg-ink-950/50 p-4">
          <h3 className={sectionTitle}>What happens next</h3>
          <p className="text-sm text-ink-100 leading-relaxed">{incident.human_ending}</p>
        </section>
      )}

      {actions.applyMyself && (
        <section className="rounded-lg border border-ink-800 bg-ink-950/50 p-4">
          <h3 className={sectionTitle}>What should happen to this change?</h3>
          <p className="text-xs text-ink-300 mb-3">
            {actions.raisePr
              ? 'The pipeline stopped after the analysis. Nothing is committed until you raise a pull request.'
              : 'OpsPilot cannot open a pull request for this change. You can still apply the diff yourself.'}
            {loc ? ` The change is in ${loc.file}${loc.function ? ` (${loc.function})` : ''}.` : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={choicePending !== null}
              onClick={() => choose('apply_myself')}
              className={quietButton}
            >
              {choicePending === 'apply_myself' ? 'Saving…' : "I'll apply changes myself"}
            </button>
            {actions.raisePr && (
              <button
                type="button"
                disabled={choicePending !== null}
                onClick={() => choose('raise_pr')}
                className={signalButton}
              >
                {choicePending === 'raise_pr' ? 'Opening pull request…' : 'Raise PR'}
              </button>
            )}
          </div>
          {choiceError && (
            <p role="alert" className="mt-3 text-xs text-red-200 bg-red-500/10 border border-red-500/30 rounded-md px-3 py-2">
              {choiceError}
            </p>
          )}
        </section>
      )}

      {actions.trackPr && prLink && (
        <section className="rounded-lg border border-signal-500/40 bg-signal-500/10 p-4">
          <h3 className={sectionTitle}>Pull request</h3>
          <p className="text-xs text-ink-200 mb-3">
            The change is on a pull request
            {incident.pr_branch ? <> in <span className="font-mono text-ink-100">{incident.pr_branch}</span></> : ''}.
            Open it in CodeCommit, or check whether it is still open.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={prLink}
              target="_blank"
              rel="noopener noreferrer"
              className={signalButton}
            >
              <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
              Open pull request
              <span className="sr-only">(opens in a new tab)</span>
            </a>
            <button type="button" disabled={prPending} onClick={trackPr} className={quietButton}>
              {prPending ? 'Checking status…' : 'Track PR status'}
            </button>
            {prStatus && (
              <span className={`px-2 py-0.5 text-xs font-semibold rounded-md border ${prStateClass(prStatus.status, Boolean(prStatus.error))}`}>
                {prStatus.error ? `Last known: ${prStatusLabel(prStatus.status)}` : prStatusLabel(prStatus.status)}
              </span>
            )}
          </div>
          {prStatus?.error && (
            <p role="status" className="mt-3 text-xs text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
              {prStatusNotice(prStatus.status)}
            </p>
          )}
          {prStatus && !prStatus.error && (
            <p role="status" className="mt-3 text-xs text-ink-200">
              Pull request status: {prStatusLabel(prStatus.status)}
              {prStatus.pull_request_status ? ` (CodeCommit ${prStatus.pull_request_status})` : ''}.
            </p>
          )}
          {!prStatus && prPending && (
            <p role="status" className="mt-3 text-xs text-ink-300">Checking pull request status…</p>
          )}
          {incident.knowledge?.body && (
            <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/40 p-3">
              <h4 className={sectionTitle}>Knowledge base</h4>
              <p className="text-xs text-ink-100">{knowledgeStatusLabel(incident.knowledge.status)}</p>
              <p className="mt-1 text-xs text-ink-300">
                {incident.knowledge.status === 'ingested'
                  ? 'This document was stored for later incidents to retrieve.'
                  : 'This document is stored after the pull request merges.'}
              </p>
              {incident.knowledge.error && (
                <p role="alert" className="mt-2 text-xs text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
                  {incident.knowledge.error}
                </p>
              )}
              <pre className="mt-2 max-h-64 overflow-auto text-xs font-mono text-ink-200 whitespace-pre-wrap">{incident.knowledge.body}</pre>
            </div>
          )}
          {showTestPanel(incident) && (
            <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/40 p-3">
              <h4 className={sectionTitle}>Verification test</h4>
              {incident.test_status && (
                <p className="text-xs text-ink-100">
                  Test {testStatusLabel(incident.test_status).toLowerCase()}
                  {incident.test_name ? <>: <span className="font-mono text-ink-200">{incident.test_name}</span></> : '.'}
                </p>
              )}
              {incident.test_summary && <p className="mt-2 text-xs text-ink-200">{incident.test_summary}</p>}
              {incident.test_log && (
                <pre className="mt-2 max-h-32 overflow-auto text-xs font-mono text-ink-300 whitespace-pre-wrap">{incident.test_log}</pre>
              )}
              {incident.test_error && (
                <p role="status" className="mt-2 text-xs text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
                  {incident.test_error}
                </p>
              )}
            </div>
          )}
          {showDeployPanel(incident) && (
            <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/40 p-3">
              <h4 className={sectionTitle}>Deploy</h4>
              {incident.deploy_status && (
                <p className="text-xs text-ink-100">
                  Deploy {deployStatusLabel(incident.deploy_status).toLowerCase()}
                  {incident.deploy_stage ? <> ({incident.deploy_stage})</> : ''}.
                </p>
              )}
              {incident.deploy_summary && <p className="mt-2 text-xs text-ink-200">{incident.deploy_summary}</p>}
              {incident.deploy_error && (
                <p role="status" className="mt-2 text-xs text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
                  {incident.deploy_error}
                </p>
              )}
              <a
                href={incident.deploy_url || PIPELINE_VIEW_URL}
                target="_blank"
                rel="noopener noreferrer"
                className={`${quietButton} mt-3`}
              >
                <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
                Open pipeline
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            </div>
          )}
        </section>
      )}

      {incident.status === 'APPLY_MYSELF' && !prLink && (
        <section className="rounded-lg border border-ink-800 bg-ink-950/50 p-4">
          <h3 className={sectionTitle}>Apply this change yourself</h3>
          <p className="text-xs text-ink-300 mb-3">
            {actions.raisePr
              ? 'You chose to apply this change yourself. The diff is below. Copy it, or raise a pull request if you change your mind.'
              : 'You chose to apply this change yourself. The diff is below. Copy it and apply the change in the repository.'}
            {loc ? ` Edit ${loc.file}${loc.line ? `:${loc.line}` : ''}.` : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            {actions.copyDiff && (
              <button type="button" onClick={copyDiff} className={quietButton}>
                <Copy className="w-3.5 h-3.5" aria-hidden="true" />
                {copied ? 'Copied' : 'Copy diff'}
              </button>
            )}
            {actions.raisePr && (
              <button
                type="button"
                disabled={choicePending !== null}
                onClick={() => choose('raise_pr')}
                className={signalButton}
              >
                {choicePending === 'raise_pr' ? 'Opening pull request…' : 'Raise PR'}
              </button>
            )}
          </div>
          {copied && (
            <p role="status" className="mt-3 text-xs text-ok-300 bg-ok-500/10 border border-ok-500/30 rounded-md px-3 py-2">
              Diff copied.
            </p>
          )}
          {copyError && (
            <p role="alert" className="mt-3 text-xs text-red-200 bg-red-500/10 border border-red-500/30 rounded-md px-3 py-2">
              {copyError}
            </p>
          )}
          {choiceError && (
            <p role="alert" className="mt-3 text-xs text-red-200 bg-red-500/10 border border-red-500/30 rounded-md px-3 py-2">
              {choiceError}
            </p>
          )}
        </section>
      )}

      {incident.patch_diff && (
        <section>
          <h3 className={sectionTitle}>Proposed patch</h3>
          <pre className="text-xs font-mono rounded-lg bg-ink-950 border border-ink-800 p-3 overflow-x-auto">
            {incident.patch_diff.split('\n').map((line, idx) => (
              <div key={idx} className={`px-1 ${diffLineClass(line)}`}>
                {line || ' '}
              </div>
            ))}
          </pre>
        </section>
      )}

      <section>
        <h3 className={sectionTitle}>Agent trace</h3>
        {incident.agent_run_id ? (
          <AgentTrace runId={incident.agent_run_id} compact />
        ) : traceSteps.length > 0 ? (
          <div>
            <p className="text-xs text-ink-400 mb-2">
              Reconstructed from the saved RCA. The live agent session was not stored.
            </p>
            <ol className="space-y-2">
              {traceSteps.map((step, index) => (
                <li key={step.id} className="p-3 rounded-lg bg-ink-950/50 border border-ink-800 text-xs">
                  <div className="font-mono text-ink-400">
                    {index + 1}. {step.label}
                  </div>
                  {step.detail && <p className="text-ink-200 mt-1 leading-relaxed">{step.detail}</p>}
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <p className="text-xs text-ink-400">No agent trace was recorded for this incident.</p>
        )}
      </section>

      {(incident.ticket_key || incident.pr_branch) && (
        <section className="flex flex-wrap gap-3 text-xs">
          {incident.ticket_key && (
            <LinkOrLabel url={incident.ticket_url} icon={<Ticket className="w-3.5 h-3.5" aria-hidden="true" />}>
              {incident.ticket_key}
            </LinkOrLabel>
          )}
          {prLink && incident.pr_branch && (
            <LinkOrLabel url={prLink} icon={<GitBranch className="w-3.5 h-3.5" aria-hidden="true" />}>
              {incident.pr_branch}
            </LinkOrLabel>
          )}
          {!incident.ticket_url && !prLink && (
            <span className="text-ink-400 self-center">No ticket or PR was created for this {incident.source === 'dynamodb' ? 'incident' : 'demo record'}.</span>
          )}
        </section>
      )}
    </Modal>
  );
};

const LinkOrLabel: React.FC<{ url?: string | null; icon: React.ReactNode; children: React.ReactNode }> = ({ url, icon, children }) => {
  const cls = `inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-ink-700 bg-ink-800/60 font-mono text-ink-200 ${focusRing}`;
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className={`${cls} hover:bg-ink-700`}>
      {icon}
      {children}
      <ExternalLink className="w-3 h-3" aria-hidden="true" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  ) : (
    <span className={cls}>
      {icon}
      {children}
    </span>
  );
};
