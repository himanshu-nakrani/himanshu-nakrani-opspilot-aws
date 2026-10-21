"""Unit tests for the FastAPI SRE Dashboard."""

import os

import pytest
from fastapi.testclient import TestClient
from dashboard.app import dashboard_app, seed_cache_from_fixtures

client = TestClient(dashboard_app)


@pytest.fixture(autouse=True)
def setup_dashboard():
    seed_cache_from_fixtures()


def test_tickets_page_lists_open_opscenter_items(monkeypatch):
    import dashboard.app as app_mod

    monkeypatch.setattr(
        app_mod,
        "list_opscenter_tickets",
        lambda: [
            {
                "key": "oi-open",
                "title": "missing order",
                "status": "Open",
                "severity": "2",
                "priority": 2,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": None,
                "incident_id": "inc-open",
                "url": "https://example/oi-open",
                "source": "opscenter",
                "category": "Availability",
            },
            {
                "key": "oi-done",
                "title": "resolved",
                "status": "Resolved",
                "severity": "4",
                "priority": 4,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": None,
                "incident_id": "inc-done",
                "url": "https://example/oi-done",
                "source": "opscenter",
                "category": "Availability",
            },
        ],
    )
    with TestClient(dashboard_app) as c:
        page = c.get("/tickets")
        assert page.status_code == 200 and "OpsPilot" in page.text
        open_rows = c.get("/api/tickets").json()
        assert open_rows["view"] == "open"
        assert [row["key"] for row in open_rows["tickets"]] == ["oi-open"]
        assert open_rows["counts"]["all"] == 2 and open_rows["counts"]["open"] == 1
        assert open_rows["recorded"]
        assert all(row["source"] == "dashboard" for row in open_rows["recorded"])
        assert c.get("/api/tickets?view=all").json()["tickets"][1]["key"] == "oi-done"
        assert c.get("/api/tickets?view=nope").status_code == 400


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
    # Seeded incidents offer a diff and wait. A pull request counts only after Raise PR.
    assert stats["total_prs_opened"] == 0
    awaiting = [i for i in client.get("/api/incidents").json() if i.get("status") == "AWAITING_CHOICE"]
    assert awaiting and all(i.get("patch_diff") and not i.get("pr_url") for i in awaiting)


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


def test_every_scenario_simulates_and_matches_router(monkeypatch):
    """Every scenario's dashboard outcome must equal opspilot.route.route_rca, both ways."""
    import dashboard.app as app_mod
    from dashboard.scenarios import SCENARIOS
    from opspilot.route import route_rca

    def started(event):
        return {"status": "started", "incident_id": f"inc-route-{event['detail']['alarmName']}"}

    monkeypatch.setattr(app_mod, "handle_alarm_event", started)
    with TestClient(dashboard_app) as c:
        for sid, sc in SCENARIOS.items():
            data = c.post("/api/trigger", json={"scenario": sid}).json()
            inc = data["incident"]
            assert data["scenario"] == sid and inc["classification"] == sc["classification"]
            assert inc["status"] != "DUPLICATE_SKIPPED", sid
            route = route_rca(_scenario_rca(sid, sc))
            if route == "propose_fix":
                assert inc["status"] == "AWAITING_CHOICE", sid
                assert inc["patch_diff"], sid
                assert inc["pr_branch"] is None, sid
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
    assert first["status"] == "AWAITING_CHOICE"
    assert other["status"] == "NOTIFIED"
    assert again["status"] == "DUPLICATE_SKIPPED"


def test_fixture_diffs_match_the_suspected_function():
    """Seeded create_order incidents must not be offered the planted get_order patch."""
    with TestClient(dashboard_app) as c:
        incidents = {i["incident_id"]: i for i in c.get("/api/incidents").json()}
    created = incidents["inc-eval-09"]
    assert created["status"] == "AWAITING_CHOICE"
    assert created["suspected_location"]["function"] == "create_order"
    assert created["can_raise_pr"] is True
    assert "customer_id is required" in created["patch_diff"]
    assert "def get_order" not in created["patch_diff"]
    orders = incidents["inc-eval-01"]
    assert orders["suspected_location"]["function"] == "get_order"
    assert "status_code=404" in orders["patch_diff"]
    assert orders["can_raise_pr"] is True


def test_authored_diff_without_a_generator_hides_raise_pr():
    from dashboard.app import LOCAL_INCIDENTS_CACHE

    inc_id = "inc-no-generator"
    LOCAL_INCIDENTS_CACHE.insert(0, {
        "incident_id": inc_id,
        "service": "sample-service",
        "detected_at": "2026-10-21T00:00:00+00:00",
        "status": "AWAITING_CHOICE",
        "classification": "code_defect",
        "confidence": 0.9,
        "severity": "sev2",
        "summary": "Unknown coupon is indexed without a check.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 177, "function": "checkout"},
        "evidence": [{"kind": "stack_frame", "ref": "sample_service/faults.py:177", "claim": "COUPONS[coupon]"}],
        "suggested_fix_strategy": "Return 400 for an unknown coupon.",
        "patch_diff": "--- a/sample_service/faults.py\n+++ b/sample_service/faults.py\n@@ -1 +1 @@\n-old\n+new\n",
        "pr_url": None,
        "source": "fixture",
    })
    with TestClient(dashboard_app) as c:
        body = c.get(f"/api/incidents/{inc_id}").json()
        assert "faults.py" in body["patch_diff"]
        assert body["can_raise_pr"] is False
        refused = c.post(f"/api/incidents/{inc_id}/fix-choice", json={"action": "raise_pr"})
        assert refused.status_code == 400
        assert "No fix generator" not in refused.text
        applied = c.post(f"/api/incidents/{inc_id}/fix-choice", json={"action": "apply_myself"})
        assert applied.status_code == 200
        assert applied.json()["status"] == "APPLY_MYSELF"
        assert applied.json()["can_raise_pr"] is False


def test_unknown_scenario_is_rejected():
    with TestClient(dashboard_app) as c:
        assert c.post("/api/trigger", json={"scenario": "nope"}).status_code == 400


def test_fix_choice_apply_myself_or_raise_pr(monkeypatch):
    """The incident offers the diff first. Apply-myself opens nothing. Raise PR opens one."""
    import dashboard.app as app_mod
    from opspilot.contracts import PrRef

    seq = {"n": 0}

    def fake_ingest(_event):
        seq["n"] += 1
        return {"status": "started", "incident_id": f"inc-choice-{seq['n']}"}

    def fake_propose(rca, ticket, **kwargs):
        assert os.environ.get("CODECOMMIT_REPO") == "opspilot-sample-service"
        assert rca.suspected_location.function == "get_order"
        return PrRef(
            branch=f"opspilot/{ticket.key}",
            base="main",
            repro_test_path="sample_service/tests/test_get_order_repro.py",
            pr_url="https://codecommit.example/pr/9",
            pr_number=9,
        )

    monkeypatch.setattr(app_mod, "handle_alarm_event", fake_ingest)
    monkeypatch.setattr(app_mod, "propose_fix", fake_propose)
    with TestClient(dashboard_app) as c:
        first = c.post("/api/trigger", json={"scenario": "null_order"}).json()["incident"]
        assert first["status"] == "AWAITING_CHOICE" and first["pr_url"] is None and first["patch_diff"]

        manual = c.post(f"/api/incidents/{first['incident_id']}/fix-choice", json={"action": "apply_myself"})
        assert manual.status_code == 200
        assert manual.json()["status"] == "APPLY_MYSELF"
        assert manual.json()["pr_url"] is None
        assert c.post(f"/api/incidents/{first['incident_id']}/fix-choice", json={"action": "raise_pr"}).status_code == 409

        second = c.post("/api/trigger", json={"scenario": "null_order"}).json()["incident"]
        assert "status_code=404" in second["patch_diff"] and second["can_raise_pr"] is True
        raised = c.post(f"/api/incidents/{second['incident_id']}/fix-choice", json={"action": "raise_pr"})
        assert raised.status_code == 200, raised.text
        opened = raised.json()
        assert opened["status"] == "PR_OPENED"
        assert opened["pr_url"] == "https://codecommit.example/pr/9"
        assert opened["pr_branch"].startswith("opspilot/")
        assert opened["patch_diff"]

        missing = c.post("/api/trigger", json={"scenario": "missing_field"}).json()["incident"]
        assert missing["suspected_location"]["function"] == "create_order"
        assert "customer_id is required" in missing["patch_diff"]
        assert "status_code=422" in missing["patch_diff"]
        assert "def get_order" not in missing["patch_diff"]
        assert missing["can_raise_pr"] is True

        def fake_propose_create(rca, ticket, **kwargs):
            assert rca.suspected_location.function == "create_order"
            return PrRef(
                branch=f"opspilot/{ticket.key}",
                base="main",
                repro_test_path="sample_service/tests/test_create_order_repro.py",
                pr_url="https://codecommit.example/pr/10",
                pr_number=10,
            )

        monkeypatch.setattr(app_mod, "propose_fix", fake_propose_create)
        created = c.post(f"/api/incidents/{missing['incident_id']}/fix-choice", json={"action": "raise_pr"})
        assert created.status_code == 200, created.text
        assert created.json()["pr_url"] == "https://codecommit.example/pr/10"
        assert "customer_id is required" in created.json()["patch_diff"]

        notified = c.post("/api/trigger", json={"scenario": "config_env"}).json()["incident"]
        assert notified["can_raise_pr"] is False
        assert c.post(f"/api/incidents/{notified['incident_id']}/fix-choice", json={"action": "raise_pr"}).status_code == 400


# --- Agent runs and traces ---

def test_fixture_incidents_record_agent_runs_with_spans():
    with TestClient(dashboard_app) as c:
        runs = c.get("/api/runs").json()
        incidents = [i for i in c.get("/api/incidents").json() if i.get("source") == "fixture"]
        assert runs, "seeded fixtures should record agent runs"
        run_ids = {r["run_id"] for r in runs}
        linked = [i for i in incidents if i.get("agent_run_id")]
        assert linked and all(i["agent_run_id"] in run_ids for i in linked)
        assert all("spans" not in r for r in runs)  # list is summaries only

        run = c.get(f"/api/runs/{runs[0]['run_id']}").json()
        kinds = {s["kind"] for s in run["spans"]}
        assert {"cycle", "model", "tool"} <= kinds
        tools = [s for s in run["spans"] if s["kind"] == "tool"]
        assert len(tools) == run["tool_calls"]
        assert all(s["duration_ms"] is not None and s["start_ms"] is not None for s in run["spans"])
        ids = {s["id"] for s in run["spans"]}
        assert all(s["parent_id"] is None or s["parent_id"] in ids for s in run["spans"])
        assert run["offline_model"] is True  # no Bedrock in tests: UI must flag stand-in tokens


def test_unknown_run_is_404():
    with TestClient(dashboard_app) as c:
        assert c.get("/api/runs/nope").status_code == 404


def test_simulated_incidents_have_no_agent_run():
    with TestClient(dashboard_app) as c:
        res = c.post("/api/trigger", json={"scenario": "dependency_timeout"}).json()
        inc = res.get("incident") or {}
        assert not inc.get("agent_run_id")


def test_build_spans_pairs_tool_history_and_flags_blocked_calls():
    from dashboard.runs import build_spans
    traces = [{"id": "c1", "name": "Cycle 1", "start_time": 10.0, "end_time": 10.5, "duration": 0.5, "children": [
        {"id": "m1", "name": "stream_messages", "start_time": 10.0, "end_time": 10.1, "duration": 0.1,
         "message": {"content": [{"toolUse": {"name": "get_file", "input": {"path": "x"}}}],
                     "metadata": {"usage": {"inputTokens": 5, "outputTokens": 2}, "metrics": {"latencyMs": 9}}}},
        {"id": "t1", "name": "Tool: get_file", "start_time": 10.1, "end_time": 10.2, "duration": 0.1,
         "metadata": {"tool_name": "get_file"}},
    ]}]
    hist = [{"tool_name": "get_file", "input": {"path": "x"}, "output": "denied", "status": "policy_violation"}]
    spans = build_spans(traces, hist)
    model, tool = spans[1], spans[2]
    assert model["input_tokens"] == 5 and "get_file" in model["output"]
    assert tool["start_ms"] == 100.0 and tool["status"] == "error" and tool["policy_status"] == "policy_violation"
    assert '"path": "x"' in tool["input"]
