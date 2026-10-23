"""Demo storefront routes with deliberately planted faults.

OpsPilot needs something real to watch. These routes behave like a small
storefront backend, and each one hides a realistic production bug that only
fires for a specific input, so a demo can break the service on demand:

    component   trigger                                   failure            OpsPilot path
    ---------   ---------------------------------------   ----------------   -------------------------
    orders      GET /orders/999                           AttributeError     code_defect -> fix PR
    checkout    GET /checkout?sku=SKU-1&coupon=SPRING50   KeyError           code_defect -> ticket + PR attempt
    inventory   GET /inventory/BULK-42                    TimeoutError (DB)  dependency -> notify on-call
    payments    GET /payments/77/status?provider=legacy   6 s latency        dependency -> notify on-call
    reports     GET /reports/export?days=90               Lambda OOM crash   resource -> notify on-call
    basket      GET /basket/average?count=0               ZeroDivisionError  code_defect -> notify on-call
    settings    GET /settings                             KeyError           config_regression -> notify on-call
    payments    GET /payments/77/status?provider=down     TimeoutError       dependency -> notify on-call
    writes      POST /writes/orders                       throttle           dependency -> notify on-call
    pricing     GET /pricing/SKU-1                        TypeError          code_defect -> notify on-call
    shipments   GET /shipments/404                        IndexError         code_defect -> notify on-call
    refunds     POST /refunds {}                          KeyError           code_defect -> notify on-call
    tax         GET /tax/quote?subtotal=10&rate=          ValueError         code_defect -> notify on-call

Every request writes one JSON line (``event`` = ``request`` or
``unhandled_exception``) so CloudWatch metric filters can count errors per
component, and unhandled exceptions are also logged as a plain Python
traceback, which is what OpsPilot's CollectContext step parses.
"""

import json
import logging
import os
import time
import traceback
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("sample_service")
logger.setLevel(logging.INFO)

SERVICE_NAME = "sample-service"

# Planted-fault knobs. Defaults are tuned for the deployed Lambda (256 MB memory,
# 30 s timeout); tests shrink them so nothing actually sleeps or eats RAM.
DB_TIMEOUT_S = float(os.environ.get("FAULT_DB_TIMEOUT_S", "2.0"))
LEGACY_GATEWAY_LATENCY_S = float(os.environ.get("FAULT_LATENCY_S", "6.0"))
REPORT_MB_PER_DAY = int(os.environ.get("FAULT_REPORT_MB_PER_DAY", "8"))

CATALOG: Dict[str, Dict[str, Any]] = {
    "SKU-1": {"name": "Mechanical keyboard", "price": 89.00, "stock": 42},
    "SKU-2": {"name": "USB-C dock", "price": 129.00, "stock": 7},
    "SKU-3": {"name": "27in monitor", "price": 249.00, "stock": 0},
}

# Active coupons. SPRING50 was announced by marketing but never added here.
COUPONS: Dict[str, float] = {
    "WELCOME10": 0.10,
    "VIP20": 0.20,
}

# Shelf prices. SKU-1 was imported from a merchandising CSV as text.
SHELF_PRICES: Dict[str, Any] = {
    "SKU-1": "89.00",
    "SKU-2": 129,
    "SKU-3": 249,
}
SHIPPING_FLAT_FEE = 5

SHIPMENTS: List[Dict[str, str]] = [
    {"id": "100", "carrier": "ups", "status": "delivered"},
    {"id": "101", "carrier": "usps", "status": "in_transit"},
]

FAULTS: List[Dict[str, str]] = [
    {
        "id": "orders",
        "trigger": "GET /orders/999",
        "symptom": "500: AttributeError 'NoneType' object has no attribute 'total'",
        "alarm": "OpsPilotSampleServiceErrors",
        "expected_route": "code_defect -> OpsCenter OpsItem -> fix PR -> CodeBuild verify",
    },
    {
        "id": "checkout",
        "trigger": "GET /checkout?sku=SKU-1&qty=2&coupon=SPRING50",
        "symptom": "500: KeyError 'SPRING50' (unknown coupon is not validated)",
        "alarm": "OpsPilotSampleService-CheckoutErrors",
        "expected_route": "code_defect -> OpsCenter OpsItem -> fix PR (unknown coupon returns 400)",
    },
    {
        "id": "inventory",
        "trigger": "GET /inventory/BULK-42",
        "symptom": "500: TimeoutError connecting to inventory-db (connection pool exhausted)",
        "alarm": "OpsPilotSampleService-InventoryDbTimeouts",
        "expected_route": "dependency -> OpsCenter OpsItem -> notify on-call (no PR)",
    },
    {
        "id": "payments",
        "trigger": "GET /payments/77/status?provider=legacy",
        "symptom": "200 after ~6 s: legacy payment gateway latency spike",
        "alarm": "OpsPilotSampleService-LatencyP95",
        "expected_route": "code_defect on payment_status -> fix PR (skip the legacy delay); otherwise a person handles it",
    },
    {
        "id": "reports",
        "trigger": "GET /reports/export?days=90",
        "symptom": "Lambda killed: export buffers the whole history in memory (Runtime.OutOfMemory)",
        "alarm": "OpsPilotSampleService-Crashes",
        "expected_route": "resource -> OpsCenter OpsItem -> notify on-call (no PR)",
    },
    {
        "id": "basket",
        "trigger": "GET /basket/average?count=0",
        "symptom": "500: ZeroDivisionError while averaging an empty order list",
        "alarm": "OpsPilotSampleService-BasketErrors",
        "expected_route": "code_defect below the fix threshold -> notify on-call",
    },
    {
        "id": "settings",
        "trigger": "GET /settings",
        "symptom": "500: KeyError 'ORDERS_TABLE' after the setting was dropped",
        "alarm": "OpsPilotSampleService-ConfigErrors",
        "expected_route": "config_regression -> notify on-call (no PR)",
    },
    {
        "id": "payments_down",
        "trigger": "GET /payments/77/status?provider=down",
        "symptom": "500: TimeoutError from the payment gateway",
        "alarm": "OpsPilotSampleService-PaymentTimeouts",
        "expected_route": "dependency -> notify on-call (no PR)",
    },
    {
        "id": "writes",
        "trigger": "POST /writes/orders",
        "symptom": "500: ProvisionedThroughputExceededException on the orders table",
        "alarm": "OpsPilotSampleService-WriteThrottles",
        "expected_route": "dependency -> notify on-call (no PR)",
    },
    {
        "id": "pricing",
        "trigger": "GET /pricing/SKU-1",
        "symptom": "500: TypeError adding a string shelf price to the integer shipping fee",
        "alarm": "OpsPilotSampleService-PricingErrors",
        "expected_route": "code_defect -> notify on-call (no PR)",
    },
    {
        "id": "shipments",
        "trigger": "GET /shipments/404",
        "symptom": "500: IndexError indexing a shipment id that is not in the list",
        "alarm": "OpsPilotSampleService-ShipmentErrors",
        "expected_route": "code_defect -> notify on-call (no PR)",
    },
    {
        "id": "refunds",
        "trigger": "POST /refunds",
        "symptom": "500: KeyError 'order_id' when the refund body is empty",
        "alarm": "OpsPilotSampleService-RefundErrors",
        "expected_route": "code_defect -> notify on-call (no PR)",
    },
    {
        "id": "tax",
        "trigger": "GET /tax/quote?subtotal=10&rate=",
        "symptom": "500: ValueError converting a blank tax rate with float()",
        "alarm": "OpsPilotSampleService-TaxErrors",
        "expected_route": "code_defect -> notify on-call (no PR)",
    },
]


class InventoryDbTimeout(TimeoutError):
    """The inventory database did not accept a connection in time."""


def _emit(record: Dict[str, Any]) -> None:
    """One JSON object per line, so CloudWatch JSON metric filters can match it."""
    record.setdefault("service", SERVICE_NAME)
    print(json.dumps(record, default=str), flush=True)


def _component(path: str) -> str:
    first = path.strip("/").split("/", 1)[0]
    return first or "root"


def _open_inventory_connection(sku: str) -> Dict[str, Any]:
    """Simulated DB driver call. Bulk SKUs are served by an overloaded replica."""
    if sku.upper().startswith("BULK-"):
        time.sleep(DB_TIMEOUT_S)
        raise InventoryDbTimeout(
            f"connect to inventory-db.internal:5432 timed out after {DB_TIMEOUT_S:.1f}s "
            "(pool exhausted: 10/10 connections in use)"
        )
    return {"host": "inventory-db.internal", "pool_in_use": 3, "pool_size": 10}


def install(app: FastAPI) -> None:
    """Attach the request logger and the planted-fault routes to ``app``."""

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        path = request.url.path
        component = _component(path)
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - this is the service's last line of defence
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            _emit({
                "level": "ERROR",
                "event": "unhandled_exception",
                "component": component,
                "method": request.method,
                "path": path,
                "status": 500,
                "latency_ms": latency_ms,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            })
            # Plain-text traceback in a single log event: CollectContext parses this.
            logger.error(
                "Unhandled exception on %s %s\n%s",
                request.method,
                path,
                "".join(traceback.format_exception(exc)).rstrip(),
            )
            return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        _emit({
            "level": "WARN" if latency_ms >= 3000 else "INFO",
            "event": "request",
            "component": component,
            "method": request.method,
            "path": path,
            "status": response.status_code,
            "latency_ms": latency_ms,
        })
        return response

    @app.get("/faults")
    def list_faults():
        """Catalog of planted faults and how to trigger each one."""
        return {"service": SERVICE_NAME, "faults": FAULTS}

    @app.get("/checkout")
    def checkout(sku: str = "SKU-1", qty: int = 1, coupon: str = ""):
        item = CATALOG.get(sku)
        if item is None:
            return JSONResponse(status_code=404, content={"detail": f"Unknown SKU {sku}"})
        subtotal = round(item["price"] * qty, 2)
        discount = 0.0
        if coupon:
            # Planted bug: unknown coupon codes are not validated -> KeyError (500).
            # A proper check returns 400 "invalid coupon" instead of indexing blindly.
            discount = round(subtotal * COUPONS[coupon], 2)
        return {
            "sku": sku,
            "qty": qty,
            "subtotal": subtotal,
            "coupon": coupon or None,
            "discount": discount,
            "total": round(subtotal - discount, 2),
        }

    @app.get("/inventory/{sku}")
    def inventory(sku: str):
        conn = _open_inventory_connection(sku)
        item = CATALOG.get(sku.upper())
        return {
            "sku": sku,
            "in_stock": bool(item and item["stock"] > 0),
            "stock": item["stock"] if item else 0,
            "db": conn["host"],
        }

    @app.get("/payments/{order_id}/status")
    def payment_status(order_id: str, provider: str = "stripe"):
        if provider == "down":
            raise TimeoutError("httpx.ReadTimeout: The read operation timed out")
        if provider == "legacy":
            # Planted latency: the legacy gateway is called synchronously with no timeout.
            time.sleep(LEGACY_GATEWAY_LATENCY_S)
        return {"order_id": order_id, "provider": provider, "status": "captured"}

    @app.get("/basket/average")
    def average_basket(count: int = 0):
        # Planted bug: an empty order list divides by zero.
        total = 100
        return {"count": count, "average": total / count}

    @app.get("/settings")
    def load_settings():
        # Planted config fault: the orders table name was removed from the environment.
        raise KeyError("ORDERS_TABLE")

    @app.post("/writes/orders")
    def write_order():
        raise RuntimeError(
            "ProvisionedThroughputExceededException: The level of configured provisioned "
            "throughput for the table was exceeded"
        )

    @app.get("/reports/export")
    def export_report(days: int = 7):
        # Planted resource bug: the export materialises every row for the period in
        # memory instead of streaming it. ~8 MB per day, so 90 days blows a 256 MB Lambda.
        days = max(1, min(days, 365))
        rows: List[bytearray] = []
        for _ in range(days):
            rows.append(bytearray(REPORT_MB_PER_DAY * 1024 * 1024))
        size_mb = sum(len(r) for r in rows) // (1024 * 1024)
        return {"days": days, "buffered_mb": size_mb, "status": "exported"}

    @app.get("/pricing/{sku}")
    def quote_price(sku: str):
        listed = SHELF_PRICES.get(sku)
        if listed is None:
            return JSONResponse(status_code=404, content={"detail": f"Unknown SKU {sku}"})
        # Planted bug: a price stored as a string is added to the integer shipping fee.
        total = listed + SHIPPING_FLAT_FEE
        return {"sku": sku, "price": listed, "shipping": SHIPPING_FLAT_FEE, "total": total}

    @app.get("/shipments/{shipment_id}")
    def get_shipment(shipment_id: str):
        matches = [row for row in SHIPMENTS if row["id"] == shipment_id]
        # Planted bug: a missing shipment is indexed and raises IndexError.
        row = matches[0]
        return {"shipment_id": row["id"], "carrier": row["carrier"], "status": row["status"]}

    @app.post("/refunds")
    def create_refund(payload: dict):
        # Planted bug: order_id is read with no validation, so an empty body raises KeyError.
        order_id = payload["order_id"]
        return {"refund_id": "r-9001", "order_id": order_id, "status": "queued"}

    @app.get("/tax/quote")
    def tax_quote(subtotal: float = 0.0, rate: str = ""):
        # Planted bug: a blank rate is converted with float() and raises ValueError.
        parsed_rate = float(rate)
        tax = round(subtotal * parsed_rate, 2)
        return {"subtotal": subtotal, "rate": parsed_rate, "tax": tax}
