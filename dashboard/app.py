"""Lightweight SRE Dashboard for OpsPilot built with FastAPI.

Provides real-time visualization of:
- Ingested incidents and deduplication status
- Bedrock RCA confidence scores and grounded evidence
- Suspected code locations and patch unified diffs
- AWS OpsCenter OpsItem links and CodeCommit PRs
- Live trigger simulation and M6 evaluation benchmark results
"""

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import glob
import hashlib
import json
import logging
import os
import time
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from pydantic import BaseModel

from opspilot.contracts import ContextBundle, RcaResult, TicketRef
from opspilot.fix.agent import propose_fix, suggested_diff
from opspilot.fix.guardrails import PatchRejectedException
from opspilot.ingest import handle_alarm_event
from opspilot.rca.agent import run_rca_agent
from opspilot.agentcore.runtime import AgentCoreRuntime
from dashboard.runs import build_agent_run, summarize as summarize_run
from opspilot.route import route_rca
from opspilot.ticketing import list_opscenter_tickets
from sample_service.app import app as sample_app
from dashboard.scenarios import (
    DEFAULT_SCENARIO,
    SCENARIOS,
    expected_status,
    list_scenarios,
    simulation_alarm_name,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "index.html"
FRONTEND_DIST_PATH = REPO_ROOT / "frontend" / "dist"

# Fix pull requests land in the storefront repo CodePipeline deploys, not the platform repo.
STOREFRONT_REPO = "opspilot-sample-service"
CLOSED_FIX_CHOICES = {"APPLY_MYSELF", "PR_OPENED", "VERIFIED"}

# Local in-memory incident cache for demo & offline mode
LOCAL_INCIDENTS_CACHE: List[Dict[str, Any]] = []
# Choices made in this dashboard process, merged onto both cache and DynamoDB rows.
FIX_CHOICES: Dict[str, Dict[str, Any]] = {}
# Agent runs captured while the dashboard ran the RCA agent, keyed by run (session) id.
AGENT_RUNS: Dict[str, Dict[str, Any]] = {}


def _run_rca_with_trace(bundle: ContextBundle):
    """Run the RCA agent and keep its AgentCore session so the dashboard can show the trace.

    Uses the same Strands/AgentCore path as run_rca_agent; with OPSPILOT_AGENT_BACKEND=converse
    (or if the runtime cannot start) it falls back to run_rca_agent and records no trace.
    """
    if os.environ.get("OPSPILOT_AGENT_BACKEND", "").lower() == "converse":
        return run_rca_agent(bundle), None
    try:
        rca, session = AgentCoreRuntime().execute_rca(bundle)
        return rca, session.to_dict()
    except Exception as e:
        logger.warning("AgentCore run failed for %s, falling back without a trace: %s", bundle.incident_id, e)
        return run_rca_agent(bundle), None
# Cap the demo cache so repeated simulations cannot grow memory without bound
LOCAL_INCIDENTS_CACHE_MAX = 200


def _rca_for_offer(inc: Dict[str, Any]) -> Optional[RcaResult]:
    """Build an RCA from a dashboard row so the fix agent can accept or refuse it."""
    if not inc.get("classification"):
        return None
    try:
        return RcaResult.model_validate(
            {
                "incident_id": inc.get("incident_id") or "unknown",
                "classification": inc.get("classification"),
                "severity": inc.get("severity") or "sev3",
                "confidence": inc.get("confidence") if inc.get("confidence") is not None else 0,
                "summary": (inc.get("summary") or "Suggested fix")[:600],
                "suspected_location": inc.get("suspected_location"),
                "evidence": inc.get("evidence") or [],
                "suggested_fix_strategy": inc.get("suggested_fix_strategy") or "Apply the suggested diff.",
            }
        )
    except Exception:
        return None


def apply_fix_offer(item: Dict[str, Any]) -> None:
    """Show the generator's diff when one exists. Raise PR only in that case.

    An authored diff with no generator stays visible so the operator can apply it
    themselves. The Raise PR button is not offered for that row.
    """
    rca = _rca_for_offer(item)
    generated = suggested_diff(rca) if rca is not None else None
    if generated and (item.get("patch_diff") or item.get("status") == "AWAITING_CHOICE"):
        item["patch_diff"] = generated
    choice_closed = bool(item.get("pr_url")) or item.get("status") in CLOSED_FIX_CHOICES
    item["can_raise_pr"] = bool(generated) and bool(item.get("patch_diff")) and not choice_closed


@contextmanager
def _storefront_repo_env():
    """Point propose_fix at the storefront repo for this call, then restore the process env."""
    key = "CODECOMMIT_REPO"
    previous = os.environ.get(key)
    os.environ[key] = os.environ.get("APP_CODECOMMIT_REPO", STOREFRONT_REPO)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


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
            rca_mock, session = _run_rca_with_trace(ContextBundle.model_validate(bundle))
            route = route_rca(rca_mock)
            run_id = None
            if session:
                run = build_agent_run(session, route=route, classification=rca_mock.classification,
                                      confidence=rca_mock.confidence)
                run["incident_id"] = inc_id
                run_id = run["run_id"]
                AGENT_RUNS[run_id] = run

            awaiting = route == "propose_fix"
            ticket_key = f"OPS-{stable_ticket_number(inc_id)}"

            sample_patch = suggested_diff(rca_mock) if awaiting else None

            LOCAL_INCIDENTS_CACHE.append({
                "incident_id": inc_id,
                "service": bundle.get("service", "sample-service"),
                "alarm_name": "OpsPilotSampleServiceErrors",
                "detected_at": bundle.get("detected_at", datetime.now(timezone.utc).isoformat()),
                "status": "AWAITING_CHOICE" if awaiting else "NOTIFIED",
                "classification": rca_mock.classification,
                "confidence": rca_mock.confidence,
                "severity": rca_mock.severity,
                "summary": rca_mock.summary,
                "suspected_location": rca_mock.suspected_location.model_dump() if rca_mock.suspected_location else None,
                "evidence": [e.model_dump() for e in rca_mock.evidence],
                "ticket_key": ticket_key,
                # Fixture replays never created a real ticket or PR, so no links are emitted.
                "ticket_url": None,
                "pr_branch": None,
                "pr_url": None,
                "patch_diff": sample_patch,
                "can_raise_pr": bool(sample_patch),
                "suggested_fix_strategy": rca_mock.suggested_fix_strategy,
                "source": "fixture",
                "agent_run_id": run_id,
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
@dashboard_app.get("/tickets", response_class=HTMLResponse)
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
                    "patch_diff": raw.get("patch_diff", {}).get("S"),
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

    for item in items:
        chosen = FIX_CHOICES.get(item.get("incident_id") or "")
        if chosen:
            item.update(chosen)
        apply_fix_offer(item)
    return sorted(items, key=lambda x: str(x.get("detected_at", "")), reverse=True)


@dashboard_app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str) -> Dict[str, Any]:
    """Retrieve full incident details by ID."""
    incidents = list_incidents()
    for inc in incidents:
        if inc.get("incident_id") == incident_id:
            return inc
    raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")


_TICKET_VIEWS = {"open", "in_progress", "resolved", "all"}
_OPEN_TICKET_STATUSES = {"Open", "InProgress"}


def _recorded_tickets() -> List[Dict[str, Any]]:
    """Ticket labels already stored on dashboard incidents. These are not OpsCenter rows."""
    rows = []
    for inc in list_incidents():
        key = inc.get("ticket_key")
        if not key:
            continue
        rows.append(
            {
                "key": key,
                "title": inc.get("summary") or inc.get("incident_id"),
                "status": inc.get("status") or "RECORDED",
                "severity": inc.get("severity"),
                "priority": None,
                "created_at": inc.get("detected_at"),
                "updated_at": None,
                "incident_id": inc.get("incident_id"),
                "url": inc.get("ticket_url"),
                "source": "dashboard",
                "classification": inc.get("classification"),
                "category": None,
            }
        )
    return rows


@dashboard_app.get("/api/tickets")
def get_tickets(view: str = "open") -> Dict[str, Any]:
    """Open OpsCenter OpsItems, plus ticket labels recorded only on incidents."""
    if view not in _TICKET_VIEWS:
        raise HTTPException(status_code=400, detail=f"view must be one of {sorted(_TICKET_VIEWS)}")
    opscenter_error = None
    try:
        opscenter = list_opscenter_tickets()
    except Exception as e:  # noqa: BLE001 - the page still shows tickets recorded on incidents
        logger.info("OpsCenter ticket list unavailable: %s", e)
        opscenter = []
        opscenter_error = str(e)

    if view == "open":
        shown = [row for row in opscenter if row.get("status") in _OPEN_TICKET_STATUSES]
    elif view == "in_progress":
        shown = [row for row in opscenter if row.get("status") == "InProgress"]
    elif view == "resolved":
        shown = [row for row in opscenter if row.get("status") == "Resolved"]
    else:
        shown = opscenter

    filed = {row["key"] for row in opscenter}
    recorded = [row for row in _recorded_tickets() if row["key"] not in filed]
    counts = {
        "open": sum(1 for row in opscenter if row.get("status") in _OPEN_TICKET_STATUSES),
        "in_progress": sum(1 for row in opscenter if row.get("status") == "InProgress"),
        "resolved": sum(1 for row in opscenter if row.get("status") == "Resolved"),
        "all": len(opscenter),
    }
    return {
        "view": view,
        "opscenter_error": opscenter_error,
        "counts": counts,
        "tickets": shown,
        "recorded": recorded,
    }


class FixChoiceBody(BaseModel):
    action: Literal["apply_myself", "raise_pr"]


def _record_choice(incident_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Remember a human fix choice for this dashboard session and, when live, the incident row."""
    FIX_CHOICES[incident_id] = {**FIX_CHOICES.get(incident_id, {}), **fields}
    for cached in LOCAL_INCIDENTS_CACHE:
        if cached.get("incident_id") == incident_id:
            cached.update(fields)
    stored = {
        key: str(value)
        for key, value in fields.items()
        if key in {"status", "pr_branch", "pr_url", "patch_diff"} and value
    }
    if stored:
        try:
            from opspilot.audit import update_incident

            update_incident(incident_id, stored)
        except Exception as e:  # noqa: BLE001
            logger.info("Fix choice for %s stayed in the dashboard session: %s", incident_id, e)
    return get_incident(incident_id)


@dashboard_app.post("/api/incidents/{incident_id}/fix-choice")
def choose_fix(incident_id: str, body: FixChoiceBody) -> Dict[str, Any]:
    """Record "I'll apply this myself" or open the CodeCommit pull request for the suggested diff."""
    inc = get_incident(incident_id)
    if inc.get("pr_url") or inc.get("status") in {"APPLY_MYSELF", "PR_OPENED", "VERIFIED"}:
        raise HTTPException(status_code=409, detail="A choice was already recorded for this incident.")
    if not inc.get("patch_diff"):
        raise HTTPException(status_code=400, detail="This incident has no suggested change.")
    if body.action == "apply_myself":
        return _record_choice(incident_id, {"status": "APPLY_MYSELF"})
    if not inc.get("can_raise_pr"):
        raise HTTPException(
            status_code=400,
            detail="This change has no pull-request generator. Apply it yourself.",
        )

    try:
        rca = RcaResult.model_validate(
            {
                "incident_id": incident_id,
                "classification": inc.get("classification"),
                "severity": inc.get("severity") or "sev3",
                "confidence": inc.get("confidence") if inc.get("confidence") is not None else 0,
                "summary": (inc.get("summary") or "Suggested fix")[:600],
                "suspected_location": inc.get("suspected_location"),
                "evidence": inc.get("evidence") or [],
                "suggested_fix_strategy": inc.get("suggested_fix_strategy") or "Apply the suggested diff.",
            }
        )
        ticket = TicketRef(
            key=inc.get("ticket_key") or f"OPS-{incident_id[-8:]}",
            url=inc.get("ticket_url") or "",
            incident_id=incident_id,
        )
        with _storefront_repo_env():
            pr = propose_fix(rca, ticket)
    except PatchRejectedException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.warning("Raise PR failed for %s: %s", incident_id, e)
        raise HTTPException(status_code=502, detail=f"Could not open the pull request: {e}") from e
    return _record_choice(
        incident_id,
        {
            "status": "PR_OPENED",
            "pr_branch": pr.branch,
            "pr_url": pr.pr_url,
            "patch_diff": inc.get("patch_diff"),
        },
    )


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
    alarm_name = simulation_alarm_name(scenario_id)
    alarm_event = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "time": now,
        "detail": {
            "alarmName": alarm_name,
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
    awaiting = outcome == "AWAITING_CHOICE" and not duplicate
    ticket_key = f"OPS-{stable_ticket_number(inc_id)}"

    new_inc = {
        "incident_id": inc_id,
        "service": "sample-service",
        "alarm_name": alarm_name,
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
        "pr_branch": None,
        "pr_url": None,
        "patch_diff": sc.get("patch_diff") if awaiting else None,
        "can_raise_pr": False,
        "suggested_fix_strategy": sc.get("suggested_fix_strategy"),
        "source": "simulated",
        "scenario": scenario_id,
    }
    apply_fix_offer(new_inc)
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


@dashboard_app.get("/api/runs")
def list_agent_runs() -> List[Dict[str, Any]]:
    """Agent runs recorded by this dashboard process, newest first (no span payloads)."""
    runs = sorted(AGENT_RUNS.values(), key=lambda r: r.get("started_at") or "", reverse=True)
    return [summarize_run(r) for r in runs]


@dashboard_app.get("/api/runs/{run_id}")
def get_agent_run(run_id: str) -> Dict[str, Any]:
    run = AGENT_RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


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
