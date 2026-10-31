# OpsPilot demo runbook

The demo target is the sample storefront service (`sample_service/`): FastAPI on Lambda behind a public Function URL attached to the `live` alias. It carries **13 planted fault triggers**; each component has its own CloudWatch alarm, and every alarm name starts with `OpsPilotSampleService`. One EventBridge rule matches that prefix and starts the OpsPilot Step Functions pipeline (ingest → CollectContext → RCA → OpsCenter OpsItem → route → notify). Fix pull requests are operator-raised from the dashboard and land in the storefront repo `opspilot-sample-service`, which CodePipeline deploys.

## 1. Deploy (once)

Everything (CoreStack, SampleServiceStack, PipelineStack) deploys with one command:

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.deploy.example .env.deploy      # AWS_PROFILE/AWS_REGION, CODECOMMIT_REPO, BEDROCK_MODEL_ID
bash scripts/deploy.sh                  # or: make deploy
```

`bash scripts/deploy.sh` (no argument means `up`) runs these steps in order and stops at the first failure:

| Step | What it does |
|---|---|
| preflight | Python 3.10+, Node 22.22.2+ (or 24.15+/26+), CDK libs, pip/uv; reads account and region from STS; validates `CODECOMMIT_REPO` (owned, or imported when `CODECOMMIT_REPO_EXISTS=1`); checks OpsCenter reachability and warns if the Bedrock model is not enabled |
| bootstrap | `cdk bootstrap` only if the CDKToolkit stack is missing |
| synth | Bundles every Lambda for Linux/cp312 (no Docker) and writes `cdk.out/` |
| deploy | `cdk deploy --all`; stack outputs go to `cdk-outputs.json` |
| seed | Pushes the git-tracked files of this checkout to the platform repo's `main` via the CodeCommit API (boto3 + IAM; no git credentials, no AWS CLI). Skipped if `main` exists; `RESEED=1` pushes on top |
| seed-knowledge | Uploads the generated sample runbooks to the knowledge bucket and syncs the Bedrock knowledge base when `KNOWLEDGE_BASE_ID` is set (otherwise S3-only, with a warning) |
| secrets | Writes the optional `SLACK_WEBHOOK_URL` into `opspilot/slack`. Blank is skipped. Ticketing (OpsCenter) and CodeCommit need no tokens |
| verify | Checks the 3 stacks, 9 Lambdas, the `opspilot` state machine, the EventBridge rule and its target, the headline alarms, the Slack secret, OpsCenter access, both CodeCommit repos (storefront `main` with buildspec + app, pipeline stages Source→Build→Deploy), then calls `GET /health` and `GET /faults` on the live service |

Other commands: `preflight`, `bootstrap`, `synth` (`OFFLINE=1` synthesizes without AWS credentials), `diff`, `deploy`, `seed`, `seed-knowledge`, `secrets`, `verify`, `outputs`, `dashboard` (builds the frontend and serves the dashboard on :8000), `checkpoint1 [ui|app]` (Checkpoint 1 UI on :8001) and `destroy`. `bash scripts/deploy.sh help` lists them. Neither Docker nor the AWS CLI is needed. Full reference: [DEPLOYMENT.md](DEPLOYMENT.md).

Settings that become Lambda environment values (`CODECOMMIT_REPO`, `BEDROCK_MODEL_ID`, `KNOWLEDGE_BASE_ID`) are read at synth time — change one, run deploy again. Secrets can be re-written any time with `bash scripts/deploy.sh secrets`.

Outputs: `SampleServiceUrl` (the service) and the `OpsPilot-SampleService` CloudWatch dashboard (alarm status, requests vs errors, p95 latency, recent exceptions). `verify` prints both links.

## 2. Planted faults

The full catalog (also live at `GET /faults`):

| Trigger | Failure | Alarm | Expected OpsPilot path |
|---|---|---|---|
| `GET /orders/999` | 500 AttributeError | OpsPilotSampleServiceErrors | code defect → ticket → fix PR → CodeBuild verify |
| `POST /orders` (no `customer_id`) | 500 KeyError | OpsPilotSampleServiceErrors | code defect → ticket → fix PR (422 validation) |
| `GET /checkout?sku=SKU-1&qty=2&coupon=SPRING50` | 500 KeyError | -CheckoutErrors | code defect → ticket → fix PR (400 invalid coupon) |
| `GET /payments/77/status?provider=legacy` | ~6 s latency | -LatencyP95 (p95 ≥ 3000 ms) | code defect on `payment_status` → fix PR; otherwise a person |
| `GET /inventory/BULK-42` | 500 TimeoutError (DB pool) | -InventoryDbTimeouts | dependency → ticket → notify (no PR) |
| `GET /reports/export?days=90` | Lambda out of memory | -Crashes | resource → ticket → notify (no PR) |
| `GET /basket/average?count=0` | 500 ZeroDivisionError | -BasketErrors | code defect below the fix threshold → notify |
| `GET /settings` | 500 KeyError `ORDERS_TABLE` | -ConfigErrors | config_regression → notify (no revert agent yet) |
| `GET /payments/77/status?provider=down` | 500 gateway TimeoutError | -PaymentTimeouts | dependency → notify |
| `POST /writes/orders` | 500 DynamoDB throttle | -WriteThrottles | dependency → notify |
| `GET /pricing/SKU-1` | 500 TypeError (string price) | -PricingErrors | code defect, no generator → notify |
| `GET /shipments/404` | 500 IndexError | -ShipmentErrors | code defect, no generator → notify |
| `POST /refunds {}` | 500 KeyError `order_id` | -RefundErrors | code defect, no generator → notify |
| `GET /tax/quote?subtotal=10&rate=` | 500 ValueError (blank rate) | -TaxErrors | code defect, no generator → notify |

Alarm names after the first row are abbreviated: they all start with `OpsPilotSampleService`.

## 3. Run a scenario

From a terminal (`scripts/demo_faults.py` covers the five headline faults):

```bash
export SAMPLE_SERVICE_URL=https://<id>.lambda-url.<region>.on.aws   # or let the script read the stack output
python3 scripts/demo_faults.py list
python3 scripts/demo_faults.py baseline                  # healthy traffic only
python3 scripts/demo_faults.py orders --watch            # inject, then watch the alarm and the execution
# or: make demo-fault SCENARIO=inventory                 # orders|checkout|inventory|payments|reports
curl -s "$SAMPLE_SERVICE_URL/orders/999"                 # raw trigger
```

From the dashboard (**Trigger simulation** — all 17 scenarios, including the low-confidence, config, throttle, pricing, shipment, refund, and tax cases): the button fires the scenario's HTTP probe at the deployed service, so the real alarm → EventBridge → pipeline path runs; the agent, not the catalogue text, writes the incident.

Then start the dashboard if it is not running:

```bash
bash scripts/deploy.sh dashboard        # local, on :8000
# EC2 instance: bash scripts/ec2.sh startup   (dashboard :8000, Checkpoint 1 UI :8001)
```

Timeline: the alarm moves to ALARM about 1–2 min after the burst. The execution starts within seconds of that. Watch the OpsPilot dashboard, Systems Manager → OpsCenter (OpsItems with Source `OpsPilot`), and the CodeCommit console (`opspilot-sample-service` → Pull requests) after raising a PR.

**Raise PR flow:** open the incident → *Raise PR* → the stub patch + repro test are committed to `opspilot/<ticket-id>` and one PR opens → *verification* starts the CodeBuild two-phase check and comments the verdict on the PR → a human reviews and merges → the dashboard tracks the CodePipeline deploy and ingests the merged solution into the knowledge base.

## Notes and limits

- Run **one scenario at a time**. CollectContext reads the whole service log group; two simultaneous faults blur the evidence.
- Dedup is per alarm name for 15 minutes, so repeating a scenario inside that window does not open a new incident. An alarm also has to return to OK before it can fire again.
- CollectContext pulls error/warning events first (`?Traceback ?ERROR …`) and falls back to the raw window; steady traffic no longer pushes the traceback out of the first 50 events.
- The fix agent patches only the four generated bugs (orders, create_order, checkout, legacy payments). Every other incident ends with a ticket + notification and, on the dashboard, a "a person has to handle this" ending.
- The Function URL is public (auth NONE) and serves only the demo service. Run `bash scripts/deploy.sh destroy` after the event (both CodeCommit repos and the knowledge bucket are retained).
