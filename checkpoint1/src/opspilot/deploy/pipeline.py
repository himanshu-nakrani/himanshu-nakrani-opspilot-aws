"""Read the storefront CodePipeline execution for a merged pull request.

Merging to main of opspilot-sample-service starts pipeline opspilot-sample-service.
This module only reads that pipeline. It does not start an execution and it does not merge.
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PIPELINE_NAME = os.environ.get("STOREFRONT_PIPELINE_NAME", "opspilot-sample-service")
PIPELINE_REGION = "us-east-1"
PIPELINE_NOT_READ = "The pipeline could not be read."
PR_NOT_READ = "The pull request could not be read, so the deploy was not checked."
MERGE_COMMIT_MISSING = "The merge commit is not on this pull request, so the deploy was not checked."
NOT_STARTED_SUMMARY = "The deploy has not started. It starts when this pull request is merged to main."

_STATUS = {
    "InProgress": "in_progress",
    "Stopping": "in_progress",
    "Succeeded": "succeeded",
    "Failed": "failed",
}


def pipeline_view_url() -> str:
    return (
        f"https://{PIPELINE_REGION}.console.aws.amazon.com/codesuite/codepipeline/pipelines/"
        f"{PIPELINE_NAME}/view?region={PIPELINE_REGION}"
    )


def execution_url(execution_id: str) -> str:
    return (
        f"https://{PIPELINE_REGION}.console.aws.amazon.com/codesuite/codepipeline/pipelines/"
        f"{PIPELINE_NAME}/executions/{execution_id}/visualization?region={PIPELINE_REGION}"
    )


def deploy_not_started() -> Dict[str, Any]:
    """Fields stored when a pull request exists and has not been merged."""
    return deploy_fields(status="not_started", summary=NOT_STARTED_SUMMARY, url=pipeline_view_url())


def deploy_fields(
    status: Optional[str] = None,
    summary: str = "",
    url: Optional[str] = None,
    error: Optional[str] = None,
    execution_id: Optional[str] = None,
    stage: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "deploy_status": status,
        "deploy_summary": summary or "",
        "deploy_url": url or pipeline_view_url(),
        "deploy_error": error,
        "deploy_execution_id": execution_id or "",
        "deploy_stage": stage or "",
    }


def public_deploy(fields: Dict[str, Any]) -> Dict[str, Any]:
    def blank(value: Any) -> Optional[str]:
        text = "" if value is None else str(value).strip()
        return text or None

    return {
        "status": blank(fields.get("deploy_status")),
        "stage": blank(fields.get("deploy_stage")),
        "execution_id": blank(fields.get("deploy_execution_id")),
        "url": blank(fields.get("deploy_url")) or pipeline_view_url(),
        "summary": blank(fields.get("deploy_summary")),
        "error": blank(fields.get("deploy_error")),
    }


def _stage_for(state: Dict[str, Any], execution_id: str) -> Optional[str]:
    found = None
    for stage in state.get("stageStates") or []:
        latest = stage.get("latestExecution") or {}
        if latest.get("pipelineExecutionId") != execution_id:
            continue
        found = stage.get("stageName")
        if latest.get("status") == "InProgress":
            return found
    return found


def _summary(status: str, stage: Optional[str]) -> str:
    if status == "in_progress":
        return f"Deploy is in progress{f' in the {stage} stage' if stage else ''}."
    if status == "succeeded":
        return "Deploy succeeded."
    if status == "failed":
        return "Deploy failed."
    if status == "not_started":
        return NOT_STARTED_SUMMARY
    return f"Pipeline status: {status}."


def _match_execution(summaries: list, merge_commit: str) -> Optional[Dict[str, Any]]:
    for summary in summaries:
        for revision in summary.get("sourceRevisions") or []:
            revision_id = revision.get("revisionId") or ""
            if revision_id and (revision_id == merge_commit or merge_commit.startswith(revision_id)):
                return summary
    return None


def refresh_deploy(
    inc: Dict[str, Any],
    pr_status: Dict[str, Any],
    pipeline_client: Any = None,
) -> Dict[str, Any]:
    """Deploy state for an incident that already has a pull request.

    An open pull request is not started. A merged one is matched to the pipeline
    execution whose source revision is the merge commit. A failed read keeps the
    last stored status and sets an error. It does not report succeeded or failed
    from a guess.
    """
    last = deploy_fields(
        status=inc.get("deploy_status"),
        summary=inc.get("deploy_summary") or "",
        url=inc.get("deploy_url") or pipeline_view_url(),
        error=inc.get("deploy_error"),
        execution_id=inc.get("deploy_execution_id") or "",
        stage=inc.get("deploy_stage") or "",
    )
    if pr_status.get("error"):
        last["deploy_error"] = PR_NOT_READ
        last["deploy_url"] = last.get("deploy_url") or pipeline_view_url()
        return last
    merged = pr_status.get("is_merged") is True or pr_status.get("status") == "merged"
    if not merged:
        return deploy_not_started()

    merge_commit = pr_status.get("merge_commit") or inc.get("merge_commit")
    if not merge_commit:
        last["deploy_error"] = MERGE_COMMIT_MISSING
        last["deploy_url"] = pipeline_view_url()
        return last

    try:
        client = pipeline_client
        if client is None:
            import boto3

            client = boto3.client(
                "codepipeline",
                region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or PIPELINE_REGION,
            )
        listed = client.list_pipeline_executions(pipelineName=PIPELINE_NAME, maxResults=20)
        summaries = listed.get("pipelineExecutionSummaries") or []
        state = client.get_pipeline_state(name=PIPELINE_NAME)
    except Exception as e:  # noqa: BLE001
        logger.warning("Pipeline %s could not be read: %s", PIPELINE_NAME, e)
        last["deploy_error"] = PIPELINE_NOT_READ
        last["deploy_url"] = last.get("deploy_url") or pipeline_view_url()
        return last

    match = _match_execution(summaries, str(merge_commit))
    if not match:
        return deploy_fields(
            status="not_started",
            summary="The deploy has not started for this merge yet.",
            url=pipeline_view_url(),
        )
    execution_id = match.get("pipelineExecutionId") or ""
    raw = match.get("status") or ""
    status = _STATUS.get(raw, raw or None)
    stage = _stage_for(state, execution_id) if execution_id else None
    url = execution_url(execution_id) if execution_id else pipeline_view_url()
    return deploy_fields(
        status=status,
        summary=_summary(status or raw, stage),
        url=url,
        execution_id=execution_id,
        stage=stage,
    )
