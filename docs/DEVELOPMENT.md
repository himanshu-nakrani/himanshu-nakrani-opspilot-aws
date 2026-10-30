# Development guide

## Layout

```
src/opspilot/
  config.py            OPSPILOT_MODE (live|replay) — never inferred from credentials
  contracts.py         pydantic models matching contracts/*.schema.json (extra="forbid")
  ingest.py            EventBridge alarm handler: dedup claim + StartExecution
  collect_context.py   CloudWatch Logs (±10 min, error events first), traceback parsing, repo context
  rca/
    agent.py           Bedrock Converse tool-use loop + Lambda handler; backend selection
    strands_agent.py   Strands SDK entry (run_strands_rca)
    prompts.py         system prompt + <untrusted_*> fenced user prompt
    tools.py           tool schemas + sandboxed executors (query_logs/get_file/get_commit_diff)
    grounding.py       ground_rca / align_citations / check_evidence / abstain — single source of truth
  route.py             pure router: classification + confidence + evidence → propose_fix | notify
  ticketing.py         OpsCenter OpsItem create/update/list (idempotent), DynamoDB mirror
  fix/
    agent.py           stub patch generator (4 planted bugs) + repro tests + propose_fix/mark_needs_human handlers
    guardrails.py      patch limits (delegates to agentcore.policy)
    codecommit.py      CodeCommit client (files/branches/commits/PRs/comments) — IAM only
    git_ops.py         GitHub fallback client + pure-Python unified-diff applier
    scm.py             provider switch: SCM_PROVIDER=codecommit (default) | github
  verify/
    buildspec.yml      two-phase check: repro fails on base (pytest rc=1), suite passes on fix
    runner.py          ParseVerification: CodeBuild build → VerificationResult
    pr_check.py        dashboard-side: start/refresh the verify build, comment on the PR
  notify.py            Slack Block Kit + SNS; mirrors the outcome onto the OpsItem
  knowledge/           optional Bedrock KB: seed corpus, retrieve tool, merged-PR ingestion
  deploy/pipeline.py   post-merge CodePipeline deploy tracking for the dashboard
  agentcore/           LOCAL AgentCore-style modules: runtime, gateway, policy, memory
  redact.py            PII/secret scrubbing (emails, IPs, AWS keys, GitHub/Bearer tokens, k=v secrets)
  audit.py             DynamoDB incident updates + timeline (raises in live mode)
dashboard/             FastAPI app (app.py), scenario catalog (scenarios.py), run records (runs.py), endings text
frontend/              React 18 + TypeScript + Vite + Tailwind SPA (built into frontend/dist)
infra/                 CDK: core_stack, sample_service_stack, pipeline_stack, app_delivery, bundling
sample_service/        FastAPI+Mangum storefront with planted faults (faults.py) and its own tests
statemachine/          opspilot.asl.json — Step Functions contract (placeholders substituted by pipeline_stack)
contracts/             incident_event + rca_output JSON Schemas — the source of truth
evals/                 run_evals.py + 10 fixtures with gold labels
scripts/               deploy.sh, deploy_check.py, ec2.sh, demo_faults.py, trigger_incident.py
checkpoint1/           frozen Checkpoint 1 snapshot (self-contained; own README)
```

## Setup & commands

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # incl. strands-agents, aws-cdk-lib, moto, pytest
cd frontend && npm install && cd ..

make test               # pytest tests/ sample_service/tests/ with fake AWS env vars — no network, no credentials
make eval               # replay the 10 fixtures; exits non-zero when targets fail
make dashboard          # FastAPI on :8000 (serves frontend/dist if built)
make frontend           # Vite dev server on :5173, proxies /api → 127.0.0.1:8000
make build-frontend     # tsc && vite build → frontend/dist
make trigger-incident   # local M1 demo: hits /orders/999 in-process, shows dedup (moto)
make demo-faults        # list planted faults of the deployed service
make demo-fault SCENARIO=orders   # inject a fault against the deployed service (--watch)
cd frontend && npm test && npm run typecheck   # vitest + tsc
```

`make test` exports `AWS_ACCESS_KEY_ID=testing` etc. on purpose: `_live_aws_enabled()` treats the literal `testing` key as "not live", so tests never reach Bedrock.

## Execution modes

| Knob | Values | Meaning |
|---|---|---|
| `OPSPILOT_MODE` | `replay` (default) / `live` | Live: real AWS writes; any failure **raises** so Step Functions routes it (audit, ticketing, notify). Replay: failures only log. CDK sets `live` on every Lambda. Mode is never inferred from credentials. |
| `OPSPILOT_LIVE=1` or a real `AWS_ACCESS_KEY_ID` | — | Selects the live `BedrockModel` in the Strands runtime; otherwise `AgentCoreOfflineModel` (deterministic, grounding-aware, zero credentials) |
| `OPSPILOT_AGENT_BACKEND` | unset / `converse` | Default runs the Strands agent loop; `converse` runs the plain Bedrock Converse loop in `rca/agent.py`. An explicitly injected `bedrock_client` (unit tests) always uses the Converse loop. Without live AWS, the Converse path falls back to the offline keyword heuristic (capped below the PR threshold). |
| `BEDROCK_MODEL_ID` | default `us.moonshotai.kimi-k3` | Kimi K3 rejects `temperature` and replayed reasoning blocks; `agentcore/runtime.py` strips both. |

The dashboard works with or without AWS credentials: with credentials it reads live incidents from `opspilot-incidents` (rows carry `source: "dynamodb"`); without, it seeds an in-memory cache by replaying `evals/fixtures/` through the offline model (`source: "fixture"`, no ticket/PR links are fabricated).

## Invariants to keep when changing code

These are pinned by tests in `tests/` — don't break them silently:

- **Grounding is the only path.** Every RCA (Strands, Converse, offline model, heuristic) returns through `ground_rca`. Evidence refs must exist in the bundle; a `code_defect` needs a grounded stack frame or commit; violations force `abstain()` (`insufficient_evidence`, confidence ≤ 0.4). Citations within 8 lines of a traceback frame are aligned to it (`NEARBY_FRAME_LINES`).
- **Routing needs evidence, not just confidence.** `route_rca` returns `propose_fix` only for `code_defect`, confidence ≥ 0.6, a `suspected_location`, and a `stack_frame` evidence item whose ref is exactly `file:line`. Everything else notifies.
- **The alarm path never opens a PR.** In `opspilot.asl.json`, `ProposeFix` is reachable only when the execution input has `action = raise_pr`; the dashboard's Raise PR button calls `propose_fix` in its own process instead. Every state reaches `Notify` (or `NotifyFailed`); every Task has Retry, Catch, and TimeoutSeconds; CollectContext/RunRCA failures go through `BuildAbstainRca` → ticket → notify.
- **The stub fix agent refuses unknown targets.** `ensure_supported_fix` allows only `code_defect` in `sample_service/app.py` (`get_order`, `create_order`) or `sample_service/faults.py` (`checkout`, `payment_status`) and raises `UnsupportedFixTarget` otherwise. Patches apply through a context-checking pure-Python applier (`PatchApplyError` on mismatch). Limits: ≤ 3 files, ≤ 80 changed lines, no CI/IaC/contract/manifest paths.
- **No placeholder successes.** A failed external write raises (`TicketingError`, `CodeCommitError`/`GitHubError`); `MarkNeedsHuman` requires a `pr_number`; notify in live mode raises if no channel delivered; dashboard fields that aren't measured return `null`, never invented values; a branch name is never presented as a PR URL.
- **Dedup safety.** The claim is written `PENDING`, promoted to `STARTED` after `StartExecution`; stale PENDING claims (> `PENDING_STALE_SECONDS`, default 120) can be re-claimed; execution names are deterministic and `ExecutionAlreadyExists` counts as success; records expire via `ttl` (default 30 days).
- **Contracts are the source of truth.** `contracts/*.schema.json` ↔ `contracts.py` ↔ ASL change together, or not at all.

## Dashboard API (FastAPI, `dashboard/app.py`)

| Endpoint | Purpose |
|---|---|
| `GET /`, `GET /tickets` | React SPA from `frontend/dist`, falling back to the SSR template `dashboard/templates/index.html` |
| `GET /api/incidents` | All incidents: DynamoDB (live) merged with the fixture cache; per-item fix offer, human-ending text, knowledge preview |
| `GET /api/incidents/{id}` | One incident with full RCA, evidence, and patch diff |
| `GET /api/incidents/{id}/pr-status` | Live CodeCommit PR state + verify build + post-merge deploy tracking + knowledge ingestion (refreshes stored fields) |
| `POST /api/incidents/{id}/fix-choice` | `{"action": "apply_myself" \| "raise_pr"}` — records the choice or opens the CodeCommit PR in-process (one PR per incident; Raise PR stays available after apply-myself) |
| `GET /api/tickets?view=open\|in_progress\|resolved\|all` | OpsCenter OpsItems filed by OpsPilot + ticket labels recorded on incidents |
| `GET /api/stats` | KPIs and active AgentCore policies; unmeasured values are `null` |
| `GET /api/scenarios` | The 17 simulatable scenarios (`dashboard/scenarios.py`) |
| `POST /api/trigger` | `{"scenario": "<id>"?}` — fires the scenario's HTTP probe at the deployed sample service so the real alarm → EventBridge → pipeline path runs (default `null_order`) |
| `GET /api/runs`, `GET /api/runs/{run_id}` | Agent runs recorded by this process: Strands spans as a waterfall, tool history, policy audit |
| `GET /api/evals` | Runs the M6 harness and returns `EvalsReport` (fields match `frontend/src/types.ts`) |

CORS: same-origin by default; `DASHBOARD_CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`) for the Vite dev server; credentials are never allowed. Static assets are mounted at `/assets` with `check_dir=False` so a rebuild while the server runs is picked up.

Useful dashboard env: `PORT` (8000), `SAMPLE_SERVICE_URL` (else read from stack outputs), `INCIDENTS_TABLE_NAME` (`opspilot-incidents`), `AWS_REGION`, `DASHBOARD_CORS_ORIGINS`.

## Evals (M6)

`evals/run_evals.py` replays all fixtures in `evals/fixtures/` through `run_rca_agent` (offline model) + `route_rca` and reports classification accuracy, router accuracy, location hit rate (file match ± 2 lines), abstention precision, evidence-ref validity, mean tokens (chars/4 estimate) and latency. Pass targets: classification ≥ 90%, location ≥ 90%, abstention = 100%, evidence validity ≥ 95%. **These scores validate the plumbing, not model quality** — there is no live-model eval mode yet. Fixtures: sample missing order, missing env var, config typo, downstream payment timeout, noise-only logs, DB pool exhaustion, OOM kill, auth-provider 503, unhandled KeyError payload, truncated/incomplete logs.

## Adding a planted fault / scenario

1. `sample_service/faults.py`: add the route (emit JSON lines via `_emit`; unhandled exceptions must also log a real traceback) and an entry in `FAULTS`.
2. `infra/sample_service_stack.py`: add the component to `ERROR_ALARMS` (name must start with `OpsPilotSampleService`).
3. `dashboard/scenarios.py`: add a scenario with a live `probe`, `alarm_name`, and the expected classification/evidence (the label is for the button only — the agent writes the actual incident).
4. Optionally add a patch generator + repro test in `src/opspilot/fix/agent.py` (and register it in `_STUB_TARGETS` / `_REPRO_BY_FUNCTION`) if the fix agent should offer a diff.
5. `scripts/demo_faults.py` `SCENARIOS` if `make demo-fault` should inject it; add a `sample_service/tests/` case; redeploy.

## Sample-service fault knobs

Deployed defaults are tuned for the 256 MB / 30 s Lambda; tests shrink them so nothing sleeps or eats RAM: `FAULT_DB_TIMEOUT_S` (2.0), `FAULT_LATENCY_S` (6.0), `FAULT_REPORT_MB_PER_DAY` (8).

## Checkpoint 1

`checkpoint1/` is a frozen, self-contained snapshot of the hackathon's first checkpoint (own `frontend/`, `dashboard/`, `src/opspilot/`, `start.sh`). Run it with `bash checkpoint1/start.sh local` (UI on :5174), `bash checkpoint1/start.sh ec2` (UI on :8001), or `bash scripts/deploy.sh checkpoint1`. It shows demo incidents and grounded RCA with milestone rails; the repo root is the finished product. See `checkpoint1/README.md`.
