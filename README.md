# OpsPilot — AWS POC

OpsPilot is an agent pipeline that takes a production alert and carries it through to a reviewable fix:

**CloudWatch alarm → EventBridge → Step Functions → RCA agent (Strands + Bedrock) → OpsCenter OpsItem → Slack/SNS notify → an operator raises a fix PR (CodeCommit) → CodeBuild verification → a human merges → CodePipeline deploys**

This is a proof-of-concept. It targets **one** deliberately broken sample service (a FastAPI-on-Lambda storefront with 13 planted fault triggers) and **deterministic code-level failures**. It never merges and never deploys on its own.

## Status

| Milestone | State |
|---|---|
| M0 Design docs, contracts, state machine | ✅ |
| M1 Sample service + failure + alarm → EventBridge | ✅ |
| M2 Context collector + RCA agent (Bedrock, structured output) | ✅ |
| M3 Classifier/router + OpsCenter ticket | ✅ |
| M4 Patch agent → branch + PR with reproduction test | ✅ (stub generator, 4 known bugs) |
| M5 CodeBuild verification + notification | ✅ |
| M6 Offline eval harness (replay fixtures) | ✅ (offline model only; live-model eval mode is still to do) |

## Deploy

One command deploys the three stacks (core, sample service with planted faults, pipeline), seeds both CodeCommit repos and the optional knowledge base, writes secrets, and smoke-checks the result. Needs Python 3.10+, Node 22.22.2+ (or 24.15+/26+), and AWS credentials — no Docker, no AWS CLI.

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.deploy.example .env.deploy    # AWS_PROFILE/AWS_REGION, CODECOMMIT_REPO, BEDROCK_MODEL_ID
bash scripts/deploy.sh                # preflight → bootstrap → synth → deploy → seed → seed-knowledge → secrets → verify
```

Then break the service on purpose and watch OpsPilot respond:

```bash
python3 scripts/demo_faults.py list
python3 scripts/demo_faults.py orders --watch    # alarm in ~1–2 min, then the pipeline runs
```

Full reference for every subcommand, environment variable, and the AWS resources created: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Demo flow and the fault catalog: [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md).

## Dashboard

The SRE dashboard (FastAPI + React 19/TypeScript 7/Vite 8/Tailwind 4) shows every incident end-to-end:

```bash
make dashboard          # or: bash scripts/deploy.sh dashboard  → http://localhost:8000
make frontend           # Vite dev server on :5173, proxies /api to :8000
```

- **Incident stream** — live rows from the DynamoDB incidents table (plus offline fixture replays when no AWS credentials are present), filterable by classification with confidence and status.
- **RCA inspector** — summary, `file:line` suspected location, fix strategy, and grounded evidence citations (log ids, stack frames, commits).
- **Patch diff viewer + operator actions** — *I'll apply this myself* or *Raise PR*; Raise PR commits the stub patch plus a reproduction test to the storefront repo and opens one CodeCommit pull request, in-process (an alarm run can never open a PR).
- **PR lifecycle tracking** — CodeCommit PR state, CodeBuild verification verdict (commented on the PR), post-merge CodePipeline deploy status, and knowledge-base ingestion of the merged solution.
- **Simulation** — 17 scenarios that fire a real HTTP probe at the deployed sample service so the real alarm/pipeline path runs.
- **Agent runs & traces** — Strands event-loop spans, gateway tool calls, policy audit (waterfall view).
- **Tickets page** — OpsCenter OpsItems filed by OpsPilot.
- **Evals** — replays the 10 M6 fixtures through the offline model and reports the metrics.

On the EC2 demo instance, `scripts/ec2.sh` controls the processes (dashboard `:8000`, Checkpoint 1 UI `:8001`): `startup`, `kill`, `restart`, `redeploy`, `fix`, `status`, `logs`, `login`, `verify`, `open-ports`. It does not create stacks; `scripts/deploy.sh` does.

## Repo map

| Path | What it is |
|---|---|
| `src/opspilot/` | Pipeline code: ingest/dedup, context collector, RCA agent (+grounding), router, OpsCenter ticketing, fix agent (CodeCommit/GitHub), verify, notify, knowledge base, local AgentCore-style modules |
| `dashboard/` | FastAPI app + scenario catalog + agent-run records |
| `frontend/` | React SPA served by the dashboard (`frontend/dist`) |
| `infra/` | CDK stacks: `CoreStack`, `SampleServiceStack`, `PipelineStack` + app delivery (CodePipeline/CodeDeploy) |
| `sample_service/` | The deliberately broken storefront (FastAPI + Mangum on Lambda) and its planted faults |
| `statemachine/opspilot.asl.json` | Step Functions definition (ARN placeholders substituted at deploy) |
| `contracts/*.schema.json` | JSON Schemas passed between steps — the source of truth |
| `scripts/` | `deploy.sh`, `deploy_check.py`, `ec2.sh`, `demo_faults.py`, `trigger_incident.py` |
| `evals/` | M6 harness + 10 recorded fixtures with gold labels |
| `tests/` | Unit tests (moto/fakes, no network, no credentials) |
| `checkpoint1/` | Frozen hackathon Checkpoint 1 snapshot (own README; UI on :8001) |
| `docs/ARCHITECTURE.md` | Components, data flow, guardrails |
| `docs/DEPLOYMENT.md` | Deploy/ops reference: scripts, stacks, env vars, IAM |
| `docs/DEVELOPMENT.md` | Local dev, modes, testing, evals, dashboard API |
| `docs/DEMO_RUNBOOK.md` | Demo flow + full fault/scenario catalog |
| `docs/IMPLEMENTATION_SPEC.md`, `docs/REVIEW_FIXES.md` | Historical: original build spec and engineering-review fix log |

## Key design choices

1. **Evidence-first RCA with abstention.** Every RCA goes through `opspilot.rca.grounding.ground_rca`: evidence refs must match the context bundle exactly (log ids, stack-frame `file:line`, commit SHAs). Fabricated refs, a `code_defect` without a grounded stack frame, Bedrock errors, empty/`max_tokens` responses, malformed output after one repair attempt, or no `submit_rca` within 6 turns all force `insufficient_evidence` with confidence ≤ 0.4 — a route that files a ticket and notifies but **never offers a PR**.
2. **The classification decides the route.** `code_defect` at confidence ≥ 0.6 *with* a stack-frame-backed `suspected_location` → a suggested diff the operator can apply or raise as a PR. `config_regression` (no revert agent yet), `dependency`, `resource`, `insufficient_evidence` → ticket + notify only.
3. **A verified PR, not just a green build.** The fix agent adds a reproduction test that must fail on the base commit (pytest exit code 1, not "file missing") and pass with the fix. CodeBuild runs both phases and comments the verdict on the PR. A failed verification goes to `MarkNeedsHuman`, never to a retry of the identical patch.
4. **The fix agent is a stub that knows it.** It only patches the 4 planted bugs it has generators for (`get_order`, `create_order`, `checkout`, `payment_status`) and raises `UnsupportedFixTarget` for anything else. Patches are capped at 3 files / 80 lines with protected paths (CI config, IaC, contracts, dependency manifests).
5. **Least privilege, human in the loop.** The LLM gets no AWS write permissions. Source control is CodeCommit with IAM only (no Git tokens); the fix Lambda's role is scoped to the one repo ARN with branch/commit/PR permissions but **no merge permission**. Bedrock is scoped to the configured model ARN. Every alarm-path failure routes to Notify; a failed execution alarms SNS via `opspilot-executions-failed`.
6. **Prompt-injection hygiene.** Logs, code, and commits reach the model inside `<untrusted_*>` tags with explicit do-not-follow instructions; `get_file` is sandboxed to the repo checkout (no absolute paths, `..`, `.git/`, `.env*`); `get_commit_diff` accepts hex SHAs only. PII/secrets (emails, IPs, AWS keys, tokens) are redacted before any Bedrock call.
7. **The model is configurable** (`BEDROCK_MODEL_ID`, default `us.moonshotai.kimi-k3`). Model quirks are handled in code: Kimi K3 rejects `temperature` and replayed reasoning blocks, so both are stripped.
8. **Optional long-term memory.** When `KNOWLEDGE_BASE_ID` is set, merged-PR solutions are ingested into a managed Bedrock Knowledge Base and the RCA agent can call `retrieve_knowledge` to find how a similar incident was fixed before.

## Agent stack: Strands SDK + AgentCore-style components

> **Honesty note:** the agent loop uses the real Strands SDK (`strands-agents`) and real Bedrock
> (`strands.models.bedrock.BedrockModel`). The "AgentCore" Runtime/Gateway/Policy/Memory classes are
> **local Python modules modelled on Amazon Bedrock AgentCore concepts** (`src/opspilot/agentcore/`).
> They do not call the AgentCore service, MCP, or any AgentCore AWS resource.

- **Strands agent loop** — `strands.Agent` with `@tool` functions, multi-turn reasoning, streaming events; `OPSPILOT_AGENT_BACKEND=converse` switches to the plain Bedrock Converse loop instead.
- **AgentCore Runtime (local)** — session lifecycle, model selection (live `BedrockModel` vs the deterministic `AgentCoreOfflineModel` for tests/evals/offline demos), CloudWatch EMF telemetry (`OpsPilot/AgentCore`).
- **AgentCore Gateway (local)** — tool registry with Bedrock/MCP-compatible schemas: `retrieve_knowledge`, `query_logs`, `get_file`, `get_commit_diff`, `submit_rca`.
- **AgentCore Policy (local)** — blast-radius guardrails (3 files / 80 lines, protected paths), evidence grounding verification, forced abstention.
- **AgentCore Memory (local)** — per-session working memory: tool audit trail, ruled-out hypotheses, notes, token counts.

Details and the full data-flow diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

```bash
make test               # pytest, fake AWS credentials, no network
make eval               # replay the 10 fixtures (offline model unless real AWS creds are exported)
make trigger-incident   # local M1 dedup demo (in-process, moto)
```

Local runs default to `OPSPILOT_MODE=replay`; deployed Lambdas get `live`, where every external write either succeeds and is recorded or raises so Step Functions can route the failure. Replay only changes what a *failed* write does (log instead of raise) — it does not by itself make a run offline. The RCA agent picks the deterministic offline model by **credentials**: a real `AWS_ACCESS_KEY_ID` (or `OPSPILOT_LIVE=1`) selects live Bedrock instead, so force offline evals with `env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY make eval`. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Deliberately out of scope

Multi-service causal analysis, metric anomaly detection, auto-merge or auto-deploy, multi-repo support, GitLab, Datadog/Sentry ingestion (the design is source-neutral: only CollectContext changes), live-model evals, a real (non-stub) patch agent, an AWS Incident Manager integration (AWS closed it to new customers on 2025-11-07; OpsCenter is the supported alternative).
