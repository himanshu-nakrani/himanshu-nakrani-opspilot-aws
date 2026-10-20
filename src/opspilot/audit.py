"""Audit-trail writes for the incidents table.

In live mode a failed audit write raises, so Step Functions retries the step
instead of silently losing the audit trail. In replay mode it only logs.
"""

import logging
import os
from typing import Dict, Optional

import boto3

from opspilot.config import is_live

logger = logging.getLogger(__name__)


def update_incident(incident_id: str, fields: Dict[str, str], dynamodb_client=None) -> None:
    if not fields:
        return
    table_name = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    names = {f"#f{i}": k for i, k in enumerate(fields)}
    values = {f":v{i}": {"S": str(v)} for i, v in enumerate(fields.values())}
    expr = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(fields)))
    try:
        (dynamodb_client or boto3.client("dynamodb")).update_item(
            TableName=table_name,
            Key={"incident_id": {"S": incident_id}},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except Exception as e:
        if is_live():
            raise
        logger.warning("Audit write skipped for %s in replay mode: %s", incident_id, e)
