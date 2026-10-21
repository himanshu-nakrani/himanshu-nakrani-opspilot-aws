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


def _scenario_rca(sid, sc):
    from opspilot.contracts import RcaResult
    return RcaResult(
        incident_id=f"inc-{sid}",
        classification=sc["classification"],
        severity=sc["severity"],
        confidence=sc["confidence"],
        summary=sc["summary"],
        suspected_location=sc.get("suspected_location"),
        evidence=sc["evidence"],
        suggested_fix_strategy=sc.get("suggested_fix_strategy") or "n/a",
    )


def test_every_scenario_simulates_and_matches_router():
    """Every scenario's dashboard outcome must equal opspilot.route.route_rca, both ways."""
    from dashboard.scenarios import SCENARIOS
    from opspilot.route import route_rca
    with TestClient(dashboard_app) as c:
        for sid, sc in SCENARIOS.items():
            data = c.post("/api/trigger", json={"scenario": sid}).json()
            inc = data["incident"]
            assert data["scenario"] == sid and inc["classification"] == sc["classification"]
            assert inc["status"] != "DUPLICATE_SKIPPED", sid
            route = route_rca(_scenario_rca(sid, sc))
            if route == "propose_fix":
                assert inc["status"] == "PROPOSED", sid
                assert inc["patch_diff"] and inc["pr_branch"], sid
            else:
                assert inc["status"] == "NOTIFIED", sid
                assert inc["patch_diff"] is None and inc["pr_branch"] is None, sid
            assert inc["pr_url"] is None


def test_catalogue_has_both_routes():
    from dashboard.scenarios import SCENARIOS
    from opspilot.route import route_rca
    routes = {route_rca(_scenario_rca(sid, sc)) for sid, sc in SCENARIOS.items()}
    assert routes == {"propose_fix", "notify"}


def test_high_confidence_without_stack_frame_notifies():
    """determine_route would say propose_fix here; the stack-frame check must still veto it."""
    import copy
    from dashboard.scenarios import SCENARIOS, expected_status
    from opspilot.route import determine_route, route_rca
    sc = copy.deepcopy(SCENARIOS["null_order"])
    sc["confidence"] = 0.95
    sc["evidence"] = [e for e in sc["evidence"] if e["kind"] != "stack_frame"]
    assert sc["evidence"]
    assert determine_route(sc["classification"], sc["confidence"]) == "propose_fix"
    assert route_rca(_scenario_rca("null_order", sc)) == "notify"
    assert expected_status(sc) == "NOTIFIED"


def test_simulation_identities_are_distinct_per_scenario():
    from dashboard.scenarios import SCENARIOS, simulation_alarm_name
    names = [simulation_alarm_name(sid) for sid in SCENARIOS]
    assert len(set(names)) == len(names)
    assert simulation_alarm_name("null_order") == SCENARIOS["null_order"]["alarm_name"]


def test_different_scenarios_do_not_dedupe_but_repeats_do(monkeypatch):
    """With a deduping ingest (as in live AWS mode), two different scenarios in one window are
    separate incidents, and re-running the same scenario is skipped as a duplicate."""
    import dashboard.app as app_mod
    from datetime import datetime, timezone
    from opspilot.ingest import compute_incident_id

    seen = set()

    def fake_ingest(event):
        when = datetime.fromisoformat(event["time"])
        inc_id, _, _ = compute_incident_id(event["detail"]["alarmName"], when.replace(minute=0, second=0))
        if inc_id in seen:
            return {"status": "duplicate", "incident_id": inc_id}
        seen.add(inc_id)
        return {"status": "started", "incident_id": inc_id}

    monkeypatch.setattr(app_mod, "handle_alarm_event", fake_ingest)
    with TestClient(dashboard_app) as c:
        first = c.post("/api/trigger", json={"scenario": "null_order"}).json()["incident"]
        other = c.post("/api/trigger", json={"scenario": "config_env"}).json()["incident"]
        again = c.post("/api/trigger", json={"scenario": "config_env"}).json()["incident"]
    assert first["status"] == "PROPOSED"
    assert other["status"] == "NOTIFIED"
    assert again["status"] == "DUPLICATE_SKIPPED"


def test_unknown_scenario_is_rejected():
    with TestClient(dashboard_app) as c:
        assert c.post("/api/trigger", json={"scenario": "nope"}).status_code == 400
