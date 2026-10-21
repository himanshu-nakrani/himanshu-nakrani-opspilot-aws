# Engineering review fixes: reliability, failure handling, security boundaries

Branch: `eng-lead/reliability-fixes` (base `78b86eb`). Covers the system-level findings from the Engineering Lead review.
Agent-side findings (RCA grounding, prompts, Strands/AgentCore loop, route rules, real patch agent) are on the AI Engineering Lead's branch `ai-eng/fix-review-findings`.
Dashboard CORS and simulated-data findings are on `frontend/fix-review-findings`.

## Principle
The pipeline never reports a success it did not observe. Every external write either succeeds and is recorded, or raises so Step Functions can route the failure to Notify.

## Changes

| Finding | Fix | Files |
|---|---|---|
| R1. Fix branch was never pushed. GitHub token was never read. PR failure returned a fake `pull/1` | `GitHubClient` commits only the approved files through the GitHub Git Data API (no git binary in Lambda) and opens PRs idempotently. The token comes from `GITHUB_TOKEN` or Secrets Manager. Any non-2xx response raises `GitHubError` | `src/opspilot/fix/git_ops.py`, `src/opspilot/fix/agent.py` |
| R2 (interim). Hardcoded patch was applied to any incident | Merged with the AI lead’s `ensure_supported_fix` gate: only `code_defect` in `sample_service/app.py:get_order` and raises `UnsupportedFixTarget` for any other file. The diff is applied with a pure-Python applier that checks context, so a patch that doesn't match is rejected (`PatchApplyError`) | `fix/agent.py`, `fix/git_ops.py` |
| Ticket failure returned a fake `OPS-99` ticket | Raises `TicketingError` (Jira since replaced by OpsCenter) | `src/opspilot/ticketing.py` |
| R3. Lambdas shipped without their libraries | One shared bundled asset (`requirements-lambda.txt` plus `src/opspilot`) | `infra/pipeline_stack.py`, `requirements-lambda.txt` |
| R4. RCA failure skipped ticket and notify | ASL rewrite. A failure in CollectContext or RunRCA goes to `BuildAbstainRca` (insufficient_evidence, confidence 0), then CreateTicket, then Notify. Every Task has Retry, Catch and TimeoutSeconds. If Notify itself fails, the run ends in `NotifyFailed` and a CloudWatch alarm on failed executions alerts SNS | `statemachine/opspilot.asl.json`, `infra/pipeline_stack.py` |
| Retrying the identical patch | A failed verification goes straight to MarkNeedsHuman until a real (non-deterministic) patch agent exists | ASL |
| R8. CodeBuild output was misread | New `ParseVerification` Lambda converts the Build object (or the error Cause) to a `VerificationResult` using the variables the buildspec exports | `src/opspilot/verify/runner.py` |
| Buildspec false positive: the repro test doesn't exist on base, so pytest's "file not found" counted as "fails on base" | The repro test is copied onto the base checkout, and only pytest exit code 1 counts as a real failure | `src/opspilot/verify/buildspec.yml` |
| R9. Dedup could lose an incident | The claim is written as PENDING, then promoted to STARTED after the execution exists. A stale PENDING claim can be re-claimed. Execution names are deterministic. `ExecutionAlreadyExists` is treated as success. Records get a TTL | `src/opspilot/ingest.py` |
| R11. Mode was inferred from credential env vars | Explicit `OPSPILOT_MODE` (live/replay). CDK sets `live` on every Lambda | `src/opspilot/config.py` |
| R12. Audit writes failed silently | `update_incident()` raises in live mode and only logs in replay | `src/opspilot/audit.py` |
| Notify | Final status is FAILED / VERIFIED / NEEDS_HUMAN / NOTIFIED. In live mode it raises if no channel delivered | `src/opspilot/notify.py` |
| MarkNeedsHuman | Requires `pr_number`. GitHub failure raises | `fix/agent.py` |
| IAM wildcards | Bedrock is scoped to the model (and its inference profile). Lambda invoke, CodeBuild, `states:StartExecution` and the events rule are scoped to specific ARNs. The synthesized template has 0 `Resource: "*"` statements. EventBridge target has a DLQ and retries | `infra/pipeline_stack.py` |

## Tests
- `tests/test_reliability_fixes.py`: ASL invariants (every state reaches Notify, every Task has a timeout and Catch, RCA failure abstains, Route requires no recorded error), stale PENDING re-claim, ParseVerification verdicts, Jira failure raises.
- `tests/test_fix_agent.py`: rewritten against a fake GitHub. It checks the committed file set, that a PR failure raises, that unsupported targets are refused, that a non-matching patch is rejected, and that MarkNeedsHuman labels the PR.

## Not verified
Nothing was deployed. Live behaviour of the Git Data API calls, CodeBuild exported variables and the Step Functions catch paths is covered by unit tests and a CDK synth, not an AWS run.
