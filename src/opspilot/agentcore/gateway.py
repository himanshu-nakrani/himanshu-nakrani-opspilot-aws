"""Amazon Bedrock AgentCore Gateway primitive for OpsPilot.

Provides Model Context Protocol (MCP) compatibility and a secure tool gateway
that decouples underlying tools (CloudWatch Logs, CodeCommit/Git, OpsCenter, Sandbox)
from foundation models, validating schemas and enforcing AgentCore Policies.
"""

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from strands import tool

from opspilot.contracts import ContextBundle
from opspilot.agentcore.memory import AgentCoreMemory
from opspilot.agentcore.policy import AgentCorePolicy
from opspilot.knowledge.retrieve import retrieve_knowledge as search_knowledge
from opspilot.rca.tools import (
    RCA_SCHEMA,
    execute_get_commit_diff,
    execute_get_file,
    execute_query_logs,
)

logger = logging.getLogger(__name__)


class AgentCoreGateway:
    """Bedrock AgentCore Gateway managing tool discovery, MCP schemas, and execution."""

    def __init__(self, policy: Optional[AgentCorePolicy] = None):
        self.policy = policy or AgentCorePolicy()
        self.registry: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default tools for incident investigation and remediation."""
        self.register_tool(
            name="retrieve_knowledge",
            description="Search the knowledge base of merged fixes, notes, and documentation. Results are background and must not be cited as evidence.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up in past incidents and docs"},
                },
                "required": ["query"],
            },
            handler=self._handle_retrieve_knowledge,
        )

        self.register_tool(
            name="query_logs",
            description="Query or filter recent application logs for specific search terms or error patterns.",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern or keyword to match"},
                    "limit": {"type": "integer", "description": "Max matching lines to return (default 20)"},
                },
                "required": ["pattern"],
            },
            handler=self._handle_query_logs,
        )

        self.register_tool(
            name="get_file",
            description="Read file contents from the target service repository around specific lines.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository-relative file path"},
                    "start_line": {"type": "integer", "description": "First line to read (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Last line to read (inclusive)"},
                },
                "required": ["path"],
            },
            handler=self._handle_get_file,
        )

        self.register_tool(
            name="get_commit_diff",
            description="Get git diff and metadata for a specific commit hash.",
            input_schema={
                "type": "object",
                "properties": {
                    "commit_sha": {"type": "string", "description": "Git commit SHA to inspect"},
                },
                "required": ["commit_sha"],
            },
            handler=self._handle_get_commit_diff,
        )

        self.register_tool(
            name="submit_rca",
            description="Submit final Root Cause Analysis result matching the RcaResult schema with evidence grounding.",
            input_schema=RCA_SCHEMA,
            handler=self._handle_submit_rca,
        )

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool with its MCP/Bedrock input schema and execution handler."""
        self.registry[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
            "handler": handler,
        }

    def get_tool_specs(self) -> List[Dict[str, Any]]:
        """Return tool specifications in Bedrock Converse / MCP compatible format."""
        specs = []
        for entry in self.registry.values():
            specs.append(
                {
                    "toolSpec": {
                        "name": entry["name"],
                        "description": entry["description"],
                        "inputSchema": {
                            "json": entry["input_schema"],
                        },
                    }
                }
            )
        return specs

    # Handlers for core tools
    def _handle_retrieve_knowledge(self, bundle: ContextBundle, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        return search_knowledge(
            str(args.get("query", "")),
            knowledge_base_id=os.environ.get("KNOWLEDGE_BASE_ID", ""),
        )

    def _handle_query_logs(self, bundle: ContextBundle, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        pattern = args.get("pattern", "")
        limit = int(args.get("limit", 20))
        return execute_query_logs(bundle, pattern=pattern, limit=limit)

    def _handle_get_file(self, bundle: ContextBundle, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        path = args.get("path", "")
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        repo_root = kwargs.get("repo_root")
        return execute_get_file(bundle, path=path, start_line=start_line, end_line=end_line, repo_root=repo_root)

    def _handle_get_commit_diff(self, bundle: ContextBundle, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        commit_sha = args.get("commit_sha", "")
        repo_root = kwargs.get("repo_root")
        return execute_get_commit_diff(bundle, commit_sha=commit_sha, repo_root=repo_root)

    def _handle_submit_rca(
        self,
        bundle: ContextBundle,
        args: Dict[str, Any],
        memory: Optional[AgentCoreMemory] = None,
        policy: Optional[AgentCorePolicy] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        from pydantic import ValidationError

        from opspilot.rca.grounding import ground_rca

        if memory and memory.submitted_rca:
            return {"status": "rejected", "error": "submit_rca was already called; the first submission is final."}
        try:
            rca_result, issues = ground_rca(bundle, args)
        except ValidationError as e:
            # Not recorded: the model may fix the payload and call submit_rca again.
            return {"status": "validation_error", "error": str(e)[:1500]}
        if issues:
            (policy or self.policy).log_violation("evidence_grounding", "Ungrounded RCA; abstained", {"issues": issues})

        if memory:
            memory.record_submitted_rca(rca_result)

        return {
            "status": "accepted",
            "incident_id": rca_result.incident_id,
            "classification": rca_result.classification,
            "confidence": rca_result.confidence,
            "grounding_issues": issues,
            "summary": rca_result.summary,
            "rca_result": rca_result.model_dump(),
        }

    def execute_tool(
        self,
        name: str,
        args: Dict[str, Any],
        bundle: ContextBundle,
        memory: Optional[AgentCoreMemory] = None,
        policy: Optional[AgentCorePolicy] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute tool through gateway with timing, memory logging, and policy boundaries."""
        if name not in self.registry:
            raise KeyError(f"Tool '{name}' not found in AgentCore Gateway registry.")

        entry = self.registry[name]
        budget = kwargs.pop("max_tool_calls", None)
        if budget is not None and memory is not None and name != "submit_rca":
            if len(memory.tool_invocation_history) >= budget:
                return {"error": f"Tool budget of {budget} calls exhausted. Call submit_rca now."}
        start_t = time.perf_counter()
        status = "success"
        try:
            result = entry["handler"](bundle=bundle, args=args, memory=memory, policy=policy, **kwargs)
            return result
        except Exception as e:
            status = f"error: {str(e)}"
            logger.error("Error executing tool '%s': %s", name, e)
            raise
        finally:
            latency_ms = (time.perf_counter() - start_t) * 1000
            if memory:
                memory.record_tool_call(name, args, result if status == "success" else str(status), latency_ms, status)

    def as_strands_tools(
        self,
        bundle: ContextBundle,
        memory: Optional[AgentCoreMemory] = None,
        policy: Optional[AgentCorePolicy] = None,
        repo_root: Optional[str] = None,
        max_tool_calls: Optional[int] = None,
    ) -> List[Any]:
        """Generate AWS Strands @tool decorated callables bound to the current context."""
        gateway = self
        active_policy = policy or self.policy

        @tool
        def retrieve_knowledge(query: str) -> str:
            """Search merged fixes, notes, and documentation. Results are background, not evidence.

            Args:
                query: What to look up in past incidents and docs
            """
            res = gateway.execute_tool(
                "retrieve_knowledge",
                {"query": query},
                bundle,
                memory,
                active_policy,
                repo_root=repo_root,
                max_tool_calls=max_tool_calls,
            )
            return json.dumps(res)

        @tool
        def query_logs(pattern: str, limit: int = 20) -> str:
            """Query or filter recent application logs for specific search terms or error patterns.

            Args:
                pattern: Keyword or substring to find in logs
                limit: Maximum matching lines to return (default 20)
            """
            res = gateway.execute_tool("query_logs", {"pattern": pattern, "limit": limit}, bundle, memory, active_policy, repo_root=repo_root, max_tool_calls=max_tool_calls)
            return json.dumps(res)

        @tool
        def get_file(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
            """Read file contents from the target service repository around specific lines.

            Args:
                path: Repository-relative file path
                start_line: First line to read (1-indexed)
                end_line: Last line to read (inclusive)
            """
            res = gateway.execute_tool("get_file", {"path": path, "start_line": start_line, "end_line": end_line}, bundle, memory, active_policy, repo_root=repo_root, max_tool_calls=max_tool_calls)
            return json.dumps(res)

        @tool
        def get_commit_diff(commit_sha: str) -> str:
            """Get git diff and metadata for a specific commit hash.

            Args:
                commit_sha: The commit SHA to inspect
            """
            res = gateway.execute_tool("get_commit_diff", {"commit_sha": commit_sha}, bundle, memory, active_policy, repo_root=repo_root, max_tool_calls=max_tool_calls)
            return json.dumps(res)

        @tool
        def submit_rca(
            incident_id: str,
            classification: str,
            severity: str,
            confidence: float,
            summary: str,
            evidence: List[Dict[str, Any]],
            suggested_fix_strategy: str,
            suspected_location: Optional[Dict[str, Any]] = None,
            ruled_out: Optional[List[str]] = None,
        ) -> str:
            """Submit the final Root Cause Analysis result with grounded evidence.

            Args:
                incident_id: The identifier of the incident
                classification: Issue classification (code_defect, config_regression, dependency, resource, insufficient_evidence)
                severity: Severity rating (sev1, sev2, sev3, sev4)
                confidence: Confidence score between 0.0 and 1.0
                summary: Concise technical explanation of root cause
                evidence: Array of evidence items with kind, ref, and claim
                suggested_fix_strategy: High-level remediation strategy
                suspected_location: Suspected file, line, function, and commit
                ruled_out: List of issue types ruled out during investigation
            """
            submission = {
                "incident_id": incident_id,
                "classification": classification,
                "severity": severity,
                "confidence": confidence,
                "summary": summary,
                "evidence": evidence,
                "suggested_fix_strategy": suggested_fix_strategy,
                "suspected_location": suspected_location,
                "ruled_out": ruled_out or [],
            }
            res = gateway.execute_tool("submit_rca", submission, bundle, memory, active_policy, repo_root=repo_root, max_tool_calls=max_tool_calls)
            return json.dumps(res)

        return [retrieve_knowledge, query_logs, get_file, get_commit_diff, submit_rca]
