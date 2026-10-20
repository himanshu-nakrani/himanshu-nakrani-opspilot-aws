"""Unit tests for alarm ingestion and deduplication."""

from datetime import datetime, timezone
import json
import boto3
import pytest
from moto import mock_aws

from opspilot.ingest import compute_incident_id, handle_alarm_event, record_incident_if_new


def test_compute_incident_id_window_dedup():
    """Events within the same 15-minute window produce identical incident_ids."""
    dt1 = datetime(2026, 10, 20, 12, 1, 0, tzinfo=timezone.utc)
    dt2 = datetime(2026, 10, 20, 12, 14, 59, tzinfo=timezone.utc)
    dt3 = datetime(2026, 10, 20, 12, 16, 0, tzinfo=timezone.utc)

    id1, win_start1, win_end1 = compute_incident_id("SampleAlarm", dt1, window_min=15)
    id2, win_start2, win_end2 = compute_incident_id("SampleAlarm", dt2, window_min=15)
    id3, win_start3, win_end3 = compute_incident_id("SampleAlarm", dt3, window_min=15)

    assert id1 == id2
    assert win_start1 == win_start2
    assert win_end1 == win_end2

    # Across window boundary, ID must differ
    assert id1 != id3
    assert win_start1 != win_start3


@mock_aws
def test_record_incident_if_new_conditional_put():
    """DynamoDB conditional put enforces deduplication."""
    dynamodb = boto3.client("dynamodb", region_name="us-east-1")
    table_name = "opspilot-incidents"
    dynamodb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    incident_id = "test-incident-123"
    is_new_1 = record_incident_if_new(
        table_name=table_name,
        incident_id=incident_id,
        alarm_name="SampleAlarm",
        service="sample-service",
        detected_at="2026-10-20T12:00:00Z",
        dynamodb_client=dynamodb,
    )
    assert is_new_1 is True

    # Second call with same incident_id should return False (deduplicated)
    is_new_2 = record_incident_if_new(
        table_name=table_name,
        incident_id=incident_id,
        alarm_name="SampleAlarm",
        service="sample-service",
        detected_at="2026-10-20T12:05:00Z",
        dynamodb_client=dynamodb,
    )
    assert is_new_2 is False


@mock_aws
def test_handle_alarm_event_lifecycle(monkeypatch):
    """Alarm ingestion triggers Step Functions once, then deduplicates subsequent alarms."""
    region = "us-east-1"
    dynamodb = boto3.client("dynamodb", region_name=region)
    sfn = boto3.client("stepfunctions", region_name=region)

    table_name = "opspilot-incidents"
    dynamodb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    role_arn = "arn:aws:iam::123456789012:role/DummyRole"
    sfn_def = {
        "StartAt": "PassState",
        "States": {"PassState": {"Type": "Pass", "End": True}},
    }
    sfn_res = sfn.create_state_machine(
        name="opspilot-test",
        definition=json.dumps(sfn_def),
        roleArn=role_arn,
    )
    sm_arn = sfn_res["stateMachineArn"]

    monkeypatch.setenv("INCIDENTS_TABLE_NAME", table_name)
    monkeypatch.setenv("STATE_MACHINE_ARN", sm_arn)
    monkeypatch.setenv("AWS_DEFAULT_REGION", region)

    event_payload = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "time": "2026-10-20T12:00:00Z",
        "detail": {
            "alarmName": "OpsPilotSampleServiceErrors",
            "state": {
                "value": "ALARM",
                "timestamp": "2026-10-20T12:00:00.000+0000",
                "reason": "Threshold Crossed",
            },
        },
    }

    # First alarm trigger
    res1 = handle_alarm_event(event_payload, dynamodb_client=dynamodb, sfn_client=sfn)
    assert res1["status"] == "started"
    assert res1["execution_arn"] is not None
    assert "incident_event" in res1
    assert res1["incident_event"]["service"] == "sample-service"

    # Verify execution was started
    execs = sfn.list_executions(stateMachineArn=sm_arn)["executions"]
    assert len(execs) == 1

    # Second alarm trigger inside 15-minute window (e.g. 2 minutes later)
    event_payload_2 = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "time": "2026-10-20T12:02:00Z",
        "detail": {
            "alarmName": "OpsPilotSampleServiceErrors",
            "state": {
                "value": "ALARM",
                "timestamp": "2026-10-20T12:02:00.000+0000",
                "reason": "Threshold Crossed",
            },
        },
    }
    res2 = handle_alarm_event(event_payload_2, dynamodb_client=dynamodb, sfn_client=sfn)
    assert res2["status"] == "skipped_duplicate"

    # Step Functions should still only have 1 execution
    execs_after = sfn.list_executions(stateMachineArn=sm_arn)["executions"]
    assert len(execs_after) == 1


def test_handle_alarm_event_ignores_non_alarm():
    event_ok = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "detail": {
            "alarmName": "OpsPilotSampleServiceErrors",
            "state": {"value": "OK"},
        },
    }
    res = handle_alarm_event(event_ok)
    assert res["status"] == "ignored"
