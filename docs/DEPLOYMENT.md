# Deployment & operations reference

Everything deploys with `scripts/deploy.sh` (boto3 + `npx aws-cdk@2`). **No Docker and no AWS CLI are required.** On the EC2 demo instance, `scripts/ec2.sh` controls the demo processes but never creates stacks.

## Prerequisites

- Python 3.10+ (3.12 recommended — Lambdas run `PYTHON_3_12`), Node.js 22.22.2+/24.15+/26+ (CDK CLI, Vite 8 frontend build, Vitest 5 tests), pip or uv (Lambda bundling).
- `pip install -r requirements.txt` inside a venv (`aws-cdk-lib`, `constructs`, `boto3` must import).
- AWS credentials via the normal chain (`AWS_PROFILE`, SSO, or access keys). Bedrock model access for `BEDROCK_MODEL_ID` in the target region (preflight warns if the model is not enabled).

## Configuration

Copy `.env.deploy.example` to `.env.deploy`; `deploy.sh` sources it automatically. Values baked into Lambda environments (`CODECOMMIT_REPO`, `BEDROCK_MODEL_ID`, `KNOWLEDGE_BASE_ID`) are read **at synth time** — change them, run deploy again. Secrets can be re-written any time with `bash scripts/deploy.sh secrets`.

| Variable | Default | Effect |
|---|---|---|
| `AWS_PROFILE` / `AWS_REGION` | — / `us-east-1` | Credentials and target region (account/region resolved from STS) |
| `CODECOMMIT_REPO` | `opspilot-aws` | Platform repo CoreStack owns and `seed` pushes this checkout to |
| `CODECOMMIT_REPO_EXISTS` | `0` | Export `1` to make CoreStack *import* the repo instead of owning it (importing detaches it from the stack) |
| `BEDROCK_MODEL_ID` | `us.moonshotai.kimi-k3` | RCA model; IAM is scoped to this model's ARN (+ inference profile) |
| `KNOWLEDGE_BASE_ID` | *(blank)* | Managed Bedrock Knowledge Base for merged-PR solutions. Blank = documents land in S3 only, no sync, no `retrieve_knowledge` results |
| `KNOWLEDGE_BUCKET` | `seed-knowledge` falls back to the CoreStack output `KnowledgeBucketName`; **the dashboard has no fallback** | Source bucket for the knowledge base connector. `deploy.sh dashboard` does not fill this from stack outputs — export `KNOWLEDGE_BUCKET=<KnowledgeBucketName>` in the dashboard environment or merged-PR ingestion fails with "Knowledge bucket is not configured" |
| `SLACK_WEBHOOK_URL` | *(blank)* | Written to Secrets Manager `opspilot/slack` after deploy; blank skips (SNS still notifies) |

Deploy-script knobs: `OFFLINE=1` (synth without AWS credentials, fake account), `RESEED=1` (re-push the checkout over an existing `main`), `YES=1` (skip the destroy confirmation), `REBUILD_FRONTEND=1` (force `npm ci && npm run build` in `dashboard`), `PORT` (dashboard port, default 8000), `PYTHON` (interpreter, default `python3`).

> `.env.example` lists runtime variables for local development; see DEVELOPMENT.md. Note that `RCA_MAX_TURNS` and `RCA_CONFIDENCE_THRESHOLD` appear there but are **not read by the code** — the limits are hardcoded (6 turns, 0.6 threshold).

## `scripts/deploy.sh`

| Command | What it does |
|---|---|
| *(no arg)* / `up` | `preflight → bootstrap → synth → deploy → seed → seed-knowledge → secrets → verify`, stops at the first failure |
| `preflight` | Python/Node versions, CDK libs importable, pip/uv present; resolves account+region from STS; validates `CODECOMMIT_REPO`; checks OpsCenter reachability and Bedrock model availability |
| `bootstrap` | `cdk bootstrap` only if the `CDKToolkit` stack is missing |
| `synth` | Bundles every Lambda for Linux/cp312 (no Docker) and writes `cdk.out/`; `OFFLINE=1` needs no credentials |
| `diff` | `cdk diff --all` |
| `deploy` | `cdk deploy --all --require-approval never`, outputs to `cdk-outputs.json` |
| `seed` | Pushes the git-tracked files of this checkout to the **platform repo** (`CODECOMMIT_REPO`) `main` via the CodeCommit API (boto3 + IAM; no git credentials). Skipped if `main` exists, unless `RESEED=1` |
| `seed-knowledge` | Uploads generated sample runbooks (`src/opspilot/knowledge/corpus.json`) to the knowledge bucket; starts an ingestion job when `KNOWLEDGE_BASE_ID` is set |
| `secrets` | Writes `SLACK_WEBHOOK_URL` into `opspilot/slack` (only values present in env) |
| `verify` | Post-deploy smoke test (see below) |
| `outputs` | Prints every stack output |
| `dashboard` | Builds `frontend/` if needed and serves the dashboard on `0.0.0.0:${PORT:-8000}`; exports AWS region and `aws login` session credentials for boto3 |
| `checkpoint1 [ui\|app]` | Delegates to `checkpoint1/start.sh ec2` (Checkpoint 1 UI on :8001) |
| `destroy` | `cdk destroy --all --force` after confirmation. Secrets Manager keeps `opspilot/*` secrets for the 7–30-day recovery window; the platform repo is RETAINed |
| `help` | Prints this list |

`verify` (implemented in `scripts/deploy_check.py`) checks: the 3 stacks; all 9 Lambda functions Active (`opspilot-ingest`, `-collect-context`, `-run-rca`, `-create-ticket`, `-propose-fix`, `-mark-needs-human`, `-notify`, `-parse-verification`, `opspilot-sample-service`); state machine `opspilot`; EventBridge rule `opspilot-alarm-trigger` enabled and targeting ingest; the 6 headline alarms; the Slack secret; OpsCenter reachability; both CodeCommit repos (`opspilot-sample-service` with `main`, `buildspec.yml`, `sample_service/app.py`, and pipeline stages Source→Build→Deploy; the platform repo with the seeded checkout); and live `GET /health` + `GET /faults` on the sample service. It prints the service URL and the `OpsPilot-SampleService` CloudWatch dashboard link.

## `scripts/ec2.sh` (demo instance process control)

Dashboard on `http://<public-ip>:8000` (log `/tmp/dashboard.log`), Checkpoint 1 UI on `:8001` (log `/tmp/checkpoint1.log`).

| Command | What it does |
|---|---|
| `startup [dashboard\|checkpoint1\|all]` | Starts the selected processes (prefers the active conda env, falls back to `.venv`, then PATH python); waits for the port and fails loudly with the log if the process dies |
| `kill [dashboard\|checkpoint1\|all]` | Stops listeners on the ports |
| `restart […]` | kill + startup |
| `redeploy` | `git pull`, then updates the existing stacks (never destroys, never creates a second copy) |
| `fix` | `git pull` + restart the main dashboard (the Raise PR region fix) |
| `status` | Shows listeners, PIDs, and URLs |
| `logs [dashboard\|checkpoint1]` | Tails the process log |
| `login` | `aws login` for instance credentials |
| `verify` | Runs `scripts/deploy_check.py verify` |
| `open-ports` | Idempotently allows inbound TCP 8000/8001 from your IP in the instance security group |

## What gets deployed

### `OpsPilotCoreStack` (`infra/core_stack.py`)
- DynamoDB table **`opspilot-incidents`** (PK `incident_id`, PAY_PER_REQUEST, TTL attribute `ttl`) — dedup claims, incident audit trail, timeline.
- CodeCommit repo **`opspilot-aws`** (or `CODECOMMIT_REPO`; RETAIN on destroy) — platform repo seeded with this checkout.
- Secrets Manager: **`opspilot/slack`** (webhook), plus deprecated `opspilot/jira` and `opspilot/github` kept one release for export-import ordering.
- S3 **knowledge bucket** (RETAIN, SSL-enforced, public access blocked) + Bedrock **knowledge base role**.
- SNS topic **`opspilot-alerts`**.

### `OpsPilotSampleServiceStack` (`infra/sample_service_stack.py`, `infra/app_delivery.py`)
- Lambda **`opspilot-sample-service`** (FastAPI + Mangum, 256 MB / 30 s — the memory ceiling is part of the `reports` fault), log group `/aws/lambda/opspilot-sample-service` (1-week retention).
- CodeCommit repo **`opspilot-sample-service`** seeded with the storefront code + buildspec, CodePipeline **`opspilot-sample-service`** (Source → Build → Deploy): CodeBuild publishes a Lambda version, CodeDeploy shifts alias **`live`**. The public Function URL is attached to the `live` alias, so alarms watch exactly what users hit, and a merged fix PR is what the next pipeline run deploys.
- 13 CloudWatch alarms: 11 per-component error alarms driven by JSON metric filters (`$.event = unhandled_exception` + `$.component`, namespace `OpsPilot/SampleService`, ≥1/min): `OpsPilotSampleServiceErrors` (orders), `-CheckoutErrors`, `-InventoryDbTimeouts`, `-BasketErrors`, `-ConfigErrors`, `-PaymentTimeouts`, `-WriteThrottles`, `-PricingErrors`, `-ShipmentErrors`, `-RefundErrors`, `-TaxErrors`; plus `-LatencyP95` (p95 ≥ 3000 ms) and `-Crashes` (Lambda Errors ≥ 1).
- CloudWatch dashboard **`OpsPilot-SampleService`** (alarm states, requests vs errors, p95 + crashes, recent exceptions log query).

### `OpsPilotPipelineStack` (`infra/pipeline_stack.py`)
- 8 Lambdas (Python 3.12, one shared bundle: `src/opspilot` + `requirements-lambda.txt`): `opspilot-collect-context`, `opspilot-run-rca`, `opspilot-create-ticket`, `opspilot-propose-fix`, `opspilot-mark-needs-human`, `opspilot-notify`, `opspilot-parse-verification`, `opspilot-ingest`. All get `OPSPILOT_MODE=live` and `CODECOMMIT_REPO=opspilot-sample-service` (the storefront repo — fix PRs and RCA source reads target it, not the platform repo).
- Step Functions state machine **`opspilot`** built from `statemachine/opspilot.asl.json` (ARN placeholders substituted at synth; an unsubstituted placeholder fails the build).
- CodeBuild project **`opspilot-verify-fix`** (two-phase buildspec inlined from `src/opspilot/verify/buildspec.yml`).
- EventBridge rule **`opspilot-alarm-trigger`**: `CloudWatch Alarm State Change`, alarm-name prefix `OpsPilotSampleService`, state `ALARM` → `opspilot-ingest` (DLQ `opspilot-ingest-dlq`, 4 retries, 2 h max age).
- Alarm **`opspilot-executions-failed`** (ExecutionsFailed ≥ 1 → SNS) — pages a human when the pipeline itself fails.
- IAM: Bedrock scoped to the configured model + inference-profile ARNs (`bedrock:Retrieve` on the KB only when `KNOWLEDGE_BASE_ID` is set); CodeCommit scoped to the storefront repo ARN (read actions; PR-write actions for propose-fix; title/comment actions for mark-needs-human — **no merge permission anywhere**); OpsCenter `CreateOpsItem`/`DescribeOpsItems` (not resource-scopable) + `Get/UpdateOpsItem` on `opsitem/*`; `states:StartExecution` on the one state machine; `lambda:InvokeFunction` on the 7 pipeline functions only.

## Teardown

```bash
bash scripts/deploy.sh destroy        # asks for confirmation; YES=1 skips
```

Retained by design: both CodeCommit repos (fix history survives) and the knowledge bucket. The sample-service Function URL is public (auth NONE) and serves only the demo — destroy the stacks after the event.
