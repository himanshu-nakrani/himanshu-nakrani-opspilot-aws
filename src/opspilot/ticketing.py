"""Native AWS ticketing for OpsPilot: AWS Systems Manager OpsCenter + DynamoDB.

Every incident gets exactly one OpsCenter OpsItem, created with the Lambda's IAM
role (no external accounts, tokens or secrets). The OpsItem carries the RCA as
Markdown, an OpsCenter severity/priority mapped from the RCA severity, and
searchable operational data (``opspilot:incident_id``) that makes creation
idempotent. The incidents DynamoDB table mirrors the ticket id, URL, severity,
priority and status and keeps an append-only timeline, so the dashboard can
track tickets without calling SSM.

Why OpsCenter and not Incident Manager: AWS stopped accepting new Incident
Manager customers on 2025-11-07 and points to OpsCenter as the alternative, so a
fresh hackathon account cannot rely on Incident Manager.

Status lifecycle (OpsCenter statuses are Open / InProgress / Resolved):
  CreateTicket                       -> Open
  Notify, fix PR verified            -> InProgress (a human still reviews and merges)
  Notify, needs human / failed / no PR -> stays Open, with the reason recorded
A person sets Resolved after merging or mitigating; OpsPilot never auto-resolves.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

import boto3

from opspilot.audit import append_timeline, update_incident
from opspilot.config import is_live
from opspilot.contracts import RcaResult, TicketRef

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

PROVIDER = "opscenter"
INCIDENT_KEY = "opspilot:incident_id"  # keys must not start with aws/ssm/amazon/amzn
DESCRIPTION_MAX = 2048  # CreateOpsItem Description limit
TITLE_MAX = 1024

# OpsCenter severity is a string "1".."4" (Critical/High/Medium/Low); priority is 1..5.
SEVERITY_TO_OPSCENTER = {"sev1": "1", "sev2": "2", "sev3": "3", "sev4": "4"}
SEVERITY_TO_PRIORITY = {"sev1": 1, "sev2": 2, "sev3": 3, "sev4": 4}
CLASSIFICATION_TO_CATEGORY = {
    "code_defect": "Availability",
    "config_regression": "Availability",
    "dependency": "Availability",
    "resource": "Performance",
    "insufficient_evidence": "Availability",
}
VALID_STATUSES = ("Open", "InProgress", "Resolved")


class TicketingError(RuntimeError):
    """An OpsCenter call did not succeed."""


def _region(ssm_client=None) -> str:
    if ssm_client is not None and getattr(getattr(ssm_client, "meta", None), "region_name", None):
        return ssm_client.meta.region_name
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def opsitem_url(ops_item_id: str, region: str) -> str:
    return (
        f"https://{region}.console.aws.amazon.com/systems-manager/opsitems/{ops_item_id}"
        f"?region={region}"
    )


def build_description(rca: RcaResult) -> str:
    """Markdown description, truncated to the 2048-char OpsCenter limit."""
    lines = [
        "## OpsPilot root cause analysis",
        f"- **Incident ID:** `{rca.incident_id}`",
        f"- **Classification:** `{rca.classification}`",
        f"- **Severity:** {rca.severity.upper()}",
        f"- **Confidence:** {int(rca.confidence * 100)}%",
    ]
    if rca.suspected_location:
        loc = rca.suspected_location
        where = f"{loc.file}:{loc.line}" + (f" in {loc.function}()" if loc.function else "")
        lines.append(f"- **Suspected location:** `{where}`")
    lines += ["", "### Summary", rca.summary, "", "### Suggested fix strategy", rca.suggested_fix_strategy]
    if rca.evidence:
        lines += ["", "### Grounded evidence"]
        lines += [f"- [{ev.kind}] `{ev.ref}`: {ev.claim}" for ev in rca.evidence]
    text = "\n".join(lines)
    if len(text) > DESCRIPTION_MAX:
        suffix = "\n\n_(truncated; full RCA in operational data `opspilot:rca`)_"
        text = text[: DESCRIPTION_MAX - len(suffix)] + suffix
    return text


RCA_DATA_MAX = 20000  # OperationalData value limit


def _bounded_rca_json(rca: RcaResult, limit: int = RCA_DATA_MAX) -> str:
    """Serialize the RCA so it is always valid JSON within ``limit`` characters.

    Free-text fields are shortened before serializing (never the serialized string), and trailing
    evidence items are dropped if needed. ``_truncated`` is set when anything was cut.
    """
    full = rca.model_dump_json()
    if len(full) <= limit:
        return full
    data = json.loads(full)
    data["_truncated"] = True
    for budget in (4000, 1500, 500, 200):
        for key in ("summary", "suggested_fix_strategy"):
            if isinstance(data.get(key), str) and len(data[key]) > budget:
                data[key] = data[key][: budget - 1] + "…"
        for ev in data.get("evidence") or []:
            for key in ("claim", "ref"):
                if isinstance(ev.get(key), str) and len(ev[key]) > budget // 4:
                    ev[key] = ev[key][: budget // 4 - 1] + "…"
        out = json.dumps(data, ensure_ascii=False)
        if len(out) <= limit:
            return out
    while data.get("evidence") and len(json.dumps(data, ensure_ascii=False)) > limit:
        data["evidence"].pop()
    out = json.dumps(data, ensure_ascii=False)
    if len(out) > limit:  # pathological: keep only the identifying fields
        out = json.dumps({k: data.get(k) for k in ("incident_id", "classification", "severity",
                                                      "confidence", "_truncated")})
    return out


def _operational_data(rca: RcaResult, incident: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    data = {
        INCIDENT_KEY: {"Value": rca.incident_id, "Type": "SearchableString"},
        "opspilot:classification": {"Value": rca.classification, "Type": "SearchableString"},
        "opspilot:severity": {"Value": rca.severity, "Type": "SearchableString"},
        "opspilot:confidence": {"Value": f"{rca.confidence:.2f}", "Type": "String"},
        # RCA JSON, shortened field-by-field to stay valid JSON under the 20 KB value limit.
        "opspilot:rca": {"Value": _bounded_rca_json(rca), "Type": "String"},
    }
    for field in ("service", "alarm_name", "log_group", "detected_at"):
        value = (incident or {}).get(field)
        if value:
            data[f"opspilot:{field}"] = {"Value": str(value), "Type": "SearchableString"}
    return data


def find_existing(incident_id: str, ssm_client) -> Optional[str]:
    """Return the OpsItem id already filed for this incident, if any."""
    resp = ssm_client.describe_ops_items(
        OpsItemFilters=[
            {
                "Key": "OperationalData",
                "Operator": "Equal",
                "Values": [json.dumps({"key": INCIDENT_KEY, "value": incident_id})],
            }
        ],
        MaxResults=1,
    )
    items = resp.get("OpsItemSummaries", [])
    return items[0]["OpsItemId"] if items else None


def _ticket_from_dynamodb(incident_id: str, dynamodb_client) -> Optional[str]:
    """First idempotency layer: the incident record already holds an OpsItem id."""
    table = os.environ.get("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    try:
        item = dynamodb_client.get_item(
            TableName=table, Key={"incident_id": {"S": incident_id}}, ConsistentRead=True
        ).get("Item", {})
    except Exception as e:  # noqa: BLE001 - the SSM search below is the authoritative fallback
        logger.warning("Could not read incident %s for ticket reuse: %s", incident_id, e)
        return None
    if item.get("ticket_provider", {}).get("S") == PROVIDER:
        return item.get("ticket_key", {}).get("S") or None
    return None


def create_ticket(
    rca: RcaResult,
    incident: Optional[Dict[str, Any]] = None,
    ssm_client=None,
    dynamodb_client=None,
) -> TicketRef:
    """Create (or reuse) the OpsItem for this incident. Raises TicketingError on failure."""
    ssm = ssm_client or boto3.client("ssm")
    region = _region(ssm)
    severity = SEVERITY_TO_OPSCENTER.get(rca.severity, "3")
    priority = SEVERITY_TO_PRIORITY.get(rca.severity, 3)

    def ref(ops_item_id: str, status: str = "Open") -> TicketRef:
        return TicketRef(
            key=ops_item_id,
            url=opsitem_url(ops_item_id, region),
            incident_id=rca.incident_id,
            provider=PROVIDER,
            status=status,
            severity=severity,
            priority=priority,
        )

    existing = None
    if dynamodb_client is not None or is_live():
        existing = _ticket_from_dynamodb(rca.incident_id, dynamodb_client or boto3.client("dynamodb"))
    try:
        existing = existing or find_existing(rca.incident_id, ssm)
    except Exception as e:  # noqa: BLE001
        raise TicketingError(f"OpsCenter search failed: {e}") from e
    if existing:
        logger.info("Reusing OpsItem %s for incident %s", existing, rca.incident_id)
        return ref(existing)

    title = f"[OpsPilot] {rca.classification}: {rca.summary}"[:TITLE_MAX]
    kwargs: Dict[str, Any] = dict(
        Title=title,
        Description=build_description(rca),
        Source=os.environ.get("OPSCENTER_SOURCE", "OpsPilot"),
        Category=CLASSIFICATION_TO_CATEGORY.get(rca.classification, "Availability"),
        Severity=severity,
        Priority=priority,
        OperationalData=_operational_data(rca, incident),
    )
    topic = os.environ.get("OPSCENTER_SNS_TOPIC_ARN")
    if topic:  # optional: OpsCenter emails/notifies on every OpsItem change
        kwargs["Notifications"] = [{"Arn": topic}]
    try:
        ops_item_id = ssm.create_ops_item(**kwargs).get("OpsItemId")
    except Exception as e:  # noqa: BLE001
        logger.error("CreateOpsItem failed for %s: %s", rca.incident_id, e)
        raise TicketingError(f"OpsCenter CreateOpsItem failed: {e}") from e
    if not ops_item_id:
        raise TicketingError("OpsCenter CreateOpsItem returned no OpsItemId")
    logger.info("Created OpsItem %s for incident %s", ops_item_id, rca.incident_id)
    return ref(ops_item_id)


def update_ticket(
    ticket: TicketRef,
    status: Optional[str],
    note: str,
    extra: Optional[Dict[str, str]] = None,
    ssm_client=None,
) -> None:
    """Record ``note`` (and ``extra``) as operational data; move the OpsItem to ``status`` unless None."""
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}")
    data = {"opspilot:last_update": {"Value": note[:20000], "Type": "String"}}
    for k, v in (extra or {}).items():
        if v:
            data[f"opspilot:{k}"] = {"Value": str(v)[:20000], "Type": "SearchableString"}
    try:
        kwargs: Dict[str, Any] = {"OpsItemId": ticket.key, "OperationalData": data}
        if status is not None:
            kwargs["Status"] = status
        (ssm_client or boto3.client("ssm")).update_ops_item(**kwargs)
    except Exception as e:  # noqa: BLE001
        raise TicketingError(f"OpsCenter UpdateOpsItem failed for {ticket.key}: {e}") from e


def get_status(ticket: TicketRef, ssm_client=None) -> Optional[str]:
    """Current OpsItem status as set in OpsCenter (by a human or by OpsPilot)."""
    try:
        resp = (ssm_client or boto3.client("ssm")).get_ops_item(OpsItemId=ticket.key)
    except Exception as e:  # noqa: BLE001
        raise TicketingError(f"OpsCenter GetOpsItem failed for {ticket.key}: {e}") from e
    return (resp.get("OpsItem") or {}).get("Status")


def handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """Lambda entry point for the Step Functions CreateTicket state."""
    logger.info("CreateTicket invoked with event keys: %s", list(event.keys()))
    rca = RcaResult.model_validate(event["rca"] if "rca" in event else event)
    incident = event.get("incident") if isinstance(event.get("incident"), dict) else None

    ticket = create_ticket(rca, incident=incident)

    update_incident(
        rca.incident_id,
        {
            "ticket_provider": PROVIDER,
            "ticket_key": ticket.key,
            "ticket_url": ticket.url,
            "ticket_status": ticket.status or "Open",
            "severity": rca.severity,
            "ticket_severity": ticket.severity or "",
            "ticket_priority": str(ticket.priority or ""),
            "classification": rca.classification,
            "status": "TICKETED",
        },
    )
    append_timeline(rca.incident_id, "TICKETED", f"OpsItem {ticket.key} Open ({rca.severity})")
    return ticket.model_dump()
