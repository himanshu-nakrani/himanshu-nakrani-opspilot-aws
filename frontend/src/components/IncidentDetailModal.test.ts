import { describe, expect, it } from 'vitest';
import type { Incident } from '../types';
import {
  deployStatusLabel,
  fixChoiceActions,
  knowledgeStatusLabel,
  prStatusLabel,
  prStatusNotice,
  pullRequestUrl,
  showDeployPanel,
  showTestPanel,
  testStatusLabel,
} from './IncidentDetailModal';

const open = {
  patch_diff: '--- a/sample_service/app.py\n+    raise HTTPException(status_code=422)',
  pr_url: null,
  status: 'AWAITING_CHOICE',
  can_raise_pr: true,
};

describe('fixChoiceActions', () => {
  it('offers Raise PR only when a generator exists for the diff', () => {
    expect(fixChoiceActions(open)).toEqual({ applyMyself: true, raisePr: true, copyDiff: false, trackPr: false });
    expect(fixChoiceActions({ ...open, can_raise_pr: false })).toEqual({
      applyMyself: true,
      raisePr: false,
      copyDiff: false,
      trackPr: false,
    });
    expect(fixChoiceActions({ ...open, can_raise_pr: undefined })).toEqual({
      applyMyself: true,
      raisePr: false,
      copyDiff: false,
      trackPr: false,
    });
  });

  it('keeps copy and Raise PR after apply-myself, and tracks a pull request once one exists', () => {
    expect(fixChoiceActions({ ...open, status: 'APPLY_MYSELF' })).toEqual({
      applyMyself: false,
      raisePr: true,
      copyDiff: true,
      trackPr: false,
    });
    expect(fixChoiceActions({ ...open, status: 'APPLY_MYSELF', can_raise_pr: false }).raisePr).toBe(false);
    expect(fixChoiceActions({ ...open, status: 'PR_OPENED', pr_url: 'https://example/pr/1' })).toEqual({
      applyMyself: false,
      raisePr: false,
      copyDiff: false,
      trackPr: true,
    });
    expect(fixChoiceActions({ ...open, status: 'PR_OPENED', pr_url: 'opspilot/OPS-342' })).toEqual({
      applyMyself: true,
      raisePr: true,
      copyDiff: false,
      trackPr: false,
    });
    expect(fixChoiceActions({ ...open, pr_url: 'https://example/pr/1' }).raisePr).toBe(false);
    expect(fixChoiceActions({ ...open, patch_diff: null }).applyMyself).toBe(false);
    expect(fixChoiceActions({ ...open, patch_diff: null, status: 'APPLY_MYSELF' }).copyDiff).toBe(false);
  });
});

describe('prStatusLabel', () => {
  it('labels known states and leaves any other status unchanged', () => {
    expect(prStatusLabel('open')).toBe('Open');
    expect(prStatusLabel('merged')).toBe('Merged');
    expect(knowledgeStatusLabel('waiting')).toBe('Waiting for merge');
    expect(knowledgeStatusLabel(undefined)).toBe('Waiting for merge');
    expect(knowledgeStatusLabel('ingested')).toBe('Ingested');
    expect(knowledgeStatusLabel('failed')).toBe('Ingest failed');
    expect(prStatusLabel('closed')).toBe('Closed');
    expect(prStatusLabel('opened')).toBe('Opened');
    expect(prStatusLabel('PENDING')).toBe('PENDING');
  });
});

describe('pull request link', () => {
  it('ignores a branch name and keeps an http link', () => {
    expect(pullRequestUrl('opspilot/OPS-342')).toBeNull();
    expect(pullRequestUrl(null)).toBeNull();
    expect(pullRequestUrl(' https://example/pr/1 ')).toBe('https://example/pr/1');
  });

  it('does not put the request path or a missing-PR error in the status note', () => {
    const note = prStatusNotice('opened');
    expect(note).toBe("Couldn't refresh the pull request status. Last known status: Opened.");
    expect(note).not.toContain('pr-status');
    expect(note).not.toContain('no pull request');
    expect(note).not.toContain('/incidents/');
  });
});

describe('verification and deploy panels', () => {
  const pr: Pick<Incident, 'pr_url' | 'test_status' | 'test_error' | 'deploy_status'> = {
    pr_url: 'https://example/pr/1',
    test_status: null,
    test_error: null,
    deploy_status: null,
  };

  it('hides both panels until a real pull request exists', () => {
    expect(showTestPanel({ ...pr, pr_url: null, test_status: 'passed' })).toBe(false);
    expect(showDeployPanel({ pr_url: null })).toBe(false);
    expect(showDeployPanel({ pr_url: 'opspilot/OPS-1' })).toBe(false);
    expect(showTestPanel({ ...pr, test_status: 'running' })).toBe(true);
    expect(showTestPanel(pr)).toBe(false);
    expect(showTestPanel({ ...pr, test_error: 'The verification build could not be started.' })).toBe(true);
    expect(showDeployPanel(pr)).toBe(true);
  });

  it('labels test and deploy states without inventing a word', () => {
    expect(testStatusLabel('running')).toBe('Running');
    expect(testStatusLabel('passed')).toBe('Passed');
    expect(testStatusLabel('failed')).toBe('Failed');
    expect(deployStatusLabel('not_started')).toBe('Not started');
    expect(deployStatusLabel('in_progress')).toBe('In progress');
    expect(deployStatusLabel('succeeded')).toBe('Succeeded');
    expect(deployStatusLabel('failed')).toBe('Failed');
    expect(deployStatusLabel('Superseded')).toBe('Superseded');
  });
});
