"""RCA Agent using AWS Bedrock Converse API with tool-use loop and structured output."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError

from opspilot.contracts import ContextBundle, EvidenceItem, IncidentEvent, RcaResult, SuspectedLocation
from pydantic import ValidationError

from opspilot.rca.grounding import abstain
from opspilot.rca.prompts import SYSTEM_PROMPT, build_user_prompt
from opspilot.rca.strands_agent import run_strands_rca
from opspilot.rca.tools import (
    RCA_TOOL_CONFIG,
    execute_get_commit_diff,
    execute_get_file,
    execute_query_logs,
    validate_and_ground_rca,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-5-5"


def resolve_model_id(model_id: Optional[str] = None) -> str:
    """Model comes from the caller or BEDROCK_MODEL_ID; the default is only a placeholder."""
    return model_id or os.environ.get("BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID


def _live_aws_enabled() -> bool:
    key = os.environ.get("AWS_ACCESS_KEY_ID")
    return bool(os.environ.get("OPSPILOT_LIVE") == "1" or (key and key != "testing"))


def analyze_heuristically(bundle: ContextBundle) -> RcaResult:
    """Offline-only keyword heuristic for local demos without AWS credentials.

    It is never used as a fallback for a failed live run (a failed run abstains instead),
    and its confidence is capped below the routing threshold so it can never open a PR.
    """
    st = bundle.stack_trace
    log_refs = [l.id for l in bundle.log_lines]
    primary_log_ref = log_refs[0] if log_refs else "none"

    if not st or not st.frames:
        # Check logs for known failure keywords
        full_log = " ".join(l.message for l in bundle.log_lines).lower()
        if "connection pool" in full_log or "out of memory" in full_log or "oom" in full_log or "killed" in full_log:
            return RcaResult(
                incident_id=bundle.incident_id,
                classification="resource",
                severity="sev1",
                confidence=0.5,
                summary="Resource exhaustion detected (memory or database connection pool limit reached).",
                evidence=[EvidenceItem(kind="log_line", ref=primary_log_ref, claim="Resource limit error in logs")],
                suggested_fix_strategy="Increase resource limits or tune pool size and concurrency.",
            )
        elif "timeout" in full_log or "gateway" in full_log or "503" in full_log:
            return RcaResult(
                incident_id=bundle.incident_id,
                classification="dependency",
                severity="sev2",
                confidence=0.5,
                summary="Downstream service failure or network timeout detected in logs.",
                evidence=[EvidenceItem(kind="log_line", ref=primary_log_ref, claim="Timeout / 503 log message detected")],
                suggested_fix_strategy="Implement retry policy with exponential backoff and circuit breaker.",
            )
        elif "config" in full_log or "env" in full_log or "invalid port" in full_log:
            return RcaResult(
                incident_id=bundle.incident_id,
                classification="config_regression",
                severity="sev2",
                confidence=0.5,
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
        f"{st.error_message}. Offline heuristic only; not reviewed by a model."
    )
    if len(summary) > 600:
        summary = summary[:597] + "..."

    return RcaResult(
        incident_id=bundle.incident_id,
        classification="code_defect",
        severity="sev2",
        # Below the 0.6 routing threshold: a keyword heuristic must never open a PR.
        confidence=0.5,
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
        suggested_fix_strategy=f"Inspect {top_frame.function}() at {ref_location} for the unhandled {st.error_type}.",
    )


def run_rca_agent(
    bundle: ContextBundle,
    bedrock_client=None,
    model_id: Optional[str] = None,
    max_turns: int = 6,
    repo_root: Optional[str] = None,
    use_strands: bool = True,
) -> RcaResult:
    """Run Bedrock Converse tool-use loop or AWS Strands + AgentCore Runtime."""
    model_id = resolve_model_id(model_id)
    if os.environ.get("OPSPILOT_AGENT_BACKEND", "").lower() == "converse":
        use_strands = False

    # If explicit bedrock_client passed (e.g. mock in unit tests), use Converse loop
    if bedrock_client is not None:
        client = bedrock_client
    elif use_strands:
        return run_strands_rca(
            bundle=bundle,
            model_id=model_id,
            max_turns=max_turns,
            repo_root=repo_root,
        )
    else:
        if not _live_aws_enabled():
            return analyze_heuristically(bundle)
        client = boto3.client("bedrock-runtime")

    messages = [{"role": "user", "content": [{"text": build_user_prompt(bundle)}]}]
    repair_attempts = 0

    for turn in range(max_turns):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=messages,
                system=[{"text": SYSTEM_PROMPT}],
                toolConfig=RCA_TOOL_CONFIG,
            )
        except Exception as e:
            logger.error("Bedrock converse call failed on turn %d: %s. Abstaining.", turn, e)
            return abstain(bundle, f"RCA model call failed ({type(e).__name__}); no analysis was produced.")

        stop_reason = resp.get("stopReason")
        output_msg = (resp.get("output") or {}).get("message") or {}
        if not output_msg.get("content"):
            logger.error("Bedrock returned no message content (stopReason=%s). Abstaining.", stop_reason)
            return abstain(bundle, f"RCA model returned an empty response (stopReason={stop_reason}).")
        messages.append(output_msg)

        if stop_reason == "tool_use":
            tool_requests = [c["toolUse"] for c in output_msg.get("content", []) if "toolUse" in c]
            tool_results = []

            for req in tool_requests:
                tool_id = req["toolUseId"]
                tool_name = req["name"]
                tool_input = req.get("input", {})

                if tool_name == "submit_rca":
                    if not isinstance(tool_input, dict):
                        tool_input = {}
                    try:
                        rca, issues = validate_and_ground_rca(bundle, tool_input)
                        logger.info("submit_rca received and validated. Issues: %s", issues)
                        return rca
                    except ValidationError as val_err:
                        repair_attempts += 1
                        if repair_attempts > 1:
                            return abstain(bundle, "RCA model output did not match the RcaResult contract after one repair attempt.")
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

                if not isinstance(tool_input, dict):
                    result = {"error": "tool input must be a JSON object"}
                elif tool_name == "query_logs":
                    result = execute_query_logs(bundle, str(tool_input.get("pattern", "")), min(int(tool_input.get("limit", 20) or 20), 50))
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

        elif stop_reason in ("max_tokens", "guardrail_intervened", "content_filtered"):
            logger.error("Bedrock stopped with %s before submit_rca. Abstaining.", stop_reason)
            return abstain(bundle, f"RCA model stopped early ({stop_reason}) without submitting a result.")
        elif stop_reason == "end_turn":
            # Bedrock finished turn without calling submit_rca; prompt it to submit
            messages.append(
                {
                    "role": "user",
                    "content": [{"text": "Please provide your final root cause analysis by invoking the submit_rca tool."}],
                }
            )

    logger.warning("RCA agent reached max turns (%d) without a valid submit_rca. Abstaining.", max_turns)
    return abstain(bundle, f"RCA model did not submit a result within {max_turns} turns.")


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
