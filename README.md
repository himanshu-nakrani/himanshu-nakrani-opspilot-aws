# OpsPilot — AWS POC

OpsPilot is an agent pipeline that takes a production alert and carries it through to a reviewable fix:

**CloudWatch alarm → EventBridge → Step Functions → RCA agent (Bedrock) → classification → AWS OpsCenter OpsItem → fix PR (AWS CodeCommit) → CodeBuild tests → Slack/SNS notification → a human merges**

This is a proof-of-concept. It targets **one** deliberately broken sample service and **deterministic code-level failures** (unhandled exceptions, missing env vars). It never merges or deploys on its own.

## Status
| Milestone | State |
|---|---|
| M0 Design docs, contracts, state machine | ✅ this commit |
| M1 Sample service + failure + alarm → EventBridge | ✅ done |
| M2 Context collector + RCA agent (Bedrock, structured output) | ✅ done |
| M3 Classifier/router + OpsCenter ticket | ✅ done |
| M4 Patch agent → branch + PR with reproduction test | ✅ done |
| M5 CodeBuild verification + notification | ✅ done |
| M6 Offline eval harness (replay fixtures) | ✅ done |

## Deploy

One command deploys the whole stack (core, sample service with planted faults, pipeline), writes secrets and checks the result:

```bash
cp .env.deploy.example .env.deploy   # AWS profile/region, CodeCommit repo name
bash scripts/deploy.sh                    # preflight -> bootstrap -> synth -> deploy -> secrets -> verify
```

See docs/DEMO_RUNBOOK.md for every subcommand and the demo flow.

On the EC2 instance, `scripts/ec2.sh` starts and stops the demo processes. It does not create the stacks; `bash scripts/deploy.sh` does that.

```bash
bash scripts/ec2.sh startup          # dashboard :8000 and Checkpoint 1 UI :8001
bash scripts/ec2.sh kill             # stop both
bash scripts/ec2.sh restart
bash scripts/ec2.sh redeploy         # git pull, then update the existing stacks
bash scripts/ec2.sh fix              # git pull, restart the dashboard (Raise PR region)
bash scripts/ec2.sh status
bash scripts/ec2.sh logs dashboard
bash scripts/ec2.sh verify
bash scripts/ec2.sh open-ports       # inbound TCP 8000 and 8001
```

## Repo map
- docs/ARCHITECTURE.md — components, data flow, decisions and guardrails
- docs/IMPLEMENTATION_SPEC.md — the build spec: layout, module contracts, acceptance criteria per milestone
- contracts/*.schema.json — JSON Schemas passed between the steps (these are the source of truth)
- statemachine/opspilot.asl.json — the Step Functions definition (contract; ARNs are substituted at deploy time)

## Key design choices
1. **Evidence-first RCA with abstention.** The RCA agent must cite log lines or stack frames for every claim. When evidence is weak it returns `classification: "insufficient_evidence"`; that route files a ticket and notifies, and **never opens a PR**.
2. **The issue type decides the route:** `code_defect` → fix PR; `config_regression` → ticket + notify until a revert agent exists; `dependency`/`resource` → ticket + notify only.
3. **A verified PR, not just a green build.** The patch agent must add a reproduction test that fails on `main` and passes on the fix branch. CodeBuild runs both checks.
4. **Least privilege.** The LLM gets no AWS write permissions. Source control is AWS CodeCommit with IAM only (no Git tokens): the fix Lambda's role is scoped to the one repo ARN and can create branches/commits/PRs but has no merge permission, so a human merges every fix.
5. **The model is configurable** (`BEDROCK_MODEL_ID`). The default is the Moonshot Kimi K3 US inference profile, `us.moonshotai.kimi-k3`.

## Agent Stack: AWS Strands Agents SDK + AgentCore-style components
> **Honesty note:** the agent loop uses the real Strands SDK (`strands-agents`) and Bedrock.
> The "AgentCore" Runtime/Gateway/Policy/Memory classes are **local Python modules modelled on
> Amazon Bedrock AgentCore concepts**. They do not call the AgentCore service, MCP or any AgentCore
> AWS resource. Swap in the real AgentCore SDK only if you need long sessions or cross-incident memory.

### RCA safety rules (enforced in code)
- Every RCA from any path goes through `opspilot.rca.grounding.ground_rca`. Evidence refs must match
  the context bundle exactly (log ids, stack-trace `file:line`, commit SHAs). Any fabricated ref, or a
  `code_defect` without a grounded stack frame/commit, makes the result **abstain** (`insufficient_evidence`).
- Bedrock errors, empty/`max_tokens` responses, malformed output after one repair, or no `submit_rca`
  within `max_turns` all **abstain**. The keyword heuristic is offline-only and capped below the PR threshold.
- A suggested diff needs `code_defect` + confidence ≥ 0.6 + a `suspected_location` backed by matching stack-frame evidence.
  The pipeline stops there. The incident screen offers two actions: apply the diff yourself, or raise a CodeCommit pull request.
  `config_regression` files a ticket and notifies until a revert agent exists.
- The fix agent refuses anything but the planted sample bug, and never opens a PR if a git step fails.
- Model tools are sandboxed: `get_file` stays inside the repo (no absolute paths, `..`, `.git/`, `.env*`);
  `get_commit_diff` only accepts hex SHAs. Logs/code/commits reach the model inside `<untrusted_*>` tags.
- `BEDROCK_MODEL_ID` and `AWS_REGION` are read from the environment; set `OPSPILOT_AGENT_BACKEND=converse`
  to use the plain Converse loop instead of Strands.

Component overview:
- **AWS Strands Agents SDK (`strands-agents`):** Model-first agent execution loop (`strands.Agent`, `@tool` decorators, streaming events, multi-turn reasoning).
- **Amazon Bedrock AgentCore Architecture:**
  - **AgentCore Runtime:** Serverless agent execution environment, session isolation, task handoff, and CloudWatch EMF telemetry (`OpsPilot/AgentCore`).
  - **AgentCore Gateway:** Model Context Protocol (MCP) compatible tool gateway (`query_logs`, `get_file`, `get_commit_diff`, `submit_rca`).
  - **AgentCore Policy:** Blast-radius guardrails (max 3 files / 80 lines, protected files check), evidence grounding verification, and automatic abstention on noisy logs.
  - **AgentCore Memory:** Structured working memory for session state, ruled-out hypotheses, and tool audit trails.

## SRE Dashboard (React + Vite + Tailwind + FastAPI)
OpsPilot provides a modern, responsive SRE operational dashboard built with **React 18, TypeScript, Vite, Tailwind CSS, and Lucide icons**, served by the **FastAPI** backend:

### Running the Dashboard
```bash
# 1. Full Production Mode: Run FastAPI with integrated React SPA:
make dashboard
# -> Open http://localhost:8000

# 2. Frontend Development Mode (Vite Hot-Reload):
make frontend
# -> Open http://localhost:5173 (proxies /api requests to FastAPI on port 8000)

# 3. Build React distribution:
make build-frontend
```

### Dashboard Features
- **Live Incident Stream & Audit Trail:** Search, filter, and inspect incidents by classification (`code_defect`, `config_regression`, `dependency`, `resource`, `insufficient_evidence`) with confidence bars and status indicators.
- **Root Cause & Grounded Evidence Inspector:** View full RCA summaries, pinpointed source file:line locations, suggested fix strategies, and validated citations (log IDs, stack trace frames, git commits).
- **Interactive Unified Patch Diff Viewer:** Syntax-highlighted git diff display with additions (`+`), deletions (`-`), and hunk headers.
- **One-Click Incident Simulation (M1):** Trigger the planted missing-order bug on `sample-service`, observe CloudWatch metric filter thresholds, alarm state transitions, DynamoDB 15-minute dedup verification, and automated patch creation.
- **M6 Benchmark Evaluation Suite:** Replays the 10 fixtures through the scripted offline model. These scores check the plumbing, not model quality; a live-model eval mode is still to do.
- **AWS Strands & Bedrock AgentCore Inspector:** Live panel displaying active AgentCore policies (blast radius, protected paths, evidence grounding, abstention) and Gateway tools (`query_logs`, `get_file`, `get_commit_diff`, `submit_rca`).

- **API Endpoints:**
  - `GET /` — Serves modern React SPA (with fallback to lightweight SSR template)
  - `GET /api/incidents` — List all incidents & audit logs
  - `GET /api/incidents/{id}` — Full incident RCA, evidence & unified patch diff
  - `GET /api/stats` — Incident KPI metrics and active AgentCore policies
  - `POST /api/trigger` — Simulate planted bug failure & alarm dedup
  - `GET /api/evals` — Execute live M6 benchmark fixtures replay
