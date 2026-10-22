# OpsPilot — Hackathon Checkpoint 1

Self-contained snapshot. The dashboard you present, the FastAPI app, the agent code, the sample service, eval fixtures, and the start scripts all live in this folder. The repo root is the Checkpoint 2 product and is not required to run this copy.

## Layout

| Path | Role |
|------|------|
| `frontend/` | Checkpoint 1 UI (work in progress) |
| `dashboard/` | FastAPI dashboard |
| `src/opspilot/` | Agent, RCA, fix, verify |
| `sample_service/` | Planted-fault service the dashboard imports |
| `evals/` | M6 fixtures and replay helpers |
| `requirements.txt` | Python deps (copied from the main app) |
| `start.sh` | `local` or `ec2` startup |
| `ssm-tunnel.sh` | Laptop port-forward over Session Manager |

## What the UI shows

Checkpoint 1 is the in-progress build: demo incidents, grounded RCA, and milestone/pipeline rails. Tickets, live ingest, patch PRs, evals, and agent traces are marked as still underway.

`start.sh … app` runs the copied API. The Vite UI (`ui`) still uses demo data so the checkpoint story stays stable without a live alarm.

## Startup

| Mode | Where | Credentials |
|------|--------|-------------|
| `local` | Laptop | AWS CLI profile. Copy `.env.deploy.example` to `.env.deploy` in this folder. |
| `ec2` | SSM shell on the instance | Instance IAM role. Profile and static keys are cleared. |

```bash
cd checkpoint1

bash start.sh local              # UI → http://127.0.0.1:5174
bash start.sh local app          # API + built UI → http://127.0.0.1:8000

# On the instance, inside an SSM session:
bash start.sh ec2                # UI on 127.0.0.1:5174
bash start.sh ec2 app            # API on 127.0.0.1:8000
```

From the laptop, forward that port (AWS CLI + Session Manager plugin, `.env.deploy` in this folder):

```bash
bash ssm-tunnel.sh i-0123456789abcdef0 5174
bash ssm-tunnel.sh i-0123456789abcdef0 8000
```

`app` creates `checkpoint1/.venv` and installs `requirements.txt` if FastAPI, uvicorn, boto3, or strands are not already importable.

Optional env: `CP1_PORT` (default `5174`), `PORT` (default `8000`), `BIND_HOST` on EC2 (default `127.0.0.1`).

## Presenting

1. Open the Checkpoint 1 banner and the build-progress panel.
2. Open an incident and walk through the grounded evidence. The fix block is labeled for the next checkpoint.
3. Use the repo-root app when you want the finished pipeline.
