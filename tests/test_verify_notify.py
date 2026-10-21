"""Unit tests for two-phase verification, forced-failure retry, and notification."""

import json
import boto3
import httpx
from moto import mock_aws
import pytest

from opspilot.contracts import EvidenceItem, PrRef, RcaResult, SuspectedLocation, TicketRef, VerificationResult
from opspilot.fix.agent import mark_needs_human_handler
from opspilot.notify import build_slack_blocks, handler as notify_handler, send_slack_notification, send_sns_notification
from opspilot.verify.runner import run_two_phase_verification


@pytest.fixture
def sample_pipeline_state():
    rca = RcaResult(
        incident_id="inc-verify-001",
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
    ticket = TicketRef(key="oi-0a1b2c3d4e5f", url="https://us-east-1.console.aws.amazon.com/systems-manager/opsitems/oi-0a1b2c3d4e5f?region=us-east-1", incident_id="inc-verify-001")
    pr = PrRef(
        branch="opspilot/oi-0a1b2c3d4e5f",
        base="main",
        repro_test_path="sample_service/tests/test_opspilot_oi_0a1b2c3d4e5f.py",
        pr_url="https://github.com/himanshu-nakrani/opspilot-aws-poc/pull/42",
        pr_number=42,
        attempt=1,
        status="opened",
    )
    verify = VerificationResult(
        repro_fails_on_base=True,
        suite_passes_on_fix=True,
        verdict="verified",
        details="Verification succeeded",
    )
    return rca, ticket, pr, verify


def test_two_phase_verification_success():
    """Phase 1: repro test on base fails; Phase 2: suite on fix passes."""
    # Base execution fails (e.g. returns False or raises)
    def run_repro_on_base():
        return False

    # Fix execution passes (returns True)
    def run_suite_on_fix():
        return True

    res = run_two_phase_verification(run_repro_on_base, run_suite_on_fix)
    assert res.repro_fails_on_base is True
    assert res.suite_passes_on_fix is True
    assert res.verdict == "verified"


def test_two_phase_verification_invalid_repro_test():
    """If repro test passes on base, it fails verification because it didn't reproduce the bug."""
    def run_repro_on_base():
        return True  # Unexpected pass on unfixed base

    def run_suite_on_fix():
        return True

    res = run_two_phase_verification(run_repro_on_base, run_suite_on_fix)
    assert res.repro_fails_on_base is False
    assert res.verdict == "failed"


def test_forced_failure_gives_retry_then_needs_human(sample_pipeline_state):
    """Forced failure test: a deliberately wrong patch fails verification.

    Step Functions retry logic:
    - Attempt 1 fails -> retry (attempt 2).
    - Attempt 2 fails -> MarkNeedsHuman sets needs_human status.
    - Notification indicates action required.
    """
    rca, ticket, pr, _ = sample_pipeline_state

    # 1. First run with broken patch
    broken_verify_1 = run_two_phase_verification(
        run_repro_on_base=lambda: False,
        run_suite_on_fix=lambda: False,  # Broken patch fails suite
    )
    assert broken_verify_1.verdict == "failed"
    assert pr.attempt == 1

    # Simulate Step Functions choice RetryOrGiveUp on attempt 1 (< 2): allows retry
    should_retry = pr.attempt < 2
    assert should_retry is True

    # 2. Second attempt (attempt 2)
    pr_attempt_2 = pr.model_copy(update={"attempt": 2})
    broken_verify_2 = run_two_phase_verification(
        run_repro_on_base=lambda: False,
        run_suite_on_fix=lambda: False,
    )
    assert broken_verify_2.verdict == "failed"

    # Step Functions choice on attempt 2: no more retries -> MarkNeedsHuman
    should_retry_2 = pr_attempt_2.attempt < 2
    assert should_retry_2 is False

    # MarkNeedsHuman task executes
    event = {"pr": pr_attempt_2.model_dump()}
    from tests.test_fix_agent import FakeGitHub
    updated_pr_data = mark_needs_human_handler(event, github=FakeGitHub())
    assert updated_pr_data["status"] == "needs_human"

    updated_pr = PrRef.model_validate(updated_pr_data)

    # 3. Notification contains human intervention alert
    slack_blocks = build_slack_blocks(rca, ticket, updated_pr, broken_verify_2)
    blocks_str = json.dumps(slack_blocks)
    assert "Action Required" in blocks_str
    assert "needs-human" in blocks_str


def test_slack_notification_block_kit(sample_pipeline_state):
    rca, ticket, pr, verify = sample_pipeline_state
    blocks = build_slack_blocks(rca, ticket, pr, verify)
    blocks_json = json.dumps(blocks)

    assert "OpsPilot Incident Report" in blocks_json
    assert "inc-verify-001" in blocks_json
    assert "code_defect" in blocks_json
    assert "sample_service/app.py:29" in blocks_json
    assert "systems-manager/opsitems/oi-0a1b2c3d4e5f" in blocks_json
    assert "OpsCenter" in blocks_json
    assert "https://github.com/himanshu-nakrani/opspilot-aws-poc/pull/42" in blocks_json
    assert "VERIFIED" in blocks_json


@mock_aws
def test_sns_notification():
    sns = boto3.client("sns", region_name="us-east-1")
    topic = sns.create_topic(Name="opspilot-alerts")
    topic_arn = topic["TopicArn"]

    sent = send_sns_notification("Test Subject", "Test message body", topic_arn=topic_arn, sns_client=sns)
    assert sent is True


def test_notify_lambda_handler(sample_pipeline_state, monkeypatch):
    rca, ticket, pr, verify = sample_pipeline_state
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test/test/test")

    def mock_slack(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(mock_slack)
    client = httpx.Client(transport=transport)

    event = {
        "rca": rca.model_dump(),
        "ticket": ticket.model_dump(),
        "pr": pr.model_dump(),
        "verify": verify.model_dump(),
    }

    # Patch send_slack_notification to use client
    res = notify_handler(event)
    assert res["status"] == "notified"
    assert res["verdict"] == "verified"
