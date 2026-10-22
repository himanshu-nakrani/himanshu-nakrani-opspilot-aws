"""Tests for AWS Strands Agents SDK integration in OpsPilot."""

import pytest
from strands import Agent
from strands.tools.decorator import DecoratedFunctionTool

from opspilot.contracts import ContextBundle, LogLine, RcaResult
from opspilot.agentcore import AgentCoreRuntime
from opspilot.rca.strands_agent import create_strands_rca_agent, run_strands_rca


def _sample_bundle() -> ContextBundle:
    logs = [
        LogLine(id="log-101", timestamp="2026-10-20T12:00:00Z", message="Starting batch processor"),
        LogLine(
            id="log-102",
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
        incident_id="inc-strands-test-1",
        service="sample-service",
        log_group="/aws/lambda/opspilot-sample-service",
        detected_at="2026-10-20T12:00:00Z",
        log_lines=logs,
        stack_trace=st,
        repo="himanshu-nakrani/opspilot-aws-poc",
        repo_files={"sample_service/app.py": "def get_order(order_id: str):\n    order = ORDERS.get(order_id)\n    return {'total': order.total}\n"},
    )


def test_create_strands_rca_agent():
    """Verify that create_strands_rca_agent instantiates an AWS Strands Agent."""
    bundle = _sample_bundle()
    agent = create_strands_rca_agent(bundle)

    assert isinstance(agent, Agent)
    assert agent.name == f"OpsPilot-RCA-{bundle.incident_id}"
    assert len(agent.tool_names) == 5
    for tool_name in ["query_logs", "get_file", "get_commit_diff", "submit_rca"]:
        assert tool_name in agent.tool_names


def test_strands_tools_spec_generation():
    """Verify that Strands tools generate valid OpenAPI/Bedrock schemas."""
    bundle = _sample_bundle()
    agent = create_strands_rca_agent(bundle)

    specs = agent.tool_registry.get_all_tool_specs()
    assert len(specs) == 5
    for spec in specs:
        assert "name" in spec
        assert "description" in spec
        assert "inputSchema" in spec
        assert "json" in spec["inputSchema"]
        assert spec["inputSchema"]["json"].get("type") == "object"


def test_strands_agent_execution_loop():
    """Verify that the Strands Agent executes multi-turn tool calling event loop."""
    bundle = _sample_bundle()
    agent = create_strands_rca_agent(bundle)

    result = agent("Please analyze the incident context and find the root cause.")
    assert result.stop_reason == "end_turn"

    # Multi-turn messages: user -> assistant (toolUse) -> user (toolResult) -> assistant (toolUse) -> user (toolResult) -> assistant (text)
    assert len(agent.messages) >= 4
    tool_uses = [
        block["toolUse"]["name"]
        for msg in agent.messages
        if msg["role"] == "assistant"
        for block in msg["content"]
        if "toolUse" in block
    ]
    assert "query_logs" in tool_uses
    assert "submit_rca" in tool_uses


def test_run_strands_rca_end_to_end():
    """Verify run_strands_rca end-to-end RCA extraction and grounding."""
    bundle = _sample_bundle()
    rca = run_strands_rca(bundle)

    assert isinstance(rca, RcaResult)
    assert rca.classification == "code_defect"
    assert rca.confidence >= 0.70
    assert rca.suspected_location is not None
    assert rca.suspected_location.file == "sample_service/app.py"
    assert rca.suspected_location.line == 29

    valid_log_ids = {l.id for l in bundle.log_lines}
    for ev in rca.evidence:
        if ev.kind == "log_line":
            assert ev.ref in valid_log_ids or any(ev.ref in l.message for l in bundle.log_lines)
        elif ev.kind == "stack_frame":
            assert "sample_service/app.py" in ev.ref
