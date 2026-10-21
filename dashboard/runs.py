"""Agent run records for the dashboard.

Turns an AgentCore session (Strands event-loop trace + gateway tool history + policy audit)
into a JSON-safe run record with a flat span list the frontend renders as a waterfall.
Nothing here is invented: every span, timing and token count comes from the session.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

MAX_PAYLOAD_CHARS = 4000

# Models that do not call Bedrock. Their token counts and latencies are fixed stand-ins.
OFFLINE_MODELS = {"AgentCoreOfflineModel"}


def _clip(value: Any) -> Any:
    """Keep payloads small and JSON-safe."""
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, default=str, indent=2)
    if len(text) > MAX_PAYLOAD_CHARS:
        return text[:MAX_PAYLOAD_CHARS] + f"\n… ({len(text) - MAX_PAYLOAD_CHARS} more chars)"
    return text


def _message_text(message: Dict[str, Any]) -> Optional[str]:
    """Summarise a Strands message: text blocks plus any tool-use requests."""
    parts: List[str] = []
    for block in (message or {}).get("content") or []:
        if not isinstance(block, dict):
            continue
        if "text" in block and block["text"]:
            parts.append(str(block["text"]))
        if "toolUse" in block:
            tu = block["toolUse"] or {}
            parts.append(f"→ {tu.get('name')}({json.dumps(tu.get('input'), default=str)})")
    return "\n".join(parts) or None


def _tool_result(message: Dict[str, Any]) -> Dict[str, Any]:
    for block in (message or {}).get("content") or []:
        if isinstance(block, dict) and "toolResult" in block:
            return block["toolResult"] or {}
    return {}


def _kind(name: str) -> str:
    if name.startswith("Cycle"):
        return "cycle"
    if name == "stream_messages":
        return "model"
    if name.startswith("Tool:"):
        return "tool"
    return "step"


def build_spans(traces: List[Dict[str, Any]], tool_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten Strands traces into spans with offsets (ms) from the first span start."""
    starts = [t.get("start_time") for t in traces if t.get("start_time") is not None]
    t0 = min(starts) if starts else None
    # Gateway records each tool call (input/output/status) in call order; pair them with tool spans.
    history = list(tool_history or [])
    spans: List[Dict[str, Any]] = []

    def walk(node: Dict[str, Any], parent: Optional[str], depth: int) -> None:
        name = str(node.get("name") or "span")
        kind = _kind(name)
        start, end = node.get("start_time"), node.get("end_time")
        span_id = str(node.get("id") or f"s{len(spans)}")
        span: Dict[str, Any] = {
            "id": span_id,
            "parent_id": parent,
            "depth": depth,
            "kind": kind,
            "name": name,
            "start_ms": round((start - t0) * 1000, 2) if (start is not None and t0 is not None) else None,
            "duration_ms": round(node["duration"] * 1000, 2) if node.get("duration") is not None else None,
            "status": "ok",
            "input": None,
            "output": None,
            "input_tokens": None,
            "output_tokens": None,
            "model_latency_ms": None,
        }
        if start is not None and end is None:
            span["status"] = "incomplete"
        message = node.get("message") or {}
        meta = node.get("metadata") or {}
        if kind == "model":
            usage = ((message.get("metadata") or {}).get("usage")) or {}
            metrics = ((message.get("metadata") or {}).get("metrics")) or {}
            span["input_tokens"] = usage.get("inputTokens")
            span["output_tokens"] = usage.get("outputTokens")
            span["model_latency_ms"] = metrics.get("latencyMs")
            span["output"] = _clip(_message_text(message))
            span["name"] = "Model call"
        elif kind == "tool":
            tool_name = meta.get("tool_name") or name.removeprefix("Tool:").strip()
            span["name"] = tool_name
            result = _tool_result(message)
            if result.get("status") == "error":
                span["status"] = "error"
            rec = None
            for i, h in enumerate(history):
                if h.get("tool_name") == tool_name:
                    rec = history.pop(i)
                    break
            if rec is not None:
                span["input"] = _clip(rec.get("input"))
                span["output"] = _clip(rec.get("output"))
                if rec.get("status") not in (None, "success", "ok"):
                    span["status"] = "error" if span["status"] == "ok" else span["status"]
                    span["policy_status"] = rec.get("status")
            elif result:
                span["output"] = _clip(_message_text(result) or result.get("content"))
        spans.append(span)
        for child in node.get("children") or []:
            walk(child, span_id, depth + 1)

    for trace in traces:
        walk(trace, None, 0)
    return spans


def build_agent_run(session: Dict[str, Any], *, route: Optional[str] = None, classification: Optional[str] = None,
                    confidence: Optional[float] = None) -> Dict[str, Any]:
    """Build the run record from AgentCoreSession.to_dict()."""
    metrics = session.get("agent_metrics") or {}
    memory = session.get("memory") or {}
    tool_history = memory.get("tool_history") or []
    spans = build_spans(metrics.get("traces") or [], tool_history)
    usage = metrics.get("accumulated_usage") or {}
    model_name = session.get("model_name")
    if session.get("error"):
        status = "failed"
    elif not memory.get("submitted_rca"):
        status = "no_rca_submitted"
    else:
        status = "completed"
    return {
        "run_id": session.get("session_id"),
        "incident_id": session.get("incident_id"),
        "started_at": session.get("started_at"),
        "duration_ms": round(float(session.get("duration_ms") or 0), 2),
        "status": status,
        "error": session.get("error"),
        "model": model_name,
        "offline_model": model_name in OFFLINE_MODELS,
        "cycles": metrics.get("total_cycles"),
        "tool_calls": len(tool_history),
        "input_tokens": usage.get("inputTokens"),
        "output_tokens": usage.get("outputTokens"),
        "total_tokens": usage.get("totalTokens"),
        "policy_violations": int(session.get("policy_violations") or 0),
        "policy_audit": [_clip(a) if not isinstance(a, dict) else {k: _clip(v) for k, v in a.items()}
                         for a in (session.get("policy_audit") or [])],
        "route": route,
        "classification": classification,
        "confidence": confidence,
        "spans": spans,
    }


def summarize(run: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in run.items() if k not in ("spans", "policy_audit")}
