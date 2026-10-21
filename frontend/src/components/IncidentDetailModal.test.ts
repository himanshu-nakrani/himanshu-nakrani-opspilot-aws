import { describe, expect, it } from 'vitest';
import { fixChoiceActions } from './IncidentDetailModal';

const open = {
  patch_diff: '--- a/sample_service/app.py\n+    raise HTTPException(status_code=422)',
  pr_url: null,
  status: 'AWAITING_CHOICE',
  can_raise_pr: true,
};

describe('fixChoiceActions', () => {
  it('offers Raise PR only when a generator exists for the diff', () => {
    expect(fixChoiceActions(open)).toEqual({ applyMyself: true, raisePr: true });
    expect(fixChoiceActions({ ...open, can_raise_pr: false })).toEqual({ applyMyself: true, raisePr: false });
    expect(fixChoiceActions({ ...open, can_raise_pr: undefined })).toEqual({ applyMyself: true, raisePr: false });
  });

  it('hides both buttons once a choice is recorded or there is no diff', () => {
    expect(fixChoiceActions({ ...open, status: 'APPLY_MYSELF' }).applyMyself).toBe(false);
    expect(fixChoiceActions({ ...open, status: 'PR_OPENED' }).raisePr).toBe(false);
    expect(fixChoiceActions({ ...open, pr_url: 'https://example/pr/1' }).raisePr).toBe(false);
    expect(fixChoiceActions({ ...open, patch_diff: null }).applyMyself).toBe(false);
  });
});
