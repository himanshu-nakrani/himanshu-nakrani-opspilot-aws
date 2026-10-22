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


def test_missing_customer_id_is_500():
    res = client.post("/orders", json={})
    assert res.status_code == 500


def test_unknown_coupon_is_500():
    res = client.get("/checkout", params={"sku": "SKU-1", "qty": 2, "coupon": "SPRING50"})
    assert res.status_code == 500


def test_empty_basket_average_is_500():
    res = client.get("/basket/average", params={"count": 0})
    assert res.status_code == 500


def test_missing_orders_table_is_500():
    res = client.get("/settings")
    assert res.status_code == 500


def test_payment_gateway_down_is_500():
    res = client.get("/payments/77/status", params={"provider": "down"})
    assert res.status_code == 500


def test_throttled_write_is_500():
    res = client.post("/writes/orders", json={})
    assert res.status_code == 500
