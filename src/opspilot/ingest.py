"""Alarm ingestion and deduplication handler.

Triggered by EventBridge on CloudWatch Alarm State Change.
Deduplicates alarms within a configurable window (default 15 minutes)
using DynamoDB conditional puts, and starts the Step Functions workflow.
"""

from datetime import datetime, timezone
import hashlib
import logging
import os
from typing import Any, Dict, Optional
import boto3
from botocore.exceptions import ClientError
from dateutil import parser as dt_parser

from opspilot.config import is_live
from opspilot.contracts import IncidentEvent

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def compute_incident_id(alarm_name: str, detected_at_dt: datetime, window_min: int = 15) -> tuple[str, str, str]:
    """Compute incident_id as sha256(alarm_name + floor(detected_at / dedup window)).

    Returns:
        (incident_id, window_start_iso, window_end_iso)
    """
    window_seconds = window_min * 60
    epoch = int(detected_at_dt.timestamp())
    window_start_epoch = (epoch // window_seconds) * window_seconds
    window_end_epoch = window_start_epoch + window_seconds

    window_start = datetime.fromtimestamp(window_start_epoch, tz=timezone.utc).isoformat()
    window_end = datetime.fromtimestamp(window_end_epoch, tz=timezone.utc).isoformat()

    seed = f"{alarm_name}-{window_start_epoch}".encode("utf-8")
    incident_id = hashlib.sha256(seed).hexdigest()
    return incident_id, window_start, window_end


PENDING_STALE_SECONDS = int(os.environ.get("PENDING_STALE_SECONDS", "120"))
RECORD_TTL_DAYS = int(os.environ.get("RECORD_TTL_DAYS", "30"))


def record_incident_if_new(
    table_name: str,
    incident_id: str,
    alarm_name: str,
    service: str,
    detected_at: str,
    dynamodb_client=None,
) -> bool:
    """Claim the incident in DynamoDB before starting the workflow.

    The record is written as PENDING and only promoted to STARTED after the
    Step Functions execution exists (see ``mark_incident_started``). A PENDING
    record older than PENDING_STALE_SECONDS is re-claimable, so an ingest
    failure between the claim and ``start_execution`` no longer loses the
    incident. Returns True if this caller owns the claim.
    """
    client = dynamodb_client or boto3.client("dynamodb")
    now = datetime.now(timezone.utc)
    now_epoch = int(now.timestamp())
    try:
        client.put_item(
            TableName=table_name,
            Item={
                "incident_id": {"S": incident_id},
                "alarm_name": {"S": alarm_name},
                "service": {"S": service},
                "detected_at": {"S": detected_at},
                "created_at": {"S": now.isoformat()},
                "claimed_at_epoch": {"N": str(now_epoch)},
                "status": {"S": "PENDING"},
                "ttl": {"N": str(now_epoch + RECORD_TTL_DAYS * 86400)},
            },
            ConditionExpression=(
                "attribute_not_exists(incident_id) OR "
                "(#st = :pending AND claimed_at_epoch < :stale)"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":pending": {"S": "PENDING"},
                ":stale": {"N": str(now_epoch - PENDING_STALE_SECONDS)},
            },
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            logger.info("Duplicate incident %s inside dedup window, skipping.", incident_id)
            return False
        raise


def mark_incident_started(table_name: str, incident_id: str, execution_arn: Optional[str], dynamodb_client=None) -> None:
    client = dynamodb_client or boto3.client("dynamodb")
    names = {"#st": "status"}
    values = {":started": {"S": "STARTED"}}
    expr = "SET #st = :started"
    if execution_arn:
        expr += ", execution_arn = :arn"
        values[":arn"] = {"S": execution_arn}
    client.update_item(
        TableName=table_name,
        Key={"incident_id": {"S": incident_id}},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def handle_alarm_event(
    event: Dict[str, Any],
    context: Optional[Any] = None,
    dynamodb_client=None,
    sfn_client=None,
) -> Dict[str, Any]:
    """Lambda handler for EventBridge alarm state change events."""
    logger.info("Received event: %s", event)

    detail = event.get("detail", {})
    state = detail.get("state", {})
    state_val = state.get("value")

    # Only act on transitions to ALARM
    if state_val != "ALARM":
        logger.info("Alarm state is %s, not ALARM. Skipping.", state_val)
        return {"status": "ignored", "reason": f"state is {state_val}"}

    alarm_name = detail.get("alarmName", "unknown-alarm")
    raw_timestamp = state.get("timestamp") or event.get("time") or datetime.now(timezone.utc).isoformat()

    try:
        detected_at_dt = dt_parser.parse(raw_timestamp)
        if detected_at_dt.tzinfo is None:
            detected_at_dt = detected_at_dt.replace(tzinfo=timezone.utc)
    except Exception:
        detected_at_dt = datetime.now(timezone.utc)

    detected_at_iso = detected_at_dt.isoformat()
    dedup_window_min = int(os.environ.get("DEDUP_WINDOW_MIN", "15"))
    table_name = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    state_machine_arn = os.environ.get("STATE_MACHINE_ARN", "")
    service = os.environ.get("SERVICE_NAME", "sample-service")
    log_group = os.environ.get("LOG_GROUP_NAME", "/aws/lambda/opspilot-sample-service")
    from opspilot.fix.scm import repo_name

    repo = repo_name()  # CodeCommit repository name by default

    incident_id, window_start, window_end = compute_incident_id(alarm_name, detected_at_dt, dedup_window_min)

    is_new = record_incident_if_new(
        table_name=table_name,
        incident_id=incident_id,
        alarm_name=alarm_name,
        service=service,
        detected_at=detected_at_iso,
        dynamodb_client=dynamodb_client,
    )

    if not is_new:
        return {
            "status": "skipped_duplicate",
            "incident_id": incident_id,
            "alarm_name": alarm_name,
        }

    incident_event = IncidentEvent(
        incident_id=incident_id,
        source="cloudwatch",
        service=service,
        alarm_name=alarm_name,
        detected_at=detected_at_iso,
        window_start=window_start,
        window_end=window_end,
        log_group=log_group,
        repo=repo,
    )

    execution_arn = None
    if state_machine_arn:
        sfn = sfn_client or boto3.client("stepfunctions")
        # Step Functions execution names must be <= 80 characters
        # Deterministic per incident, so a retried ingest cannot start a second execution.
        exec_name = f"opspilot-{incident_id[:64]}"
        try:
            resp = sfn.start_execution(
                stateMachineArn=state_machine_arn,
                name=exec_name,
                input=incident_event.model_dump_json(),
            )
            execution_arn = resp.get("executionArn")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ExecutionAlreadyExists":
                raise  # leave the claim PENDING; it becomes re-claimable after PENDING_STALE_SECONDS
            execution_arn = f"{state_machine_arn.replace(':stateMachine:', ':execution:')}:{exec_name}"
        logger.info("Started Step Functions execution %s for incident %s", execution_arn, incident_id)
    elif is_live():
        raise RuntimeError("STATE_MACHINE_ARN is not set in live mode; refusing to drop the incident")

    mark_incident_started(table_name, incident_id, execution_arn, dynamodb_client=dynamodb_client)

    return {
        "status": "started",
        "incident_id": incident_id,
        "execution_arn": execution_arn,
        "incident_event": incident_event.model_dump(),
    }
