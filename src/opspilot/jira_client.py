"""Jira REST API v3 client for OpsPilot.

Creates idempotent Jira issues with Atlassian Document Format (ADF) descriptions,
severity-to-priority mapping, and labels for auditability and tracking.
"""

import json
import logging
import os
from typing import Any, Dict, Optional
import boto3
import httpx

from opspilot.audit import update_incident
from opspilot.contracts import RcaResult, TicketRef

logger = logging.getLogger(__name__)


class JiraError(RuntimeError):
    """A Jira API call did not succeed."""
logger.setLevel(logging.INFO)

SEVERITY_TO_PRIORITY = {
    "sev1": "Highest",
    "sev2": "High",
    "sev3": "Medium",
    "sev4": "Low",
}


def build_adf_description(rca: RcaResult) -> Dict[str, Any]:
    """Build Atlassian Document Format (ADF) description for Jira REST v3."""
    content: list[dict] = [
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "OpsPilot Root Cause Analysis"}],
        },
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": f"Incident ID: {rca.incident_id}\n"},
                {"type": "text", "text": f"Classification: {rca.classification}\n"},
                {"type": "text", "text": f"Severity: {rca.severity.upper()}\n"},
                {"type": "text", "text": f"Confidence: {int(rca.confidence * 100)}%\n"},
            ],
        },
        {
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": "Summary"}],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": rca.summary}],
        },
    ]

    if rca.suspected_location:
        loc = rca.suspected_location
        loc_str = f"{loc.file}:{loc.line}" + (f" in {loc.function}()" if loc.function else "")
        content.extend(
            [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "Suspected Location"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": loc_str}],
                },
            ]
        )

    # Evidence bullet points
    if rca.evidence:
        content.append(
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Grounded Evidence"}],
            }
        )
        bullet_items = []
        for ev in rca.evidence:
            bullet_items.append(
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": f"[{ev.kind}] {ev.ref}: ", "marks": [{"type": "strong"}]},
                                {"type": "text", "text": ev.claim},
                            ],
                        }
                    ],
                }
            )
        content.append({"type": "bulletList", "content": bullet_items})

    # Strategy
    content.extend(
        [
            {
                "type": "heading",
                "attrs": {"level": 3},
                "content": [{"type": "text", "text": "Suggested Fix Strategy"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": rca.suggested_fix_strategy}],
            },
        ]
    )

    return {"version": 1, "type": "doc", "content": content}


def get_jira_credentials() -> tuple[str, str, str, str]:
    """Retrieve Jira credentials from environment or Secrets Manager."""
    base_url = os.environ.get("JIRA_BASE_URL", "https://example.atlassian.net").rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "opspilot@example.com")
    project_key = os.environ.get("JIRA_PROJECT_KEY", "OPS")
    api_token = os.environ.get("JIRA_API_TOKEN", "")

    secret_arn = os.environ.get("JIRA_SECRET_ARN")
    if secret_arn and not api_token:
        try:
            sm = boto3.client("secretsmanager")
            val = sm.get_secret_value(SecretId=secret_arn)
            secret_str = val.get("SecretString", "")
            if secret_str.startswith("{"):
                data = json.loads(secret_str)
                api_token = data.get("api_token") or data.get("token", "")
                email = data.get("email", email)
                base_url = data.get("base_url", base_url).rstrip("/")
            else:
                api_token = secret_str
        except Exception as e:
            logger.warning("Could not read Jira secret %s: %s", secret_arn, e)

    if not api_token:
        api_token = "mock-jira-token"

    return base_url, email, project_key, api_token


def search_existing_ticket(
    client: httpx.Client,
    base_url: str,
    project_key: str,
    incident_id: str,
    auth: tuple[str, str],
) -> Optional[TicketRef]:
    """Idempotency check: search Jira for an issue labeled inc:<incident_id>."""
    jql = f'project = "{project_key}" AND labels = "inc:{incident_id}"'
    search_url = f"{base_url}/rest/api/3/search"
    try:
        resp = client.get(search_url, params={"jql": jql, "maxResults": 1}, auth=auth, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            issues = data.get("issues", [])
            if issues:
                key = issues[0]["key"]
                logger.info("Found existing Jira ticket %s for incident %s", key, incident_id)
                return TicketRef(
                    key=key,
                    url=f"{base_url}/browse/{key}",
                    incident_id=incident_id,
                )
    except Exception as e:
        logger.warning("Failed to search existing Jira issues: %s", e)
    return None


def create_issue(
    rca: RcaResult,
    http_client: Optional[httpx.Client] = None,
) -> TicketRef:
    """Create or retrieve existing Jira issue for the incident."""
    base_url, email, project_key, api_token = get_jira_credentials()
    auth = (email, api_token)

    def _do_call(client: httpx.Client) -> TicketRef:
        # 1. Idempotency check: see if issue already exists
        existing = search_existing_ticket(client, base_url, project_key, rca.incident_id, auth)
        if existing:
            return existing

        # 2. Create new issue
        summary = f"[OpsPilot] {rca.classification}: {rca.summary[:80]}"
        adf_desc = build_adf_description(rca)
        priority_name = SEVERITY_TO_PRIORITY.get(rca.severity, "Medium")

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "description": adf_desc,
                "issuetype": {"name": "Bug"},
                "priority": {"name": priority_name},
                "labels": ["opspilot", f"cls:{rca.classification}", f"inc:{rca.incident_id}"],
            }
        }

        create_url = f"{base_url}/rest/api/3/issue"
        resp = client.post(create_url, json=payload, auth=auth, timeout=10.0)
        if resp.status_code in (200, 201):
            key = resp.json().get("key")
            if not key:
                raise JiraError("Jira create issue returned no key")
            logger.info("Created Jira issue %s for incident %s", key, rca.incident_id)
            return TicketRef(key=key, url=f"{base_url}/browse/{key}", incident_id=rca.incident_id)
        else:
            logger.error("Jira create issue returned %s: %s", resp.status_code, resp.text[:300])
            raise JiraError(f"Jira create issue failed: HTTP {resp.status_code}")

    if http_client:
        return _do_call(http_client)
    with httpx.Client() as client:
        return _do_call(client)


def handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """Lambda entry point for Step Functions CreateTicket state."""
    logger.info("CreateTicket invoked with event keys: %s", list(event.keys()))

    if "rca" in event:
        rca_data = event["rca"]
    else:
        rca_data = event

    rca = RcaResult.model_validate(rca_data)
    ticket_ref = create_issue(rca)

    update_incident(rca.incident_id, {"ticket_key": ticket_ref.key, "ticket_url": ticket_ref.url, "status": "TICKETED"})

    return ticket_ref.model_dump()
