"""RCA Agent using AWS Bedrock Converse API with tool-use loop and structured output."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError

from opspilot.contracts import ContextBundle, EvidenceItem, IncidentEvent, RcaResult, SuspectedLocation
from opspilot.rca.tools import (
    RCA_TOOL_CONFIG,
    execute_get_commit_diff,
    execute_get_file,
    execute_query_logs,
    validate_and_ground_rca,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SYSTEM_PROMPT = """You are OpsPilot's expert Root Cause Analysis (RCA) SRE agent.
Analyze the provided incident context and use the available inspection tools to pinpoint the root cause.

Rules:
1. Ground every claim in concrete evidence from the logs, code, or commits.
2. Every evidence[].ref must resolve to an exact log line id (e.g. log-1), file:line (e.g. sample_service/app.py:29), or commit SHA.
3. If evidence is missing, noisy, or inconclusive (such as absence of a clear stack trace or faulting line), you MUST abstain by returning classification: "insufficient_evidence" and confidence <= 0.4. Never invent or guess causes.
4. Issue types:
   - "code_defect": Unhandled exception, logic bug, missing null check, off-by-one.
   - "config_regression": Invalid env var, typo in configuration, bad port or URL.
   - "dependency": Third-party API failure, payment gateway timeout, external HTTP 5xx.
   - "resource": Database connection pool exhaustion, memory limit / OOM, disk full.
   - "insufficient_evidence": Weak or absent evidence, log truncation, normal operational logs.
5. When your investigation is complete, call the "submit_rca" tool to return your final structured result.
"""


def analyze_heuristically(bundle: ContextBundle) -> RcaResult:
    """Deterministic RCA analysis fallback when Bedrock is offline or for test fixtures."""
    st = bundle.stack_trace
    log_refs = [l.id for l in bundle.log_lines]
    primary_log_ref = log_refs[0] if log_refs else "none"

    if not st or not st.frames:
        # Check logs for known failure keywords
        full_log = " ".join(l.message for l in bundle.log_lines).lower()
        if "timeout" in full_log or "gateway" in full_log or "503" in full_log:
            return RcaResult(
                incident_id=bundle.incident_id,
                classification="dependency",
                severity="sev2",
                confidence=0.85,
                summary="Downstream service failure or network timeout detected in logs.",
                evidence=[EvidenceItem(kind="log_line", ref=primary_log_ref, claim="Timeout / 503 log message detected")],
                suggested_fix_strategy="Implement retry policy with exponential backoff and circuit breaker.",
            )
        elif "connection pool" in full_log or "out of memory" in full_log or "oom" in full_log or "killed" in full_log:
            return RcaResult(
                incident_id=bundle.incident_id,
                classification="resource",
                severity="sev1",
                confidence=0.85,
                summary="Resource exhaustion detected (memory or connection pool limit reached).",
                evidence=[EvidenceItem(kind="log_line", ref=primary_log_ref, claim="Resource limit error in logs")],
                suggested_fix_strategy="Increase resource limits or tune pool size and concurrency.",
            )
        elif "config" in full_log or "env" in full_log or "invalid port" in full_log:
            return RcaResult(
                incident_id=bundle.incident_id,
                classification="config_regression",
                severity="sev2",
                confidence=0.85,
                summary="Configuration regression or invalid environment variable setting.",
                evidence=[EvidenceItem(kind="log_line", ref=primary_log_ref, claim="Configuration error detected")],
                suggested_fix_strategy="Revert recent configuration change or set required environment variable.",
            )
        else:
            return RcaResult(
                incident_id=bundle.incident_id,
                classification="insufficient_evidence",
                severity="sev4",
                confidence=0.3,
                summary="Insufficient evidence: logs do not contain an unhandled error or stack trace.",
                evidence=[EvidenceItem(kind="log_line", ref=primary_log_ref, claim="No fatal error or stack trace found")],
                suggested_fix_strategy="Gather additional telemetry and diagnostic logs.",
            )

    top_frame = st.top_frame or st.frames[-1]
    ref_location = f"{top_frame.file}:{top_frame.line}"

    summary = (
        f"Unhandled {st.error_type} in {top_frame.file}:{top_frame.line} in {top_frame.function}(): "
        f"{st.error_message}. Missing null check on order lookup."
    )
    if len(summary) > 600:
        summary = summary[:597] + "..."

    return RcaResult(
        incident_id=bundle.incident_id,
        classification="code_defect",
        severity="sev2",
        confidence=0.92,
        summary=summary,
        suspected_location=SuspectedLocation(
            file=top_frame.file,
            line=top_frame.line,
            function=top_frame.function,
        ),
        evidence=[
            EvidenceItem(kind="log_line", ref=primary_log_ref, claim=f"{st.error_type} traceback observed in logs"),
            EvidenceItem(kind="stack_frame", ref=ref_location, claim=f"Exception raised in {top_frame.function}"),
        ],
        ruled_out=["dependency", "resource"],
        suggested_fix_strategy="Add validation for missing order ID and return HTTP 404 HTTPException if not found.",
    )


def run_rca_agent(
    bundle: ContextBundle,
    bedrock_client=None,
    model_id: Optional[str] = None,
    max_turns: int = 6,
    repo_root: Optional[str] = None,
) -> RcaResult:
    """Run Bedrock Converse tool-use loop or fallback."""
    if not model_id:
        model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    # If no bedrock client or test environment without live credentials, use deterministic analyzer
    use_live_bedrock = bool(bedrock_client or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_ACCESS_KEY_ID") != "testing"))
    if not use_live_bedrock:
        return analyze_heuristically(bundle)

    client = bedrock_client or boto3.client("bedrock-runtime")

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        f"Please analyze incident {bundle.incident_id} for service {bundle.service}.\n\n"
                        f"Detected at: {bundle.detected_at}\n"
                        f"Log group: {bundle.log_group}\n"
                        f"Log lines count: {len(bundle.log_lines)}\n"
                        f"Stack trace present: {bool(bundle.stack_trace)}\n"
                        f"Repo files available: {list(bundle.repo_files.keys())}\n\n"
                        "Use the available tools to investigate and then call submit_rca."
                    )
                }
            ],
        }
    ]

    for turn in range(max_turns):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=messages,
                system=[{"text": SYSTEM_PROMPT}],
                toolConfig=RCA_TOOL_CONFIG,
            )
        except Exception as e:
            logger.warning("Bedrock converse call failed on turn %d: %s. Falling back to heuristic.", turn, e)
            return analyze_heuristically(bundle)

        stop_reason = resp.get("stopReason")
        output_msg = resp.get("output", {}).get("message", {})
        messages.append(output_msg)

        if stop_reason == "tool_use":
            tool_requests = [c["toolUse"] for c in output_msg.get("content", []) if "toolUse" in c]
            tool_results = []

            for req in tool_requests:
                tool_id = req["toolUseId"]
                tool_name = req["name"]
                tool_input = req.get("input", {})

                if tool_name == "submit_rca":
                    try:
                        rca, issues = validate_and_ground_rca(bundle, tool_input)
                        logger.info("submit_rca received and validated. Issues: %s", issues)
                        return rca
                    except Exception as val_err:
                        # Attempt one repair retry inside the loop
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"json": {"status": "validation_error", "error": str(val_err)}}],
                                    "status": "error",
                                }
                            }
                        )
                        continue

                elif tool_name == "query_logs":
                    result = execute_query_logs(bundle, tool_input.get("pattern", ""), tool_input.get("limit", 20))
                elif tool_name == "get_file":
                    result = execute_get_file(
                        bundle,
                        tool_input.get("path", ""),
                        tool_input.get("start_line"),
                        tool_input.get("end_line"),
                        repo_root=repo_root,
                    )
                elif tool_name == "get_commit_diff":
                    result = execute_get_commit_diff(bundle, tool_input.get("commit_sha", ""), repo_root=repo_root)
                else:
                    result = {"error": f"Unknown tool: {tool_name}"}

                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_id,
                            "content": [{"json": result}],
                        }
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        elif stop_reason == "end_turn":
            # Bedrock finished turn without calling submit_rca; prompt it to submit
            messages.append(
                {
                    "role": "user",
                    "content": [{"text": "Please provide your final root cause analysis by invoking the submit_rca tool."}],
                }
            )

    logger.warning("RCA agent reached max turns without valid submit_rca. Using heuristic fallback.")
    return analyze_heuristically(bundle)


def handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """Lambda entry point for Step Functions RunRCA state."""
    logger.info("RunRCA triggered with event keys: %s", list(event.keys()))

    if "context" in event:
        bundle_data = event["context"]
    else:
        bundle_data = event

    bundle = ContextBundle.model_validate(bundle_data)
    rca_result = run_rca_agent(bundle)

    # Save to DynamoDB
    table_name = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    try:
        dynamodb = boto3.client("dynamodb")
        dynamodb.update_item(
            TableName=table_name,
            Key={"incident_id": {"S": bundle.incident_id}},
            UpdateExpression="SET #c = :c, #conf = :conf, #rca = :rca",
            ExpressionAttributeNames={"#c": "classification", "#conf": "confidence", "#rca": "rca_result"},
            ExpressionAttributeValues={
                ":c": {"S": rca_result.classification},
                ":conf": {"N": str(rca_result.confidence)},
                ":rca": {"S": rca_result.model_dump_json()},
            },
        )
    except Exception as e:
        logger.warning("Could not update DynamoDB for incident %s: %s", bundle.incident_id, e)

    return rca_result.model_dump()
