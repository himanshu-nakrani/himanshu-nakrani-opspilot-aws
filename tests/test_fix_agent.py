"""Unit tests for patch agent, PR creation, and needs-human marking."""

import pytest
from opspilot.contracts import EvidenceItem, RcaResult, SuspectedLocation, TicketRef
from opspilot.fix.agent import generate_repro_test_and_patch, mark_needs_human_handler, propose_fix


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


def test_propose_fix_creates_pr_ref(sample_inputs, monkeypatch, tmp_path):
    rca, ticket = sample_inputs
    monkeypatch.setenv("GITHUB_REPO", "himanshu-nakrani/opspilot-aws-poc")

    # Run propose_fix using tmp_path as repo_root
    pr_ref = propose_fix(rca, ticket, repo_root=str(tmp_path))
    assert pr_ref.branch == "opspilot/OPS-42"
    assert pr_ref.base == "main"
    assert "test_opspilot_ops_42.py" in pr_ref.repro_test_path
    assert pr_ref.pr_url is not None
    assert pr_ref.attempt == 1


def test_mark_needs_human(sample_inputs, monkeypatch):
    event = {
        "pr": {
            "branch": "opspilot/OPS-42",
            "base": "main",
            "repro_test_path": "sample_service/tests/test_opspilot_ops_42.py",
            "pr_number": 42,
            "attempt": 2,
        }
    }
    result = mark_needs_human_handler(event)
    assert result["status"] == "needs_human"
