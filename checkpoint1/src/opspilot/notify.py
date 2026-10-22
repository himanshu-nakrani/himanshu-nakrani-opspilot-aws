"""Notification service for OpsPilot using Slack Block Kit and AWS SNS."""

import json
import logging
import os
from typing import Any, Dict, List, Optional
import boto3
import httpx

from opspilot.audit import append_timeline, update_incident
from opspilot.config import is_live
from opspilot.contracts import PrRef, RcaResult, TicketRef, VerificationResult
from opspilot.fix.agent import suggested_diff
from opspilot.route import route_rca

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

    # Links: OpsCenter OpsItem and PR
    link_parts = []
    if ticket:
        link_parts.append(f"🎫 *OpsCenter:* <{ticket.url}|{ticket.key}>")
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


def sync_ticket_status(
    ticket: Optional[TicketRef],
    final_status: str,
    pr: Optional[PrRef],
    verify: Optional[VerificationResult],
    error: Optional[str],
    ssm_client=None,
) -> "tuple[Optional[str], bool]":
    """Mirror the run outcome onto the OpsCenter OpsItem. Best effort: never blocks the notification.

    Verified fix PR -> InProgress (human review/merge pending). Everything else stays Open with the
    reason recorded. OpsPilot never sets Resolved; the on-call engineer does after merge/mitigation.

    The current status is read first: OpsPilot only moves a ticket that is still ``Open``. If a human
    already changed it (InProgress, Resolved, ...) during the run, that status is kept and only the
    run outcome is recorded. If the read fails, the status is left untouched (fail safe).
    """
    if not ticket or ticket.provider != "opscenter":
        return None, False
    from opspilot.ticketing import get_status, update_ticket  # local import: notify works without ssm

    if final_status == "VERIFIED":
        status, note = "InProgress", "OpsPilot fix PR verified; awaiting human review and merge."
    elif final_status == "NEEDS_HUMAN":
        status, note = "Open", "Automated fix not verified; needs human."
    elif final_status == "FAILED":
        status, note = "Open", f"OpsPilot pipeline error: {(error or '')[:500]}"
    elif final_status == "AWAITING_CHOICE":
        status, note = "Open", "RCA delivered. Open the incident to apply the change yourself or raise a pull request."
    else:
        status, note = "Open", "RCA delivered; no automated fix proposed. On-call action required."
    extra = {"run_status": final_status, "verdict": verify.verdict if verify else "unverified",
             "pr_url": pr.pr_url if pr and pr.pr_url else ""}
    try:
        current = get_status(ticket, ssm_client=ssm_client)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read OpsItem %s, leaving its status unchanged: %s", ticket.key, e)
        current = None
    if current != "Open":
        # Human-owned (or unknown) status: record the outcome, do not move the ticket.
        extra["proposed_status"] = status
        status = None
    try:
        update_ticket(ticket, status, note, extra=extra, ssm_client=ssm_client)
        return (status or current or ticket.status or "Open"), True
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not update OpsItem %s: %s", ticket.key, e)
        return ticket.status or "Open", False


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

    error = event.get("error")
    error_str = str(error) if error else None

    # Construct messages
    blocks = build_slack_blocks(rca, ticket, pr, verify, error=error_str)
    slack_sent = send_slack_notification(blocks)

    subject = f"[OpsPilot] Alert: {rca.classification if rca else 'Incident'}"
    summary_text = rca.summary if rca else "OpsPilot pipeline completed."
    sns_sent = send_sns_notification(subject, summary_text)

    incident_id = (rca.incident_id if rca else None) or event.get("incident_id", "unknown")
    if not (slack_sent or sns_sent) and is_live():
        raise RuntimeError("No notification channel delivered the message")
    offered_diff = suggested_diff(rca) if rca and pr is None and route_rca(rca) == "propose_fix" else None
    if error_str:
        final_status = "FAILED"
    elif verify and verify.verdict == "verified":
        final_status = "VERIFIED"
    elif pr and pr.status == "needs_human":
        final_status = "NEEDS_HUMAN"
    elif pr and pr.pr_url:
        final_status = "PR_OPENED"
    elif offered_diff:
        final_status = "AWAITING_CHOICE"
    else:
        final_status = "NOTIFIED"
    ticket_status, ticket_synced = sync_ticket_status(ticket, final_status, pr, verify, error_str)
    fields: Dict[str, str] = {"status": final_status, "verdict": verify.verdict if verify else "unverified"}
    if offered_diff and final_status == "AWAITING_CHOICE":
        fields["patch_diff"] = offered_diff
    if ticket_status:
        fields["ticket_status"] = ticket_status
    update_incident(incident_id, fields)
    append_timeline(incident_id, final_status,
                    f"ticket {ticket.key} -> {ticket_status}" if ticket and ticket_synced else
                    (f"ticket {ticket.key} status sync failed" if ticket else "no ticket"))

    return {
        "status": "notified",
        "slack_sent": slack_sent,
        "sns_sent": sns_sent,
        "incident_id": incident_id,
        "verdict": verify.verdict if verify else "unverified",
        "ticket_status": ticket_status,
        "ticket_synced": ticket_synced,
    }
