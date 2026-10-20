"""Unit tests for classification and confidence router."""

from opspilot.contracts import EvidenceItem, RcaResult
from opspilot.route import determine_route, route_rca


def test_route_code_defect_high_confidence():
    assert determine_route("code_defect", 0.9) == "propose_fix"


def test_route_config_regression_high_confidence():
    assert determine_route("config_regression", 0.65) == "propose_fix"


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
    assert route_rca(rca) == "propose_fix"
