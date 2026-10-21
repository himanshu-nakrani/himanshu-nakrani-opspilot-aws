# OpsPilot hackathon demo runbook

The demo target is the sample storefront service (`sample_service/`): FastAPI on
Lambda behind a public Function URL. It has five deliberately planted faults.
Each one has its own CloudWatch alarm, and every alarm name starts with
`OpsPilotSampleService`. One EventBridge rule matches that prefix and starts
the OpsPilot Step Functions pipeline (ingest -> CollectContext -> RCA -> route
-> Jira / fix PR / verify / notify).

## 1. Deploy (once)

Everything (CoreStack, SampleServiceStack, PipelineStack) deploys with one command:

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.deploy.example .env.deploy      # fill in AWS_PROFILE/AWS_REGION, Jira URL, tokens
scripts/deploy.sh                       # or: make deploy
```

`scripts/deploy.sh` (no argument means `up`) runs these steps in order and stops at the first failure:

| Step | What it does |
|---|---|
| preflight | Python 3.10+, Node 18+, CDK libs, pip/uv; reads the AWS account and region from STS; checks GITHUB_REPO and JIRA_BASE_URL; warns if the Bedrock model is not enabled |
| bootstrap | Runs `cdk bootstrap aws://<account>/<region>` only if the CDKToolkit stack is missing |
| synth | Bundles every Lambda for Linux/cp312 (no Docker) and writes cdk.out/ |
| deploy | `cdk deploy --all`; stack outputs go to cdk-outputs.json |
| secrets | Writes JIRA_API_TOKEN, GITHUB_TOKEN and SLACK_WEBHOOK_URL into opspilot/jira, opspilot/github and opspilot/slack. Blank values are skipped |
| verify | Checks the 3 stacks, 9 Lambdas, the opspilot state machine, the EventBridge rule and its target, the 6 alarms and the 3 secrets, then calls GET /health and GET /faults on the live service |

Other commands: `preflight`, `synth` (`OFFLINE=1` synthesizes without AWS credentials), `diff`,
`secrets`, `verify`, `outputs`, `dashboard` (builds the frontend and serves the OpsPilot
dashboard on :8000) and `destroy`. `scripts/deploy.sh help` lists them. Neither Docker nor the AWS CLI is needed.

Settings that become Lambda environment values (GITHUB_REPO, JIRA_BASE_URL, JIRA_PROJECT_KEY,
JIRA_EMAIL, BEDROCK_MODEL_ID) are read at synth time. If you change one, run deploy again. Secrets
can be changed at any time with `scripts/deploy.sh secrets`.

Outputs: `SampleServiceUrl` (the service) and the `OpsPilot-SampleService`
CloudWatch dashboard (alarm status, requests vs errors, p95 latency, recent
exceptions). `verify` prints both links.

## 2. Planted faults

| Scenario | Trigger | Failure | Alarm | Expected OpsPilot path |
|---|---|---|---|---|
| orders | `GET /orders/999` | 500 AttributeError | OpsPilotSampleServiceErrors | code defect -> ticket -> fix PR -> CodeBuild verify |
| checkout | `GET /checkout?sku=SKU-1&coupon=SPRING50` | 500 KeyError | OpsPilotSampleService-CheckoutErrors | code defect -> ticket -> fix attempt (stub patcher only patches orders, so needs human) |
| inventory | `GET /inventory/BULK-42` | 500 TimeoutError (DB pool) | OpsPilotSampleService-InventoryDbTimeouts | dependency -> ticket -> notify |
| payments | `GET /payments/77/status?provider=legacy` | ~6 s latency | OpsPilotSampleService-LatencyP95 (p95 >= 3000 ms) | dependency -> ticket -> notify |
| reports | `GET /reports/export?days=90` | Lambda out of memory | OpsPilotSampleService-Crashes (Lambda Errors) | resource -> ticket -> notify |

`GET /faults` on the live service returns the same catalog.

## 3. Run a scenario

```bash
export SAMPLE_SERVICE_URL=https://<id>.lambda-url.<region>.on.aws   # or let the script read the stack output
python scripts/demo_faults.py list
python scripts/demo_faults.py baseline                 # healthy traffic only
python scripts/demo_faults.py orders --watch           # inject, then watch the alarm and the execution
# or: make demo-fault SCENARIO=inventory
curl -s "$SAMPLE_SERVICE_URL/orders/999"               # raw trigger
```

Timeline: the alarm moves to ALARM about 1-2 min after the burst. The execution
starts within seconds of that. Then check the OpsPilot dashboard, Jira and GitHub.

## Notes and limits
- Run **one scenario at a time**. CollectContext reads the whole service log group.
- Dedup is per alarm name for 15 minutes, so repeating a scenario inside that window does not open a new incident. An alarm also has to go back to OK before it can fire again.
- CollectContext now pulls error and warning events first (`?Traceback ?ERROR ...`) and falls back to the raw window. Before this, steady traffic pushed the traceback out of the first 50 events.
- The Function URL is public (auth NONE) and serves only the demo service. Run `scripts/deploy.sh destroy` after the event.
