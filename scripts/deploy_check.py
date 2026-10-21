#!/usr/bin/env python3
"""AWS-side helpers for scripts/deploy.sh (boto3 only, no AWS CLI needed).

    python scripts/deploy_check.py whoami            # prints "<account> <region>"
    python scripts/deploy_check.py bootstrap-status  # exit 0 if CDKToolkit is deployed
    python scripts/deploy_check.py bedrock           # warn if the model is not usable
    python scripts/deploy_check.py secrets           # push JIRA/GitHub/Slack values from env
    python scripts/deploy_check.py verify            # post-deploy smoke test
    python scripts/deploy_check.py outputs           # print every stack output
"""

import json
import os
import sys
import time
import urllib.request

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

STACKS = ["OpsPilotCoreStack", "OpsPilotSampleServiceStack", "OpsPilotPipelineStack"]
LAMBDAS = ["opspilot-ingest", "opspilot-collect-context", "opspilot-run-rca", "opspilot-create-ticket",
           "opspilot-propose-fix", "opspilot-mark-needs-human", "opspilot-notify",
           "opspilot-parse-verification", "opspilot-sample-service"]
ALARMS = ["OpsPilotSampleServiceErrors", "OpsPilotSampleService-CheckoutErrors",
          "OpsPilotSampleService-InventoryDbTimeouts", "OpsPilotSampleService-LatencyP95",
          "OpsPilotSampleService-Crashes", "opspilot-executions-failed"]
OK_STATES = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}
DEFAULT_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
failures: list[str] = []
warnings: list[str] = []


def ok(msg): print(f"  {GREEN}PASS{RESET} {msg}")
def bad(msg): failures.append(msg); print(f"  {RED}FAIL{RESET} {msg}")
def warn(msg): warnings.append(msg); print(f"  {YELLOW}WARN{RESET} {msg}")


def session():
    return boto3.session.Session(region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))


def region(s) -> str:
    return s.region_name or "us-east-1"


def whoami():
    s = session()
    try:
        ident = s.client("sts", region_name=region(s)).get_caller_identity()
    except (NoCredentialsError, ClientError, BotoCoreError) as e:
        sys.exit(f"No usable AWS credentials: {e}")
    print(ident["Account"], region(s))


def bootstrap_status():
    s = session()
    try:
        st = s.client("cloudformation").describe_stacks(StackName="CDKToolkit")["Stacks"][0]["StackStatus"]
    except ClientError:
        sys.exit(1)
    sys.exit(0 if st in OK_STATES else 1)


def bedrock():
    s = session()
    model = os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL)
    base = model.split(".", 1)[1] if model.split(".", 1)[0] in ("us", "eu", "apac", "global") else model
    try:
        s.client("bedrock").get_foundation_model(modelIdentifier=base)
        print(f"  {GREEN}PASS{RESET} Bedrock model {model} exists in {region(s)}")
    except ClientError as e:
        print(f"  {YELLOW}WARN{RESET} Bedrock model {model} not available in {region(s)} "
              f"({e.response['Error']['Code']}). Enable model access in the Bedrock console or set BEDROCK_MODEL_ID; "
              "RCA will fail at runtime until then.")
    except BotoCoreError as e:
        print(f"  {YELLOW}WARN{RESET} could not check Bedrock: {e}")


def _put(sm, name, value):
    sm.put_secret_value(SecretId=name, SecretString=value)
    print(f"  {GREEN}SET{RESET}  {name}")


def secrets():
    """Write third-party credentials into the secrets CoreStack created. Only values present in env are written."""
    sm = session().client("secretsmanager")
    e = os.environ
    if e.get("JIRA_API_TOKEN"):
        _put(sm, "opspilot/jira", json.dumps({k: v for k, v in {
            "api_token": e["JIRA_API_TOKEN"], "email": e.get("JIRA_EMAIL"), "base_url": e.get("JIRA_BASE_URL"),
        }.items() if v}))
    else:
        print(f"  {YELLOW}SKIP{RESET} opspilot/jira   (JIRA_API_TOKEN not set; tickets fall back to a mock token and will fail live)")
    if e.get("GITHUB_TOKEN"):
        _put(sm, "opspilot/github", json.dumps({"token": e["GITHUB_TOKEN"]}))
    else:
        print(f"  {YELLOW}SKIP{RESET} opspilot/github (GITHUB_TOKEN not set; fix PRs will fail)")
    if e.get("SLACK_WEBHOOK_URL"):
        _put(sm, "opspilot/slack", json.dumps({"webhook_url": e["SLACK_WEBHOOK_URL"]}))
    else:
        print(f"  {YELLOW}SKIP{RESET} opspilot/slack  (SLACK_WEBHOOK_URL not set; on-call notify is skipped)")


def stack_outputs(cf) -> dict:
    out = {}
    for name in STACKS:
        try:
            for o in cf.describe_stacks(StackName=name)["Stacks"][0].get("Outputs", []):
                out[o["OutputKey"]] = o["OutputValue"]
        except ClientError:
            pass
    return out


def outputs():
    for k, v in stack_outputs(session().client("cloudformation")).items():
        print(f"{k}={v}")


def http_get(url: str, timeout=35):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode()


def verify():
    s = session()
    cf, lam, cw = s.client("cloudformation"), s.client("lambda"), s.client("cloudwatch")
    print("Stacks")
    for name in STACKS:
        try:
            st = cf.describe_stacks(StackName=name)["Stacks"][0]["StackStatus"]
            (ok if st in OK_STATES else bad)(f"{name}: {st}")
        except ClientError:
            bad(f"{name}: not deployed")

    print("Lambda functions")
    for fn in LAMBDAS:
        try:
            cfg = lam.get_function_configuration(FunctionName=fn)
            (ok if cfg.get("State", "Active") == "Active" else bad)(f"{fn}: {cfg.get('State', 'Active')}")
        except ClientError:
            bad(f"{fn}: missing")

    print("Step Functions + EventBridge wiring")
    acct = s.client("sts").get_caller_identity()["Account"]
    sm_arn = f"arn:aws:states:{region(s)}:{acct}:stateMachine:opspilot"
    try:
        s.client("stepfunctions").describe_state_machine(stateMachineArn=sm_arn)
        ok("state machine opspilot exists")
    except ClientError:
        bad("state machine opspilot missing")
    try:
        rule = s.client("events").describe_rule(Name="opspilot-alarm-trigger")
        (ok if rule["State"] == "ENABLED" else bad)(f"rule opspilot-alarm-trigger: {rule['State']}")
        targets = s.client("events").list_targets_by_rule(Rule="opspilot-alarm-trigger")["Targets"]
        (ok if any("opspilot-ingest" in t["Arn"] for t in targets) else bad)("rule targets opspilot-ingest")
    except ClientError:
        bad("EventBridge rule opspilot-alarm-trigger missing")

    print("CloudWatch alarms")
    found = {a["AlarmName"]: a["StateValue"] for a in cw.describe_alarms(AlarmNames=ALARMS)["MetricAlarms"]}
    for a in ALARMS:
        if a not in found:
            bad(f"{a}: missing")
        elif found[a] == "ALARM":
            warn(f"{a}: already in ALARM (it must return to OK before it can fire again)")
        else:
            ok(f"{a}: {found[a]}")

    print("Secrets")
    sm = s.client("secretsmanager")
    for name in ("opspilot/jira", "opspilot/github", "opspilot/slack"):
        try:
            versions = sm.list_secret_version_ids(SecretId=name)["Versions"]
            # CDK generates a random placeholder as the first version; a second version means someone set it.
            (ok if len(versions) > 1 else warn)(f"{name}: {'set' if len(versions) > 1 else 'still the CDK placeholder'}")
        except ClientError:
            bad(f"{name}: missing")

    print("Sample service (live HTTP)")
    url = stack_outputs(cf).get("SampleServiceUrl", "").rstrip("/")
    if not url:
        bad("SampleServiceUrl output missing")
    else:
        for attempt in range(3):  # first call after deploy can hit a cold start
            try:
                code, body = http_get(url + "/health")
                (ok if code == 200 else bad)(f"GET /health -> {code}")
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    bad(f"GET /health failed: {e}")
                time.sleep(3)
        try:
            code, body = http_get(url + "/faults")
            n = len(json.loads(body)) if body.strip().startswith(("[", "{")) else 0
            (ok if code == 200 else bad)(f"GET /faults -> {code} ({n} entries)")
        except Exception as e:  # noqa: BLE001
            bad(f"GET /faults failed: {e}")
        print(f"\n  Service URL: {url}")
        print(f"  Dashboard:   https://{region(s)}.console.aws.amazon.com/cloudwatch/home?region={region(s)}#dashboards/dashboard/OpsPilot-SampleService")

    print()
    if failures:
        print(f"{RED}{len(failures)} check(s) failed{RESET}, {len(warnings)} warning(s).")
        sys.exit(1)
    print(f"{GREEN}All checks passed{RESET}, {len(warnings)} warning(s).")


if __name__ == "__main__":
    cmds = {"whoami": whoami, "bootstrap-status": bootstrap_status, "bedrock": bedrock,
            "secrets": secrets, "verify": verify, "outputs": outputs}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
