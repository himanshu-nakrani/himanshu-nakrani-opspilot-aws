"""Lightweight SRE Dashboard for OpsPilot built with FastAPI.

Provides real-time visualization of:
- Ingested incidents and deduplication status
- Bedrock RCA confidence scores and grounded evidence
- Suspected code locations and patch unified diffs
- Jira issue links and GitHub PRs
- Live trigger simulation and M6 evaluation benchmark results
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import glob
import hashlib
import json
import logging
import os
import time
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, List, Optional
import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from pydantic import BaseModel

from opspilot.contracts import ContextBundle, RcaResult
from opspilot.ingest import handle_alarm_event
from opspilot.rca.agent import run_rca_agent
from opspilot.route import route_rca
from sample_service.app import app as sample_app
from dashboard.scenarios import DEFAULT_SCENARIO, SCENARIOS, expected_status, list_scenarios

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "index.html"
FRONTEND_DIST_PATH = REPO_ROOT / "frontend" / "dist"

# Local in-memory incident cache for demo & offline mode
LOCAL_INCIDENTS_CACHE: List[Dict[str, Any]] = []
# Cap the demo cache so repeated simulations cannot grow memory without bound
LOCAL_INCIDENTS_CACHE_MAX = 200


def stable_ticket_number(seed: str, modulo: int = 900, offset: int = 100) -> int:
    """Deterministic ticket number (Python's hash() is randomised per process)."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo + offset


def seed_cache_from_fixtures():
    """Seed dashboard with recorded fixtures if cache is empty."""
    if LOCAL_INCIDENTS_CACHE:
        return
    fixtures_dir = REPO_ROOT / "evals" / "fixtures"
    fixture_files = sorted(glob.glob(str(fixtures_dir / "*.json")))

    for path in fixture_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            bundle = data.get("context_bundle", {})
            gold = data.get("gold", {})
            inc_id = bundle.get("incident_id", Path(path).stem)

            # Build mock incident record from fixture
            rca_mock = run_rca_agent(ContextBundle.model_validate(bundle))
            route = route_rca(rca_mock)

            has_pr = route == "propose_fix"
            ticket_key = f"OPS-{stable_ticket_number(inc_id)}"
            pr_branch = f"opspilot/{ticket_key}" if has_pr else None

            sample_patch = """--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -28,3 +29,5 @@
 def get_order(order_id: str):
     order: Optional[Order] = ORDERS.get(order_id)
+    if order is None:
+        raise HTTPException(status_code=404, detail="Order not found")
""" if has_pr else None

            LOCAL_INCIDENTS_CACHE.append({
                "incident_id": inc_id,
                "service": bundle.get("service", "sample-service"),
                "alarm_name": "OpsPilotSampleServiceErrors",
                "detected_at": bundle.get("detected_at", datetime.now(timezone.utc).isoformat()),
                "status": "VERIFIED" if has_pr else "NOTIFIED",
                "classification": rca_mock.classification,
                "confidence": rca_mock.confidence,
                "severity": rca_mock.severity,
                "summary": rca_mock.summary,
                "suspected_location": rca_mock.suspected_location.model_dump() if rca_mock.suspected_location else None,
                "evidence": [e.model_dump() for e in rca_mock.evidence],
                "ticket_key": ticket_key,
                # Fixture replays never created a real ticket or PR, so no links are emitted.
                "ticket_url": None,
                "pr_branch": pr_branch,
                "pr_url": None,
                "patch_diff": sample_patch,
                "suggested_fix_strategy": rca_mock.suggested_fix_strategy,
                "source": "fixture",
            })
        except Exception as e:
            logger.warning("Could not load fixture %s into dashboard cache: %s", path, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_cache_from_fixtures()
    yield


dashboard_app = FastAPI(title="OpsPilot SRE Dashboard", lifespan=lifespan)

# The SPA is served same-origin (and the Vite dev server proxies /api), so CORS is only
# needed for explicitly configured origins. Never combine a wildcard with credentials.
_cors_origins = [
    o.strip()
    for o in os.environ.get("DASHBOARD_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]
dashboard_app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# check_dir=False so assets built after the server starts are still served.
dashboard_app.mount(
    "/assets",
    StaticFiles(directory=str(FRONTEND_DIST_PATH / "assets"), check_dir=False),
    name="assets",
)


@dashboard_app.get("/", response_class=HTMLResponse)
def get_dashboard_html():
    """Serve the SRE dashboard single page interface (React SPA with template fallback)."""
    dist_index = FRONTEND_DIST_PATH / "index.html"
    if dist_index.exists():
        with open(dist_index, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    if TEMPLATE_PATH.exists():
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>OpsPilot Dashboard Template Not Found</h1>", status_code=404)


@dashboard_app.get("/api/incidents")
def list_incidents() -> List[Dict[str, Any]]:
    """List all incidents from DynamoDB or in-memory fallback cache."""
    table_name = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    items = []

    # Attempt to read from DynamoDB if AWS credentials are active
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_ACCESS_KEY_ID") != "testing":
        try:
            dynamodb = boto3.client("dynamodb")
            resp = dynamodb.scan(TableName=table_name, Limit=50)
            for raw in resp.get("Items", []):
                item = {
                    "incident_id": raw.get("incident_id", {}).get("S"),
                    "service": raw.get("service", {}).get("S", "sample-service"),
                    "detected_at": raw.get("detected_at", {}).get("S"),
                    "status": raw.get("status", {}).get("S", "RECORDED"),
                    # Missing values stay null so the UI shows "unknown" instead of a
                    # fabricated confident code_defect.
                    "classification": raw.get("classification", {}).get("S"),
                    "confidence": float(raw["confidence"]["N"]) if "N" in raw.get("confidence", {}) else None,
                    "source": "dynamodb",
                    "ticket_key": raw.get("ticket_key", {}).get("S"),
                    "ticket_url": raw.get("ticket_url", {}).get("S"),
                    "pr_branch": raw.get("pr_branch", {}).get("S"),
                    "pr_url": raw.get("pr_url", {}).get("S"),
                }
                if "rca_result" in raw:
                    try:
                        rca_dict = json.loads(raw["rca_result"]["S"])
                        item.update(rca_dict)
                    except Exception:
                        pass
                items.append(item)
        except Exception as e:
            logger.info("DynamoDB scan bypassed (%s); using in-memory cache.", e)

    seed_cache_from_fixtures()
    # Merge items with fallback cache
    seen_ids = {i["incident_id"] for i in items}
    for local in LOCAL_INCIDENTS_CACHE:
        if local["incident_id"] not in seen_ids:
            items.append(local)

    return sorted(items, key=lambda x: str(x.get("detected_at", "")), reverse=True)


@dashboard_app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str) -> Dict[str, Any]:
    """Retrieve full incident details by ID."""
    incidents = list_incidents()
    for inc in incidents:
        if inc.get("incident_id") == incident_id:
            return inc
    raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")


AGENTCORE_POLICIES = ["blast_radius_files", "blast_radius_lines", "protected_paths", "evidence_grounding", "abstention_policy"]
AGENTCORE_GATEWAY_TOOLS = ["query_logs", "get_file", "get_commit_diff", "submit_rca"]


def _installed_version(dist_name: str) -> Optional[str]:
    try:
        return importlib_metadata.version(dist_name)
    except importlib_metadata.PackageNotFoundError:
        return None


@dashboard_app.get("/api/stats")
def get_stats() -> Dict[str, Any]:
    """Aggregate KPI statistics for OpsPilot pipeline.

    Values that are not measured are returned as null, never as a fixed success figure.
    """
    incidents = list_incidents()
    total = len(incidents)

    confidences = [float(i["confidence"]) for i in incidents if i.get("confidence") is not None]
    with_pr = [i for i in incidents if i.get("pr_branch") or i.get("pr_url")]
    verified = [i for i in with_pr if i.get("status") == "VERIFIED"]

    return {
        "total_incidents": total,
        "mean_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "total_prs_opened": len(with_pr),
        "verified_prs": len(verified),
        # Share of fix PRs whose incident reached VERIFIED; null when there are no PRs.
        "verification_pass_rate": round(len(verified) / len(with_pr), 3) if with_pr else None,
        "agent_framework": "AWS Strands Agents SDK + Amazon Bedrock AgentCore Runtime",
        "strands_sdk_version": _installed_version("strands-agents"),
        "agentcore_policies_active": AGENTCORE_POLICIES,
        "agentcore_gateway_tools": AGENTCORE_GATEWAY_TOOLS,
    }


class TriggerRequest(BaseModel):
    scenario: Optional[str] = None


@dashboard_app.get("/api/scenarios")
def get_scenarios() -> List[Dict[str, Any]]:
    """Catalogue of incident scenarios the dashboard can simulate."""
    return list_scenarios()


@dashboard_app.post("/api/trigger")
def trigger_incident_simulation(body: Optional[TriggerRequest] = None) -> Dict[str, Any]:
    """Simulate an incident from the scenario catalogue (default: the planted null-order bug).

    This is a demo path. The RCA fields are a canned example, and the response is flagged
    ``simulated`` so the UI can label it; no real ticket or PR is created. Only scenarios
    with a ``probe_path`` send real traffic to sample_service.
    """
    scenario_id = (body.scenario if body and body.scenario else DEFAULT_SCENARIO)
    sc = SCENARIOS.get(scenario_id)
    if sc is None:
        raise HTTPException(status_code=400, detail=f"Unknown scenario '{scenario_id}'")

    failed_calls = 0
    probe_path = sc.get("probe_path")
    if probe_path:
        client = TestClient(sample_app, raise_server_exceptions=False)
        for _ in range(5):
            if client.get(probe_path).status_code >= 500:
                failed_calls += 1

    now = datetime.now(timezone.utc).isoformat()
    alarm_event = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "time": now,
        "detail": {
            "alarmName": sc["alarm_name"],
            "state": {
                "value": "ALARM",
                "timestamp": now,
                "reason": "Threshold Crossed: " + sc["alarm_reason"].format(failed=failed_calls),
            },
        },
    }

    ingest_mode = "live"
    try:
        res = handle_alarm_event(alarm_event)
        inc_id = res.get("incident_id") or f"inc-{int(time.time())}"
    except Exception as e:
        logger.info("Local mode: handle_alarm_event simulated without AWS credentials: %s", e)
        ingest_mode = "offline"
        res = {"status": "started"}
        inc_id = f"inc-sim-{int(time.time() * 1000)}"

    ingest_status = res.get("status", "unknown")
    duplicate = ingest_status != "started"
    outcome = expected_status(sc)
    proposes_fix = outcome == "PROPOSED" and not duplicate
    ticket_key = f"OPS-{stable_ticket_number(inc_id)}"

    new_inc = {
        "incident_id": inc_id,
        "service": "sample-service",
        "alarm_name": sc["alarm_name"],
        "detected_at": now,
        "status": "DUPLICATE_SKIPPED" if duplicate else outcome,
        "classification": sc["classification"],
        "confidence": sc["confidence"],
        "severity": sc["severity"],
        "summary": sc["summary"],
        "suspected_location": sc.get("suspected_location"),
        "evidence": sc["evidence"],
        "ticket_key": None if duplicate else ticket_key,
        "ticket_url": None,
        "pr_branch": f"opspilot/{ticket_key}" if proposes_fix else None,
        "pr_url": None,
        "patch_diff": sc.get("patch_diff") if proposes_fix else None,
        "suggested_fix_strategy": sc.get("suggested_fix_strategy"),
        "source": "simulated",
        "scenario": scenario_id,
    }
    LOCAL_INCIDENTS_CACHE.insert(0, new_inc)
    del LOCAL_INCIDENTS_CACHE[LOCAL_INCIDENTS_CACHE_MAX:]

    if probe_path:
        message = f"{failed_calls} calls to {probe_path} returned 5xx. Ingested incident {inc_id} ({ingest_mode} mode)."
    else:
        message = f"Synthetic alarm '{sc['label']}'. Ingested incident {inc_id} ({ingest_mode} mode)."

    return {
        "status": "success",
        "simulated": True,
        "scenario": scenario_id,
        "live_probe": bool(probe_path),
        "ingest_mode": ingest_mode,
        "ingest_status": ingest_status,
        "failed_calls": failed_calls,
        "incident_id": inc_id,
        "summary": new_inc["summary"],
        "message": message,
        "incident": new_inc,
    }


# Same thresholds as evals/run_evals.py
EVAL_TARGETS = {
    "classification_accuracy": 90.0,
    "location_hit_rate": 90.0,
    "abstention_precision": 100.0,
    "evidence_ref_validity_rate": 95.0,
}


@dashboard_app.get("/api/evals")
def run_evals_api() -> Dict[str, Any]:
    """Execute M6 benchmark eval harness and return structured metrics.

    Field names match ``EvalsReport`` / ``FixtureEvalDetail`` in frontend/src/types.ts.
    """
    from evals.run_evals import estimate_tokens, verify_evidence_refs

    fixtures_dir = REPO_ROOT / "evals" / "fixtures"
    fixture_files = sorted(glob.glob(str(fixtures_dir / "*.json")))

    total = len(fixture_files)
    correct_cls = 0
    correct_routes = 0
    loc_hits = 0
    loc_total = 0
    abstain_hits = 0
    abstain_total = 0
    evidence_validity_sum = 0.0
    latencies: List[float] = []
    token_counts: List[int] = []
    details = []

    for path in fixture_files:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        f_id = data.get("id", Path(path).stem)
        gold = data["gold"]
        bundle = ContextBundle.model_validate(data["context_bundle"])

        t0 = time.perf_counter()
        rca = run_rca_agent(bundle)
        route = route_rca(rca)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        tokens = estimate_tokens(bundle, rca)
        latencies.append(latency_ms)
        token_counts.append(tokens)

        cls_ok = rca.classification == gold["classification"]
        correct_cls += int(cls_ok)
        route_ok = route == gold["route"]
        correct_routes += int(route_ok)

        loc_ok: Optional[bool] = None
        if "location" in gold:
            loc_total += 1
            g_loc = gold["location"]
            loc_ok = bool(
                rca.suspected_location
                and rca.suspected_location.file == g_loc["file"]
                and abs(rca.suspected_location.line - g_loc.get("line", rca.suspected_location.line)) <= 2
            )
            loc_hits += int(loc_ok)

        abstain_ok: Optional[bool] = None
        if gold.get("should_abstain"):
            abstain_total += 1
            abstain_ok = rca.classification == "insufficient_evidence" and route == "notify"
            abstain_hits += int(abstain_ok)

        evidence_validity_sum += verify_evidence_refs(bundle, rca)

        details.append({
            "id": f_id,
            "name": data.get("name", f_id),
            "gold_classification": gold["classification"],
            "predicted_classification": rca.classification,
            "gold_route": gold["route"],
            "predicted_route": route,
            "confidence": round(float(rca.confidence), 3),
            "tokens": tokens,
            "latency_ms": round(latency_ms, 2),
            "location_hit": loc_ok,
            "abstention_correct": abstain_ok,
            "passed": cls_ok and route_ok and loc_ok is not False and abstain_ok is not False,
        })

    metrics = {
        "classification_accuracy": (correct_cls / total) * 100.0 if total else 0.0,
        "route_accuracy": (correct_routes / total) * 100.0 if total else 0.0,
        "location_hit_rate": (loc_hits / loc_total) * 100.0 if loc_total else 100.0,
        "abstention_precision": (abstain_hits / abstain_total) * 100.0 if abstain_total else 100.0,
        "evidence_ref_validity_rate": (evidence_validity_sum / total) * 100.0 if total else 0.0,
    }
    all_targets_passed = total > 0 and all(metrics[k] >= v for k, v in EVAL_TARGETS.items())

    return {
        "total_fixtures": total,
        "passed_fixtures": sum(1 for d in details if d["passed"]),
        "classification_correct": correct_cls,
        "route_correct": correct_routes,
        "location_hits": loc_hits,
        "location_total": loc_total,
        "abstention_hits": abstain_hits,
        "abstention_total": abstain_total,
        **metrics,
        "mean_tokens": sum(token_counts) / len(token_counts) if token_counts else 0.0,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "targets": EVAL_TARGETS,
        "all_targets_passed": all_targets_passed,
        "details": details,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    print(f"🚀 Starting OpsPilot SRE Dashboard at http://localhost:{port}")
    uvicorn.run("dashboard.app:dashboard_app", host="0.0.0.0", port=port, reload=True)
