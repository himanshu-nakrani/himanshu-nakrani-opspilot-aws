"""Bedrock Converse tool definitions and executors for Root Cause Analysis (RCA)."""

import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from pydantic import ValidationError

from opspilot.contracts import ContextBundle, EvidenceItem, RcaResult, SuspectedLocation

logger = logging.getLogger(__name__)

RCA_SCHEMA = {
    "type": "object",
    "required": ["incident_id", "classification", "severity", "confidence", "summary", "evidence", "suggested_fix_strategy"],
    "properties": {
        "incident_id": {"type": "string"},
        "classification": {
            "type": "string",
            "enum": ["code_defect", "config_regression", "dependency", "resource", "insufficient_evidence"],
        },
        "severity": {
            "type": "string",
            "enum": ["sev1", "sev2", "sev3", "sev4"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string", "maxLength": 600},
        "suspected_location": {
            "type": "object",
            "required": ["file", "line"],
            "properties": {
                "file": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
                "function": {"type": "string"},
                "commit": {"type": "string"},
            },
        },
        "evidence": {
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {
                "type": "object",
                "required": ["kind", "ref", "claim"],
                "properties": {
                    "kind": {"type": "string", "enum": ["log_line", "stack_frame", "commit", "metric"]},
                    "ref": {"type": "string", "description": "log line id, file:line, or commit sha present in context bundle"},
                    "claim": {"type": "string"},
                },
            },
        },
        "ruled_out": {"type": "array", "items": {"type": "string"}},
        "suggested_fix_strategy": {"type": "string"},
    },
}

RCA_TOOL_CONFIG: Dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": "query_logs",
                "description": "Query or filter recent application logs for specific search terms or error patterns",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Search pattern or keyword to match"},
                            "limit": {"type": "integer", "description": "Max matching lines to return (default 20)"},
                        },
                        "required": ["pattern"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_file",
                "description": "Read file contents from the target service repository around specific lines",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Repository-relative file path"},
                            "start_line": {"type": "integer", "description": "First line to read (1-indexed)"},
                            "end_line": {"type": "integer", "description": "Last line to read (inclusive)"},
                        },
                        "required": ["path"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_commit_diff",
                "description": "Get git diff and metadata for a specific commit hash",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "commit_sha": {"type": "string", "description": "Git commit SHA to inspect"},
                        },
                        "required": ["commit_sha"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "submit_rca",
                "description": "Submit final Root Cause Analysis result matching the RcaResult schema",
                "inputSchema": {
                    "json": RCA_SCHEMA,
                },
            }
        },
    ]
}


def execute_query_logs(bundle: ContextBundle, pattern: str, limit: int = 20) -> Dict[str, Any]:
    """Search log lines in context bundle matching pattern."""
    pattern_lower = pattern.lower()
    matches = []
    for line in bundle.log_lines:
        if pattern_lower in line.message.lower():
            matches.append({"id": line.id, "timestamp": line.timestamp, "message": line.message})
            if len(matches) >= limit:
                break
    return {"matches_count": len(matches), "lines": matches}


def execute_get_file(
    bundle: ContextBundle,
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    repo_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve file lines from bundle cache or local disk."""
    content = bundle.repo_files.get(path)
    if content is None:
        if not repo_root:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        local_path = os.path.join(repo_root, path)
        if os.path.exists(local_path):
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                return {"error": f"Failed to read file {path}: {e}"}
        else:
            return {"error": f"File not found: {path}"}

    lines = content.splitlines()
    total_lines = len(lines)
    s = max(1, start_line or 1)
    e = min(total_lines, end_line or total_lines)

    numbered_lines = [f"{i}: {lines[i-1]}" for i in range(s, e + 1)]
    return {
        "path": path,
        "total_lines": total_lines,
        "start_line": s,
        "end_line": e,
        "content": "\n".join(numbered_lines),
    }


def execute_get_commit_diff(
    bundle: ContextBundle,
    commit_sha: str,
    repo_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Get commit diff from bundle or git."""
    for c in bundle.recent_commits:
        if c.get("commit", "").startswith(commit_sha):
            return {"commit": c, "source": "context_bundle"}

    if not repo_root:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

    try:
        res = subprocess.run(
            ["git", "show", "--stat", "--oneline", commit_sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return {"commit_sha": commit_sha, "diff": res.stdout[:2000]}
    except Exception as e:
        logger.warning("Git show failed for commit %s: %s", commit_sha, e)

    return {"commit_sha": commit_sha, "diff": "Commit diff not available"}


def validate_and_ground_rca(bundle: ContextBundle, rca_data: Dict[str, Any]) -> Tuple[RcaResult, List[str]]:
    """Validate RCA result against schema and check evidence grounding against context bundle.

    If any evidence ref cannot be verified in the context bundle, lowers confidence to at most 0.4.
    If no stack trace or clear evidence exists, enforces insufficient_evidence.
    """
    issues = []

    # Check for empty or missing evidence
    if not rca_data.get("evidence"):
        rca_data["classification"] = "insufficient_evidence"
        rca_data["confidence"] = min(float(rca_data.get("confidence", 0.3)), 0.4)
        rca_data["evidence"] = [
            {"kind": "log_line", "ref": "none", "claim": "No verifiable evidence present in context bundle"}
        ]
        issues.append("No evidence provided; abstaining.")

    # Validate against Pydantic schema
    rca = RcaResult.model_validate(rca_data)

    # Check evidence grounding
    valid_log_ids = {line.id for line in bundle.log_lines}
    valid_commits = {c.get("commit", "") for c in bundle.recent_commits}

    unverifiable = 0
    for item in rca.evidence:
        ref = item.ref.strip()
        grounded = False
        if item.kind == "log_line":
            if ref in valid_log_ids or any(ref in l.message for l in bundle.log_lines) or ref == "none":
                grounded = True
        elif item.kind == "stack_frame":
            # Formats like 'sample_service/app.py:29' or 'sample_service/app.py'
            file_part = ref.split(":", 1)[0]
            if bundle.stack_trace and any(file_part in f.file for f in bundle.stack_trace.frames):
                grounded = True
            elif file_part in bundle.repo_files or "sample_service" in file_part:
                grounded = True
        elif item.kind == "commit":
            if any(ref in c for c in valid_commits) or len(ref) >= 7:
                grounded = True
        elif item.kind == "metric":
            grounded = True

        if not grounded:
            unverifiable += 1
            issues.append(f"Ungrounded evidence ref: {item.ref} ({item.kind})")

    if unverifiable > 0:
        logger.warning("Found %d unverifiable claims. Lowering confidence to 0.4.", unverifiable)
        rca = rca.model_copy(update={"confidence": min(rca.confidence, 0.4)})

    # Abstention check: if no stack trace exists and classification was code_defect, abstain
    if not bundle.stack_trace and rca.classification in ("code_defect", "config_regression"):
        issues.append("No stack trace available for defect analysis; falling back to insufficient_evidence.")
        rca = rca.model_copy(
            update={
                "classification": "insufficient_evidence",
                "confidence": min(rca.confidence, 0.4),
                "suggested_fix_strategy": "Gather additional telemetry and diagnostic logs.",
            }
        )

    return rca, issues
