#!/usr/bin/env python3
"""Break the deployed sample service on purpose and watch OpsPilot respond.

    python scripts/demo_faults.py list
    python scripts/demo_faults.py baseline --url https://xyz.lambda-url.us-east-1.on.aws
    python scripts/demo_faults.py orders --watch          # URL from the CloudFormation output
    python scripts/demo_faults.py inventory --burst 8 --watch

Each scenario sends a little healthy traffic, then a burst of requests that hit
one planted fault (see sample_service/faults.py). The matching CloudWatch alarm
fires within ~1-2 minutes, EventBridge routes it to the OpsPilot ingest Lambda,
and a Step Functions execution starts. ``--watch`` polls the alarm and the newest
execution so the terminal shows the hand-off live.

Run one scenario at a time: CollectContext reads the whole service log group, so
two simultaneous faults blur the evidence the RCA agent sees.
"""

import argparse
import concurrent.futures
import os
import sys
import time

import httpx

SCENARIOS = {
    "orders": {"path": "/orders/999", "alarm": "OpsPilotSampleServiceErrors",
               "what": "missing order -> AttributeError (code defect, fix PR path)"},
    "checkout": {"path": "/checkout?sku=SKU-1&qty=2&coupon=SPRING50", "alarm": "OpsPilotSampleService-CheckoutErrors",
                 "what": "unknown coupon -> KeyError (code defect)"},
    "inventory": {"path": "/inventory/BULK-42", "alarm": "OpsPilotSampleService-InventoryDbTimeouts",
                  "what": "inventory DB pool exhausted -> TimeoutError (dependency, notify path)"},
    "payments": {"path": "/payments/77/status?provider=legacy", "alarm": "OpsPilotSampleService-LatencyP95",
                 "what": "legacy gateway -> ~6 s latency, p95 alarm (dependency, notify path)"},
    "reports": {"path": "/reports/export?days=90", "alarm": "OpsPilotSampleService-Crashes",
                "what": "unbounded export buffer -> Lambda out of memory (resource, notify path)"},
}
HEALTHY_PATHS = ["/health", "/orders/101", "/orders/102", "/checkout?sku=SKU-2&coupon=WELCOME10",
                 "/inventory/SKU-1", "/payments/101/status"]
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def resolve_url(url: str | None) -> str:
    url = url or os.environ.get("SAMPLE_SERVICE_URL")
    if url:
        return url.rstrip("/")
    import boto3  # only needed when the URL is looked up
    cf = boto3.client("cloudformation", region_name=REGION)
    outputs = cf.describe_stacks(StackName="OpsPilotSampleServiceStack")["Stacks"][0].get("Outputs", [])
    for o in outputs:
        if o["OutputKey"] == "SampleServiceUrl":
            return o["OutputValue"].rstrip("/")
    sys.exit("SampleServiceUrl output not found; pass --url or set SAMPLE_SERVICE_URL")


def hit(base: str, path: str, timeout: float = 35.0) -> str:
    started = time.perf_counter()
    try:
        r = httpx.get(base + path, timeout=timeout)
        code = str(r.status_code)
    except httpx.HTTPError as exc:
        code = type(exc).__name__
    return f"{code:>4}  {(time.perf_counter() - started) * 1000:7.0f} ms  {path}"


def run_requests(base: str, paths: list[str], parallel: int) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        for line in pool.map(lambda p: hit(base, p), paths):
            print("  " + line)


def watch(alarm: str, minutes: int) -> None:
    import boto3
    cw = boto3.client("cloudwatch", region_name=REGION)
    sfn = boto3.client("stepfunctions", region_name=REGION)
    machines = [m for m in sfn.list_state_machines()["stateMachines"] if "OpsPilot" in m["name"] or "opspilot" in m["name"]]
    machine = machines[0]["stateMachineArn"] if machines else None
    since = time.time()
    last_state, seen = None, set()
    print(f"\nWatching alarm {alarm} and OpsPilot executions for up to {minutes} min (Ctrl-C to stop)...")
    while time.time() - since < minutes * 60:
        state = cw.describe_alarms(AlarmNames=[alarm])["MetricAlarms"]
        state = state[0]["StateValue"] if state else "NOT FOUND"
        if state != last_state:
            print(f"  [{time.strftime('%H:%M:%S')}] alarm {alarm}: {state}")
            last_state = state
        if machine:
            for ex in sfn.list_executions(stateMachineArn=machine, maxResults=5)["executions"]:
                if ex["startDate"].timestamp() < since - 60:
                    continue
                key = (ex["executionArn"], ex["status"])
                if key not in seen:
                    seen.add(key)
                    print(f"  [{time.strftime('%H:%M:%S')}] execution {ex['name']}: {ex['status']}")
                    if ex["status"] != "RUNNING":
                        print("  Done. Open the OpsPilot dashboard to see the incident, RCA and agent trace.")
                        return
        time.sleep(10)
    print("  Stopped watching (timeout).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", choices=["list", "baseline", *SCENARIOS])
    ap.add_argument("--url", help="Sample service base URL (default: SAMPLE_SERVICE_URL or the stack output)")
    ap.add_argument("--burst", type=int, default=5, help="Faulty requests to send (default 5)")
    ap.add_argument("--parallel", type=int, default=5)
    ap.add_argument("--watch", action="store_true", help="Poll the alarm and Step Functions execution")
    ap.add_argument("--watch-minutes", type=int, default=10)
    args = ap.parse_args()

    if args.scenario == "list":
        for name, s in SCENARIOS.items():
            print(f"{name:10} {s['path']:45} alarm={s['alarm']}\n{'':10} {s['what']}")
        return

    base = resolve_url(args.url)
    print(f"Sample service: {base}\nHealthy traffic:")
    run_requests(base, HEALTHY_PATHS, args.parallel)
    if args.scenario == "baseline":
        return

    s = SCENARIOS[args.scenario]
    print(f"\nInjecting fault '{args.scenario}': {s['what']}")
    run_requests(base, [s["path"]] * args.burst, args.parallel)
    print(f"\nExpect alarm {s['alarm']} to go to ALARM within ~1-2 min, then an OpsPilot execution.")
    if args.watch:
        watch(s["alarm"], args.watch_minutes)


if __name__ == "__main__":
    main()
