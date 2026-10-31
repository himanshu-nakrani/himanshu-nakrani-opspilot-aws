"""Planted demo faults fire for their trigger input and only for it."""

import json

import pytest
from fastapi.testclient import TestClient

from sample_service import faults
from sample_service.app import app


@pytest.fixture(autouse=True)
def fast_faults(monkeypatch):
    monkeypatch.setattr(faults, "DB_TIMEOUT_S", 0.0)
    monkeypatch.setattr(faults, "LEGACY_GATEWAY_LATENCY_S", 0.0)
    monkeypatch.setattr(faults, "REPORT_MB_PER_DAY", 1)


client = TestClient(app, raise_server_exceptions=False)


def _json_lines(out: str):
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


EXPECTED_FAULT_IDS = {
    "orders", "checkout", "inventory", "payments", "reports",
    "basket", "settings", "payments_down", "writes", "pricing",
    "shipments", "refunds", "tax",
}


def test_fault_catalog_entries_are_complete():
    payload = client.get("/faults").json()
    assert payload["service"] == "sample-service"
    ids = [entry["id"] for entry in payload["faults"]]
    assert ids, "catalog must not be empty"
    assert len(ids) == len(set(ids)), f"duplicate fault ids: {ids}"
    assert set(ids) == EXPECTED_FAULT_IDS
    for entry in payload["faults"]:
        assert {"id", "trigger", "symptom", "alarm", "expected_route"} <= set(entry)
        assert entry["alarm"].startswith(("OpsPilotSampleService",))


def test_healthy_paths_return_200():
    for path in ["/health", "/orders/101", "/checkout?sku=SKU-2&coupon=WELCOME10",
                 "/inventory/SKU-1", "/payments/101/status", "/reports/export?days=2"]:
        assert client.get(path).status_code == 200, path


def test_checkout_valid_coupon_math():
    body = client.get("/checkout?sku=SKU-1&qty=2&coupon=VIP20").json()
    assert body["subtotal"] == 178.0 and body["discount"] == 35.6 and body["total"] == 142.4


# CodeBuild runs this suite on every fix branch, so it must not pin a bug that the fix agent is
# expected to repair. Orders (/orders/999) and checkout (unknown coupon) are those bugs.
# Traceback parsing for orders stays in tests/test_sample_service_traceback.py (OpsPilot suite).
@pytest.mark.parametrize("path,component,error_type", [
    ("/inventory/BULK-42", "inventory", "InventoryDbTimeout"),
])
def test_planted_errors_return_500_and_log_structured_event(path, component, error_type, capsys, caplog):
    assert client.get(path).status_code == 500
    events = [e for e in _json_lines(capsys.readouterr().out) if e["event"] == "unhandled_exception"]
    assert events and events[-1]["component"] == component and events[-1]["error_type"] == error_type
    # The plain traceback CollectContext parses must be in the log too.
    assert any("Traceback (most recent call last)" in r.getMessage() for r in caplog.records)


def test_legacy_gateway_is_slow_but_succeeds(monkeypatch):
    monkeypatch.setattr(faults, "LEGACY_GATEWAY_LATENCY_S", 0.05)
    r = client.get("/payments/77/status?provider=legacy")
    assert r.status_code == 200 and r.json()["status"] == "captured"


def test_report_export_buffers_memory_per_day():
    assert client.get("/reports/export?days=3").json()["buffered_mb"] == 3
