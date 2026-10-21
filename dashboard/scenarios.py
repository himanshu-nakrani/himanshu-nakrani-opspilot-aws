"""Canned incident scenarios for the dashboard's "Simulate incident" demo.

Each scenario is a believable alarm for sample-service with a pre-written RCA. Only
``null_order`` drives real traffic (5 calls to the planted /orders/999 bug); the rest are
synthetic alarms. Outcomes follow opspilot.route: a PR is proposed only for a code_defect
at >= 0.60 confidence whose suspected location is named by a stack_frame; everything else
notifies the SRE.
"""

from typing import Any, Dict, List, Optional

DEFAULT_SCENARIO = "null_order"

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "null_order": {
        "label": "Null order lookup",
        "description": "GET /orders/999 hits the planted bug: None.total raises AttributeError.",
        "probe_path": "/orders/999",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "alarm_reason": "{failed} unhandled AttributeError tracebacks",
        "classification": "code_defect",
        "confidence": 0.94,
        "severity": "sev2",
        "summary": "AttributeError on missing order ID in sample_service/app.py:29: None.total accessed without null check.",
        "suspected_location": {"file": "sample_service/app.py", "line": 29, "function": "get_order"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "AttributeError: 'NoneType' object has no attribute 'total'"},
            {"kind": "stack_frame", "ref": "sample_service/app.py:29", "claim": "Exception raised on order.total access"},
        ],
        "patch_diff": """--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -28,3 +29,5 @@
 def get_order(order_id: str):
     order: Optional[Order] = ORDERS.get(order_id)
+    if order is None:
+        raise HTTPException(status_code=404, detail="Order not found")
""",
        "suggested_fix_strategy": "Return 404 HTTPException if order ID does not exist in store.",
    },
    "missing_field": {
        "label": "Missing request field",
        "description": "POST /orders without customer_id raises KeyError in create_order().",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "alarm_reason": "12 unhandled KeyError tracebacks in 5 minutes",
        "classification": "code_defect",
        "confidence": 0.9,
        "severity": "sev2",
        "summary": "Unhandled KeyError 'customer_id' in sample_service/app.py:41 in create_order(): payload field read without validation.",
        "suspected_location": {"file": "sample_service/app.py", "line": 41, "function": "create_order"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "KeyError: 'customer_id'"},
            {"kind": "stack_frame", "ref": "sample_service/app.py:41", "claim": "payload['customer_id'] accessed directly"},
        ],
        "patch_diff": """--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -40,2 +40,4 @@
 def create_order(payload: dict):
-    customer_id = payload["customer_id"]
+    customer_id = payload.get("customer_id")
+    if not customer_id:
+        raise HTTPException(status_code=422, detail="customer_id is required")
""",
        "suggested_fix_strategy": "Validate the request body and return 422 when customer_id is missing.",
    },
    "divide_by_zero": {
        "label": "Low-confidence code defect",
        "description": "ZeroDivisionError with a partial stack trace; confidence is below the 0.60 fix threshold.",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "alarm_reason": "3 ZeroDivisionError tracebacks in 5 minutes",
        "classification": "code_defect",
        "confidence": 0.52,
        "severity": "sev3",
        "summary": "ZeroDivisionError while computing average basket size; stack trace is truncated so the exact line is uncertain.",
        "suspected_location": None,
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "ZeroDivisionError: division by zero"},
        ],
        "suggested_fix_strategy": "Guard the average against an empty order list once the frame is confirmed.",
    },
    "config_env": {
        "label": "Missing env variable",
        "description": "A deploy dropped ORDERS_TABLE; every request fails at startup.",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "alarm_reason": "100% error rate after deploy",
        "classification": "config_regression",
        "confidence": 0.88,
        "severity": "sev1",
        "summary": "Configuration regression: ORDERS_TABLE env var missing after the latest deploy; KeyError raised in settings loader.",
        "suspected_location": None,
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "KeyError: 'ORDERS_TABLE'"},
            {"kind": "commit", "ref": "a1b2c3d", "claim": "Lambda environment block edited in the last deploy"},
        ],
        "suggested_fix_strategy": "Restore ORDERS_TABLE in the Lambda environment and redeploy.",
    },
    "payment_timeout": {
        "label": "Payment gateway timeout",
        "description": "Downstream payment API stops responding; httpx.ReadTimeout on checkout.",
        "alarm_name": "OpsPilotSampleServiceLatency",
        "alarm_reason": "p99 latency above 10s for 3 datapoints",
        "classification": "dependency",
        "confidence": 0.86,
        "severity": "sev2",
        "summary": "Downstream dependency failure: httpx.ReadTimeout calling the payment gateway on checkout.",
        "suspected_location": None,
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "httpx.ReadTimeout: The read operation timed out"},
            {"kind": "metric", "ref": "Latency p99", "claim": "p99 rose from 300ms to 10s"},
        ],
        "suggested_fix_strategy": "Check the provider status page; add a circuit breaker and shorter timeout.",
    },
    "ddb_throttle": {
        "label": "DynamoDB throttling",
        "description": "Order writes hit ProvisionedThroughputExceededException during a traffic spike.",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "alarm_reason": "Throttled writes above threshold",
        "classification": "dependency",
        "confidence": 0.81,
        "severity": "sev3",
        "summary": "DynamoDB ProvisionedThroughputExceededException on orders table writes during traffic spike.",
        "suspected_location": None,
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "ProvisionedThroughputExceededException"},
            {"kind": "metric", "ref": "ThrottledRequests", "claim": "Throttled write requests spiked"},
        ],
        "suggested_fix_strategy": "Switch the table to on-demand or raise write capacity; add retry with backoff.",
    },
    "db_pool": {
        "label": "Connection pool exhausted",
        "description": "All database connections are held; new requests time out waiting.",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "alarm_reason": "Error rate above 25%",
        "classification": "resource",
        "confidence": 0.85,
        "severity": "sev1",
        "summary": "Resource exhaustion: database connection pool limit reached (QueuePool limit of size 10 overflow 0).",
        "suspected_location": None,
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "TimeoutError: QueuePool limit of size 10 overflow 0 reached"},
            {"kind": "metric", "ref": "DatabaseConnections", "claim": "Connections pinned at the configured maximum"},
        ],
        "suggested_fix_strategy": "Find the connection leak; raise pool size or add RDS Proxy as a stopgap.",
    },
    "lambda_oom": {
        "label": "Lambda out of memory",
        "description": "Invocations exceed the 512 MB limit while exporting a large report.",
        "alarm_name": "OpsPilotSampleServiceErrors",
        "alarm_reason": "Runtime.OutOfMemory on 8 invocations",
        "classification": "resource",
        "confidence": 0.83,
        "severity": "sev2",
        "summary": "Resource exhaustion: Lambda Runtime.OutOfMemory at 512 MB while building the orders export.",
        "suspected_location": None,
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "Runtime.OutOfMemory: Max Memory Used 512 MB"},
            {"kind": "metric", "ref": "MaxMemoryUsed", "claim": "Memory used hit the configured limit"},
        ],
        "suggested_fix_strategy": "Stream the export instead of loading it in memory, or raise memory size.",
    },
    "latency_no_errors": {
        "label": "Latency spike, no errors",
        "description": "Latency rises with no errors or stack traces in the logs; the agent abstains.",
        "alarm_name": "OpsPilotSampleServiceLatency",
        "alarm_reason": "p95 latency above 2s",
        "classification": "insufficient_evidence",
        "confidence": 0.3,
        "severity": "sev4",
        "summary": "Insufficient evidence: latency rose but logs contain no errors or stack traces to attribute a cause.",
        "suspected_location": None,
        "evidence": [
            {"kind": "metric", "ref": "Latency p95", "claim": "p95 rose from 180ms to 2.4s"},
        ],
        "suggested_fix_strategy": None,
    },
}


def list_scenarios() -> List[Dict[str, Any]]:
    """Public catalogue for the UI (no canned RCA payloads)."""
    return [
        {
            "id": sid,
            "label": s["label"],
            "description": s["description"],
            "classification": s["classification"],
            "severity": s["severity"],
            "live_probe": bool(s.get("probe_path")),
            "expected_outcome": expected_status(s),
        }
        for sid, s in SCENARIOS.items()
    ]


def expected_status(s: Dict[str, Any]) -> str:
    """Mirror opspilot.route.route_rca for the canned RCA."""
    loc: Optional[Dict[str, Any]] = s.get("suspected_location")
    if s["classification"] != "code_defect" or s["confidence"] < 0.6 or not loc:
        return "NOTIFIED"
    ref = f"{loc['file']}:{loc['line']}"
    if not any(e["kind"] == "stack_frame" and e["ref"] == ref for e in s["evidence"]):
        return "NOTIFIED"
    return "PROPOSED"
