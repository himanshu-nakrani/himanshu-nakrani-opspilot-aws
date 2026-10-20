"""Unit tests for Jira client, ADF descriptions, and idempotency."""

import json
import httpx
import pytest

from opspilot.contracts import EvidenceItem, RcaResult, SuspectedLocation
from opspilot.jira_client import build_adf_description, create_issue, handler


@pytest.fixture
def sample_rca():
    return RcaResult(
        incident_id="inc-jira-123",
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


def test_build_adf_description(sample_rca):
    adf = build_adf_description(sample_rca)
    assert adf["version"] == 1
    assert adf["type"] == "doc"

    # Convert to json to easily inspect text content
    adf_str = json.dumps(adf)
    assert "OpsPilot Root Cause Analysis" in adf_str
    assert "inc-jira-123" in adf_str
    assert "sample_service/app.py:29" in adf_str
    assert "Unhandled AttributeError" in adf_str


def test_create_jira_issue_success(sample_rca, monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.test")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "OPS")
    monkeypatch.setenv("JIRA_EMAIL", "test@test.org")
    monkeypatch.setenv("JIRA_API_TOKEN", "fake-token")

    post_called = False

    def handler_mock(request: httpx.Request) -> httpx.Response:
        nonlocal post_called
        if request.url.path == "/rest/api/3/search":
            # Idempotency check: no existing issue
            return httpx.Response(200, json={"total": 0, "issues": []})
        elif request.url.path == "/rest/api/3/issue":
            post_called = True
            body = json.loads(request.content)
            assert body["fields"]["project"]["key"] == "OPS"
            assert "opspilot" in body["fields"]["labels"]
            assert "cls:code_defect" in body["fields"]["labels"]
            assert "inc:inc-jira-123" in body["fields"]["labels"]
            assert body["fields"]["priority"]["name"] == "High"  # sev2 -> High
            return httpx.Response(201, json={"id": "10001", "key": "OPS-42"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler_mock)
    client = httpx.Client(transport=transport)

    ticket = create_issue(sample_rca, http_client=client)
    assert post_called is True
    assert ticket.key == "OPS-42"
    assert ticket.url == "https://jira.test/browse/OPS-42"
    assert ticket.incident_id == "inc-jira-123"


def test_create_jira_issue_idempotency(sample_rca, monkeypatch):
    """When an issue with label inc:<id> already exists, return existing key without calling create."""
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.test")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "OPS")

    def handler_mock(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/search":
            # Return existing issue
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "issues": [{"key": "OPS-15", "id": "10015"}],
                },
            )
        elif request.url.path == "/rest/api/3/issue":
            pytest.fail("POST /issue should not be called if issue already exists!")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler_mock)
    client = httpx.Client(transport=transport)

    ticket = create_issue(sample_rca, http_client=client)
    assert ticket.key == "OPS-15"
    assert ticket.url == "https://jira.test/browse/OPS-15"
