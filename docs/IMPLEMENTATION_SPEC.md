# Implementation spec (hand-off to the coding agent)

**Stack:** Python 3.12 Lambdas, AWS CDK v2 (Python) for infrastructure, `boto3`, `httpx`, `pydantic` v2, `pytest`, `moto` for unit tests. Region from `AWS_REGION`.

## Target layout
```
infra/                 CDK app (stacks: Core, SampleService, Pipeline)
src/opspilot/
  contracts.py         pydantic models generated from / matching contracts/*.schema.json
  collect_context.py   handler(event) -> ContextBundle
  rca/agent.py         Bedrock Converse tool-use loop; tools in rca/tools.py
  route.py             (pure) classification+confidence -> route
  jira_client.py       create_issue(rca) -> TicketRef   (ADF description)
  fix/agent.py         produce {repro_test, patch}; fix/git_ops.py apply/push/PR
  verify/buildspec.yml two-phase check (base must fail, fix must pass)
  notify.py            Slack Block Kit + SNS
  redact.py            PII/secret scrubbing
sample_service/        FastAPI-on-Lambda (Mangum) app with GET /orders/{id};
                       bug: missing order -> None.total -> AttributeError (500)
                       + its own tests/ (pass on main; no test covers the bug)
statemachine/opspilot.asl.json
evals/fixtures/*.json  recorded context bundles + gold labels; evals/run_evals.py
tests/                 unit tests for every module (Bedrock/Jira/GitHub mocked)
Makefile               make test | make deploy | make trigger-incident | make eval
.env.example
```

## Milestones and acceptance criteria
**M1 — Trigger path.** `make trigger-incident` calls the bad endpoint 5 times. Within 2 minutes an execution of `opspilot` starts. A second trigger inside 15 minutes does NOT start another execution (dedup).

**M2 — RCA.** For the sample bug, `rca_result` validates against the schema, has `classification=code_defect`, names `sample_service/app.py` and the faulting line in `suspected_location`, and every evidence ref resolves. Unit test: given a context bundle with no stack trace, the result is `insufficient_evidence`.

**M3 — Ticket.** A Jira issue is created in `JIRA_PROJECT_KEY` with labels `opspilot`, `cls:code_defect`, the RCA summary and evidence. Idempotent: re-running the step for the same incident ID returns the existing key (search by label `inc:<id>`).

**M4 — PR.** Branch `opspilot/<JIRA-KEY>` holds the fix + a new test under `sample_service/tests/test_opspilot_<key>.py`. PR title `[OpsPilot] <JIRA-KEY>: <summary>`; the body includes RCA, evidence, the Jira link and "🤖 generated — requires human review". Patch limits from ARCHITECTURE.md are enforced in code with unit tests.

**M5 — Verify + notify.** CodeBuild reports `repro_fails_on_base=true`, `suite_passes_on_fix=true`. The Slack message holds all links and the verdict. Forced-failure test: a deliberately wrong patch gives one retry, then a draft PR with a `needs-human` label, and the notification says so.

**M6 — Evals.** `make eval` replays ≥10 fixtures through RCA + route only, with Bedrock live or recorded. It reports: classification accuracy, location hit rate, abstention precision (abstained when the gold label says no evidence), evidence-ref validity rate, mean tokens and latency. Fixtures: the sample bug, a missing env var, a config value typo, a downstream timeout (gold: `dependency`, no PR), and noise logs with no fault (gold: `insufficient_evidence`).

## Config (.env.example)
```
AWS_REGION=
BEDROCK_MODEL_ID=            # current Claude Sonnet model / inference profile in your region
GITHUB_REPO=owner/name       # repo the patch agent targets (this repo for the POC)
GITHUB_TOKEN_SECRET_ARN=     # fine-grained PAT: contents+pull_requests on that repo only
JIRA_BASE_URL=  JIRA_EMAIL=  JIRA_PROJECT_KEY=  JIRA_TOKEN_SECRET_ARN=
SLACK_WEBHOOK_SECRET_ARN=    NOTIFY_EMAIL=
RCA_MAX_TURNS=6  RCA_CONFIDENCE_THRESHOLD=0.6  DEDUP_WINDOW_MIN=15
```

## Rules for the implementer
- Contracts in `contracts/` are the source of truth. Change them only together with the models and the ASL.
- No network calls in unit tests. `make test` must pass with no AWS credentials.
- Never give Lambda roles `bedrock:*` beyond `InvokeModel`/`Converse` for the configured model, or any IAM/write permission on other resources.
- Commit per milestone; update the README status table.
