"""Tests for sample service behavior and planted bug."""

import pytest
from fastapi.testclient import TestClient
from sample_service.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_valid_order_101():
    res = client.get("/orders/101")
    assert res.status_code == 200
    assert res.json()["total"] == 49.99


def test_valid_order_102():
    res = client.get("/orders/102")
    assert res.status_code == 200
    assert res.json()["total"] == 120.50


def test_missing_order_triggers_attribute_error_500():
    """Verify the planted bug: missing order causes None.total AttributeError resulting in 500."""
    res = client.get("/orders/999")
    assert res.status_code == 500
