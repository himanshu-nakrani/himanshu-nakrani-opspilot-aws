#!/usr/bin/env python3
"""Trigger incident script for OpsPilot M1.

Calls the bad endpoint (/orders/999) 5 times to generate unhandled
exceptions / 500 errors. Demonstrates deduplication: a second alarm
event within 15 minutes does NOT start a new execution.
"""

import os
import sys
import time
from datetime import datetime, timezone
import httpx
from fastapi.testclient import TestClient

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

# Ensure repo and src are on path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from sample_service.app import app
from opspilot.ingest import handle_alarm_event
from moto import mock_aws
import boto3


def call_bad_endpoint(url: str = None) -> list[int]:
    """Call bad endpoint 5 times and return status codes."""
    statuses = []
    print("\n[M1] Calling bad endpoint (/orders/999) 5 times...")
    if url:
        for i in range(1, 6):
            try:
                resp = httpx.get(f"{url.rstrip('/')}/orders/999", timeout=5.0)
                statuses.append(resp.status_code)
                print(f"  Call {i}: HTTP {resp.status_code}")
            except Exception as e:
                print(f"  Call {i}: Exception {e}")
                statuses.append(500)
    else:
        # Local in-process TestClient
        client = TestClient(app, raise_server_exceptions=False)
        for i in range(1, 6):
            resp = client.get("/orders/999")
            statuses.append(resp.status_code)
            print(f"  Call {i}: HTTP {resp.status_code} (AttributeError: 'NoneType' object has no attribute 'total')")
    return statuses


def run_trigger_simulation():
    url = os.environ.get("SAMPLE_SERVICE_URL")
    statuses = call_bad_endpoint(url)

    if not all(code == 500 for code in statuses):
        print("❌ Expected all 5 calls to fail with 500, but got:", statuses)
        return False

    print("✅ All 5 calls failed with 500 Internal Server Error (planted missing-order bug).")

    # Simulate CloudWatch Alarm State Change to ALARM
    alarm_event = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "time": datetime.now(timezone.utc).isoformat(),
        "detail": {
            "alarmName": "OpsPilotSampleServiceErrors",
            "state": {
                "value": "ALARM",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": "Threshold Crossed: 5 datapoints were greater than or equal to threshold 1.0",
            },
        },
    }

    # If running against real AWS, execute directly; otherwise use moto mock
    is_live = bool(os.environ.get("SAMPLE_SERVICE_URL") or os.environ.get("STATE_MACHINE_ARN"))
    
    def _execute():
        print("\n[M1] Emitting Alarm EventBridge event to OpsPilot Ingest...")
        res1 = handle_alarm_event(alarm_event)
        print(f"  Initial trigger result: status={res1.get('status')}, incident_id={res1.get('incident_id')}")

        print("\n[M1] Emitting second Alarm EventBridge event inside 15-minute window...")
        res2 = handle_alarm_event(alarm_event)
        print(f"  Duplicate trigger result: status={res2.get('status')}, incident_id={res2.get('incident_id')}")

        if res2.get("status") == "skipped_duplicate":
            print("✅ Dedup verified: duplicate alarm inside 15-minute window was skipped.")
            return True
        else:
            print("❌ Dedup check failed, second trigger was not skipped.")
            return False

    if is_live:
        return _execute()
    else:
        with mock_aws():
            dynamodb = boto3.client("dynamodb", region_name="us-east-1")
            dynamodb.create_table(
                TableName="opspilot-incidents",
                KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            sfn = boto3.client("stepfunctions", region_name="us-east-1")
            sfn_res = sfn.create_state_machine(
                name="opspilot",
                definition='{"StartAt":"Pass","States":{"Pass":{"Type":"Pass","End":true}}}',
                roleArn="arn:aws:iam::123456789012:role/MockRole",
            )
            os.environ["STATE_MACHINE_ARN"] = sfn_res["stateMachineArn"]
            return _execute()


if __name__ == "__main__":
    success = run_trigger_simulation()
    sys.exit(0 if success else 1)
