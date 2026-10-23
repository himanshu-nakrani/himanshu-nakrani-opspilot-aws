"""Incident scenarios the dashboard can fire on the deployed sample service.

Each scenario has a live ``probe``: one HTTP call to the sample service. That call writes
an error (or a slow request) to CloudWatch Logs. The matching alarm, whose name starts
with ``OpsPilotSampleService``, notifies EventBridge, and the pipeline runs the RCA agent.
The catalogue text is only a label for the button. The agent writes the incident.
"""

from typing import Any, Dict, List, Optional

from opspilot.fix.agent import CHECKOUT_PATCH, CREATE_ORDER_PATCH, GET_ORDER_PATCH, PAYMENTS_PATCH

DEFAULT_SCENARIO = "null_order"

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "null_order": {
        "label": "Null order lookup",
        "description": "GET /orders/999 hits the planted bug: None.total raises AttributeError.",
        "probe": {"method": "GET", "path": "/orders/999"},
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
        "patch_diff": GET_ORDER_PATCH,
        "suggested_fix_strategy": "Return 404 HTTPException if order ID does not exist in store.",
    },
    "missing_field": {
        "label": "Missing request field",
        "description": "POST /orders without customer_id raises KeyError in create_order().",
        "probe": {"method": "POST", "path": "/orders", "json": {}},
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
        "patch_diff": CREATE_ORDER_PATCH,
        "suggested_fix_strategy": "Validate the request body and return 422 when customer_id is missing.",
    },
    "unknown_coupon": {
        "label": "Unknown coupon",
        "description": "GET /checkout with coupon SPRING50 raises KeyError because the code is not in the catalog.",
        "probe": {"method": "GET", "path": "/checkout?sku=SKU-1&qty=2&coupon=SPRING50"},
        "alarm_name": "OpsPilotSampleService-CheckoutErrors",
        "alarm_reason": "KeyError SPRING50 on checkout",
        "classification": "code_defect",
        "confidence": 0.91,
        "severity": "sev2",
        "summary": "KeyError 'SPRING50' in checkout(): an unknown coupon is indexed without a check.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 177, "function": "checkout"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "KeyError: 'SPRING50'"},
            {"kind": "stack_frame", "ref": "sample_service/faults.py:177", "claim": "COUPONS[coupon]"},
        ],
        "patch_diff": CHECKOUT_PATCH,
        "suggested_fix_strategy": "Return 400 when the coupon code is not in the catalog.",
    },
    "legacy_payment": {
        "label": "Legacy payment delay",
        "description": "GET /payments/77/status?provider=legacy blocks on the legacy gateway.",
        "probe": {"method": "GET", "path": "/payments/77/status?provider=legacy"},
        "alarm_name": "OpsPilotSampleService-LatencyP95",
        "alarm_reason": "legacy provider latency",
        "classification": "code_defect",
        "confidence": 0.88,
        "severity": "sev3",
        "summary": "payment_status sleeps on the legacy provider and holds the request.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 202, "function": "payment_status"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "legacy provider blocked the status read"},
            {"kind": "stack_frame", "ref": "sample_service/faults.py:202", "claim": "time.sleep(LEGACY_GATEWAY_LATENCY_S)"},
        ],
        "patch_diff": PAYMENTS_PATCH,
        "suggested_fix_strategy": "Do not call the legacy gateway inline.",
    },
    "inventory_timeout": {
        "label": "Inventory database timeout",
        "description": "GET /inventory/BULK-42 waits on inventory-db and raises TimeoutError.",
        "probe": {"method": "GET", "path": "/inventory/BULK-42"},
        "alarm_name": "OpsPilotSampleService-InventoryDbTimeouts",
        "alarm_reason": "inventory-db connection timeouts",
        "classification": "dependency",
        "confidence": 0.9,
        "severity": "sev2",
        "summary": "Inventory lookup for BULK-42 hits a database timeout talking to inventory-db.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 112, "function": "inventory"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "InventoryDbTimeout: connect to inventory-db.internal timed out"},
        ],
        "suggested_fix_strategy": "A person has to look at the inventory database. There is no code patch.",
    },
    "report_export": {
        "label": "Report export out of memory",
        "description": "GET /reports/export?days=90 buffers the whole export and runs out of memory.",
        "probe": {"method": "GET", "path": "/reports/export?days=90"},
        "alarm_name": "OpsPilotSampleService-Crashes",
        "alarm_reason": "Runtime.OutOfMemory during export",
        "classification": "resource",
        "confidence": 0.86,
        "severity": "sev2",
        "summary": "The report export runs out of memory while buffering 90 days of rows.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 206, "function": "export_report"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "Runtime.OutOfMemory while exporting the report"},
        ],
        "suggested_fix_strategy": "A person has to change how the export uses memory. There is no code patch.",
    },
    "divide_by_zero": {
        "label": "Low-confidence code defect",
        "description": "GET /basket/average?count=0 divides by an empty order list.",
        "probe": {"method": "GET", "path": "/basket/average?count=0"},
        "alarm_name": "OpsPilotSampleService-BasketErrors",
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
        "description": "GET /settings reads ORDERS_TABLE and raises KeyError when the deploy dropped it.",
        "probe": {"method": "GET", "path": "/settings"},
        "alarm_name": "OpsPilotSampleService-ConfigErrors",
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
        "description": "GET /payments/77/status?provider=down raises a read timeout from the payment gateway.",
        "probe": {"method": "GET", "path": "/payments/77/status?provider=down"},
        "alarm_name": "OpsPilotSampleService-PaymentTimeouts",
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
        "description": "POST /writes/orders raises ProvisionedThroughputExceededException.",
        "probe": {"method": "POST", "path": "/writes/orders", "json": {}},
        "alarm_name": "OpsPilotSampleService-WriteThrottles",
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
        "description": "GET /inventory/BULK-42 exhausts the inventory database connection pool.",
        "probe": {"method": "GET", "path": "/inventory/BULK-42"},
        "alarm_name": "OpsPilotSampleService-InventoryDbTimeouts",
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
        "description": "GET /reports/export?days=90 exceeds the Lambda memory limit.",
        "probe": {"method": "GET", "path": "/reports/export?days=90"},
        "alarm_name": "OpsPilotSampleService-Crashes",
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
        "description": "GET /payments/77/status?provider=legacy holds the request with no thrown error.",
        "probe": {"method": "GET", "path": "/payments/77/status?provider=legacy"},
        "alarm_name": "OpsPilotSampleService-LatencyP95",
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
    "string_price": {
        "label": "String price plus shipping",
        "description": "GET /pricing/SKU-1 adds a shelf price stored as text to the integer shipping fee and raises TypeError.",
        "probe": {"method": "GET", "path": "/pricing/SKU-1"},
        "alarm_name": "OpsPilotSampleService-PricingErrors",
        "alarm_reason": "TypeError adding a string price to the shipping fee",
        "classification": "code_defect",
        "confidence": 0.91,
        "severity": "sev2",
        "summary": "TypeError in quote_price(): SKU-1's shelf price is a string and is added to the integer shipping fee.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 319, "function": "quote_price"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "TypeError: can only concatenate str (not \"int\") to str"},
            {"kind": "stack_frame", "ref": "sample_service/faults.py:319", "claim": "total = listed + SHIPPING_FLAT_FEE in quote_price"},
        ],
        "suggested_fix_strategy": "Parse the shelf price to a number before adding the shipping fee, and return 400 when the stored price is not numeric.",
    },
    "missing_shipment": {
        "label": "Missing shipment lookup",
        "description": "GET /shipments/404 indexes an empty match list and raises IndexError.",
        "probe": {"method": "GET", "path": "/shipments/404"},
        "alarm_name": "OpsPilotSampleService-ShipmentErrors",
        "alarm_reason": "IndexError on a missing shipment id",
        "classification": "code_defect",
        "confidence": 0.87,
        "severity": "sev3",
        "summary": "IndexError in get_shipment(): shipment 404 is not in the list and the empty match is indexed.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 326, "function": "get_shipment"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "IndexError: list index out of range"},
            {"kind": "stack_frame", "ref": "sample_service/faults.py:326", "claim": "row = matches[0] in get_shipment"},
        ],
        "suggested_fix_strategy": "Return 404 when no shipment matches the id instead of indexing the empty match list.",
    },
    "empty_refund": {
        "label": "Empty refund request",
        "description": "POST /refunds with an empty body reads order_id and raises KeyError.",
        "probe": {"method": "POST", "path": "/refunds", "json": {}},
        "alarm_name": "OpsPilotSampleService-RefundErrors",
        "alarm_reason": "KeyError order_id on an empty refund body",
        "classification": "code_defect",
        "confidence": 0.9,
        "severity": "sev2",
        "summary": "KeyError 'order_id' in create_refund(): the refund body is read without checking for order_id.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 332, "function": "create_refund"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "KeyError: 'order_id'"},
            {"kind": "stack_frame", "ref": "sample_service/faults.py:332", "claim": "payload['order_id'] in create_refund"},
        ],
        "suggested_fix_strategy": "Validate the refund body and return 422 when order_id is missing.",
    },
    "blank_tax_rate": {
        "label": "Blank tax rate",
        "description": "GET /tax/quote?subtotal=10&rate= converts a blank rate with float() and raises ValueError.",
        "probe": {"method": "GET", "path": "/tax/quote?subtotal=10&rate="},
        "alarm_name": "OpsPilotSampleService-TaxErrors",
        "alarm_reason": "ValueError converting a blank tax rate",
        "classification": "code_defect",
        "confidence": 0.84,
        "severity": "sev2",
        "summary": "ValueError in tax_quote(): a blank rate is passed to float() while quoting tax on a subtotal of 10.",
        "suspected_location": {"file": "sample_service/faults.py", "line": 338, "function": "tax_quote"},
        "evidence": [
            {"kind": "log_line", "ref": "log-1", "claim": "ValueError: could not convert string to float: ''"},
            {"kind": "stack_frame", "ref": "sample_service/faults.py:338", "claim": "parsed_rate = float(rate) in tax_quote"},
        ],
        "suggested_fix_strategy": "Reject a blank tax rate with 400 before converting it, and treat a missing rate as a required field.",
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
            "live_probe": bool(s.get("probe")),
            "alarm_name": s["alarm_name"],
            "expected_outcome": expected_status(s),
        }
        for sid, s in SCENARIOS.items()
    ]


def simulation_alarm_name(scenario_id: str) -> str:
    """CloudWatch alarm the probe trips. EventBridge matches the OpsPilotSampleService prefix."""
    return SCENARIOS[scenario_id]["alarm_name"]


def expected_status(s: Dict[str, Any]) -> str:
    """Catalogue outcome. A choice is offered when the stack frame matches a function the fix stub can patch."""
    loc: Optional[Dict[str, Any]] = s.get("suspected_location")
    if s["classification"] != "code_defect" or s["confidence"] < 0.6 or not loc:
        return "NOTIFIED"
    ref = f"{loc['file']}:{loc['line']}"
    if not any(e["kind"] == "stack_frame" and e["ref"] == ref for e in s["evidence"]):
        return "NOTIFIED"
    if not s.get("patch_diff"):
        return "NOTIFIED"
    return "AWAITING_CHOICE"
