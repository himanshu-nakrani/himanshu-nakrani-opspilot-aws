"""Unit tests for patch agent, PR creation, and needs-human marking."""

import os

import pytest
from opspilot.contracts import EvidenceItem, RcaResult, SuspectedLocation, TicketRef
from opspilot.fix.agent import UnsupportedFixTarget, generate_repro_test_and_patch, mark_needs_human_handler, propose_fix
from opspilot.fix.git_ops import GitHubError, PatchApplyError, apply_unified_diff

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def sample_inputs():
    rca = RcaResult(
        incident_id="inc-fix-001",
        classification="code_defect",
        severity="sev2",
        confidence=0.92,
        summary="AttributeError on missing order in sample_service/app.py",
        suspected_location=SuspectedLocation(file="sample_service/app.py", line=29, function="get_order"),
        evidence=[
            EvidenceItem(kind="log_line", ref="log-1", claim="Unhandled AttributeError"),
            EvidenceItem(kind="stack_frame", ref="sample_service/app.py:29", claim="Faulting line"),
        ],
        suggested_fix_strategy="Return 404 HTTPException for missing order.",
    )
    ticket = TicketRef(key="OPS-42", url="https://jira.test/browse/OPS-42", incident_id="inc-fix-001")
    return rca, ticket


def test_generate_repro_test_and_patch(sample_inputs):
    rca, ticket = sample_inputs
    repro_code, test_path, patch = generate_repro_test_and_patch(rca, ticket)

    assert "test_opspilot_ops_42.py" in test_path
    assert "test_missing_order_returns_404" in repro_code
    assert 'assert response.status_code == 404' in repro_code
    assert "HTTPException" in patch
    assert "status_code=404" in patch


class FakeGitHub:
    """In-memory stand-in for GitHubClient that records what was committed."""

    def __init__(self, fail_pr: bool = False):
        with open(os.path.join(REPO_ROOT, "sample_service/app.py")) as f:
            self.files = {"sample_service/app.py": f.read()}
        self.fail_pr = fail_pr
        self.commits = []
        self.labels = []

    def get_file(self, path, ref):
        return self.files[path]

    def commit_files_to_branch(self, branch, base, files, message):
        self.commits.append((branch, base, dict(files)))
        return "abc1234"

    def open_pull_request(self, branch, base, title, body):
        if self.fail_pr:
            raise GitHubError("GitHub create pull request failed: HTTP 403")
        return 7, f"https://github.com/o/r/pull/7"

    def add_labels(self, number, labels):
        self.labels.append((number, labels))


def test_propose_fix_commits_patched_file_and_opens_pr(sample_inputs):
    rca, ticket = sample_inputs
    gh = FakeGitHub()
    pr_ref = propose_fix(rca, ticket, github=gh)
    assert pr_ref.branch == "opspilot/OPS-42"
    assert pr_ref.pr_url == "https://github.com/o/r/pull/7" and pr_ref.pr_number == 7
    branch, base, files = gh.commits[0]
    # Only the patched file and the repro test are committed (no `git add .`).
    assert set(files) == {"sample_service/app.py", pr_ref.repro_test_path}
    assert "HTTPException(status_code=404" in files["sample_service/app.py"]


def test_propose_fix_pr_failure_raises_instead_of_fake_url(sample_inputs):
    rca, ticket = sample_inputs
    with pytest.raises(GitHubError):
        propose_fix(rca, ticket, github=FakeGitHub(fail_pr=True))


def test_propose_fix_refuses_unsupported_target(sample_inputs):
    rca, ticket = sample_inputs
    other = rca.model_copy(update={"suspected_location": SuspectedLocation(file="billing/service.py", line=3, function="x")})
    with pytest.raises(UnsupportedFixTarget):
        propose_fix(other, ticket, github=FakeGitHub())


def test_patch_that_does_not_match_base_is_rejected():
    with pytest.raises(PatchApplyError):
        apply_unified_diff("a\nb\n", "--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-zzz\n+yyy\n", "f.py")


def test_mark_needs_human_labels_pr(sample_inputs):
    gh = FakeGitHub()
    event = {"pr": {"branch": "opspilot/OPS-42", "base": "main",
                    "repro_test_path": "sample_service/tests/test_opspilot_ops_42.py", "pr_number": 42, "attempt": 1}}
    result = mark_needs_human_handler(event, github=gh)
    assert result["status"] == "needs_human"
    assert gh.labels == [(42, ["needs-human"])]


def test_mark_needs_human_requires_pr_number():
    with pytest.raises(ValueError):
        mark_needs_human_handler({"pr": {"branch": "b"}}, github=FakeGitHub())


def test_propose_fix_refuses_non_code_defect(sample_inputs):
    rca, ticket = sample_inputs
    for cls in ("config_regression", "dependency"):
        with pytest.raises(UnsupportedFixTarget):
            propose_fix(rca.model_copy(update={"classification": cls}), ticket, github=FakeGitHub())
