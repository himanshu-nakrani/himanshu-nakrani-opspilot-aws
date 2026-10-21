# OpsPilot hackathon demo runbook

The demo target is the sample storefront service (`sample_service/`): FastAPI on
Lambda behind a public Function URL. It has five deliberately planted faults.
Each one has its own CloudWatch alarm, and every alarm name starts with
`OpsPilotSampleService`. One EventBridge rule matches that prefix and starts
the OpsPilot Step Functions pipeline (ingest -> CollectContext -> RCA -> route
-> Jira / fix PR / verify / notify).

## 1. Deploy (once)

Prerequisites: AWS credentials for the target account and region, Node 18+,
Python 3.12 deps (`pip install -r requirements.txt`), and a CDK bootstrap
(`npx aws-cdk@2 bootstrap`). Docker is **not** required. Lambda assets are built
locally with Linux/cp312 wheels (`infra/bundling.py`), with Docker as a fallback.

```bash
make demo-deploy        # cdk deploy --all
```

Outputs: `SampleServiceUrl` (the service) and the `OpsPilot-SampleService`
CloudWatch dashboard (alarm status, requests vs errors, p95 latency, recent
exceptions).

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
- The Function URL is public (auth NONE) and serves only the demo service. Run `cdk destroy --all` after the event.
