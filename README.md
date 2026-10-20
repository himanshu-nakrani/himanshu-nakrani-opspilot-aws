# OpsPilot — AWS POC

OpsPilot is an agent pipeline that takes a production alert and carries it through to a reviewable fix:

**CloudWatch alarm → EventBridge → Step Functions → RCA agent (Bedrock) → classification → Jira ticket → fix PR (GitHub) → CodeBuild tests → Slack/SNS notification → a human merges**

This is a proof-of-concept. It targets **one** deliberately broken sample service and **deterministic code-level failures** (unhandled exceptions, missing env vars). It never merges or deploys on its own.

## Status
| Milestone | State |
|---|---|
| M0 Design docs, contracts, state machine | ✅ this commit |
| M1 Sample service + failure + alarm → EventBridge | ✅ done |
| M2 Context collector + RCA agent (Bedrock, structured output) | ✅ done |
| M3 Classifier/router + Jira ticket | ✅ done |
| M4 Patch agent → branch + PR with reproduction test | ✅ done |
| M5 CodeBuild verification + notification | ✅ done |
| M6 Offline eval harness (replay fixtures) | ✅ done |

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

## Agent Stack: AWS Strands Agents SDK + Amazon Bedrock AgentCore
OpsPilot is built using AWS's modern agentic architecture:
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
- **M6 Benchmark Evaluation Suite:** Execute and review live replays of the 10 golden historical incident fixtures with accuracy metrics and routing verdicts.
- **AWS Strands & Bedrock AgentCore Inspector:** Live panel displaying active AgentCore policies (blast radius, protected paths, evidence grounding, abstention) and Gateway tools (`query_logs`, `get_file`, `get_commit_diff`, `submit_rca`).

- **API Endpoints:**
  - `GET /` — Serves modern React SPA (with fallback to lightweight SSR template)
  - `GET /api/incidents` — List all incidents & audit logs
  - `GET /api/incidents/{id}` — Full incident RCA, evidence & unified patch diff
  - `GET /api/stats` — Incident KPI metrics and active AgentCore policies
  - `POST /api/trigger` — Simulate planted bug failure & alarm dedup
  - `GET /api/evals` — Execute live M6 benchmark fixtures replay
