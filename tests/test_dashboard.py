"""Unit tests for the FastAPI SRE Dashboard."""

import os

import pytest
from fastapi.testclient import TestClient
from dashboard.app import dashboard_app, seed_cache_from_fixtures

client = TestClient(dashboard_app)
PROBE_CALLS = []


class _NoLiveAws:
    """Dashboard tests must not start a verify build or read the live pipeline."""

    def start_build(self, **kwargs):
        raise AssertionError("live CodeBuild")

    def batch_get_builds(self, **kwargs):
        raise AssertionError("live CodeBuild")

    def list_pipeline_executions(self, **kwargs):
        raise AssertionError("live CodePipeline")

    def get_pipeline_state(self, **kwargs):
        raise AssertionError("live CodePipeline")


def _begin_without_aws(pr, rca, codebuild_client=None):
    from opspilot.fix.agent import repro_pytest_node

    return {
        "test_status": "running",
        "test_name": repro_pytest_node(rca, pr.repro_test_path),
        "test_summary": "Verification test is running.",
        "test_log": "",
        "test_build_id": "",
        "test_error": None,
        "test_comment_posted": "",
    }


@pytest.fixture(autouse=True)
def setup_dashboard(monkeypatch):
    seed_cache_from_fixtures()
    import dashboard.app as app_mod

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    PROBE_CALLS.clear()

    def _fake_probe(probe):
        PROBE_CALLS.append(dict(probe))
        return {"http_status": 500, "error": None, "url": "https://sample.example" + probe["path"]}

    monkeypatch.setattr(app_mod, "deliver_live_probe", _fake_probe)
    monkeypatch.setattr(app_mod, "get_codebuild_client", lambda: _NoLiveAws())
    monkeypatch.setattr(app_mod, "get_pipeline_client", lambda: _NoLiveAws())
    monkeypatch.setattr(app_mod, "begin_pr_verification", _begin_without_aws)


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


def test_fixture_replay_stays_offline_when_aws_keys_are_set(monkeypatch):
    """Startup must not call Bedrock for the built-in samples just because DynamoDB keys exist."""
    import json
    from pathlib import Path

    import dashboard.app as app_mod
    from opspilot.agentcore import runtime as runtime_mod
    from opspilot.contracts import ContextBundle

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATESTLIVE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    seen = []
    real = runtime_mod.BedrockModel

    def recording_bedrock(*args, **kwargs):
        model_id = kwargs.get("model_id", "")
        seen.append(model_id)
        assert "kimi" not in model_id
        assert "moonshot" not in model_id
        return real(*args, **kwargs)

    monkeypatch.setattr(runtime_mod, "BedrockModel", recording_bedrock)
    fixture = json.loads(
        (Path(__file__).resolve().parents[1] / "evals" / "fixtures" / "01_sample_missing_order.json").read_text()
    )
    rca, session = app_mod._run_rca_with_trace(ContextBundle.model_validate(fixture["context_bundle"]))
    assert rca.classification == "code_defect"
    assert session is not None
    assert seen
    assert all("kimi" not in model_id and "moonshot" not in model_id for model_id in seen)


def test_live_dynamodb_incident_is_listed(monkeypatch):
    import json

    import dashboard.app as app_mod

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")

    class _Table:
        def scan(self, **kwargs):
            return {
                "Items": [
                    {
                        "incident_id": {"S": "live-orders-999"},
                        "service": {"S": "sample-service"},
                        "detected_at": {"S": "2099-10-22T21:11:27+00:00"},
                        "status": {"S": "RECORDED"},
                        "classification": {"S": "insufficient_evidence"},
                        "confidence": {"N": "0"},
                        "alarm_name": {"S": "OpsPilotSampleServiceErrors"},
                        "rca_result": {
                            "S": json.dumps(
                                {
                                    "summary": "Insufficient evidence: RCA agent failed (ValidationException)",
                                    "classification": "insufficient_evidence",
                                    "confidence": 0,
                                    "severity": "sev3",
                                }
                            )
                        },
                    }
                ]
            }

    monkeypatch.setattr(app_mod.boto3, "client", lambda *args, **kwargs: _Table())
    rows = client.get("/api/incidents").json()
    assert rows[0]["incident_id"] == "live-orders-999"
    assert rows[0]["source"] == "dynamodb"
    assert rows[0]["alarm_name"] == "OpsPilotSampleServiceErrors"


def test_instance_role_reads_dynamodb_without_an_access_key(monkeypatch):
    import dashboard.app as app_mod

    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

    class _Session:
        def get_credentials(self):
            return object()

    class _Table:
        def scan(self, **kwargs):
            return {
                "Items": [
                    {
                        "incident_id": {"S": "role-incident"},
                        "service": {"S": "sample-service"},
                        "detected_at": {"S": "2099-01-01T00:00:00+00:00"},
                        "classification": {"S": "code_defect"},
                        "confidence": {"N": "0.9"},
                    }
                ]
            }

    monkeypatch.setattr(app_mod.boto3, "Session", lambda: _Session())
    monkeypatch.setattr(app_mod.boto3, "client", lambda *args, **kwargs: _Table())
    rows = client.get("/api/incidents").json()
    assert rows[0]["incident_id"] == "role-incident"


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
    assert data["status"] == "accepted"
    assert data["scenario"] == "null_order"
    assert data["live_probe"] is True
    assert data["ingest_mode"] == "eventbridge"
    assert data["alarm_name"] == "OpsPilotSampleServiceErrors"
    assert data["probe"] == "GET /orders/999"
    assert data["incident"] is None


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
        before = {i["incident_id"] for i in client.get("/api/incidents").json()}
        data = client.post("/api/trigger").json()
        assert {
            "incident_id", "summary", "simulated", "ingest_mode", "ingest_status",
            "failed_calls", "incident", "alarm_name", "probe", "live_probe",
        } <= set(data)
        assert data["simulated"] is True
        assert data["ingest_mode"] == "eventbridge"
        assert data["incident"] is None
        assert data["incident_id"] == ""
        after = {i["incident_id"] for i in client.get("/api/incidents").json()}
        assert after == before


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
    assert {"id", "label", "description", "classification", "severity", "live_probe", "alarm_name", "expected_outcome"} <= set(data[0])
    assert all(s["live_probe"] is True and s["alarm_name"].startswith("OpsPilotSampleService") for s in data)


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


def test_every_scenario_calls_the_live_service():
    """Every simulation is one request to the sample service, aimed at a real alarm."""
    from dashboard.scenarios import SCENARIOS

    PROBE_CALLS.clear()
    with TestClient(dashboard_app) as c:
        for sid, sc in SCENARIOS.items():
            data = c.post("/api/trigger", json={"scenario": sid}).json()
            assert data["scenario"] == sid, sid
            assert data["status"] == "accepted", sid
            assert data["live_probe"] is True, sid
            assert data["ingest_mode"] == "eventbridge", sid
            assert data["ingest_status"] == "waiting_for_alarm", sid
            assert data["incident"] is None, sid
            assert data["alarm_name"] == sc["alarm_name"], sid
            assert data["alarm_name"].startswith("OpsPilotSampleService"), sid
            assert "-sim-" not in data["alarm_name"], sid
            assert data["probe"] == f"{sc['probe']['method']} {sc['probe']['path']}", sid
            assert data["http_status"] == 500, sid
    assert [call["path"] for call in PROBE_CALLS] == [sc["probe"]["path"] for sc in SCENARIOS.values()]


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


def test_simulation_uses_the_real_alarm_name():
    from dashboard.scenarios import SCENARIOS, simulation_alarm_name
    for sid, sc in SCENARIOS.items():
        assert simulation_alarm_name(sid) == sc["alarm_name"]
        assert sc["alarm_name"].startswith("OpsPilotSampleService")
        assert "-sim-" not in sc["alarm_name"]
        assert sc["probe"]["method"] in {"GET", "POST"}
        assert sc["probe"]["path"].startswith("/")


def test_repeat_triggers_each_call_the_sample_service():
    """Dedup happens when EventBridge delivers the alarm, so each click still sends the probe."""
    with TestClient(dashboard_app) as c:
        first = c.post("/api/trigger", json={"scenario": "null_order"}).json()
        other = c.post("/api/trigger", json={"scenario": "config_env"}).json()
        again = c.post("/api/trigger", json={"scenario": "config_env"}).json()
    assert first["probe"] == "GET /orders/999"
    assert first["alarm_name"] == "OpsPilotSampleServiceErrors"
    assert other["probe"] == again["probe"] == "GET /settings"
    assert other["alarm_name"] == "OpsPilotSampleService-ConfigErrors"
    assert first["incident"] is other["incident"] is again["incident"] is None


def test_planted_faults_aim_at_their_alarms():
    """Each planted fault calls the live route that the matching CloudWatch alarm watches."""
    from dashboard.endings import human_ending_text
    from dashboard.scenarios import SCENARIOS

    assert SCENARIOS["unknown_coupon"]["probe"]["path"].startswith("/checkout")
    assert SCENARIOS["unknown_coupon"]["alarm_name"] == "OpsPilotSampleService-CheckoutErrors"
    assert SCENARIOS["legacy_payment"]["alarm_name"] == "OpsPilotSampleService-LatencyP95"
    assert "provider=legacy" in SCENARIOS["legacy_payment"]["probe"]["path"]
    assert SCENARIOS["inventory_timeout"]["alarm_name"] == "OpsPilotSampleService-InventoryDbTimeouts"
    assert SCENARIOS["report_export"]["alarm_name"] == "OpsPilotSampleService-Crashes"
    code_issues = {
        "string_price": ("GET", "/pricing/SKU-1", "OpsPilotSampleService-PricingErrors", "quote_price"),
        "missing_shipment": ("GET", "/shipments/404", "OpsPilotSampleService-ShipmentErrors", "get_shipment"),
        "empty_refund": ("POST", "/refunds", "OpsPilotSampleService-RefundErrors", "create_refund"),
        "blank_tax_rate": ("GET", "/tax/quote?subtotal=10&rate=", "OpsPilotSampleService-TaxErrors", "tax_quote"),
    }
    owners: dict = {}
    for sid, sc in SCENARIOS.items():
        owners.setdefault(sc["alarm_name"], []).append(sid)
    for sid, (method, path, alarm, function) in code_issues.items():
        sc = SCENARIOS[sid]
        assert sc["classification"] == "code_defect"
        assert sc["confidence"] >= 0.6
        assert sc["probe"]["method"] == method and sc["probe"]["path"] == path
        assert sc["alarm_name"] == alarm
        assert owners[alarm] == [sid]
        assert sc["suspected_location"]["function"] == function
        ref = f"{sc['suspected_location']['file']}:{sc['suspected_location']['line']}"
        assert any(e["kind"] == "stack_frame" and e["ref"] == ref for e in sc["evidence"])
        assert "patch_diff" not in sc
    inventory_note = human_ending_text({
        "status": "NOTIFIED",
        "classification": "dependency",
        "summary": "Inventory lookup for BULK-42 hits a database timeout.",
        "suspected_location": {"function": "inventory"},
    })
    export_note = human_ending_text({
        "status": "NOTIFIED",
        "classification": "resource",
        "summary": "The report export runs out of memory.",
        "suspected_location": {"function": "export_report"},
    })
    assert inventory_note and "database timeout" in inventory_note
    assert export_note and "export runs out of memory" in export_note
    with TestClient(dashboard_app) as c:
        orders = c.get("/api/incidents/inc-eval-01").json()
    assert orders["can_raise_pr"] is True and orders["human_ending"] is None
    assert orders.get("pr_url") is None and orders.get("deploy_status") is None and orders.get("test_status") is None


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
        "summary": "Inventory lookup for BULK-42 hits a database timeout.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 112, "function": "inventory"},
        "evidence": [{"kind": "log_line", "ref": "log-1", "claim": "InventoryDbTimeout"}],
        "suggested_fix_strategy": "A person has to look at the inventory database.",
        "patch_diff": "--- a/sample_service/faults.py\n+++ b/sample_service/faults.py\n@@ -1 +1 @@\n-old\n+new\n",
        "pr_url": None,
        "source": "fixture",
    })
    with TestClient(dashboard_app) as c:
        body = c.get(f"/api/incidents/{inc_id}").json()
        assert "faults.py" in body["patch_diff"]
        assert body["can_raise_pr"] is False
        assert "database timeout" in body["human_ending"]
        assert body.get("test_status") is None and body.get("deploy_status") is None
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


def _seed_incident(inc_id: str, **overrides) -> str:
    from dashboard.app import LOCAL_INCIDENTS_CACHE

    row = {
        "incident_id": inc_id,
        "service": "sample-service",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "detected_at": "2026-10-23T00:00:00+00:00",
        "status": "AWAITING_CHOICE",
        "classification": "code_defect",
        "confidence": 0.94,
        "severity": "sev2",
        "summary": "AttributeError on missing order ID",
        "suspected_location": {"file": "sample_service/app.py", "line": 36, "function": "get_order"},
        "evidence": [{"kind": "stack_frame", "ref": "sample_service/app.py:36", "claim": "order.total"}],
        "suggested_fix_strategy": "Return 404 when the order is missing.",
        "patch_diff": None,
        "pr_url": None,
        "source": "fixture",
    }
    row.update(overrides)
    LOCAL_INCIDENTS_CACHE.insert(0, row)
    return inc_id


def test_fix_choice_apply_myself_or_raise_pr(monkeypatch):
    """Apply-myself can still raise a PR. A second raise after that PR is open is refused."""
    import dashboard.app as app_mod
    from opspilot.contracts import PrRef

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

    monkeypatch.setattr(app_mod, "propose_fix", fake_propose)
    with TestClient(dashboard_app) as c:
        first_id = _seed_incident("inc-choice-orders")
        first = c.get(f"/api/incidents/{first_id}").json()
        assert first["status"] == "AWAITING_CHOICE" and first["pr_url"] is None and first["patch_diff"]

        manual = c.post(f"/api/incidents/{first['incident_id']}/fix-choice", json={"action": "apply_myself"})
        assert manual.status_code == 200
        assert manual.json()["status"] == "APPLY_MYSELF"
        assert manual.json()["pr_url"] is None
        assert manual.json()["can_raise_pr"] is True
        assert c.get(f"/api/incidents/{first['incident_id']}/pr-status").status_code == 404

        changed_mind = c.post(f"/api/incidents/{first['incident_id']}/fix-choice", json={"action": "raise_pr"})
        assert changed_mind.status_code == 200, changed_mind.text
        opened_later = changed_mind.json()
        assert opened_later["status"] == "PR_OPENED"
        assert opened_later["pr_url"] == "https://codecommit.example/pr/9"
        assert opened_later["pr_number"] == 9
        assert opened_later["can_raise_pr"] is False
        assert c.post(f"/api/incidents/{first['incident_id']}/fix-choice", json={"action": "raise_pr"}).status_code == 409

        class FakeScm:
            def get_pull_request_status(self, pr_id):
                assert str(pr_id) == "9"
                return {"pr_number": 9, "status": "open", "pull_request_status": "OPEN", "is_merged": None}

        monkeypatch.setattr(app_mod, "get_scm_client", lambda: FakeScm())
        live = c.get(f"/api/incidents/{first['incident_id']}/pr-status")
        assert live.status_code == 200, live.text
        assert live.json()["status"] == "open"
        assert live.json()["pull_request_status"] == "OPEN"
        assert live.json()["error"] is None
        assert live.json()["pr_url"] == "https://codecommit.example/pr/9"

        second_id = _seed_incident("inc-choice-orders-2")
        second = c.get(f"/api/incidents/{second_id}").json()
        assert "status_code=404" in second["patch_diff"] and second["can_raise_pr"] is True
        raised = c.post(f"/api/incidents/{second['incident_id']}/fix-choice", json={"action": "raise_pr"})
        assert raised.status_code == 200, raised.text
        opened = raised.json()
        assert opened["status"] == "PR_OPENED"
        assert opened["pr_url"] == "https://codecommit.example/pr/9"
        assert opened["pr_branch"].startswith("opspilot/")
        assert opened["patch_diff"]
        assert opened["test_status"] == "running"
        assert opened["deploy_status"] == "not_started"
        assert opened["human_ending"] is None
        assert "deploy has not started" in (opened.get("deploy_summary") or "")

        missing_id = _seed_incident(
            "inc-choice-create",
            summary="Unhandled KeyError customer_id in create_order",
            suspected_location={"file": "sample_service/app.py", "line": 43, "function": "create_order"},
            evidence=[{"kind": "stack_frame", "ref": "sample_service/app.py:43", "claim": "payload['customer_id']"}],
            suggested_fix_strategy="Validate the request body and return 422 when customer_id is missing.",
        )
        missing = c.get(f"/api/incidents/{missing_id}").json()
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

        notified_id = _seed_incident(
            "inc-choice-config",
            status="NOTIFIED",
            classification="config_regression",
            confidence=0.88,
            summary="Configuration regression: ORDERS_TABLE env var missing after the latest deploy.",
            suspected_location=None,
            evidence=[{"kind": "log_line", "ref": "log-1", "claim": "KeyError: 'ORDERS_TABLE'"}],
            suggested_fix_strategy="Restore ORDERS_TABLE in the Lambda environment and redeploy.",
            alarm_name="OpsPilotSampleService-ConfigErrors",
        )
        notified = c.get(f"/api/incidents/{notified_id}").json()
        assert notified["can_raise_pr"] is False
        assert c.post(f"/api/incidents/{notified['incident_id']}/fix-choice", json={"action": "raise_pr"}).status_code == 400


def _pr_incident(inc_id: str, pr_url: str, pr_number: int = 9) -> None:
    from dashboard.app import LOCAL_INCIDENTS_CACHE

    LOCAL_INCIDENTS_CACHE.insert(0, {
        "incident_id": inc_id,
        "service": "sample-service",
        "detected_at": "2026-10-21T00:00:00+00:00",
        "status": "PR_OPENED",
        "classification": "code_defect",
        "confidence": 0.9,
        "severity": "sev2",
        "summary": "Suggested fix",
        "suspected_location": {"file": "sample_service/faults.py", "line": 177, "function": "checkout"},
        "evidence": [],
        "suggested_fix_strategy": "Apply the diff.",
        "patch_diff": "--- a/sample_service/faults.py\n+++ b/sample_service/faults.py\n@@ -1 +1 @@\n-old\n+new\n",
        "pr_url": pr_url,
        "pr_number": pr_number,
        "pr_branch": "opspilot/OPS-1",
        "source": "fixture",
    })


def test_code_defect_middleware_frame_offers_checkout_patch_and_raise_pr():
    """A notified code defect still shows the exact diff and Raise PR when a frame names checkout."""
    inc_id = _seed_incident(
        "inc-checkout-middleware",
        status="NOTIFIED",
        summary="Unhandled KeyError in checkout() for coupon SPRING50",
        suspected_location={"file": "sample_service/faults.py", "line": 160, "function": "log_requests"},
        evidence=[
            {
                "kind": "stack_frame",
                "ref": "sample_service/faults.py:160",
                "claim": "log_requests middleware re-raises the endpoint KeyError",
            },
            {
                "kind": "stack_frame",
                "ref": "sample_service/faults.py:209",
                "claim": "checkout endpoint indexes COUPONS[coupon] and raises KeyError",
            },
        ],
        suggested_fix_strategy="Validate the coupon before indexing COUPONS.",
        patch_diff=None,
        alarm_name="OpsPilotSampleService-CheckoutErrors",
    )
    with TestClient(dashboard_app) as client:
        body = client.get(f"/api/incidents/{inc_id}").json()
    assert body["can_raise_pr"] is True
    assert "invalid coupon" in body["patch_diff"]
    assert body["human_ending"] is None


def test_fixture_branch_name_is_not_a_pull_request():
    """inc-eval-01 is a fixture. A branch label without an http link is not a CodeCommit PR."""
    from dashboard.app import LOCAL_INCIDENTS_CACHE

    with TestClient(dashboard_app) as c:
        seeded = c.get("/api/incidents/inc-eval-01").json()
        assert seeded["status"] == "AWAITING_CHOICE"
        assert seeded["ticket_key"] == "OPS-342"
        assert seeded["can_raise_pr"] is True
        assert seeded.get("pr_url") is None
        assert seeded.get("pr_branch") is None
        assert c.get("/api/incidents/inc-eval-01/pr-status").status_code == 404

    LOCAL_INCIDENTS_CACHE.insert(0, {
        "incident_id": "inc-branch-label",
        "service": "sample-service",
        "detected_at": "2026-10-21T00:00:00+00:00",
        "status": "PR_OPENED",
        "classification": "code_defect",
        "confidence": 0.9,
        "severity": "sev2",
        "summary": "missing order",
        "suspected_location": {"file": "sample_service/app.py", "line": 29, "function": "get_order"},
        "evidence": [{"kind": "stack_frame", "ref": "sample_service/app.py:29", "claim": "order.total"}],
        "suggested_fix_strategy": "Return 404 when the order is missing.",
        "patch_diff": "--- a/sample_service/app.py\n+++ b/sample_service/app.py\n@@ -1 +1 @@\n-old\n+new\n",
        "ticket_key": "OPS-342",
        "pr_branch": "opspilot/OPS-342",
        "pr_url": "opspilot/OPS-342",
        "source": "fixture",
    })
    with TestClient(dashboard_app) as c:
        body = c.get("/api/incidents/inc-branch-label").json()
        assert body["pr_url"] is None
        assert body["pr_branch"] is None
        assert body["can_raise_pr"] is True
        refused = c.get("/api/incidents/inc-branch-label/pr-status")
        assert refused.status_code == 404
        assert "pr-status" not in refused.json()["detail"]


def test_pr_status_reports_last_known_when_codecommit_is_unreachable(monkeypatch):
    import dashboard.app as app_mod

    inc_id = "inc-pr-status-down"
    pr_url = "https://codecommit.example/pr/9"
    _pr_incident(inc_id, pr_url)

    class Down:
        def get_pull_request_status(self, pr_id):
            assert str(pr_id) == "9"
            raise RuntimeError("Could not connect to CodeCommit")

    monkeypatch.setattr(app_mod, "get_scm_client", lambda: Down())
    with TestClient(dashboard_app) as c:
        body = c.get(f"/api/incidents/{inc_id}/pr-status")
    assert body.status_code == 200, body.text
    payload = body.json()
    assert payload["status"] == "opened"
    assert payload["pr_url"] == pr_url
    assert payload["pull_request_status"] is None
    assert payload["is_merged"] is None
    assert payload["error"] == "CodeCommit could not be reached."
    assert "pr-status" not in payload["error"]
    assert "no pull request" not in payload["error"]

    monkeypatch.setattr(app_mod, "get_scm_client", lambda: object())
    with TestClient(dashboard_app) as c:
        missing = c.get(f"/api/incidents/{inc_id}/pr-status")
    assert missing.status_code == 200
    assert missing.json()["status"] == "opened"
    assert missing.json()["pr_url"] == pr_url
    assert missing.json()["error"] == "CodeCommit could not be reached."
    assert "/incidents/" not in missing.json()["error"]


def test_pr_status_reads_the_repo_in_the_codecommit_url(monkeypatch):
    import dashboard.app as app_mod

    inc_id = "inc-pr-status-url"
    pr_url = (
        "https://us-east-1.console.aws.amazon.com/codesuite/codecommit/repositories/"
        "opspilot-sample-service/pull-requests/15/details?region=us-east-1"
    )
    _pr_incident(inc_id, pr_url, pr_number=15)
    created = {}

    class FakeClient:
        def __init__(self, repo, client=None, region=None):
            created["repo"] = repo
            created["region"] = region

        def get_pull_request_status(self, pr_id):
            created["pr_id"] = str(pr_id)
            return {"pr_number": 15, "status": "merged", "pull_request_status": "CLOSED", "is_merged": True}

    def refuse_default_client():
        raise AssertionError("console URL should use CodeCommitClient")

    monkeypatch.setattr("opspilot.fix.codecommit.CodeCommitClient", FakeClient)
    monkeypatch.setattr(app_mod, "get_scm_client", refuse_default_client)
    with TestClient(dashboard_app) as c:
        body = c.get(f"/api/incidents/{inc_id}/pr-status")
    assert body.status_code == 200, body.text
    assert body.json()["status"] == "merged"
    assert body.json()["error"] is None
    assert body.json()["is_merged"] is True
    assert created == {"repo": "opspilot-sample-service", "region": "us-east-1", "pr_id": "15"}


def test_second_raise_after_pr_opened_is_refused(monkeypatch):
    """A pull request that is already recorded cannot be opened again."""
    import dashboard.app as app_mod
    from opspilot.contracts import PrRef

    calls = {"n": 0}

    def fake_propose(rca, ticket, **kwargs):
        calls["n"] += 1
        return PrRef(
            branch=f"opspilot/{ticket.key}",
            base="main",
            repro_test_path="sample_service/tests/test_get_order_repro.py",
            pr_url="https://codecommit.example/pr/11",
            pr_number=11,
        )

    monkeypatch.setattr(app_mod, "propose_fix", fake_propose)
    with TestClient(dashboard_app) as c:
        inc_id = _seed_incident("inc-choice-once")
        inc = c.get(f"/api/incidents/{inc_id}").json()
        applied = c.post(f"/api/incidents/{inc['incident_id']}/fix-choice", json={"action": "apply_myself"})
        assert applied.status_code == 200
        raised = c.post(f"/api/incidents/{inc['incident_id']}/fix-choice", json={"action": "raise_pr"})
        assert raised.status_code == 200, raised.text
        assert raised.json()["status"] == "PR_OPENED"
        again = c.post(f"/api/incidents/{inc['incident_id']}/fix-choice", json={"action": "raise_pr"})
        assert again.status_code == 409
    assert calls["n"] == 1


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


def test_trigger_leaves_the_agent_to_the_pipeline():
    """The dashboard records the probe. RunRCA, started by EventBridge, owns the agent trace."""
    from dashboard.app import AGENT_RUNS

    before = set(AGENT_RUNS)
    with TestClient(dashboard_app) as c:
        data = c.post("/api/trigger", json={"scenario": "unknown_coupon"}).json()
        assert data["probe"] == "GET /checkout?sku=SKU-1&qty=2&coupon=SPRING50"
        assert data["alarm_name"] == "OpsPilotSampleService-CheckoutErrors"
        assert data["incident"] is None
        assert set(AGENT_RUNS) == before


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
