"""Notification service for OpsPilot using Slack Block Kit and AWS SNS."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
import boto3
import httpx

from opspilot.contracts import PrRef, RcaResult, TicketRef, VerificationResult

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def build_slack_blocks(
    rca: Optional[RcaResult],
    ticket: Optional[TicketRef],
    pr: Optional[PrRef],
    verify: Optional[VerificationResult],
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct Slack Block Kit message structure."""
    blocks: List[Dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 OpsPilot Incident Report",
                "emoji": True,
            },
        }
    ]

    # Status summary
    if rca:
        cls_emoji = "🐛" if rca.classification == "code_defect" else "⚙️"
        fields = [
            {"type": "mrkdwn", "text": f"*Incident ID:*\n`{rca.incident_id}`"},
            {"type": "mrkdwn", "text": f"*Classification:*\n{cls_emoji} `{rca.classification}`"},
            {"type": "mrkdwn", "text": f"*Severity:*\n`{rca.severity.upper()}`"},
            {"type": "mrkdwn", "text": f"*Confidence:*\n`{int(rca.confidence * 100)}%`"},
        ]
        blocks.append({"type": "section", "fields": fields})

        # Summary & location
        loc_str = ""
        if rca.suspected_location:
            loc = rca.suspected_location
            loc_str = f"\n*Location:* `{loc.file}:{loc.line}`" + (f" in `{loc.function}()`" if loc.function else "")

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Summary:*\n{rca.summary}{loc_str}",
                },
            }
        )

        # Evidence
        if rca.evidence:
            ev_lines = "\n".join([f"• *[{ev.kind}]* `{ev.ref}`: {ev.claim}" for ev in rca.evidence[:5]])
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Key Evidence:*\n{ev_lines}",
                    },
                }
            )

    # Links: Jira and PR
    link_parts = []
    if ticket:
        link_parts.append(f"🎫 *Jira:* <{ticket.url}|{ticket.key}>")
    if pr and pr.pr_url:
        link_parts.append(f"🐙 *GitHub PR:* <{pr.pr_url}|{pr.branch}>")
    if link_parts:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": " | ".join(link_parts)},
            }
        )

    # Verification verdict
    if verify:
        v_icon = "✅" if verify.verdict == "verified" else "❌"
        v_text = (
            f"*Verification Verdict:* {v_icon} `{verify.verdict.upper()}`\n"
            f"• Reproduction failed on main: `{'PASSED' if verify.repro_fails_on_base else 'FAILED'}`\n"
            f"• Test suite passed on fix branch: `{'PASSED' if verify.suite_passes_on_fix else 'FAILED'}`"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": v_text}})

    # Warning for human intervention
    is_needs_human = False
    if pr and (pr.status == "needs_human" or getattr(pr, "status", "") == "draft"):
        is_needs_human = True
    if error or (verify and verify.verdict == "failed"):
        is_needs_human = True

    if is_needs_human:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "⚠️ *Action Required:* Automated verification failed or exceeded retry limit. PR has been labeled `needs-human`. Manual review is required.",
                },
            }
        )
    elif pr and pr.pr_url:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "🤖 *generated — requires human review before merge*"}
                ],
            }
        )

    return {"blocks": blocks}


def get_slack_webhook_url() -> Optional[str]:
    """Retrieve Slack webhook URL from environment or Secrets Manager."""
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if url:
        return url

    secret_arn = os.environ.get("SLACK_SECRET_ARN")
    if secret_arn:
        try:
            sm = boto3.client("secretsmanager")
            val = sm.get_secret_value(SecretId=secret_arn)
            secret_str = val.get("SecretString", "")
            if secret_str.startswith("{"):
                url = json.loads(secret_str).get("webhook_url", "")
            else:
                url = secret_str
            return url
        except Exception as e:
            logger.warning("Could not load Slack secret %s: %s", secret_arn, e)
    return None


def send_slack_notification(
    blocks_payload: Dict[str, Any],
    webhook_url: Optional[str] = None,
    http_client: Optional[httpx.Client] = None,
) -> bool:
    """Post Block Kit message to Slack webhook."""
    url = webhook_url or get_slack_webhook_url()
    if not url:
        logger.info("No Slack webhook URL configured, skipping Slack notification.")
        return False

    def _post(client: httpx.Client) -> bool:
        try:
            resp = client.post(url, json=blocks_payload, timeout=10.0)
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Failed to send Slack notification: %s", e)
            return False

    if http_client:
        return _post(http_client)
    with httpx.Client() as client:
        return _post(client)


def send_sns_notification(
    subject: str,
    message: str,
    topic_arn: Optional[str] = None,
    sns_client=None,
) -> bool:
    """Publish notification to SNS topic."""
    arn = topic_arn or os.environ.get("SNS_TOPIC_ARN")
    if not arn:
        logger.info("No SNS topic ARN configured, skipping SNS publication.")
        return False

    client = sns_client or boto3.client("sns")
    try:
        client.publish(
            TopicArn=arn,
            Subject=subject[:100],
            Message=message,
        )
        return True
    except Exception as e:
        logger.warning("Failed to publish to SNS topic %s: %s", arn, e)
        return False


def handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """Lambda entry point for Step Functions Notify state."""
    logger.info("Notify state invoked with event keys: %s", list(event.keys()))

    rca = None
    if "rca" in event:
        try:
            rca = RcaResult.model_validate(event["rca"])
        except Exception:
            pass

    ticket = None
    if "ticket" in event:
        try:
            ticket = TicketRef.model_validate(event["ticket"])
        except Exception:
            pass

    pr = None
    if "pr" in event:
        try:
            pr = PrRef.model_validate(event["pr"])
        except Exception:
            pass

    verify = None
    if "verify" in event:
        try:
            verify = VerificationResult.model_validate(event["verify"])
        except Exception:
            pass

    error = event.get("error") or event.get("verify_error")
    error_str = str(error) if error else None

    # Construct messages
    blocks = build_slack_blocks(rca, ticket, pr, verify, error=error_str)
    slack_sent = send_slack_notification(blocks)

    subject = f"[OpsPilot] Alert: {rca.classification if rca else 'Incident'}"
    summary_text = rca.summary if rca else "OpsPilot pipeline completed."
    sns_sent = send_sns_notification(subject, summary_text)

    # Save final notification status in DynamoDB
    incident_id = (rca.incident_id if rca else None) or event.get("incident_id", "unknown")
    table_name = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    try:
        dynamodb = boto3.client("dynamodb")
        dynamodb.update_item(
            TableName=table_name,
            Key={"incident_id": {"S": incident_id}},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": {"S": "NOTIFIED"}},
        )
    except Exception as e:
        logger.warning("Could not update DynamoDB for incident %s: %s", incident_id, e)

    return {
        "status": "notified",
        "slack_sent": slack_sent,
        "sns_sent": sns_sent,
        "incident_id": incident_id,
        "verdict": verify.verdict if verify else "unverified",
    }
