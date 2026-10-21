"""Unit tests for native AWS ticketing (SSM OpsCenter + DynamoDB tracking)."""

import json

import boto3
import pytest
from moto import mock_aws

from opspilot import ticketing
from opspilot.contracts import EvidenceItem, PrRef, RcaResult, SuspectedLocation, TicketRef, VerificationResult
from opspilot.notify import sync_ticket_status


class FakeSSM:
    """Records OpsCenter calls; behaves like the subset of the SSM API ticketing uses."""

    def __init__(self, existing=None, fail_update=False, current_status="Open", fail_get=False):
        self.existing = existing or {}
        self.current_status, self.fail_get = current_status, fail_get
        self.created, self.updated, self.searches = [], [], []
        self.fail_update = fail_update

        class _Meta:
            region_name = "eu-west-1"

        self.meta = _Meta()

    def describe_ops_items(self, OpsItemFilters, MaxResults):
        self.searches.append(OpsItemFilters)
        f = json.loads(OpsItemFilters[0]["Values"][0])
        assert OpsItemFilters[0]["Key"] == "OperationalData" and f["key"] == ticketing.INCIDENT_KEY
        hit = self.existing.get(f["value"])
        return {"OpsItemSummaries": [{"OpsItemId": hit}] if hit else []}

    def create_ops_item(self, **kw):
        self.created.append(kw)
        return {"OpsItemId": "oi-0123456789ab"}

    def get_ops_item(self, OpsItemId):
        if self.fail_get:
            raise RuntimeError("AccessDenied")
        return {"OpsItem": {"OpsItemId": OpsItemId, "Status": self.current_status}}

    def update_ops_item(self, **kw):
        if self.fail_update:
            raise RuntimeError("ThrottlingException")
        self.updated.append(kw)
        return {}


@pytest.fixture
def rca():
    return RcaResult(
        incident_id="inc-ops-123",
        classification="code_defect",
        severity="sev1",
        confidence=0.88,
        summary="KeyError on missing order in GET /orders",
        suspected_location=SuspectedLocation(file="sample_service/app.py", line=29, function="get_order"),
        evidence=[EvidenceItem(kind="log_line", ref="log-1", claim="Unhandled KeyError")],
        suggested_fix_strategy="Return 404 for unknown order ids.",
    )


def test_create_ticket_maps_severity_priority_and_operational_data(rca):
    ssm = FakeSSM()
    ticket = ticketing.create_ticket(rca, incident={"service": "orders", "alarm_name": "A1"}, ssm_client=ssm)

    assert ticket.key == "oi-0123456789ab"
    assert ticket.provider == "opscenter" and ticket.status == "Open"
    assert ticket.url == ("https://eu-west-1.console.aws.amazon.com/systems-manager/opsitems/"
                          "oi-0123456789ab?region=eu-west-1")
    kw = ssm.created[0]
    assert kw["Severity"] == "1" and kw["Priority"] == 1 and ticket.severity == "1" and ticket.priority == 1
    assert kw["Source"] == "OpsPilot" and kw["Category"] == "Availability"
    assert kw["Title"].startswith("[OpsPilot] code_defect:")
    od = kw["OperationalData"]
    assert od[ticketing.INCIDENT_KEY] == {"Value": "inc-ops-123", "Type": "SearchableString"}
    assert od["opspilot:service"]["Value"] == "orders"
    assert json.loads(od["opspilot:rca"]["Value"])["incident_id"] == "inc-ops-123"
    assert not any(k.lower().startswith(("aws", "ssm", "amazon", "amzn")) for k in od)
    assert "sample_service/app.py:29" in kw["Description"]


def test_create_ticket_is_idempotent_via_opscenter_search(rca):
    ssm = FakeSSM(existing={"inc-ops-123": "oi-existing00001"})
    ticket = ticketing.create_ticket(rca, ssm_client=ssm)
    assert ticket.key == "oi-existing00001"
    assert ssm.created == []


@mock_aws
def test_create_ticket_reuses_ticket_recorded_in_dynamodb(rca, monkeypatch):
    monkeypatch.setenv("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(TableName="opspilot-incidents", BillingMode="PAY_PER_REQUEST",
                     KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
                     AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}])
    ddb.put_item(TableName="opspilot-incidents", Item={
        "incident_id": {"S": "inc-ops-123"}, "ticket_provider": {"S": "opscenter"}, "ticket_key": {"S": "oi-fromddb0001"}})
    ssm = FakeSSM()
    ticket = ticketing.create_ticket(rca, ssm_client=ssm, dynamodb_client=ddb)
    assert ticket.key == "oi-fromddb0001"
    assert ssm.created == [] and ssm.searches == []


def test_description_respects_opscenter_limit(rca):
    rca.evidence = [EvidenceItem(kind="log_line", ref=f"log-{i}", claim="x" * 200) for i in range(30)]
    text = ticketing.build_description(rca)
    assert len(text) <= ticketing.DESCRIPTION_MAX
    assert "truncated" in text


def test_severity_mapping_covers_every_rca_severity():
    for sev in ("sev1", "sev2", "sev3", "sev4"):
        assert ticketing.SEVERITY_TO_OPSCENTER[sev] in {"1", "2", "3", "4"}
        assert 1 <= ticketing.SEVERITY_TO_PRIORITY[sev] <= 5


@mock_aws
def test_handler_records_ticket_and_timeline_in_dynamodb(rca, monkeypatch):
    monkeypatch.setenv("INCIDENTS_TABLE_NAME", "opspilot-incidents")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(TableName="opspilot-incidents", BillingMode="PAY_PER_REQUEST",
                     KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
                     AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}])
    ssm = FakeSSM()
    monkeypatch.setattr(ticketing.boto3, "client",
                        lambda name, *a, **k: ssm if name == "ssm" else boto3.session.Session().client(name, region_name="us-east-1"))

    out = ticketing.handler({"rca": rca.model_dump(), "incident": {"service": "orders"}})

    assert out["key"] == "oi-0123456789ab"
    item = ddb.get_item(TableName="opspilot-incidents", Key={"incident_id": {"S": "inc-ops-123"}})["Item"]
    assert item["ticket_provider"]["S"] == "opscenter"
    assert item["ticket_key"]["S"] == "oi-0123456789ab"
    assert item["ticket_status"]["S"] == "Open"
    assert item["severity"]["S"] == "sev1" and item["ticket_priority"]["S"] == "1"
    assert item["status"]["S"] == "TICKETED"
    timeline = item["timeline"]["L"]
    assert timeline[0]["M"]["event"]["S"] == "TICKETED"


def _ticket():
    return TicketRef(key="oi-0123456789ab", url="https://x", incident_id="inc-ops-123", status="Open")


def test_verified_fix_moves_opsitem_to_in_progress():
    ssm = FakeSSM()
    pr = PrRef(branch="opspilot/oi-0123456789ab", repro_test_path="t.py", pr_url="https://pr/1", attempt=1)
    verify = VerificationResult(pr_branch=pr.branch, repro_fails_on_base=True, suite_passes_on_fix=True,
                                verdict="verified", details="ok")
    status, synced = sync_ticket_status(_ticket(), "VERIFIED", pr, verify, None, ssm_client=ssm)
    assert (status, synced) == ("InProgress", True)
    upd = ssm.updated[0]
    assert upd["OpsItemId"] == "oi-0123456789ab" and upd["Status"] == "InProgress"
    assert upd["OperationalData"]["opspilot:pr_url"]["Value"] == "https://pr/1"


def test_needs_human_keeps_opsitem_open_and_never_auto_resolves():
    ssm = FakeSSM()
    for final in ("NEEDS_HUMAN", "FAILED", "NOTIFIED"):
        status, synced = sync_ticket_status(_ticket(), final, None, None, "boom", ssm_client=ssm)
        assert (status, synced) == ("Open", True)
    assert all(u.get("Status") != "Resolved" for u in ssm.updated)


def test_opsitem_update_failure_does_not_block_notification():
    status, synced = sync_ticket_status(_ticket(), "VERIFIED", None, None, None, ssm_client=FakeSSM(fail_update=True))
    assert (status, synced) == ("Open", False)


def test_update_ticket_rejects_unknown_status():
    with pytest.raises(ValueError):
        ticketing.update_ticket(_ticket(), "Closed", "x", ssm_client=FakeSSM())


@pytest.mark.parametrize("human_status", ["Resolved", "InProgress"])
def test_human_set_status_is_never_overwritten(human_status):
    ssm = FakeSSM(current_status=human_status)
    status, synced = sync_ticket_status(_ticket(), "NEEDS_HUMAN", None, None, None, ssm_client=ssm)
    assert (status, synced) == (human_status, True)
    upd = ssm.updated[0]
    assert "Status" not in upd  # outcome recorded, status left as the human set it
    assert upd["OperationalData"]["opspilot:run_status"]["Value"] == "NEEDS_HUMAN"
    assert upd["OperationalData"]["opspilot:proposed_status"]["Value"] == "Open"


def test_unreadable_status_is_left_untouched():
    ssm = FakeSSM(fail_get=True)
    status, synced = sync_ticket_status(_ticket(), "VERIFIED", None, None, None, ssm_client=ssm)
    assert synced is True and status == "Open"
    assert "Status" not in ssm.updated[0]


def test_oversized_rca_stays_valid_json_within_limit(rca):
    big = rca.model_copy(update={
        "suggested_fix_strategy": "x" * 50000,
        "summary": "s" * 30000,
        "evidence": [EvidenceItem(kind="log_line", ref=f"log-{i}", claim="c" * 3000) for i in range(40)],
    })
    od = ticketing._operational_data(big, None)
    value = od["opspilot:rca"]["Value"]
    assert len(value) <= ticketing.RCA_DATA_MAX
    parsed = json.loads(value)
    assert parsed["incident_id"] == "inc-ops-123" and parsed["_truncated"] is True


def test_small_rca_is_stored_verbatim(rca):
    assert ticketing._operational_data(rca, None)["opspilot:rca"]["Value"] == rca.model_dump_json()
