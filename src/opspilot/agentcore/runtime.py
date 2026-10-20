"""Amazon Bedrock AgentCore Runtime for OpsPilot.

Provides serverless session lifecycle management, tool-agent orchestration,
CloudWatch EMF telemetry, and seamless coordination with the AWS Strands Agents SDK.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import boto3
from strands import Agent
from strands.models import Model
from strands.models.bedrock import BedrockModel

from opspilot.contracts import ContextBundle, EvidenceItem, RcaResult, SuspectedLocation
from opspilot.agentcore.gateway import AgentCoreGateway
from opspilot.agentcore.memory import AgentCoreMemory
from opspilot.agentcore.policy import AgentCorePolicy
from opspilot.rca.grounding import abstain, ground_rca
from opspilot.rca.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)

AGENTCORE_SYSTEM_PROMPT = SYSTEM_PROMPT  # single shared prompt (opspilot.rca.prompts)


class AgentCoreSession:
    """Encapsulates an active incident investigation session inside AgentCore Runtime."""

    def __init__(
        self,
        incident_id: str,
        bundle: Optional[ContextBundle] = None,
        policy: Optional[AgentCorePolicy] = None,
        gateway: Optional[AgentCoreGateway] = None,
        session_id: Optional[str] = None,
    ):
        self.session_id = session_id or str(uuid.uuid4())
        self.incident_id = incident_id
        self.bundle = bundle
        self.policy = policy or AgentCorePolicy()
        self.gateway = gateway or AgentCoreGateway(policy=self.policy)
        self.memory = AgentCoreMemory(incident_id=incident_id, session_id=self.session_id)
        if bundle:
            self.memory.context_bundle = bundle
        self.start_time = time.perf_counter()
        self.end_time: Optional[float] = None

    def close(self) -> float:
        """Mark session complete and return total elapsed duration in milliseconds."""
        self.end_time = time.perf_counter()
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session state and telemetry."""
        duration_ms = ((self.end_time or time.perf_counter()) - self.start_time) * 1000
        return {
            "session_id": self.session_id,
            "incident_id": self.incident_id,
            "duration_ms": duration_ms,
            "memory": self.memory.to_dict(),
            "policy_violations": len(self.policy.audit_log),
            "policy_audit": self.policy.audit_log,
        }


class AgentCoreOfflineModel(Model):
    """Deterministic, grounding-aware Strands Model for offline testing and eval replay.

    Simulates authentic multi-turn Bedrock Converse streaming:
    Turn 1: Inspects logs via query_logs or code via get_file.
    Turn 2: Submits structured findings via submit_rca with grounded evidence.
    Turn 3: Completes turn with technical summary.
    """

    def __init__(self, bundle: ContextBundle):
        super().__init__()
        self.bundle = bundle
        self.turn = 0
        self._converter = BedrockModel(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0", region_name="us-east-1")

    def update_config(self, **kwargs):
        pass

    def get_config(self):
        return {"model_id": "agentcore-offline-model"}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.turn += 1
        bundle = self.bundle
        st = bundle.stack_trace
        log_refs = [l.id for l in bundle.log_lines]
        primary_log = log_refs[0] if log_refs else "none"

        if self.turn == 1:
            # Turn 1: Call query_logs tool
            search_pattern = st.error_type if st and st.error_type else "error"
            resp = {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": f"call_turn1_{uuid.uuid4().hex[:6]}",
                                    "name": "query_logs",
                                    "input": {"pattern": search_pattern, "limit": 10},
                                }
                            }
                        ],
                    }
                },
                "stopReason": "tool_use",
                "usage": {"inputTokens": 180, "outputTokens": 25, "totalTokens": 205},
                "metrics": {"latencyMs": 40},
            }
        elif self.turn == 2:
            # Turn 2: Submit structured RCA via submit_rca tool
            full_log = " ".join(l.message for l in bundle.log_lines).lower()

            if not st or not st.frames:
                # Check for resource or dependency or config
                if "connection pool" in full_log or "out of memory" in full_log or "oom" in full_log or "killed" in full_log or "memory" in full_log:
                    rca_payload = {
                        "incident_id": bundle.incident_id,
                        "classification": "resource",
                        "severity": "sev1",
                        "confidence": 0.85,
                        "summary": "Resource exhaustion detected (memory or connection pool limit reached).",
                        "evidence": [{"kind": "log_line", "ref": primary_log, "claim": "Resource limit error in logs"}],
                        "suggested_fix_strategy": "Increase resource limits or tune pool concurrency.",
                    }
                elif "timeout" in full_log or "gateway" in full_log or "503" in full_log:
                    rca_payload = {
                        "incident_id": bundle.incident_id,
                        "classification": "dependency",
                        "severity": "sev2",
                        "confidence": 0.85,
                        "summary": "Downstream dependency failure or network timeout detected in logs.",
                        "evidence": [{"kind": "log_line", "ref": primary_log, "claim": "Timeout log message detected"}],
                        "suggested_fix_strategy": "Implement retry policy with exponential backoff and circuit breaker.",
                    }
                elif "config" in full_log or "env" in full_log or "invalid port" in full_log:
                    rca_payload = {
                        "incident_id": bundle.incident_id,
                        "classification": "config_regression",
                        "severity": "sev2",
                        "confidence": 0.85,
                        "summary": "Configuration regression or invalid environment variable setting.",
                        "evidence": [{"kind": "log_line", "ref": primary_log, "claim": "Configuration error detected"}],
                        "suggested_fix_strategy": "Revert recent configuration change or set required environment variable.",
                    }
                else:
                    rca_payload = {
                        "incident_id": bundle.incident_id,
                        "classification": "insufficient_evidence",
                        "severity": "sev4",
                        "confidence": 0.30,
                        "summary": "Insufficient evidence: logs do not contain an unhandled error or stack trace.",
                        "evidence": [{"kind": "log_line", "ref": primary_log, "claim": "No fatal error or stack trace found"}],
                        "suggested_fix_strategy": "Gather additional telemetry and diagnostic logs.",
                    }
            else:
                top_frame = st.top_frame or st.frames[-1]
                rca_payload = {
                    "incident_id": bundle.incident_id,
                    "classification": "code_defect",
                    "severity": "sev2",
                    "confidence": 0.92,
                    "summary": f"Unhandled {st.error_type} in {top_frame.file}:{top_frame.line} in {top_frame.function}(): {st.error_message}.",
                    "suspected_location": {
                        "file": top_frame.file,
                        "line": top_frame.line,
                        "function": top_frame.function,
                    },
                    "evidence": [
                        {"kind": "log_line", "ref": primary_log, "claim": f"{st.error_type} traceback observed in logs"},
                        {"kind": "stack_frame", "ref": f"{top_frame.file}:{top_frame.line}", "claim": f"Exception in {top_frame.function}"},
                    ],
                    "ruled_out": ["dependency", "resource"],
                    "suggested_fix_strategy": "Add validation for missing order ID and return HTTP 404 HTTPException if not found.",
                }

            resp = {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": f"call_turn2_{uuid.uuid4().hex[:6]}",
                                    "name": "submit_rca",
                                    "input": rca_payload,
                                }
                            }
                        ],
                    }
                },
                "stopReason": "tool_use",
                "usage": {"inputTokens": 320, "outputTokens": 80, "totalTokens": 400},
                "metrics": {"latencyMs": 60},
            }
        else:
            # Turn 3: Complete turn
            resp = {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "Root Cause Analysis successfully submitted to Bedrock AgentCore Runtime."}],
                    }
                },
                "stopReason": "end_turn",
                "usage": {"inputTokens": 420, "outputTokens": 20, "totalTokens": 440},
                "metrics": {"latencyMs": 20},
            }

        for ev in self._converter.convert_non_streaming_to_streaming(resp):
            yield ev

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        pass


class AgentCoreRuntime:
    """Amazon Bedrock AgentCore Runtime execution engine."""

    def __init__(self, default_model_id: Optional[str] = None, region_name: Optional[str] = None):
        from opspilot.rca.agent import resolve_model_id

        self.default_model_id = resolve_model_id(default_model_id)
        self.region_name = region_name or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

    def create_session(
        self,
        incident_id: str,
        bundle: Optional[ContextBundle] = None,
        policy: Optional[AgentCorePolicy] = None,
    ) -> AgentCoreSession:
        """Create a new isolated execution session."""
        return AgentCoreSession(incident_id=incident_id, bundle=bundle, policy=policy)

    def build_strands_agent(
        self,
        session: AgentCoreSession,
        bundle: ContextBundle,
        model_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        repo_root: Optional[str] = None,
        bedrock_client=None,
        max_tool_calls: Optional[int] = None,
    ) -> Agent:
        """Instantiate an AWS Strands Agent wired to AgentCore Gateway and Policy."""
        tools = session.gateway.as_strands_tools(
            bundle=bundle,
            memory=session.memory,
            policy=session.policy,
            repo_root=repo_root,
            max_tool_calls=max_tool_calls,
        )

        sys_prompt = system_prompt or AGENTCORE_SYSTEM_PROMPT
        chosen_model_id = model_id or self.default_model_id

        # Determine whether to use live Bedrock or AgentCoreOfflineModel
        from opspilot.rca.agent import _live_aws_enabled

        if isinstance(bedrock_client, Model):
            model = bedrock_client  # injected Strands model (tests, alternative providers)
        elif bedrock_client is not None or _live_aws_enabled():
            model = BedrockModel(
                model_id=chosen_model_id,
                boto_session=boto3.Session(region_name=self.region_name),
                temperature=0.0,
            )
        else:
            model = AgentCoreOfflineModel(bundle=bundle)

        agent = Agent(
            model=model,
            tools=tools,
            system_prompt=sys_prompt,
            name=f"OpsPilot-RCA-{bundle.incident_id}",
            description="Autonomous SRE RCA Agent powered by AWS Strands and Amazon Bedrock AgentCore",
        )
        return agent

    def execute_rca(
        self,
        bundle: ContextBundle,
        model_id: Optional[str] = None,
        max_turns: int = 6,
        repo_root: Optional[str] = None,
        bedrock_client=None,
    ) -> Tuple[RcaResult, AgentCoreSession]:
        """Execute full Root Cause Analysis workflow using Strands Agent on AgentCore Runtime."""
        session = self.create_session(incident_id=bundle.incident_id, bundle=bundle)
        agent = self.build_strands_agent(
            session=session,
            bundle=bundle,
            model_id=model_id,
            repo_root=repo_root,
            bedrock_client=bedrock_client,
            max_tool_calls=max_turns,
        )

        prompt = build_user_prompt(bundle)
        try:
            agent_result = agent(prompt)
            duration_ms = session.close()
            logger.info("AgentCore session %s completed in %.1f ms", session.session_id, duration_ms)
        except Exception as e:
            session.close()
            logger.error("Agent execution error for %s: %s", bundle.incident_id, e)
            rca_result = abstain(bundle, f"RCA agent failed ({type(e).__name__}); no analysis was produced.")
            self.emit_cloudwatch_metrics(session, rca_result)
            return rca_result, session

        # Retrieve submitted RCA from session memory
        if session.memory.submitted_rca:
            # Already grounded by the gateway; re-check so nothing unvalidated reaches the router.
            try:
                rca_result, _ = ground_rca(bundle, session.memory.submitted_rca)
            except Exception as e:  # defensive: contract drift
                rca_result = abstain(bundle, f"Submitted RCA failed validation ({type(e).__name__}).")
        else:
            rca_result = abstain(bundle, "RCA agent finished without calling submit_rca.")

        self.emit_cloudwatch_metrics(session, rca_result)
        return rca_result, session

    def emit_cloudwatch_metrics(
        self,
        session: AgentCoreSession,
        rca_result: Optional[RcaResult] = None,
    ) -> Dict[str, Any]:
        """Emit CloudWatch EMF (Embedded Metric Format) telemetry for Bedrock AgentCore."""
        duration_ms = ((session.end_time or time.perf_counter()) - session.start_time) * 1000
        emf_payload = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "OpsPilot/AgentCore",
                        "Dimensions": [["Service", "Classification"]],
                        "Metrics": [
                            {"Name": "ExecutionDurationMs", "Unit": "Milliseconds"},
                            {"Name": "ToolInvocations", "Unit": "Count"},
                            {"Name": "PolicyViolations", "Unit": "Count"},
                            {"Name": "ConfidenceScore", "Unit": "None"},
                        ],
                    }
                ],
            },
            "Service": session.bundle.service if session.bundle else "opspilot",
            "Classification": rca_result.classification if rca_result else "unknown",
            "IncidentId": session.incident_id,
            "SessionId": session.session_id,
            "ExecutionDurationMs": duration_ms,
            "ToolInvocations": len(session.memory.tool_invocation_history),
            "PolicyViolations": len(session.policy.audit_log),
            "ConfidenceScore": rca_result.confidence if rca_result else 0.0,
        }

        # Print EMF JSON string to stdout for CloudWatch Logs agent extraction
        logger.info("CloudWatch EMF Metric: %s", json.dumps(emf_payload))
        return emf_payload
