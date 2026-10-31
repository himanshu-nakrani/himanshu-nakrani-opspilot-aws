"""Tests for Amazon Bedrock AgentCore primitives (Runtime, Gateway, Policy, Memory)."""

import pytest

from opspilot.contracts import ContextBundle, LogLine, RcaResult
from opspilot.agentcore import (
    AgentCoreGateway,
    AgentCoreMemory,
    AgentCorePolicy,
    AgentCoreRuntime,
    PolicyViolationError,
)


def _sample_bundle() -> ContextBundle:
    logs = [
        LogLine(id="log-201", timestamp="2026-10-20T12:00:00Z", message="Starting web server on port 8000"),
        LogLine(
            id="log-202",
            timestamp="2026-10-20T12:00:01Z",
            message=(
                "Traceback (most recent call last):\n"
                '  File "sample_service/app.py", line 29, in get_order\n'
                '    "total": order.total,\n'
                "AttributeError: 'NoneType' object has no attribute 'total'"
            ),
        ),
    ]
    from opspilot.collect_context import parse_stack_trace_from_logs

    st = parse_stack_trace_from_logs([l.message for l in logs])
    return ContextBundle(
        incident_id="inc-agentcore-001",
        service="sample-service",
        log_group="/aws/lambda/opspilot-sample-service",
        detected_at="2026-10-20T12:00:00Z",
        log_lines=logs,
        stack_trace=st,
        repo="himanshu-nakrani/opspilot-aws-poc",
        repo_files={"sample_service/app.py": "def get_order(order_id: str):\n    order = ORDERS.get(order_id)\n    return {'total': order.total}\n"},
        recent_commits=[{"commit": "abcdef123456", "subject": "Refactor order processing"}],
    )


# 1. AgentCore Gateway Tests
def test_agentcore_gateway_specs_and_execution():
    gateway = AgentCoreGateway()
    specs = gateway.get_tool_specs()
    assert len(specs) >= 4
    names = [s["toolSpec"]["name"] for s in specs]
    assert "query_logs" in names
    assert "get_file" in names
    assert "submit_rca" in names

    bundle = _sample_bundle()
    res = gateway.execute_tool("query_logs", {"pattern": "AttributeError"}, bundle)
    assert res["matches_count"] >= 1
    assert "log-202" in [l["id"] for l in res["lines"]]


# 2. AgentCore Policy Tests
def test_agentcore_policy_patch_limits():
    policy = AgentCorePolicy()

    # Valid diff within limits
    valid_diff = """--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -1,2 +1,3 @@
+from fastapi import HTTPException
"""
    is_valid, msg = policy.enforce_patch_policy(valid_diff)
    assert is_valid is True

    # Reject more than 3 files
    four_files_diff = """--- a/f1.py
+++ b/f1.py
@@ -1 +1 @@
--- a/f2.py
+++ b/f2.py
@@ -1 +1 @@
--- a/f3.py
+++ b/f3.py
@@ -1 +1 @@
--- a/f4.py
+++ b/f4.py
@@ -1 +1 @@
"""
    with pytest.raises(PolicyViolationError) as exc_info:
        policy.enforce_patch_policy(four_files_diff)
    assert "4 files" in str(exc_info.value)
    assert exc_info.value.policy_name == "blast_radius_files"

    # Reject protected files (e.g. CI / IaC / contracts / manifests)
    ci_diff = """--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -1 +1 @@
"""
    with pytest.raises(PolicyViolationError) as exc_info:
        policy.enforce_patch_policy(ci_diff)
    assert "protected file" in str(exc_info.value)
    assert exc_info.value.policy_name == "protected_paths"


def test_agentcore_policy_evidence_grounding_penalty():
    policy = AgentCorePolicy()
    bundle = _sample_bundle()

    # RCA with ungrounded log ref
    candidate = {
        "incident_id": bundle.incident_id,
        "classification": "code_defect",
        "severity": "sev2",
        "confidence": 0.95,
        "summary": "Sample bug summary",
        "suspected_location": {"file": "sample_service/app.py", "line": 29},
        "evidence": [
            {"kind": "log_line", "ref": "log-nonexistent-999", "claim": "Fake log line"},
        ],
        "suggested_fix_strategy": "Fix bug",
    }

    rca, issues = policy.enforce_evidence_grounding(bundle, candidate)
    assert len(issues) > 0
    assert rca.confidence <= 0.40
    assert len(policy.audit_log) > 0


def test_agentcore_policy_abstention_on_inconclusive_logs():
    policy = AgentCorePolicy()
    clean_bundle = ContextBundle(
        incident_id="inc-clean-1",
        service="sample-service",
        log_group="/aws/lambda/clean",
        detected_at="2026-10-20T12:00:00Z",
        log_lines=[LogLine(id="l1", timestamp="2026-10-20T12:00:00Z", message="Healthy ping ok")],
        repo="himanshu-nakrani/opspilot-aws-poc",
    )

    from opspilot.contracts import EvidenceItem

    overconfident_rca = RcaResult(
        incident_id="inc-clean-1",
        classification="code_defect",
        severity="sev1",
        confidence=0.90,
        summary="Hallucinated crash",
        evidence=[EvidenceItem(kind="log_line", ref="l1", claim="Healthy ping")],
        suggested_fix_strategy="None",
    )

    enforced_rca = policy.enforce_abstention_policy(clean_bundle, overconfident_rca)
    assert enforced_rca.classification == "insufficient_evidence"
    assert enforced_rca.confidence <= 0.40


# 3. AgentCore Memory Tests
def test_agentcore_memory_recording():
    memory = AgentCoreMemory(incident_id="inc-mem-001")
    memory.add_note("Observed HTTP 500 error spikes")
    memory.rule_out("dependency")
    memory.record_tool_call("query_logs", {"pattern": "error"}, {"matches_count": 2}, latency_ms=12.5)

    dump = memory.to_dict()
    assert dump["incident_id"] == "inc-mem-001"
    assert "Observed HTTP 500 error spikes" in dump["notes"]
    assert "dependency" in dump["ruled_out_hypotheses"]
    assert dump["tool_invocations_count"] == 1
    assert dump["tool_history"][0]["tool_name"] == "query_logs"


# 4. AgentCore Runtime & Telemetry Tests
def test_agentcore_runtime_session_and_emf_metrics():
    runtime = AgentCoreRuntime()
    bundle = _sample_bundle()

    rca_result, session = runtime.execute_rca(bundle)
    assert isinstance(rca_result, RcaResult)
    assert rca_result.classification == "code_defect"
    assert rca_result.confidence >= 0.70

    # Verify session telemetry
    session_data = session.to_dict()
    assert session_data["incident_id"] == bundle.incident_id
    assert session_data["duration_ms"] > 0
    assert session_data["memory"]["tool_invocations_count"] >= 2

    # Verify CloudWatch EMF format
    emf = runtime.emit_cloudwatch_metrics(session, rca_result)
    assert "_aws" in emf
    assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "OpsPilot/AgentCore"
    assert emf["IncidentId"] == bundle.incident_id
    assert emf["Classification"] == "code_defect"
    assert emf["ConfidenceScore"] >= 0.70
