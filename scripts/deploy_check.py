#!/usr/bin/env python3
"""AWS-side helpers for scripts/deploy.sh (boto3 only, no AWS CLI needed).

    python scripts/deploy_check.py whoami            # prints "<account> <region>"
    python scripts/deploy_check.py bootstrap-status  # exit 0 if CDKToolkit is deployed
    python scripts/deploy_check.py bedrock           # warn if the model is not usable
    python scripts/deploy_check.py secrets           # push the optional Slack webhook from env
    python scripts/deploy_check.py opscenter         # check OpsCenter (ticketing) is reachable with these IAM creds
    python scripts/deploy_check.py repo-status       # exit 0 if the CodeCommit repo already exists
    python scripts/deploy_check.py seed-repo         # push this checkout to CodeCommit main (boto3, IAM only)
    python scripts/deploy_check.py verify            # post-deploy smoke test
    python scripts/deploy_check.py outputs           # print every stack output
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

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
DEFAULT_MODEL = "us.anthropic.claude-haiku-5-5"

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
    br = s.client("bedrock")
    try:
        br.get_foundation_model(modelIdentifier=base)
    except ClientError as e:
        print(f"  {YELLOW}WARN{RESET} Bedrock model {model} not available in {region(s)} "
              f"({e.response['Error']['Code']}). Set BEDROCK_MODEL_ID to a model offered there; "
              "RCA will fail at runtime until then.")
        return
    except BotoCoreError as e:
        print(f"  {YELLOW}WARN{RESET} could not check Bedrock: {e}")
        return
    # Existence is not access: check that this account is actually authorized/entitled to call it.
    try:
        a = br.get_foundation_model_availability(modelId=base)
    except (ClientError, BotoCoreError) as e:
        print(f"  {YELLOW}WARN{RESET} Bedrock model {model} exists, but access could not be confirmed ({e}). "
              "Check model access in the Bedrock console.")
        return
    problems = [f"{k}={a.get(k, {}).get('status') if isinstance(a.get(k), dict) else a.get(k)}"
                for k in ("authorizationStatus", "entitlementAvailability", "agreementAvailability", "regionAvailability")
                if (a.get(k, {}).get("status") if isinstance(a.get(k), dict) else a.get(k))
                not in (None, "AUTHORIZED", "AVAILABLE", "NOT_APPLICABLE")]
    if problems:
        print(f"  {YELLOW}WARN{RESET} Bedrock model {model} exists but is not usable by this account "
              f"({', '.join(problems)}). Enable model access in the Bedrock console; RCA will fail until then.")
    else:
        print(f"  {GREEN}PASS{RESET} Bedrock model {model} is enabled for this account in {region(s)}")

def _put(sm, name, value):
    sm.put_secret_value(SecretId=name, SecretString=value)
    print(f"  {GREEN}SET{RESET}  {name}")


def secrets():
    """Write third-party credentials into the secrets CoreStack created. Only values present in env are written."""
    sm = session().client("secretsmanager")
    e = os.environ
    if e.get("SLACK_WEBHOOK_URL"):
        _put(sm, "opspilot/slack", json.dumps({"webhook_url": e["SLACK_WEBHOOK_URL"]}))
    else:
        print(f"  {YELLOW}SKIP{RESET} opspilot/slack  (SLACK_WEBHOOK_URL not set; on-call notify is skipped)")


def opscenter():
    """Ticketing is AWS Systems Manager OpsCenter: confirm these IAM credentials can query OpsItems."""
    try:
        resp = session().client("ssm").describe_ops_items(
            OpsItemFilters=[{"Key": "Source", "Operator": "Equal", "Values": ["OpsPilot"]}], MaxResults=5)
        n = len(resp.get("OpsItemSummaries", []))
        print(f"  {GREEN}PASS{RESET} OpsCenter reachable ({n} recent OpsPilot OpsItem(s)); tickets use IAM, no secret needed")
    except ClientError as e:
        print(f"  {YELLOW}WARN{RESET} OpsCenter not usable by this identity ({e.response['Error']['Code']}). "
              "The deploy grants the Lambda its own ssm:*OpsItem* permissions, so this only affects local checks.")
    except (BotoCoreError, NoCredentialsError) as e:
        print(f"  {YELLOW}WARN{RESET} OpsCenter check skipped: {e}")


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
    for name in ("opspilot/slack",):
        try:
            versions = sm.list_secret_version_ids(SecretId=name)["Versions"]
            # CDK generates a random placeholder as the first version; a second version means someone set it.
            (ok if len(versions) > 1 else warn)(f"{name}: {'set' if len(versions) > 1 else 'still the CDK placeholder'}")
        except ClientError:
            bad(f"{name}: missing")

    print("OpsCenter ticketing (AWS Systems Manager)")
    try:
        items = s.client("ssm").describe_ops_items(
            OpsItemFilters=[{"Key": "Source", "Operator": "Equal", "Values": ["OpsPilot"]}], MaxResults=5
        ).get("OpsItemSummaries", [])
        ok(f"OpsCenter reachable; {len(items)} recent OpsPilot OpsItem(s)")
    except ClientError as e:
        warn(f"OpsCenter query failed for this identity: {e.response['Error']['Code']}")

    print("Sample-service app repo (CodeCommit -> CodePipeline)")
    cc = s.client("codecommit")
    try:
        meta = cc.get_repository(repositoryName="opspilot-sample-service")["repositoryMetadata"]
        ok(f"repository opspilot-sample-service exists ({meta.get('cloneUrlHttp')})")
        head = cc.get_branch(repositoryName="opspilot-sample-service", branchName="main")["branch"]["commitId"]
        ok(f"branch main at {head[:10]}")
        for path in ("buildspec.yml", "sample_service/app.py"):
            cc.get_file(repositoryName="opspilot-sample-service", commitSpecifier="main", filePath=path)
            ok(f"main has {path}")
    except ClientError as e:
        bad(f"app repo opspilot-sample-service: {e.response['Error']['Code']}")
    try:
        pipe = s.client("codepipeline").get_pipeline(name="opspilot-sample-service")["pipeline"]
        stages = [stage["name"] for stage in pipe["stages"]]
        (ok if stages == ["Source", "Build", "Deploy"] else bad)(f"pipeline stages: {' -> '.join(stages)}")
    except ClientError as e:
        bad(f"pipeline opspilot-sample-service: {e.response['Error']['Code']}")

    print("CodeCommit source repo")
    cc, repo = s.client("codecommit"), repo_name()
    try:
        meta = cc.get_repository(repositoryName=repo)["repositoryMetadata"]
        ok(f"repository {repo} exists ({meta.get('cloneUrlHttp')})")
        try:
            head = cc.get_branch(repositoryName=repo, branchName="main")["branch"]["commitId"]
            ok(f"branch main at {head[:10]}")
            for path in ("src/opspilot/verify/buildspec.yml", "sample_service/app.py"):
                try:
                    cc.get_file(repositoryName=repo, commitSpecifier="main", filePath=path)
                    ok(f"main has {path}")
                except ClientError:
                    bad(f"main is missing {path} (run: bash scripts/deploy.sh seed)")
        except ClientError:
            bad("branch main missing (run: bash scripts/deploy.sh seed)")
    except ClientError as e:
        bad(f"repository {repo} not reachable: {e.response['Error']['Code']}")

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
            data = json.loads(body) if body.strip().startswith(("[", "{")) else {}
            faults = data.get("faults", []) if isinstance(data, dict) else data
            n = len(faults) if isinstance(faults, (list, dict)) else 0
            (ok if code == 200 and n else bad)(f"GET /faults -> {code} ({n} planted faults)")
        except Exception as e:  # noqa: BLE001
            bad(f"GET /faults failed: {e}")
        print(f"\n  Service URL: {url}")
        print(f"  Dashboard:   https://{region(s)}.console.aws.amazon.com/cloudwatch/home?region={region(s)}#dashboards/dashboard/OpsPilot-SampleService")

    print()
    if failures:
        print(f"{RED}{len(failures)} check(s) failed{RESET}, {len(warnings)} warning(s).")
        sys.exit(1)
    print(f"{GREEN}All checks passed{RESET}, {len(warnings)} warning(s).")


def repo_name() -> str:
    return os.environ.get("CODECOMMIT_REPO", "opspilot-aws")


def repo_status():
    """Exit 0 if the CodeCommit repo exists (deploy.sh then imports it instead of creating it)."""
    try:
        session().client("codecommit").get_repository(repositoryName=repo_name())
    except ClientError:
        sys.exit(1)
    sys.exit(0)


SEED_BATCH = 100          # CodeCommit CreateCommit: max files per commit
SEED_MAX_BYTES = 5 << 20  # stay under the 6 MB per-request limit


def _tracked_files():
    root = Path(__file__).resolve().parent.parent
    names = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout.split(b"\0")
    files = []
    for n in filter(None, names):
        rel = n.decode()
        p = root / rel
        if p.is_file() and not p.is_symlink():
            mode = "EXECUTABLE" if os.access(p, os.X_OK) else "NORMAL"
            files.append((rel, p.read_bytes(), mode))
    return files


def seed_repo():
    """Push the files tracked in this checkout to CodeCommit `main` with the CodeCommit API.

    No git credentials, no git-remote-codecommit, no AWS CLI: just boto3 + IAM. If `main`
    already exists the seed is skipped unless RESEED=1, which commits the current checkout
    on top of main (changed/added files only; files deleted locally are not removed).
    """
    cc, repo = session().client("codecommit"), repo_name()
    try:
        parent = cc.get_branch(repositoryName=repo, branchName="main")["branch"]["commitId"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "BranchDoesNotExistException":
            raise
        parent = None
    if parent and os.environ.get("RESEED") != "1":
        print(f"  {GREEN}PASS{RESET} {repo}: main already seeded at {parent[:10]} (RESEED=1 to push this checkout again)")
        return
    files = _tracked_files()
    batches, cur, size = [], [], 0
    for f in files:
        if cur and (len(cur) >= SEED_BATCH or size + len(f[1]) > SEED_MAX_BYTES):
            batches.append(cur); cur, size = [], 0
        cur.append(f); size += len(f[1])
    if cur:
        batches.append(cur)
    for i, batch in enumerate(batches, 1):
        kw = dict(repositoryName=repo, branchName="main", authorName="OpsPilot deploy", email="opspilot@noreply.local",
                  commitMessage=f"Seed OpsPilot from local checkout ({i}/{len(batches)})",
                  putFiles=[{"filePath": p, "fileContent": c, "fileMode": m} for p, c, m in batch])
        if parent:
            kw["parentCommitId"] = parent
        try:
            parent = cc.create_commit(**kw)["commitId"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoChangeException":
                continue
            raise
    head = cc.get_branch(repositoryName=repo, branchName="main")["branch"]["commitId"]
    print(f"  {GREEN}PASS{RESET} {repo}: main at {head[:10]} ({len(files)} files)")


if __name__ == "__main__":
    cmds = {"whoami": whoami, "bootstrap-status": bootstrap_status, "bedrock": bedrock,
            "secrets": secrets, "verify": verify, "outputs": outputs,
            "repo-status": repo_status, "seed-repo": seed_repo,
            "opscenter": opscenter}
    if len(sys.argv) != 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
