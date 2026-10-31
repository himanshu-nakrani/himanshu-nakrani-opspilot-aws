"""AWS Strands Agents SDK implementation for OpsPilot Root Cause Analysis (RCA).

Uses AWS's open-source `strands-agents` framework (`from strands import Agent, tool`)
orchestrated by Amazon Bedrock AgentCore Runtime.
"""

import logging
from typing import Optional

from strands import Agent

from opspilot.contracts import ContextBundle, RcaResult
from opspilot.agentcore.runtime import AgentCoreRuntime, AgentCoreSession

logger = logging.getLogger(__name__)


def create_strands_rca_agent(
    bundle: ContextBundle,
    session: Optional[AgentCoreSession] = None,
    runtime: Optional[AgentCoreRuntime] = None,
    model_id: Optional[str] = None,
    system_prompt: Optional[str] = None,
    repo_root: Optional[str] = None,
    bedrock_client=None,
) -> Agent:
    """Instantiate a configured Strands Agent for RCA investigation."""
    rt = runtime or AgentCoreRuntime()
    sess = session or rt.create_session(incident_id=bundle.incident_id, bundle=bundle)
    return rt.build_strands_agent(
        session=sess,
        bundle=bundle,
        model_id=model_id,
        system_prompt=system_prompt,
        repo_root=repo_root,
        bedrock_client=bedrock_client,
    )


def run_strands_rca(
    bundle: ContextBundle,
    runtime: Optional[AgentCoreRuntime] = None,
    model_id: Optional[str] = None,
    max_turns: int = 6,
    repo_root: Optional[str] = None,
    bedrock_client=None,
) -> RcaResult:
    """Execute RCA investigation using AWS Strands Agent on Bedrock AgentCore Runtime."""
    rt = runtime or AgentCoreRuntime()
    rca_result, session = rt.execute_rca(
        bundle=bundle,
        model_id=model_id,
        max_turns=max_turns,
        repo_root=repo_root,
        bedrock_client=bedrock_client,
    )
    return rca_result
