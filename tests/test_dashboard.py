"""Unit tests for the FastAPI SRE Dashboard."""

import pytest
from fastapi.testclient import TestClient
from dashboard.app import dashboard_app, seed_cache_from_fixtures

client = TestClient(dashboard_app)


@pytest.fixture(autouse=True)
def setup_dashboard():
    seed_cache_from_fixtures()


def test_dashboard_home_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "OpsPilot" in response.text
    assert "Autonomous SRE Pipeline Architecture" in response.text
    assert "Grounded Evidence Breakdown" in response.text


def test_get_incidents_api():
    response = client.get("/api/incidents")
    assert response.status_code == 200
    incidents = response.json()
    assert isinstance(incidents, list)
    assert len(incidents) >= 10
    first = incidents[0]
    assert "incident_id" in first
    assert "classification" in first
    assert "confidence" in first


def test_get_incident_detail():
    incidents = client.get("/api/incidents").json()
    test_id = incidents[0]["incident_id"]

    response = client.get(f"/api/incidents/{test_id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["incident_id"] == test_id
    assert "summary" in detail
    assert "evidence" in detail


def test_get_incident_detail_not_found():
    response = client.get("/api/incidents/nonexistent-id-999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_stats_api():
    response = client.get("/api/stats")
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_incidents"] >= 10
    assert 0.0 <= stats["mean_confidence"] <= 1.0
    assert stats["total_prs_opened"] >= 1


def test_trigger_simulation_api():
    response = client.post("/api/trigger")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "incident" in data
    assert data["incident"]["classification"] == "code_defect"


def test_evals_api():
    response = client.get("/api/evals")
    assert response.status_code == 200
    evals = response.json()
    assert evals["total_fixtures"] == 10
    assert evals["classification_accuracy"] == 100.0
    assert evals["route_accuracy"] == 100.0
    assert len(evals["details"]) == 10
