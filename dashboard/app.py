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
import re
import time
import urllib.error
import urllib.request
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dashboard.endings import human_ending_text
from opspilot.contracts import ContextBundle, RcaResult, TicketRef
from opspilot.deploy.pipeline import deploy_not_started, public_deploy, refresh_deploy
from opspilot.fix.agent import propose_fix, suggested_diff
from opspilot.fix.codecommit import parse_pr_console_url
from opspilot.fix.guardrails import PatchRejectedException
from opspilot.fix.scm import get_scm_client
from opspilot.knowledge.document import public_knowledge
from opspilot.knowledge.ingest import sync_merged_solution
from opspilot.verify.pr_check import BUILD_NOT_STARTED, begin_pr_verification, public_test, refresh_verification
from opspilot.rca.agent import analyze_heuristically, run_rca_agent
from opspilot.agentcore.runtime import AgentCoreOfflineModel, AgentCoreRuntime
from dashboard.runs import build_agent_run, summarize as summarize_run
from opspilot.route import route_rca
from opspilot.ticketing import list_opscenter_tickets
from dashboard.scenarios import (
    DEFAULT_SCENARIO,
    SCENARIOS,
    list_scenarios,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "index.html"
FRONTEND_DIST_PATH = REPO_ROOT / "frontend" / "dist"

# Fix pull requests land in the storefront repo CodePipeline deploys, not the platform repo.
STOREFRONT_REPO = "opspilot-sample-service"
_LEGACY_PR_ID_RE = re.compile(r"/pr/(\d+)(?:/|$)")
_HTTP_PR_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)
_INCIDENT_FIELDS = {
    "status",
    "pr_branch",
    "pr_url",
    "pr_number",
    "patch_diff",
    "test_status",
    "test_name",
    "test_summary",
    "test_log",
    "test_build_id",
    "test_error",
    "test_comment_posted",
    "deploy_status",
    "deploy_summary",
    "deploy_url",
    "deploy_error",
    "deploy_execution_id",
    "deploy_stage",
    "knowledge_status",
    "knowledge_error",
    "knowledge_s3_key",
    "knowledge_job_id",
}
_OPTIONAL_TEXT = (
    "test_status",
    "test_name",
    "test_summary",
    "test_log",
    "test_build_id",
    "test_error",
    "test_comment_posted",
    "deploy_status",
    "deploy_summary",
    "deploy_url",
    "deploy_error",
    "deploy_execution_id",
    "deploy_stage",
    "knowledge_status",
    "knowledge_error",
    "knowledge_s3_key",
    "knowledge_job_id",
    "human_ending",
)

# Local in-memory incident cache for demo & offline mode
LOCAL_INCIDENTS_CACHE: List[Dict[str, Any]] = []
# Choices made in this dashboard process, merged onto both cache and DynamoDB rows.
FIX_CHOICES: Dict[str, Dict[str, Any]] = {}
# Agent runs captured while the dashboard ran the RCA agent, keyed by run (session) id.
AGENT_RUNS: Dict[str, Dict[str, Any]] = {}


def _run_rca_with_trace(bundle: ContextBundle):
    """Replay one recorded fixture on the offline model and keep its trace.

    These rows are the built-in samples. Live incidents are already analyzed by
    RunRCA and read from DynamoDB. Credentials on this process are for that
    read, so startup must not call Bedrock once per fixture.
    """
    try:
        rca, session = AgentCoreRuntime().execute_rca(
            bundle,
            bedrock_client=AgentCoreOfflineModel(bundle=bundle),
        )
        return rca, session.to_dict()
    except Exception as e:
        logger.warning("Offline fixture replay failed for %s: %s", bundle.incident_id, e)
        return analyze_heuristically(bundle), None
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


def _http_pr_url(value: Any) -> Optional[str]:
    """A pull request link is an http(s) URL. A branch name is not a pull request."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not _HTTP_PR_URL.match(url):
        return None
    return url


def apply_fix_offer(item: Dict[str, Any]) -> None:
    """Show the generator's diff when one exists. Raise PR only in that case.

    A code defect whose stack frames name a patchable function gets that diff
    even when the stored status is only NOTIFIED. An authored diff with no
    generator stays visible so the operator can apply it themselves. Raise PR
    stays available after "I'll apply this myself" until a pull request link exists.
    """
    rca = _rca_for_offer(item)
    generated = suggested_diff(rca) if rca is not None else None
    if generated:
        item["patch_diff"] = generated
    pr_recorded = _http_pr_url(item.get("pr_url")) is not None or item.get("status") == "VERIFIED"
    item["can_raise_pr"] = bool(generated) and bool(item.get("patch_diff")) and not pr_recorded


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


def _dynamodb_credentials_available() -> bool:
    """True when this process can read the live incidents table.

    `aws login` and an EC2 instance role do not set AWS_ACCESS_KEY_ID. The testing
    key is the offline switch used by unit tests.
    """
    key = os.environ.get("AWS_ACCESS_KEY_ID", "")
    if key == "testing":
        return False
    if key:
        return True
    try:
        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


@dashboard_app.get("/api/incidents")
def list_incidents() -> List[Dict[str, Any]]:
    """List all incidents from DynamoDB or in-memory fallback cache."""
    table_name = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    items = []

    # Attempt to read from DynamoDB if AWS credentials are active
    if _dynamodb_credentials_available():
        try:
            dynamodb = boto3.client("dynamodb")
            resp = dynamodb.scan(TableName=table_name, Limit=50)
            for raw in resp.get("Items", []):
                item = {
                    "incident_id": raw.get("incident_id", {}).get("S"),
                    "alarm_name": raw.get("alarm_name", {}).get("S"),
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
                    "pr_number": _optional_pr_number(raw.get("pr_number", {}).get("S")),
                    "patch_diff": raw.get("patch_diff", {}).get("S"),
                    **{
                        key: (raw.get(key) or {}).get("S") or None
                        for key in _OPTIONAL_TEXT
                        if key != "human_ending"
                    },
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
        normalize_pull_request_fields(item)
        apply_fix_offer(item)
        for key in _OPTIONAL_TEXT:
            if item.get(key) == "":
                item[key] = None
        item["human_ending"] = human_ending_text(item)
        item["knowledge"] = public_knowledge(item)
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
        key: "" if value is None else str(value)
        for key, value in fields.items()
        if key in _INCIDENT_FIELDS
    }
    if stored:
        try:
            from opspilot.audit import update_incident

            update_incident(incident_id, stored)
        except Exception as e:  # noqa: BLE001
            logger.info("Fix choice for %s stayed in the dashboard session: %s", incident_id, e)
    return get_incident(incident_id)


def _optional_pr_number(value: Any) -> Optional[int]:
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def normalize_pull_request_fields(item: Dict[str, Any]) -> None:
    """Drop branch names and other non-links so a fixture cannot look like a pull request.

    ``pr_branch`` is kept only together with an http(s) ``pr_url``.
    """
    url = _http_pr_url(item.get("pr_url"))
    if not url:
        item["pr_url"] = None
        item["pr_number"] = None
        item["pr_branch"] = None
        for key in _OPTIONAL_TEXT:
            if key != "human_ending":
                item[key] = None
        return
    item["pr_url"] = url
    number = _optional_pr_number(item.get("pr_number"))
    if number is None:
        _repo, parsed, _region = parse_pr_console_url(url)
        if not parsed:
            match = _LEGACY_PR_ID_RE.search(url)
            parsed = match.group(1) if match else None
        number = _optional_pr_number(parsed)
    item["pr_number"] = number


def _pull_request_id(inc: Dict[str, Any]) -> Optional[str]:
    """Id to pass to CodeCommit. Console links win; otherwise the stored number or a /pr/<id> URL."""
    _repo, pr_from_url, _region = parse_pr_console_url(inc.get("pr_url") or "")
    if pr_from_url:
        return pr_from_url
    number = _optional_pr_number(inc.get("pr_number"))
    if number is not None:
        return str(number)
    match = _LEGACY_PR_ID_RE.search(inc.get("pr_url") or "")
    return match.group(1) if match else None


def read_pull_request_status(inc: Dict[str, Any]) -> Dict[str, Any]:
    """Live CodeCommit state for an incident that already has a pull request.

    When the read fails, ``status`` stays ``opened`` (the state recorded when the
    PR was created) and ``error`` explains why. No status is invented.
    """
    pr_url = inc.get("pr_url") or ""
    pr_id = _pull_request_id(inc)
    last_known = {
        "pr_url": pr_url,
        "pr_number": _optional_pr_number(pr_id),
        "status": "opened",
        "pull_request_status": None,
        "is_merged": None,
        "merge_commit": None,
        "error": None,
    }
    if not pr_id:
        last_known["error"] = "This pull request link has no id to check."
        return last_known
    repo, _pr_from_url, region = parse_pr_console_url(pr_url)
    try:
        if repo:
            from opspilot.fix.codecommit import CodeCommitClient

            client = CodeCommitClient(repo, region=region)
        else:
            with _storefront_repo_env():
                client = get_scm_client()
        reader = getattr(client, "get_pull_request_status", None)
        if reader is None:
            last_known["error"] = "CodeCommit could not be reached."
            return last_known
        live = reader(pr_id)
    except Exception as e:  # noqa: BLE001 - the screen still shows the link and the last known state
        logger.warning("PR status read failed for %s: %s", inc.get("incident_id"), e)
        last_known["error"] = "CodeCommit could not be reached."
        return last_known
    status = live.get("status") if isinstance(live, dict) else None
    if not status:
        last_known["error"] = "CodeCommit could not be reached."
        return last_known
    return {
        "pr_url": pr_url,
        "pr_number": _optional_pr_number(live.get("pr_number")) or last_known["pr_number"],
        "status": status,
        "pull_request_status": live.get("pull_request_status"),
        "is_merged": live.get("is_merged"),
        "merge_commit": live.get("merge_commit"),
        "error": None,
    }


def _aws_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def get_codebuild_client():
    """CodeBuild client for the verify project. Tests replace this."""
    return boto3.client("codebuild", region_name=_aws_region())


def get_pipeline_client():
    """CodePipeline client for the storefront pipeline. Tests replace this."""
    return boto3.client("codepipeline", region_name=_aws_region())


def get_knowledge_s3_client():
    """S3 client for the knowledge-base document bucket. Tests replace this."""
    return boto3.client("s3", region_name=_aws_region())


def get_knowledge_agent_client():
    """Bedrock Agent client that starts a knowledge-base ingestion job. Tests replace this."""
    return boto3.client("bedrock-agent", region_name=_aws_region())


def _scm_for_incident(inc: Dict[str, Any]):
    pr_url = inc.get("pr_url") or ""
    repo, _pr_from_url, region = parse_pr_console_url(pr_url)
    if repo:
        from opspilot.fix.codecommit import CodeCommitClient

        return CodeCommitClient(repo, region=region)
    with _storefront_repo_env():
        return get_scm_client()


def _commenter_for(inc: Dict[str, Any]):
    def comment(content: str) -> None:
        pr_id = _pull_request_id(inc)
        if not pr_id:
            raise RuntimeError("missing pull request id")
        client = _scm_for_incident(inc)
        poster = getattr(client, "post_pull_request_comment", None)
        if poster is None:
            raise RuntimeError("pull request client cannot comment")
        poster(pr_id, content)

    return comment


def _verification_client(inc: Dict[str, Any]):
    """CodeBuild client only while a build still needs to be read."""
    if not inc.get("test_build_id"):
        return None
    if inc.get("test_status") in {"passed", "failed"} and inc.get("test_comment_posted") == "yes":
        return None
    return get_codebuild_client()


def _pipeline_client_for(pr_status: Dict[str, Any]):
    merged = pr_status.get("is_merged") is True or pr_status.get("status") == "merged"
    if pr_status.get("error") or not merged or not pr_status.get("merge_commit"):
        return None
    return get_pipeline_client()


@dashboard_app.get("/api/incidents/{incident_id}/pr-status")
def incident_pr_status(incident_id: str) -> Dict[str, Any]:
    """Current CodeCommit state, the verify build, and the storefront deploy."""
    inc = get_incident(incident_id)
    if not inc.get("pr_url"):
        raise HTTPException(status_code=404, detail="This incident has no pull request.")
    body = read_pull_request_status(inc)
    updates: Dict[str, Any] = {}
    try:
        test_fields = refresh_verification(
            inc,
            codebuild_client=_verification_client(inc),
            commenter=_commenter_for(inc),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Verification refresh failed for %s: %s", incident_id, e)
        test_fields = {"test_error": "The verification build could not be read.", "test_status": inc.get("test_status")}
    if test_fields:
        updates.update(test_fields)
    try:
        deploy_fields = refresh_deploy(
            {**inc, **updates},
            body,
            pipeline_client=_pipeline_client_for(body),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Deploy refresh failed for %s: %s", incident_id, e)
        deploy_fields = {
            "deploy_status": inc.get("deploy_status"),
            "deploy_summary": inc.get("deploy_summary") or "",
            "deploy_url": inc.get("deploy_url"),
            "deploy_error": "The pipeline could not be read.",
            "deploy_execution_id": inc.get("deploy_execution_id") or "",
            "deploy_stage": inc.get("deploy_stage") or "",
        }
    updates.update(deploy_fields)
    if updates:
        _record_choice(incident_id, updates)
    merged = {**inc, **updates}
    knowledge = public_knowledge(merged)
    if body.get("is_merged") is True or body.get("status") == "merged":
        try:
            knowledge, knowledge_fields = sync_merged_solution(
                merged,
                body,
                s3_client=get_knowledge_s3_client(),
                agent_client=get_knowledge_agent_client(),
                bucket=os.environ.get("KNOWLEDGE_BUCKET", ""),
                knowledge_base_id=os.environ.get("KNOWLEDGE_BASE_ID", ""),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Knowledge ingest failed for %s: %s", incident_id, e)
            knowledge_fields = {}
            if knowledge is not None:
                knowledge = {**knowledge, "status": "failed", "error": "The knowledge base document could not be stored."}
        if knowledge_fields:
            updates.update(knowledge_fields)
            _record_choice(incident_id, knowledge_fields)
            merged = {**inc, **updates}
            if knowledge and knowledge.get("status") == "ingested":
                knowledge = public_knowledge(merged)
    body["test"] = public_test(merged)
    body["deploy"] = public_deploy(merged)
    body["knowledge"] = knowledge
    return body


@dashboard_app.post("/api/incidents/{incident_id}/fix-choice")
def choose_fix(incident_id: str, body: FixChoiceBody) -> Dict[str, Any]:
    """Record "I'll apply this myself" or open the CodeCommit pull request for the suggested diff.

    Raise PR stays available after apply-myself. Once a pull request exists, another
    one is refused.
    """
    inc = get_incident(incident_id)
    if _http_pr_url(inc.get("pr_url")) or inc.get("status") == "VERIFIED":
        raise HTTPException(status_code=409, detail="A pull request was already opened for this incident.")
    if not inc.get("patch_diff"):
        raise HTTPException(status_code=400, detail="This incident has no suggested change.")
    if body.action == "apply_myself":
        if inc.get("status") == "APPLY_MYSELF":
            raise HTTPException(status_code=409, detail="You already chose to apply this change yourself.")
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
            try:
                codebuild = get_codebuild_client()
            except Exception as e:  # noqa: BLE001
                logger.warning("Verification client was not created for %s: %s", incident_id, e)
                verification = {
                    "test_status": None,
                    "test_name": None,
                    "test_summary": "",
                    "test_log": "",
                    "test_build_id": "",
                    "test_error": BUILD_NOT_STARTED,
                    "test_comment_posted": "",
                }
            else:
                verification = begin_pr_verification(pr, rca, codebuild_client=codebuild)
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
            "pr_number": pr.pr_number,
            "patch_diff": inc.get("patch_diff"),
            **verification,
            **deploy_not_started(),
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


def sample_service_base_url() -> str:
    """Public URL of the deployed sample service."""
    configured = os.environ.get("SAMPLE_SERVICE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    cf = boto3.client("cloudformation", region_name=region)
    stacks = cf.describe_stacks(StackName="OpsPilotSampleServiceStack")["Stacks"]
    for output in stacks[0].get("Outputs", []):
        if output.get("OutputKey") == "SampleServiceUrl" and output.get("OutputValue"):
            return str(output["OutputValue"]).rstrip("/")
    raise HTTPException(
        status_code=503,
        detail="Sample service URL is not set. Set SAMPLE_SERVICE_URL or deploy OpsPilotSampleServiceStack.",
    )


def deliver_live_probe(probe: Dict[str, Any]) -> Dict[str, Any]:
    """Send one request to the deployed sample service so CloudWatch can raise its alarm."""
    path = str(probe["path"])
    if not path.startswith("/"):
        path = "/" + path
    url = sample_service_base_url() + path
    method = str(probe.get("method") or "GET").upper()
    data = None
    headers: Dict[str, str] = {}
    if "json" in probe:
        data = json.dumps(probe["json"]).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            response.read()
            return {"http_status": response.status, "error": None, "url": url}
    except urllib.error.HTTPError as exc:
        return {"http_status": exc.code, "error": None, "url": url}
    except Exception as exc:  # noqa: BLE001 - OOM and gateway timeouts still reached Lambda
        return {"http_status": None, "error": str(exc), "url": url}


@dashboard_app.post("/api/trigger")
def trigger_incident_simulation(body: Optional[TriggerRequest] = None) -> Dict[str, Any]:
    """Call the sample service so an error reaches CloudWatch and EventBridge starts the pipeline.

    The RCA agent runs inside that pipeline. This process does not analyze the logs and
    does not open an incident row of its own.
    """
    scenario_id = (body.scenario if body and body.scenario else DEFAULT_SCENARIO)
    sc = SCENARIOS.get(scenario_id)
    if sc is None:
        raise HTTPException(status_code=400, detail=f"Unknown scenario '{scenario_id}'")
    probe = sc.get("probe")
    if not probe:
        raise HTTPException(status_code=400, detail=f"Scenario '{scenario_id}' has no live probe")

    try:
        delivered = deliver_live_probe(probe)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live probe for %s failed before the request: %s", scenario_id, exc)
        raise HTTPException(status_code=503, detail=f"Could not reach the sample service: {exc}") from exc

    alarm_name = sc["alarm_name"]
    method = str(probe.get("method") or "GET").upper()
    call = f"{method} {probe['path']}"
    http_status = delivered.get("http_status")
    if delivered.get("error") and http_status is None:
        detail = f"The call did not return a normal HTTP response ({delivered['error']})."
        failed_calls = 1
    elif http_status == 404:
        detail = (
            f"The sample service returned HTTP 404. Deploy OpsPilotSampleServiceStack so {call} is live, "
            "then run this scenario again."
        )
        failed_calls = 0
    elif isinstance(http_status, int):
        detail = f"The sample service returned HTTP {http_status}."
        failed_calls = 1 if http_status >= 500 else 0
    else:
        detail = "The sample service accepted the call."
        failed_calls = 0
    message = (
        f"Called {call}. {detail} CloudWatch alarm {alarm_name} notifies EventBridge when it enters ALARM, "
        "and the pipeline runs the agent on those logs. A repeat of the same alarm inside 15 minutes is skipped "
        "until the alarm returns to OK."
    )
    return {
        "status": "accepted",
        "simulated": True,
        "scenario": scenario_id,
        "live_probe": True,
        "alarm_name": alarm_name,
        "probe": call,
        "http_status": http_status,
        "ingest_mode": "eventbridge",
        "ingest_status": "waiting_for_alarm",
        "failed_calls": failed_calls,
        "incident_id": "",
        "summary": "",
        "message": message,
        "incident": None,
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
