"""Sample service running on AWS Lambda (FastAPI + Mangum)."""

from dataclasses import dataclass
from typing import Dict, Optional
from fastapi import FastAPI
from mangum import Mangum

app = FastAPI(title="OpsPilot Sample Service")


@dataclass
class Order:
    order_id: str
    total: float
    status: str


ORDERS: Dict[str, Order] = {
    "101": Order("101", 49.99, "completed"),
    "102": Order("102", 120.50, "processing"),
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order: Optional[Order] = ORDERS.get(order_id)
    # Planted bug: missing order -> None.total -> AttributeError (500)
    # A proper check should raise HTTPException(status_code=404, detail="Order not found")
    return {
        "order_id": order_id,
        "total": order.total,
        "status": order.status,
    }


@app.post("/orders")
def create_order(payload: dict):
    customer_id = payload["customer_id"]
    # Planted bug: missing customer_id -> KeyError (500).
    # A proper check should raise HTTPException(status_code=422, detail="customer_id is required")
    return {"order_id": "103", "customer_id": customer_id, "status": "created"}


# Request logging plus the planted demo faults (checkout, inventory, payments, reports).
from sample_service.faults import install as _install_demo_faults  # noqa: E402

_install_demo_faults(app)

handler = Mangum(app)
