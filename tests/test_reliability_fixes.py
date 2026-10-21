"""Regression tests for the engineering review's reliability findings (docs/REVIEW_FIXES.md)."""

import json
from pathlib import Path

import boto3
import httpx
import pytest
from moto import mock_aws

from opspilot.contracts import EvidenceItem, RcaResult
from opspilot.ingest import record_incident_if_new
from opspilot.verify.runner import parse_build, parse_verification_handler

ASL = json.loads((Path(__file__).resolve().parent.parent / "statemachine" / "opspilot.asl.json").read_text())
STATES = ASL["States"]


def _successors(state):
    out = []
    if "Next" in state:
        out.append(state["Next"])
    out += [c["Next"] for c in state.get("Catch", [])]
    out += [c["Next"] for c in state.get("Choices", [])]
    if "Default" in state:
        out.append(state["Default"])
    return out


def test_asl_every_path_ends_in_notify():
    """No state may end the execution without passing through Notify (except NotifyFailed after Notify)."""
    for name, state in STATES.items():
        if name in ("Notify", "NotifyFailed"):
            continue
        assert not state.get("End"), f"{name} ends the execution without notifying"
        assert state["Type"] != "Fail", f"{name} fails without notifying"
        # every state can reach Notify
        seen, stack = set(), [name]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack += _successors(STATES[cur])
        assert "Notify" in seen, f"{name} cannot reach Notify"


def test_asl_tasks_have_timeouts_and_catches():
    for name, state in STATES.items():
        if state["Type"] == "Task":
            assert state.get("TimeoutSeconds"), f"{name} has no timeout"
            assert state.get("Catch"), f"{name} has no Catch"


def test_asl_rca_failure_abstains_and_never_proposes_fix():
    assert STATES["RunRCA"]["Catch"][0]["Next"] == "BuildAbstainRca"
    abstain = STATES["BuildAbstainRca"]["Parameters"]
    assert abstain["classification"] == "insufficient_evidence" and abstain["confidence"] == 0.0
    # The abstain contract must validate (evidence is non-empty).
    RcaResult(incident_id="x", classification="insufficient_evidence", severity="sev3", confidence=0.0,
              summary="s", evidence=[EvidenceItem(**abstain["evidence"][0])],
              suggested_fix_strategy=abstain["suggested_fix_strategy"])
    # An abstention still cannot open a pull request: Route never enters ProposeFix.
    assert all(choice["Next"] != "ProposeFix" for choice in STATES["Route"]["Choices"])


def test_asl_verify_goes_through_parse_verification():
    assert STATES["Verify"]["Next"] == "ParseVerification"
    assert STATES["Verify"]["Catch"][0]["Next"] == "ParseVerification"
    assert STATES["VerifyOutcome"]["Choices"][0]["Variable"] == "$.verify.verdict"


def _table(ddb):
    ddb.create_table(TableName="t", KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
                     AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}],
                     BillingMode="PAY_PER_REQUEST")


@mock_aws
def test_stale_pending_claim_is_reclaimable(monkeypatch):
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    _table(ddb)
    args = ("t", "inc-1", "alarm", "svc", "2026-01-01T00:00:00Z")
    assert record_incident_if_new(*args, dynamodb_client=ddb) is True
    assert record_incident_if_new(*args, dynamodb_client=ddb) is False  # fresh PENDING: duplicate
    monkeypatch.setattr("opspilot.ingest.PENDING_STALE_SECONDS", -10)
    assert record_incident_if_new(*args, dynamodb_client=ddb) is True  # stale PENDING: re-claim
    ddb.update_item(TableName="t", Key={"incident_id": {"S": "inc-1"}}, UpdateExpression="SET #s = :s",
                    ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": {"S": "STARTED"}})
    assert record_incident_if_new(*args, dynamodb_client=ddb) is False  # STARTED is never re-claimed


def _build(status, **exported):
    return {"id": "proj:1", "buildStatus": status,
            "exportedEnvironmentVariables": [{"name": k, "value": v} for k, v in exported.items()]}


def test_parse_build_verdicts():
    ok = parse_build(_build("SUCCEEDED", REPRO_FAILS_ON_BASE="true", SUITE_PASSES_ON_FIX="true"))
    assert ok.verdict == "verified"
    bad_repro = parse_build(_build("FAILED", REPRO_FAILS_ON_BASE="false", FAILURE_REASON="bad_repro_passes_on_base"))
    assert bad_repro.verdict == "failed" and "bad_repro" in bad_repro.details
    # SUCCEEDED without both markers is not trusted as verified.
    assert parse_build(_build("SUCCEEDED")).verdict == "failed"


def test_parse_verification_handler_reads_build_from_error_cause():
    class FakeCB:
        def batch_get_builds(self, ids):
            assert ids == ["proj:9"]
            return {"builds": [_build("FAILED", REPRO_FAILS_ON_BASE="true", FAILURE_REASON="suite_fails_on_fix")]}

    event = {"verify_build": None,
             "verify_error": {"Error": "States.TaskFailed", "Cause": json.dumps({"Build": {"Id": "proj:9"}})}}
    res = parse_verification_handler(event, codebuild_client=FakeCB())
    assert res["verdict"] == "failed" and res["repro_fails_on_base"] is True


def test_parse_verification_handler_build_never_started():
    res = parse_verification_handler({"verify_build": None, "verify_error": {"Error": "X", "Cause": "boom"}})
    assert res["verdict"] == "failed" and "did not start" in res["details"]


def test_opscenter_create_failure_raises_instead_of_fake_ticket():
    from opspilot import ticketing

    rca = RcaResult(incident_id="inc-j", classification="code_defect", severity="sev2", confidence=0.9,
                    summary="s", evidence=[EvidenceItem(kind="log_line", ref="l1", claim="c")],
                    suggested_fix_strategy="x")

    class BrokenSSM:
        def describe_ops_items(self, **kw):
            return {"OpsItemSummaries": []}

        def create_ops_item(self, **kw):
            raise RuntimeError("AccessDeniedException")

    with pytest.raises(ticketing.TicketingError):
        ticketing.create_ticket(rca, ssm_client=BrokenSSM())


def test_asl_route_waits_for_a_human_pr_choice():
    """The pipeline records the analysis and notifies. It does not open a pull request.

    Whether a diff is offerable stays in route_rca. The incident screen raises the PR.
    """
    from opspilot.route import FIXABLE_CLASSES, determine_route

    assert ASL["StartAt"] == "Entry"
    assert STATES["Entry"]["Default"] == "CollectContext"
    assert STATES["Entry"]["Choices"] == [
        {"Variable": "$.action", "StringEquals": "raise_pr", "Next": "ProposeFix"}
    ]
    assert STATES["Route"]["Default"] == "Notify"
    assert all(c["Next"] != "ProposeFix" for c in STATES["Route"]["Choices"])
    assert "ProposeFix" in STATES
    assert determine_route("code_defect", 0.95) == "propose_fix"
    assert "code_defect" in FIXABLE_CLASSES
