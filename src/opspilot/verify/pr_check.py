"""Start the existing verify CodeBuild project for a pull request branch and record the result.

The dashboard calls this after propose_fix. It does not open another pull request
and it does not merge.
"""

import logging
import os
from typing import Any, Callable, Dict, Optional

from opspilot.contracts import PrRef, RcaResult
from opspilot.fix.agent import repro_pytest_node
from opspilot.verify.runner import parse_build

logger = logging.getLogger(__name__)

VERIFY_PROJECT_NAME = os.environ.get("VERIFY_PROJECT_NAME", "opspilot-verify-fix")

BUILD_NOT_STARTED = "The verification build could not be started."
BUILD_NOT_READ = "The verification build could not be read."
COMMENT_NOT_POSTED = "The test result could not be posted on the pull request."
RUNNING_SUMMARY = "Verification test is running."

_RUNNING = {"IN_PROGRESS", "QUEUED"}
_STORED_KEYS = (
    "test_status",
    "test_name",
    "test_summary",
    "test_log",
    "test_build_id",
    "test_error",
    "test_comment_posted",
)


def _region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def codecommit_clone_url() -> str:
    explicit = os.environ.get("CODECOMMIT_CLONE_URL")
    if explicit:
        return explicit
    repo = os.environ.get("CODECOMMIT_REPO") or os.environ.get("APP_CODECOMMIT_REPO") or "opspilot-sample-service"
    return f"https://git-codecommit.{_region()}.amazonaws.com/v1/repos/{repo}"


def _blank(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    return text or None


def public_test(fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Shape returned on the pr-status payload. None when no verification was started."""
    status = _blank(fields.get("test_status"))
    error = _blank(fields.get("test_error"))
    if not status and not error and not _blank(fields.get("test_build_id")):
        return None
    return {
        "status": status,
        "name": _blank(fields.get("test_name")),
        "summary": _blank(fields.get("test_summary")),
        "log_excerpt": _blank(fields.get("test_log")),
        "error": error,
    }


def _log_excerpt(build: Dict[str, Any], logs_client: Any = None) -> str:
    logs = build.get("logs") or {}
    group, stream = logs.get("groupName"), logs.get("streamName")
    client = logs_client
    if group and stream and client is None:
        try:
            import boto3

            client = boto3.client("logs", region_name=_region())
        except Exception as e:  # noqa: BLE001
            logger.info("CodeBuild log client was not created: %s", e)
            client = None
    if group and stream and client is not None:
        try:
            resp = client.get_log_events(
                logGroupName=group, logStreamName=stream, limit=30, startFromHead=False
            )
            lines = [(event.get("message") or "").rstrip() for event in resp.get("events") or []]
            text = "\n".join(line for line in lines if line).strip()
            if text:
                return text[-1500:]
        except Exception as e:  # noqa: BLE001
            logger.info("CodeBuild log excerpt was not read: %s", e)
    phases = []
    for phase in build.get("phases") or []:
        phases.append(f"{phase.get('phaseType')}: {phase.get('phaseStatus')}")
    exported = {
        item.get("name"): item.get("value") for item in build.get("exportedEnvironmentVariables") or []
    }
    lines = [f"Build status: {build.get('buildStatus') or 'UNKNOWN'}", *phases]
    if exported.get("FAILURE_REASON"):
        lines.append(f"Failure reason: {exported['FAILURE_REASON']}")
    return "\n".join(line for line in lines if line)[:1500]


def verification_comment(status: str, test_name: str, summary: str, excerpt: str) -> str:
    label = "passed" if status == "passed" else "failed"
    body = [
        f"OpsPilot verification: {label}",
        f"Test: {test_name}",
        summary.strip(),
        "",
        "Log excerpt:",
        excerpt.strip() or "No build log was returned.",
    ]
    return "\n".join(body)[:10000]


def begin_pr_verification(
    pr: PrRef,
    rca: RcaResult,
    codebuild_client: Any = None,
) -> Dict[str, Any]:
    """Start opspilot-verify-fix on the pull request branch. Returns incident fields.

    A start failure is stored as an error sentence. The pull request itself is left open.
    """
    test_name = repro_pytest_node(rca, pr.repro_test_path)
    base = {
        "test_status": None,
        "test_name": test_name,
        "test_summary": "",
        "test_log": "",
        "test_build_id": "",
        "test_error": None,
        "test_comment_posted": "",
    }
    try:
        client = codebuild_client
        if client is None:
            import boto3

            client = boto3.client("codebuild", region_name=_region())
        resp = client.start_build(
            projectName=os.environ.get("VERIFY_PROJECT_NAME", VERIFY_PROJECT_NAME),
            sourceVersion=pr.branch,
            environmentVariablesOverride=[
                {"name": "CODECOMMIT_CLONE_URL", "value": codecommit_clone_url(), "type": "PLAINTEXT"},
                {"name": "BASE_REF", "value": pr.base or "main", "type": "PLAINTEXT"},
                {"name": "REPRO_TEST", "value": pr.repro_test_path, "type": "PLAINTEXT"},
            ],
        )
        build_id = (resp.get("build") or {}).get("id")
        if not build_id:
            raise RuntimeError("CodeBuild did not return a build id")
    except Exception as e:  # noqa: BLE001
        logger.warning("Verification build did not start for %s: %s", pr.branch, e)
        base["test_error"] = BUILD_NOT_STARTED
        return base
    base.update(
        {
            "test_status": "running",
            "test_summary": RUNNING_SUMMARY,
            "test_build_id": build_id,
            "test_error": None,
        }
    )
    return base


def _stored(inc: Dict[str, Any]) -> Dict[str, Any]:
    return {key: inc.get(key) for key in _STORED_KEYS}


def refresh_verification(
    inc: Dict[str, Any],
    codebuild_client: Any = None,
    commenter: Optional[Callable[[str], None]] = None,
    logs_client: Any = None,
) -> Optional[Dict[str, Any]]:
    """Read the verify build when one is in progress and comment once it finishes.

    Does not invent passed or failed when the build cannot be read. Returns None
    when this incident never started verification.
    """
    build_id = _blank(inc.get("test_build_id"))
    status = _blank(inc.get("test_status"))
    error = _blank(inc.get("test_error"))
    if not build_id and not status and not error:
        return None
    current = _stored(inc)
    if not build_id:
        return current
    if status in {"passed", "failed"} and inc.get("test_comment_posted") == "yes":
        return current

    try:
        client = codebuild_client
        if client is None:
            import boto3

            client = boto3.client("codebuild", region_name=_region())
        builds = client.batch_get_builds(ids=[build_id]).get("builds") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("Verification build %s could not be read: %s", build_id, e)
        current["test_error"] = BUILD_NOT_READ
        if not status:
            current["test_status"] = "running" if build_id else None
        return current
    if not builds:
        current["test_error"] = BUILD_NOT_READ
        return current

    build = builds[0]
    build_status = build.get("buildStatus") or ""
    if build_status in _RUNNING:
        current["test_status"] = "running"
        current["test_summary"] = RUNNING_SUMMARY
        current["test_error"] = None
        return current

    result = parse_build(build)
    outcome = "passed" if result.verdict == "verified" else "failed"
    summary = result.details or ("Verification passed." if outcome == "passed" else "Verification failed.")
    excerpt = _log_excerpt(build, logs_client=logs_client)
    current.update(
        {
            "test_status": outcome,
            "test_summary": summary,
            "test_log": excerpt,
            "test_error": None,
        }
    )
    if inc.get("test_comment_posted") == "yes":
        return current
    comment = verification_comment(outcome, _blank(inc.get("test_name")) or "reproduction test", summary, excerpt)
    if commenter is None:
        current["test_error"] = COMMENT_NOT_POSTED
        return current
    try:
        commenter(comment)
    except Exception as e:  # noqa: BLE001
        logger.warning("Verification comment was not posted: %s", e)
        current["test_error"] = COMMENT_NOT_POSTED
        current["test_comment_posted"] = ""
        return current
    current["test_comment_posted"] = "yes"
    current["test_error"] = None
    return current
