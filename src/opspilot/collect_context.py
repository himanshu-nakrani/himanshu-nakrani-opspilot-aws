"""Collects context from CloudWatch Logs, stack traces, and Git/GitHub.

Triggered as the first Step Functions task (CollectContext).
Builds a ContextBundle containing redacted logs, parsed stack traces,
and relevant repository files with commit history.
"""

from datetime import datetime, timedelta, timezone
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional
import boto3
from dateutil import parser as dt_parser

from opspilot.contracts import ContextBundle, IncidentEvent, LogLine, StackFrame, StackTraceInfo
from opspilot.redact import redact_text

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FRAME_PATTERN = re.compile(
    r'File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+),\s+in\s+(?P<func>\w+)(?:\n\s+(?P<code>.+))?'
)
ERROR_PATTERN = re.compile(r"^(?P<error_type>[A-Za-z0-9_]+Error|[A-Za-z0-9_]+Exception):\s*(?P<error_msg>.*)$", re.MULTILINE)


def parse_stack_trace_from_logs(log_messages: List[str]) -> Optional[StackTraceInfo]:
    """Parse python traceback from a list of log messages."""
    full_text = "\n".join(log_messages)
    tb_marker = "Traceback (most recent call last):"
    if tb_marker not in full_text:
        return None

    # Grab section from traceback marker
    tb_section = full_text.split(tb_marker, 1)[1]

    frames: List[StackFrame] = []
    for match in FRAME_PATTERN.finditer(tb_section):
        file_path = match.group("file")
        # Normalize Lambda file paths like /var/task/sample_service/app.py -> sample_service/app.py
        if "/sample_service/" in file_path:
            file_path = "sample_service/" + file_path.split("/sample_service/", 1)[1]
        elif file_path.startswith("/var/task/"):
            file_path = file_path.replace("/var/task/", "")

        line_num = int(match.group("line"))
        func = match.group("func")
        code = match.group("code")
        frames.append(StackFrame(file=file_path, line=line_num, function=func, code_context=code))

    error_match = ERROR_PATTERN.search(tb_section)
    if error_match:
        error_type = error_match.group("error_type")
        error_msg = error_match.group("error_msg").strip()
    else:
        error_type = "UnhandledException"
        error_msg = "Unknown error occurred"

    top_frame = frames[-1] if frames else None
    return StackTraceInfo(
        error_type=error_type,
        error_message=error_msg,
        frames=frames,
        top_frame=top_frame,
    )


# Error-ish events first: an unfiltered FilterLogEvents call returns the *earliest*
# events in the window, and on a service with steady traffic the first 50 are
# START/END/REPORT and request lines, so the traceback never reaches the RCA.
ERROR_FILTER_PATTERN = (
    '?Traceback ?ERROR ?Exception ?WARN ?"Task timed out" ?"Runtime exited" ?"Runtime.OutOfMemory"'
)


def _filter_events(client, log_group: str, start_time: int, end_time: int,
                   filter_pattern: Optional[str], limit: int) -> List[Dict[str, Any]]:
    kwargs: Dict[str, Any] = {"logGroupName": log_group, "startTime": start_time, "endTime": end_time}
    if filter_pattern:
        kwargs["filterPattern"] = filter_pattern
    events: List[Dict[str, Any]] = []
    token = None
    for _ in range(10):  # bounded pagination
        if token:
            kwargs["nextToken"] = token
        resp = client.filter_log_events(**kwargs, limit=limit)
        events.extend(resp.get("events", []))
        token = resp.get("nextToken")
        if not token or len(events) >= limit:
            break
    return events[:limit]


def fetch_cloudwatch_logs(
    log_group: str,
    detected_at_dt: datetime,
    logs_client=None,
    window_minutes: int = 10,
    limit: int = 50,
) -> List[LogLine]:
    """Fetch logs around detected_at ± window_minutes, error/warning events first.

    Falls back to the unfiltered window when nothing matches (e.g. a pure latency
    incident with no error lines), so the RCA still sees what the service logged.
    """
    client = logs_client or boto3.client("logs")
    start_time = int((detected_at_dt - timedelta(minutes=window_minutes)).timestamp() * 1000)
    end_time = int((detected_at_dt + timedelta(minutes=window_minutes)).timestamp() * 1000)

    log_lines: List[LogLine] = []
    try:
        events = _filter_events(client, log_group, start_time, end_time, ERROR_FILTER_PATTERN, limit)
        if not events:
            events = _filter_events(client, log_group, start_time, end_time, None, limit)
        for idx, event in enumerate(events, start=1):
            ts = datetime.fromtimestamp(event["timestamp"] / 1000.0, tz=timezone.utc).isoformat()
            raw_msg = event.get("message", "")
            redacted_msg = redact_text(raw_msg)
            log_lines.append(LogLine(id=f"log-{idx}", timestamp=ts, message=redacted_msg))
    except Exception as e:
        logger.warning("Failed to fetch logs from CloudWatch (%s): %s", log_group, e)

    return log_lines


def get_repo_context(
    stack_trace: Optional[StackTraceInfo],
    repo_root: Optional[str] = None,
) -> tuple[Dict[str, str], List[Dict[str, str]]]:
    """Retrieve file contents and recent commits for files in stack trace."""
    repo_files: Dict[str, str] = {}
    recent_commits: List[Dict[str, str]] = []

    if not repo_root:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    if not stack_trace or not stack_trace.frames:
        return repo_files, recent_commits

    seen_files = set()
    for frame in stack_trace.frames:
        if frame.file in seen_files:
            continue
        seen_files.add(frame.file)

        target_path = os.path.join(repo_root, frame.file)
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    repo_files[frame.file] = f.read()
            except Exception as e:
                logger.warning("Could not read repo file %s: %s", target_path, e)

        # Get git commit info if inside git repo
        try:
            res = subprocess.run(
                ["git", "log", "-n", "3", "--pretty=format:%H|%s|%an", "--", frame.file],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().split("\n"):
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        recent_commits.append({"commit": parts[0], "subject": parts[1], "author": parts[2]})
        except Exception as e:
            logger.warning("Git log failed for %s: %s", frame.file, e)

    return repo_files, recent_commits


def collect_context_bundle(
    incident_event: IncidentEvent,
    logs_client=None,
    repo_root: Optional[str] = None,
    mock_log_lines: Optional[List[LogLine]] = None,
) -> ContextBundle:
    """Builds the complete ContextBundle for the given IncidentEvent."""
    try:
        detected_at_dt = dt_parser.parse(incident_event.detected_at)
    except Exception:
        detected_at_dt = datetime.now(timezone.utc)

    if mock_log_lines is not None:
        log_lines = mock_log_lines
    else:
        log_lines = fetch_cloudwatch_logs(incident_event.log_group, detected_at_dt, logs_client=logs_client)

    stack_trace = parse_stack_trace_from_logs([l.message for l in log_lines])
    repo_files, recent_commits = get_repo_context(stack_trace, repo_root=repo_root)

    return ContextBundle(
        incident_id=incident_event.incident_id,
        service=incident_event.service,
        log_group=incident_event.log_group,
        detected_at=incident_event.detected_at,
        log_lines=log_lines,
        stack_trace=stack_trace,
        repo=incident_event.repo,
        repo_files=repo_files,
        recent_commits=recent_commits,
    )


def handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """Lambda entry point for Step Functions CollectContext state."""
    logger.info("CollectContext triggered with event: %s", event)

    if "incident_event" in event:
        incident_data = event["incident_event"]
    else:
        incident_data = event

    incident_event = IncidentEvent.model_validate(incident_data)
    bundle = collect_context_bundle(incident_event)

    # Audit to DynamoDB if table is available
    table_name = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    try:
        dynamodb = boto3.client("dynamodb")
        dynamodb.update_item(
            TableName=table_name,
            Key={"incident_id": {"S": bundle.incident_id}},
            UpdateExpression="SET #s = :s, #ts = :ts",
            ExpressionAttributeNames={"#s": "status", "#ts": "context_collected_at"},
            ExpressionAttributeValues={
                ":s": {"S": "CONTEXT_COLLECTED"},
                ":ts": {"S": datetime.now(timezone.utc).isoformat()},
            },
        )
    except Exception as e:
        logger.warning("Could not update DynamoDB status for incident %s: %s", bundle.incident_id, e)

    return bundle.model_dump()
