# OpsPilot — AWS POC

OpsPilot is an agent pipeline that takes a production alert and carries it through to a reviewable fix:

**CloudWatch alarm → EventBridge → Step Functions → RCA agent (Bedrock) → classification → Jira ticket → fix PR (GitHub) → CodeBuild tests → Slack/SNS notification → a human merges**

This is a proof-of-concept. It targets **one** deliberately broken sample service and **deterministic code-level failures** (unhandled exceptions, missing env vars). It never merges or deploys on its own.

## Status
| Milestone | State |
|---|---|
| M0 Design docs, contracts, state machine | ✅ this commit |
| M1 Sample service + failure + alarm → EventBridge | ✅ done |
| M2 Context collector + RCA agent (Bedrock, structured output) | ⏳ |
| M3 Classifier/router + Jira ticket | ⏳ |
| M4 Patch agent → branch + PR with reproduction test | ⏳ |
| M5 CodeBuild verification + notification | ⏳ |
| M6 Offline eval harness (replay fixtures) | ⏳ |

## Repo map
- docs/ARCHITECTURE.md — components, data flow, decisions and guardrails
- docs/IMPLEMENTATION_SPEC.md — the build spec: layout, module contracts, acceptance criteria per milestone
- contracts/*.schema.json — JSON Schemas passed between the steps (these are the source of truth)
- statemachine/opspilot.asl.json — the Step Functions definition (contract; ARNs are substituted at deploy time)

## Key design choices
1. **Evidence-first RCA with abstention.** The RCA agent must cite log lines or stack frames for every claim. When evidence is weak it returns `classification: "insufficient_evidence"`; that route files a ticket and notifies, and **never opens a PR**.
2. **The issue type decides the route:** `code_defect` → fix PR; `config_regression` → revert-suggestion PR; `dependency`/`resource` → ticket + notify only.
3. **A verified PR, not just a green build.** The patch agent must add a reproduction test that fails on `main` and passes on the fix branch. CodeBuild runs both checks.
4. **Least privilege.** The LLM gets no AWS write permissions. The GitHub token can only write to `opspilot/*` branches on the one target repo. Branch protection requires a human review before merge.
5. **The model is configurable** (`BEDROCK_MODEL_ID`). The plan named Claude 3.5 Sonnet. Pick the current Claude Sonnet model or inference profile available in your Bedrock region.
