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


# --- API contract tests: field names must match frontend/src/types.ts ---

EVALS_KEYS = {
    "total_fixtures", "passed_fixtures", "classification_correct", "route_correct",
    "location_hits", "location_total", "abstention_hits", "abstention_total",
    "classification_accuracy", "route_accuracy", "location_hit_rate", "abstention_precision",
    "evidence_ref_validity_rate", "mean_tokens", "mean_latency_ms", "targets",
    "all_targets_passed", "details",
}
EVAL_DETAIL_KEYS = {
    "id", "name", "gold_classification", "predicted_classification", "gold_route",
    "predicted_route", "confidence", "tokens", "latency_ms", "location_hit",
    "abstention_correct", "passed",
}


def test_evals_contract():
    with TestClient(dashboard_app) as client:
        data = client.get("/api/evals").json()
    assert EVALS_KEYS <= set(data)
    assert data["details"], "expected fixtures"
    for d in data["details"]:
        assert EVAL_DETAIL_KEYS <= set(d)
        assert isinstance(d["confidence"], float)
        assert isinstance(d["latency_ms"], float)
        assert isinstance(d["passed"], bool)
    assert data["passed_fixtures"] == sum(d["passed"] for d in data["details"])


def test_trigger_contract_and_no_fake_links():
    with TestClient(dashboard_app) as client:
        data = client.post("/api/trigger").json()
        assert {"incident_id", "summary", "simulated", "ingest_mode", "ingest_status", "failed_calls", "incident"} <= set(data)
        assert data["simulated"] is True
        assert data["incident_id"] == data["incident"]["incident_id"]
        assert data["incident"]["pr_url"] is None
        assert client.get(f"/api/incidents/{data['incident_id']}").status_code == 200


def test_stats_are_derived_not_hardcoded():
    with TestClient(dashboard_app) as client:
        stats = client.get("/api/stats").json()
    rate = stats["verification_pass_rate"]
    if stats["total_prs_opened"]:
        assert rate == round(stats["verified_prs"] / stats["total_prs_opened"], 3)
    else:
        assert rate is None
    assert stats["agentcore_policies_active"] and stats["agentcore_gateway_tools"]


def test_cors_does_not_allow_arbitrary_origins():
    with TestClient(dashboard_app) as client:
        res = client.options(
            "/api/stats",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
    assert res.headers.get("access-control-allow-origin") is None


# --- Simulation scenario catalogue ---

def test_scenarios_catalogue_covers_every_class():
    from dashboard.scenarios import SCENARIOS
    with TestClient(dashboard_app) as c:
        data = c.get("/api/scenarios").json()
    assert len(data) == len(SCENARIOS) >= 8
    assert {s["classification"] for s in data} == {
        "code_defect", "config_regression", "dependency", "resource", "insufficient_evidence",
    }
    assert {"id", "label", "description", "classification", "severity", "live_probe", "expected_outcome"} <= set(data[0])


def test_every_scenario_simulates_and_matches_router():
    from dashboard.scenarios import SCENARIOS
    from opspilot.route import determine_route
    with TestClient(dashboard_app) as c:
        for sid, sc in SCENARIOS.items():
            data = c.post("/api/trigger", json={"scenario": sid}).json()
            inc = data["incident"]
            assert data["scenario"] == sid and inc["classification"] == sc["classification"]
            if inc["status"] == "DUPLICATE_SKIPPED":
                continue
            if inc["status"] == "PROPOSED":
                assert determine_route(sc["classification"], sc["confidence"]) == "propose_fix"
                assert inc["patch_diff"] and inc["pr_branch"]
            else:
                assert inc["status"] == "NOTIFIED" and inc["patch_diff"] is None and inc["pr_branch"] is None
            assert inc["pr_url"] is None


def test_unknown_scenario_is_rejected():
    with TestClient(dashboard_app) as c:
        assert c.post("/api/trigger", json={"scenario": "nope"}).status_code == 400
