"""Unit tests for context collector."""

from opspilot.collect_context import collect_context_bundle, parse_stack_trace_from_logs
from opspilot.contracts import IncidentEvent, LogLine


def test_parse_python_stack_trace():
    raw_logs = [
        "2026-10-20T12:00:00Z INFO [app] Incoming GET /orders/999",
        "Traceback (most recent call last):",
        '  File "/var/task/sample_service/app.py", line 29, in get_order',
        '    "total": order.total,',
        "AttributeError: 'NoneType' object has no attribute 'total'",
    ]

    st = parse_stack_trace_from_logs(raw_logs)
    assert st is not None
    assert st.error_type == "AttributeError"
    assert "NoneType" in st.error_message
    assert len(st.frames) == 1
    assert st.frames[0].file == "sample_service/app.py"
    assert st.frames[0].line == 29
    assert st.frames[0].function == "get_order"


def test_parse_stack_trace_none_when_no_traceback():
    raw_logs = [
        "2026-10-20T12:00:00Z INFO Health check ok",
        "2026-10-20T12:00:01Z INFO Handled 200 requests",
    ]
    st = parse_stack_trace_from_logs(raw_logs)
    assert st is None


def test_collect_context_bundle_with_sample_bug():
    incident_event = IncidentEvent(
        incident_id="test-incident-999",
        source="cloudwatch",
        service="sample-service",
        alarm_name="OpsPilotSampleServiceErrors",
        detected_at="2026-10-20T12:00:00Z",
        window_start="2026-10-20T12:00:00Z",
        window_end="2026-10-20T12:15:00Z",
        log_group="/aws/lambda/opspilot-sample-service",
        repo="himanshu-nakrani/opspilot-aws-poc",
    )

    mock_logs = [
        LogLine(id="log-1", timestamp="2026-10-20T12:00:00Z", message="Incoming GET /orders/999"),
        LogLine(
            id="log-2",
            timestamp="2026-10-20T12:00:01Z",
            message='Traceback (most recent call last):\n  File "/var/task/sample_service/app.py", line 29, in get_order\n    "total": order.total,\nAttributeError: \'NoneType\' object has no attribute \'total\'',
        ),
    ]

    bundle = collect_context_bundle(incident_event, mock_log_lines=mock_logs)
    assert bundle.incident_id == "test-incident-999"
    assert bundle.stack_trace is not None
    assert bundle.stack_trace.error_type == "AttributeError"
    assert "sample_service/app.py" in bundle.repo_files
    assert "ORDERS" in bundle.repo_files["sample_service/app.py"]
