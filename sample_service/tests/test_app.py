"""Unit tests for sample service (pass on main branch)."""

from fastapi.testclient import TestClient
from sample_service.app import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_existing_order_101():
    response = client.get("/orders/101")
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "101"
    assert data["total"] == 49.99
    assert data["status"] == "completed"


def test_get_existing_order_102():
    response = client.get("/orders/102")
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "102"
    assert data["total"] == 120.50
    assert data["status"] == "processing"
