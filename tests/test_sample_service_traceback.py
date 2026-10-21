"""The demo service's orders fault logs a traceback that CollectContext can parse.

Lives in the OpsPilot suite (not sample_service/tests) because the fix-verification CodeBuild job
only installs the sample service, and because this pins the unrepaired orders bug on main.
"""

from fastapi.testclient import TestClient

from opspilot.collect_context import parse_stack_trace_from_logs
from sample_service.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_orders_fault_traceback_parses_to_sample_service_frame(caplog):
    assert client.get("/orders/999").status_code == 500
    text = next(r.getMessage() for r in caplog.records if "Traceback" in r.getMessage())
    info = parse_stack_trace_from_logs([text])
    assert info is not None and info.error_type == "AttributeError"
    assert info.top_frame.file.endswith("sample_service/app.py") and info.top_frame.function == "get_order"
