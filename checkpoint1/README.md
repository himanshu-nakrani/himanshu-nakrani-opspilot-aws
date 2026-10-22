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
| `ssm-tunnel.sh` | Optional port-forward. This demo is reached on the instance public IP. |

## What the UI shows

Checkpoint 1 is the in-progress build: demo incidents, grounded RCA, and milestone/pipeline rails. Tickets, live ingest, patch PRs, evals, and agent traces are marked as still underway.

`start.sh … app` runs the copied API. The Vite UI (`ui`) still uses demo data so the checkpoint story stays stable without a live alarm.

## Startup

| Mode | Where | Credentials |
|------|--------|-------------|
| `local` | Laptop | AWS CLI profile. Copy `.env.deploy.example` to `.env.deploy` in this folder. UI on `127.0.0.1:5174`. |
| `ec2` | Shell on the instance | Checkpoint 1 UI needs none and listens on `0.0.0.0:8001`. `app` uses the AWS credential chain (`aws login` needs `botocore[crt]` in the venv). |

Laptop:

```bash
cd checkpoint1

bash start.sh local              # UI → http://127.0.0.1:5174
bash start.sh local app          # API + built UI → http://127.0.0.1:8000
```

EC2 hackathon demo (Checkpoint 1 UI, not the repo-root dashboard). From the repo root on the instance:

```bash
bash scripts/deploy.sh checkpoint1
# or
bash checkpoint1/start.sh ec2
```

Open `http://<public-ipv4>:8001` in Safari. The script prints that URL when instance metadata returns a public IPv4. Allow inbound TCP 8001 from your IP in the instance security group.

`app` (`bash checkpoint1/start.sh ec2 app`) creates `checkpoint1/.venv`, installs `requirements.txt`, and installs `botocore[crt]` so boto3 can use `aws login` credentials. UI-only mode does not install that extra. The API listens on `0.0.0.0` and `PORT` (default `8000`).

Optional env: `CP1_PORT` (local default `5174`, EC2 default `8001`), `PORT` (API default `8000`), `BIND_HOST` on EC2 (default `0.0.0.0`).

## Presenting

1. Open the Checkpoint 1 banner and the build-progress panel.
2. Open an incident and walk through the grounded evidence. The fix block is labeled for the next checkpoint.
3. Use the repo-root app when you want the finished pipeline.
