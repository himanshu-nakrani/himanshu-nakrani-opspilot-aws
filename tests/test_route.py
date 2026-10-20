"""Unit tests for classification and confidence router."""

from opspilot.contracts import EvidenceItem, RcaResult, SuspectedLocation
from opspilot.route import determine_route, route_rca


def test_route_code_defect_high_confidence():
    assert determine_route("code_defect", 0.9) == "propose_fix"


def test_route_config_regression_notifies_until_revert_agent_exists():
    assert determine_route("config_regression", 0.95) == "notify"


def test_route_code_defect_low_confidence_abstains():
    assert determine_route("code_defect", 0.59) == "notify"


def test_route_dependency_always_notifies():
    assert determine_route("dependency", 0.99) == "notify"


def test_route_resource_always_notifies():
    assert determine_route("resource", 0.95) == "notify"


def test_route_insufficient_evidence_always_notifies():
    assert determine_route("insufficient_evidence", 0.2) == "notify"


def test_route_rca_model_helper():
    rca = RcaResult(
        incident_id="inc-1",
        classification="code_defect",
        severity="sev2",
        confidence=0.88,
        summary="Bug found",
        evidence=[EvidenceItem(kind="log_line", ref="log-1", claim="claim")],
        suggested_fix_strategy="fix",
    )
    # High confidence alone is not enough: no suspected_location / stack frame evidence.
    assert route_rca(rca) == "notify"


def test_route_rca_needs_location_backed_by_stack_frame():
    base = dict(
        incident_id="inc-1", classification="code_defect", severity="sev2", confidence=0.88,
        summary="Bug found", suggested_fix_strategy="fix",
        suspected_location=SuspectedLocation(file="svc/app.py", line=10, function="f"),
    )
    good = RcaResult(**base, evidence=[EvidenceItem(kind="stack_frame", ref="svc/app.py:10", claim="faulting frame")])
    wrong = RcaResult(**base, evidence=[EvidenceItem(kind="stack_frame", ref="svc/other.py:3", claim="other frame")])
    assert route_rca(good) == "propose_fix"
    assert route_rca(wrong) == "notify"
