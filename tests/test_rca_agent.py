"""Unit tests for RCA agent, structured output, grounding, and abstention."""

from unittest.mock import MagicMock
import pytest

from opspilot.contracts import ContextBundle, IncidentEvent, LogLine, RcaResult
from opspilot.rca.agent import run_rca_agent
from opspilot.rca.tools import validate_and_ground_rca


def _create_sample_bundle(with_error: bool = True) -> ContextBundle:
    if with_error:
        mock_logs = [
            LogLine(id="log-1", timestamp="2026-10-20T12:00:00Z", message="Incoming GET /orders/999"),
            LogLine(
                id="log-2",
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

        st = parse_stack_trace_from_logs([l.message for l in mock_logs])
        repo_files = {"sample_service/app.py": "def get_order(order_id: str):\n    order = ORDERS.get(order_id)\n    return {'total': order.total}\n"}
    else:
        mock_logs = [
            LogLine(id="log-1", timestamp="2026-10-20T12:00:00Z", message="Heartbeat check ok"),
            LogLine(id="log-2", timestamp="2026-10-20T12:00:05Z", message="Processed 10 items successfully"),
        ]
        st = None
        repo_files = {}

    return ContextBundle(
        incident_id="inc-sample-001",
        service="sample-service",
        log_group="/aws/lambda/opspilot-sample-service",
        detected_at="2026-10-20T12:00:00Z",
        log_lines=mock_logs,
        stack_trace=st,
        repo="himanshu-nakrani/opspilot-aws-poc",
        repo_files=repo_files,
        recent_commits=[{"commit": "66bd14a2bd08c46f54eb1530908d6ea8485ae6d3", "subject": "Initial commit"}],
    )


def test_rca_for_sample_bug():
    bundle = _create_sample_bundle(with_error=True)
    rca = run_rca_agent(bundle)

    # 1. Validates against schema
    assert isinstance(rca, RcaResult)
    # 2. Classification is code_defect
    assert rca.classification == "code_defect"
    assert rca.confidence >= 0.6
    # 3. Names sample_service/app.py and faulting line in suspected_location
    assert rca.suspected_location is not None
    assert rca.suspected_location.file == "sample_service/app.py"
    assert rca.suspected_location.line == 29
    # 4. Every evidence ref resolves in context bundle
    valid_log_ids = {l.id for l in bundle.log_lines}
    for ev in rca.evidence:
        if ev.kind == "log_line":
            assert ev.ref in valid_log_ids or any(ev.ref in l.message for l in bundle.log_lines)
        elif ev.kind == "stack_frame":
            assert "sample_service/app.py" in ev.ref


def test_rca_abstains_when_no_stack_trace():
    """Unit test required by M2: given a context bundle with no stack trace, the result is insufficient_evidence."""
    bundle = _create_sample_bundle(with_error=False)
    rca = run_rca_agent(bundle)

    assert rca.classification == "insufficient_evidence"
    assert rca.confidence <= 0.4
    assert "insufficient" in rca.summary.lower()


def test_evidence_grounding_penalty():
    """Unverifiable evidence references reduce confidence to at most 0.4."""
    bundle = _create_sample_bundle(with_error=True)
    bogus_submission = {
        "incident_id": bundle.incident_id,
        "classification": "code_defect",
        "severity": "sev2",
        "confidence": 0.95,
        "summary": "Sample bug summary",
        "suspected_location": {"file": "sample_service/app.py", "line": 29},
        "evidence": [
            {"kind": "log_line", "ref": "log-99999", "claim": "Bogus log ref not in bundle"},
        ],
        "suggested_fix_strategy": "Fix bug",
    }

    rca, issues = validate_and_ground_rca(bundle, bogus_submission)
    assert any("Ungrounded" in iss for iss in issues)
    assert rca.confidence <= 0.4


def test_bedrock_converse_tool_loop_mock():
    """Verify tool-use loop with Bedrock Converse API mocking."""
    bundle = _create_sample_bundle(with_error=True)
    mock_client = MagicMock()

    # Turn 1: Model calls query_logs
    turn1_resp = {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tu-1",
                            "name": "query_logs",
                            "input": {"pattern": "AttributeError"},
                        }
                    }
                ],
            }
        },
    }

    # Turn 2: Model calls submit_rca
    turn2_resp = {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "tu-2",
                            "name": "submit_rca",
                            "input": {
                                "incident_id": bundle.incident_id,
                                "classification": "code_defect",
                                "severity": "sev2",
                                "confidence": 0.9,
                                "summary": "AttributeError on missing order in sample_service/app.py",
                                "suspected_location": {"file": "sample_service/app.py", "line": 29},
                                "evidence": [
                                    {"kind": "log_line", "ref": "log-2", "claim": "AttributeError traceback in logs"},
                                    {"kind": "stack_frame", "ref": "sample_service/app.py:29", "claim": "Faulting line"},
                                ],
                                "suggested_fix_strategy": "Return 404 for missing orders.",
                            },
                        }
                    }
                ],
            }
        },
    }

    mock_client.converse.side_effect = [turn1_resp, turn2_resp]

    rca = run_rca_agent(bundle, bedrock_client=mock_client)
    assert rca.classification == "code_defect"
    assert rca.confidence == 0.9
    assert rca.suspected_location.file == "sample_service/app.py"
    assert mock_client.converse.call_count == 2
