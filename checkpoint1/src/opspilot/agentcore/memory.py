"""Amazon Bedrock AgentCore Memory primitive for OpsPilot.

Maintains context, session history, working hypotheses, tool execution trails,
and cross-turn state across multi-turn agent interactions.
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from opspilot.contracts import ContextBundle, RcaResult


class AgentCoreMemory:
    """Manages working memory and audit trails for an AgentCore session."""

    def __init__(self, incident_id: str, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.incident_id = incident_id
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.notes: List[str] = []
        self.ruled_out_hypotheses: List[str] = []
        self.tool_invocation_history: List[Dict[str, Any]] = []
        self.submitted_rca: Optional[Dict[str, Any]] = None
        self.context_bundle: Optional[ContextBundle] = None
        self.metadata: Dict[str, Any] = {}
        self.tokens_used: int = 0

    def record_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
        latency_ms: float = 0.0,
        status: str = "success",
    ) -> None:
        """Record a tool execution into working memory."""
        self.tool_invocation_history.append(
            {
                "tool_name": tool_name,
                "input": tool_input,
                "output": tool_output,
                "latency_ms": latency_ms,
                "status": status,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    def add_note(self, note: str) -> None:
        """Add an investigation note into memory."""
        self.notes.append(note)

    def rule_out(self, hypothesis: str) -> None:
        """Mark an issue classification or hypothesis as ruled out."""
        if hypothesis not in self.ruled_out_hypotheses:
            self.ruled_out_hypotheses.append(hypothesis)

    def record_submitted_rca(self, rca: RcaResult | Dict[str, Any]) -> None:
        """Store the final structured RCA result."""
        if isinstance(rca, RcaResult):
            self.submitted_rca = rca.model_dump()
        else:
            self.submitted_rca = rca

    def increment_tokens(self, tokens: int) -> None:
        """Track model token usage."""
        self.tokens_used += tokens

    def to_dict(self) -> Dict[str, Any]:
        """Serialize memory state to dictionary."""
        return {
            "session_id": self.session_id,
            "incident_id": self.incident_id,
            "created_at": self.created_at,
            "notes": self.notes,
            "ruled_out_hypotheses": self.ruled_out_hypotheses,
            "tool_invocations_count": len(self.tool_invocation_history),
            "tool_history": self.tool_invocation_history,
            "has_rca": self.submitted_rca is not None,
            "submitted_rca": self.submitted_rca,
            "tokens_used": self.tokens_used,
            "metadata": self.metadata,
        }
