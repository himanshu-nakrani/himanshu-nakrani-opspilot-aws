"""Write a merged pull request's knowledge document to S3 and start a Bedrock sync."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from opspilot.knowledge.document import public_knowledge

logger = logging.getLogger(__name__)

_STORE_FAILED = "The knowledge base document could not be stored."
_SYNC_FAILED = "The knowledge base sync could not be started."
_NO_BUCKET = "Knowledge bucket is not configured."
_NO_KB = "Knowledge base is not configured."
_ONE_SOURCE = "The knowledge base must have one data source."


def _merged(pr_status: Dict[str, Any]) -> bool:
    return pr_status.get("is_merged") is True or pr_status.get("status") == "merged"


def _failed(preview: Dict[str, Any], message: str) -> Tuple[Dict[str, Any], Dict[str, str]]:
    public = {**preview, "status": "failed", "error": message}
    return public, {
        "knowledge_status": "failed",
        "knowledge_error": message,
        "knowledge_s3_key": preview["s3_key"],
    }


def data_source_id(agent_client: Any, knowledge_base_id: str) -> str:
    """The one connector on the knowledge base. Several connectors is a configuration error."""
    response = agent_client.list_data_sources(knowledgeBaseId=knowledge_base_id)
    sources = response.get("dataSourceSummaries") or []
    if len(sources) != 1 or not sources[0].get("dataSourceId"):
        raise ValueError(_ONE_SOURCE)
    return str(sources[0]["dataSourceId"])


def sync_merged_solution(
    incident: Dict[str, Any],
    pr_status: Dict[str, Any],
    *,
    s3_client: Any,
    agent_client: Any,
    bucket: str,
    knowledge_base_id: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """Upload the preview after merge and start one ingestion job.

    An open pull request returns the waiting preview and stores nothing.
    A second call after a successful sync does not upload again.
    """
    preview = public_knowledge(incident)
    if preview is None:
        return None, {}
    if not _merged(pr_status):
        return {**preview, "status": "waiting", "error": None}, {}

    if (
        incident.get("knowledge_status") == "ingested"
        and incident.get("knowledge_s3_key") == preview["s3_key"]
        and incident.get("knowledge_job_id")
    ):
        return preview, {}

    if not bucket:
        return _failed(preview, _NO_BUCKET)
    if not knowledge_base_id:
        return _failed(preview, _NO_KB)
    try:
        source_id = data_source_id(agent_client, knowledge_base_id)
    except Exception as exc:
        logger.warning("Knowledge base %s has no single data source: %s", knowledge_base_id, exc)
        return _failed(preview, _ONE_SOURCE)
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=preview["s3_key"],
            Body=preview["body"].encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
            ServerSideEncryption="AES256",
        )
    except Exception as exc:
        logger.warning("Knowledge document upload failed for %s: %s", incident.get("incident_id"), exc)
        return _failed(preview, _STORE_FAILED)

    try:
        response = agent_client.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=source_id,
        )
    except Exception as exc:
        logger.warning("Knowledge base sync failed for %s: %s", incident.get("incident_id"), exc)
        return _failed(preview, _SYNC_FAILED)

    job_id = str((response.get("ingestionJob") or {}).get("ingestionJobId") or "")
    if not job_id:
        return _failed(preview, _SYNC_FAILED)
    return {**preview, "status": "ingested", "error": None}, {
        "knowledge_status": "ingested",
        "knowledge_error": "",
        "knowledge_s3_key": preview["s3_key"],
        "knowledge_job_id": job_id,
    }
