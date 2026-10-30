"""Shared fixtures for the OpsPilot unit tests (offline: moto/fakes, no network)."""

import pytest

from opspilot.contracts import EvidenceItem, RcaResult, SuspectedLocation, TicketRef


@pytest.fixture
def sample_inputs():
    """A grounded code_defect RCA plus its OpsCenter ticket — the fix-agent input pair."""
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
    ticket = TicketRef(key="oi-0a1b2c3d4e5f", url="https://us-east-1.console.aws.amazon.com/systems-manager/opsitems/oi-0a1b2c3d4e5f?region=us-east-1", incident_id="inc-fix-001")
    return rca, ticket
