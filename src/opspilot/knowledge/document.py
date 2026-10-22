"""The knowledge-base document shown on the incident page and stored after merge."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from opspilot.redact import redact_text

_HTTP_PR_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def _pull_request_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not _HTTP_PR_URL.match(url):
        return None
    return url


def _safe_id(incident_id: str) -> str:
    cleaned = _SAFE_ID.sub("-", incident_id).strip("-")
    return cleaned or "incident"


def _location(incident: Dict[str, Any]) -> str:
    loc = incident.get("suspected_location") or {}
    if not isinstance(loc, dict) or not loc.get("file") or not loc.get("line"):
        return "No source location recorded."
    function = loc.get("function") or ""
    text = f"{loc['file']}:{loc['line']}"
    return f"{text} {function}".rstrip()


def _evidence(incident: Dict[str, Any]) -> str:
    lines = []
    for item in incident.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('kind', '')} {item.get('ref', '')}: {item.get('claim', '')}".rstrip())
    return "\n".join(lines) if lines else "No evidence items recorded."


def build_document(incident: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Markdown that will be ingested. None until the incident has a pull request URL."""
    url = _pull_request_url(incident.get("pr_url"))
    if url is None:
        return None
    incident_id = str(incident.get("incident_id") or "incident")
    summary = str(incident.get("summary") or incident_id)
    body = redact_text(
        "\n".join(
            [
                f"# {summary}",
                "",
                f"- Incident: {incident_id}",
                f"- Service: {incident.get('service') or ''}",
                f"- Classification: {incident.get('classification') or ''}",
                f"- Pull request: {url}",
                f"- Branch: {incident.get('pr_branch') or ''}",
                "",
                "## Summary",
                summary,
                "",
                "## Evidence",
                _evidence(incident),
                "",
                "## Location",
                _location(incident),
                "",
                "## Suggested fix",
                str(incident.get("suggested_fix_strategy") or "No fix recorded."),
                "",
                "## Patch",
                str(incident.get("patch_diff") or "No patch recorded."),
                "",
            ]
        )
    )
    return {
        "title": redact_text(summary)[:120],
        "body": body,
        "s3_key": f"solutions/{_safe_id(incident_id)}.md",
    }


def public_knowledge(incident: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Preview payload for the incident page. Status comes from a previous merge ingest."""
    document = build_document(incident)
    if document is None:
        return None
    status = incident.get("knowledge_status") or "waiting"
    if status not in {"waiting", "ingested", "failed"}:
        status = "waiting"
    error = incident.get("knowledge_error") or None
    if status != "failed":
        error = None
    return {**document, "status": status, "error": error}
