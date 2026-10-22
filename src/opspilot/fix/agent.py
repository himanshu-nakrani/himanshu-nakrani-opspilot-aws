"""Patch generation agent for OpsPilot.

Generates reproduction test and code fix unified diff, enforces
patch limits, and manages branch and pull request creation.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from opspilot.contracts import PrRef, RcaResult, TicketRef
from opspilot.audit import update_incident
from opspilot.fix.git_ops import apply_unified_diff
from opspilot.fix.scm import get_scm_client
from opspilot.fix.guardrails import PatchRejectedException, validate_patch_limits

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# The patch generator below is a STUB for the planted sample-service bugs only.
# Until a real patch agent exists, ProposeFix refuses any other target instead
# of applying one of these diffs to an unrelated incident.
STUB_SUPPORTED_FILES = {"sample_service/app.py", "sample_service/faults.py"}


# Unnamed locations in app.py keep the original missing-order patch.
SUPPORTED_FIX_FUNCTION = "get_order"
SUPPORTED_FIX_FUNCTIONS = frozenset({"get_order", "create_order", "checkout", "payment_status"})
# file + function. An unnamed function is only assumed for app.py (get_order).
_STUB_TARGETS = {
    ("sample_service/app.py", "get_order"),
    ("sample_service/app.py", "create_order"),
    ("sample_service/faults.py", "checkout"),
    ("sample_service/faults.py", "payment_status"),
}


GET_ORDER_PATCH = """--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -4,3 +4,4 @@
 from typing import Dict, Optional
+from fastapi import HTTPException
 from fastapi import FastAPI
 from mangum import Mangum
@@ -28,3 +29,5 @@
 def get_order(order_id: str):
     order: Optional[Order] = ORDERS.get(order_id)
+    if order is None:
+        raise HTTPException(status_code=404, detail="Order not found")
     # Planted bug: missing order -> None.total -> AttributeError (500)
"""


CREATE_ORDER_PATCH = """--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -4,3 +4,4 @@
 from typing import Dict, Optional
+from fastapi import HTTPException
 from fastapi import FastAPI
 from mangum import Mangum
@@ -40,2 +41,4 @@
 def create_order(payload: dict):
-    customer_id = payload["customer_id"]
+    customer_id = payload.get("customer_id")
+    if not customer_id:
+        raise HTTPException(status_code=422, detail="customer_id is required")
"""


# Applies to sample_service/faults.py on main: unknown coupons index COUPONS and raise KeyError.
CHECKOUT_PATCH = """--- a/sample_service/faults.py
+++ b/sample_service/faults.py
@@ -174,4 +174,7 @@
         if coupon:
-            # Planted bug: unknown coupon codes are not validated -> KeyError (500).
-            # A proper check returns 400 "invalid coupon" instead of indexing blindly.
-            discount = round(subtotal * COUPONS[coupon], 2)
+            rate = COUPONS.get(coupon)
+            if rate is None:
+                return JSONResponse(status_code=400, content={"detail": "invalid coupon"})
+            discount = round(subtotal * rate, 2)
"""


# Applies to sample_service/faults.py on main: the legacy provider sleeps on this line.
PAYMENTS_PATCH = """--- a/sample_service/faults.py
+++ b/sample_service/faults.py
@@ -200,3 +200,3 @@
         if provider == "legacy":
-            # Planted latency: the legacy gateway is called synchronously with no timeout.
-            time.sleep(LEGACY_GATEWAY_LATENCY_S)
+            # Legacy gateway is not called inline, so this status read does not block.
+            pass
"""


class UnsupportedFixTarget(PatchRejectedException):
    """No patch generator exists for this RCA (classification or location)."""


def _supported_function_in_frames(rca: RcaResult, file: str) -> Optional[str]:
    """A patchable function named by a stack frame in ``file``.

    The model often cites the middleware frame that re-raises (``log_requests``).
    The endpoint frame in the same traceback is the line the stub can patch.
    """
    names = tuple(name for frame_file, name in _STUB_TARGETS if frame_file == file)
    for item in rca.evidence:
        if item.kind != "stack_frame" or not item.ref.startswith(f"{file}:"):
            continue
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", item.claim, re.IGNORECASE):
                return name
    return None


def target_function(rca: RcaResult) -> Optional[str]:
    """Function the stub can patch, or None when the RCA names no location.

    Only ``sample_service/app.py`` with no function name falls back to get_order.
    A cited function that has no generator yields to a patchable function named
    in another stack frame of the same file.
    """
    loc = rca.suspected_location
    if loc is None:
        return None
    if loc.function and (loc.file, loc.function) in _STUB_TARGETS:
        return loc.function
    framed = _supported_function_in_frames(rca, loc.file)
    if framed:
        return framed
    if loc.function:
        return loc.function
    if loc.file == "sample_service/app.py":
        return SUPPORTED_FIX_FUNCTION
    return None


def ensure_supported_fix(rca: RcaResult) -> None:
    """Refuse anything but the patches the stub can generate."""
    if rca.classification != "code_defect":
        raise UnsupportedFixTarget(f"No automated fix for classification {rca.classification!r}")
    loc = rca.suspected_location
    if loc is None:
        raise UnsupportedFixTarget("RCA has no suspected_location; refusing to guess a patch")
    function = target_function(rca)
    if (loc.file, function) not in _STUB_TARGETS:
        raise UnsupportedFixTarget(
            f"No fix generator for {loc.file}:{loc.line} ({loc.function}); route to human."
        )


def _repro_path(ticket_ref: TicketRef) -> str:
    ticket_slug = ticket_ref.key.lower().replace("-", "_")
    return f"sample_service/tests/test_opspilot_{ticket_slug}.py"


def _get_order_repro(ticket_ref: TicketRef) -> str:
    return f'''"""Automated reproduction test generated by OpsPilot for {ticket_ref.key}.

Tests the planted missing-order bug: requesting an unknown order ID must return HTTP 404
instead of crashing with an unhandled AttributeError (500).
"""

from fastapi.testclient import TestClient
from sample_service.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_missing_order_returns_404():
    """Reproduction check: GET /orders/999 should return 404 with error detail."""
    response = client.get("/orders/999")
    assert response.status_code == 404
    assert response.json() == {{"detail": "Order not found"}}
'''


def _create_order_repro(ticket_ref: TicketRef) -> str:
    return f'''"""Automated reproduction test generated by OpsPilot for {ticket_ref.key}.

Tests the planted missing-field bug: POST /orders without customer_id must return HTTP 422
instead of crashing with an unhandled KeyError (500).
"""

from fastapi.testclient import TestClient
from sample_service.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_missing_customer_id_returns_422():
    """Reproduction check: POST /orders with an empty body should return 422."""
    response = client.post("/orders", json={{}})
    assert response.status_code == 422
    assert response.json() == {{"detail": "customer_id is required"}}
'''


def _checkout_repro(ticket_ref: TicketRef) -> str:
    return f'''"""Automated reproduction test generated by OpsPilot for {ticket_ref.key}.

Tests the planted coupon bug: GET /checkout with an unknown coupon must return HTTP 400
instead of crashing with an unhandled KeyError (500).
"""

from fastapi.testclient import TestClient
from sample_service.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_unknown_coupon_returns_400():
    """Reproduction check: GET /checkout?sku=SKU-1&coupon=SPRING50 should return 400."""
    response = client.get("/checkout", params={{"sku": "SKU-1", "coupon": "SPRING50"}})
    assert response.status_code == 400
    assert response.json() == {{"detail": "invalid coupon"}}
'''


def _payments_repro(ticket_ref: TicketRef) -> str:
    return f'''"""Automated reproduction test generated by OpsPilot for {ticket_ref.key}.

Tests the planted legacy-provider delay: GET /payments/77/status?provider=legacy must
return without blocking.
"""

import time

from fastapi.testclient import TestClient
from sample_service.app import app

client = TestClient(app, raise_server_exceptions=False)


def test_legacy_provider_returns_without_delay():
    """Reproduction check: the legacy provider must respond in under a second."""
    started = time.perf_counter()
    response = client.get("/payments/77/status", params={{"provider": "legacy"}})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert response.json()["status"] == "captured"
    assert elapsed < 1.0
'''


_REPRO_BY_FUNCTION = {
    "create_order": (_create_order_repro, CREATE_ORDER_PATCH, "test_missing_customer_id_returns_422"),
    "checkout": (_checkout_repro, CHECKOUT_PATCH, "test_unknown_coupon_returns_400"),
    "payment_status": (_payments_repro, PAYMENTS_PATCH, "test_legacy_provider_returns_without_delay"),
    "get_order": (_get_order_repro, GET_ORDER_PATCH, "test_missing_order_returns_404"),
}


def repro_pytest_node(rca: RcaResult, repro_path: str) -> str:
    """Pytest node id for the reproduction test this stub writes."""
    _builder, _patch, test_name = _REPRO_BY_FUNCTION.get(
        target_function(rca) or "",
        _REPRO_BY_FUNCTION["get_order"],
    )
    return f"{repro_path}::{test_name}"


_CHECKOUT_SUITE = "sample_service/tests/test_faults.py"
_CHECKOUT_PIN = '    ("/checkout?sku=SKU-1&coupon=SPRING50", "checkout", "KeyError"),'


def checkout_suite_without_pin(source: str) -> Optional[str]:
    """Drop the suite row that requires the unknown-coupon crash.

    CodeBuild runs sample_service/tests on the fix branch. That row would fail
    once checkout returns 400. Returns None when the file has no such row.
    """
    if _CHECKOUT_PIN not in source:
        return None
    return source.replace(_CHECKOUT_PIN + "\n", "").replace(_CHECKOUT_PIN, "")


def generate_repro_test_and_patch(
    rca: RcaResult,
    ticket_ref: TicketRef,
    repo_root: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Generate (repro_test_code, repro_test_path, patch_diff)."""
    ensure_supported_fix(rca)
    repro_test_path = _repro_path(ticket_ref)
    builder, patch, _test_name = _REPRO_BY_FUNCTION[target_function(rca) or "get_order"]
    return builder(ticket_ref), repro_test_path, patch


def _pr_body(rca: RcaResult, ticket_ref: TicketRef, test_path: str) -> str:
    evidence_md = "\n".join(f"- **[{ev.kind}]** `{ev.ref}`: {ev.claim}" for ev in rca.evidence)
    return f"""## OpsPilot automated fix proposal

**Incident ID:** `{rca.incident_id}`
**Classification:** `{rca.classification}`
**Severity:** `{rca.severity.upper()}`
**Confidence:** `{int(rca.confidence * 100)}%`
**OpsCenter OpsItem:** [{ticket_ref.key}]({ticket_ref.url})

### Root cause summary
{rca.summary}

### Grounded evidence
{evidence_md}

### Reproduction & fix
- Added reproduction test `{test_path}`.

---
> Generated by OpsPilot. Requires human review before merge.
"""


def suggested_diff(rca: RcaResult) -> Optional[str]:
    """The patch a human can apply or turn into a PR. Does not touch the repo.

    Returns None when this RCA is not one the fix agent is allowed to patch.
    """
    try:
        ensure_supported_fix(rca)
    except UnsupportedFixTarget:
        return None
    preview = TicketRef(key="preview", url="", incident_id=rca.incident_id)
    _repro, _path, patch_diff = generate_repro_test_and_patch(rca, preview)
    return patch_diff


def propose_fix(
    rca: RcaResult,
    ticket_ref: TicketRef,
    repo_root: Optional[str] = None,  # kept for signature compatibility; unused
    attempt: int = 1,
    github: Optional[Any] = None,  # SCM client (CodeCommit by default); name kept for compatibility
    base_branch: str = "main",
) -> PrRef:
    """Generate the fix, enforce limits, commit it to a branch in the source repo
    (AWS CodeCommit by default) and open a PR.

    Every failure raises (UnsupportedFixTarget, PatchApplyError, CodeCommitError/GitHubError,
    PolicyViolationError); nothing returns a placeholder PR.
    """
    ensure_supported_fix(rca)
    target = rca.suspected_location.file

    repro_code, test_path, patch_diff = generate_repro_test_and_patch(rca, ticket_ref, repo_root)
    if github is None:
        github = get_scm_client()

    extra_files = [test_path]
    extra_lines = len(repro_code.splitlines())
    suite_files: Dict[str, str] = {}
    if target_function(rca) == "checkout":
        try:
            current_suite = github.get_file(_CHECKOUT_SUITE, base_branch)
        except Exception as e:  # noqa: BLE001 - the fix can still be committed; verification reports a suite failure
            logger.info("Checkout suite pin left in place: %s", e)
            current_suite = None
        updated_suite = checkout_suite_without_pin(current_suite) if current_suite else None
        if updated_suite is not None:
            suite_files[_CHECKOUT_SUITE] = updated_suite
            extra_files.append(_CHECKOUT_SUITE)
            extra_lines += 1
    validate_patch_limits(patch_diff, extra_files=extra_files, extra_lines=extra_lines)

    base_content = github.get_file(target, base_branch)
    patched = apply_unified_diff(base_content, patch_diff, target)

    branch_name = f"opspilot/{ticket_ref.key}"
    title = f"[OpsPilot] {ticket_ref.key}: {rca.summary[:60]}"
    github.commit_files_to_branch(
        branch=branch_name,
        base=base_branch,
        files={target: patched, test_path: repro_code, **suite_files},
        message=title,
    )
    pr_number, pr_url = github.open_pull_request(branch_name, base_branch, title, _pr_body(rca, ticket_ref, test_path))

    return PrRef(
        branch=branch_name,
        base=base_branch,
        repro_test_path=test_path,
        pr_url=pr_url,
        pr_number=pr_number,
        attempt=attempt,
        status="opened",
    )


def handler(event: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """Lambda entry point for Step Functions ProposeFix state."""
    logger.info("ProposeFix invoked with event keys: %s", list(event.keys()))
    rca = RcaResult.model_validate(event["rca"])
    ticket_ref = TicketRef.model_validate(event["ticket"])
    attempt = int((event.get("pr") or {}).get("attempt", 0)) + 1

    pr_ref = propose_fix(rca, ticket_ref, attempt=attempt)
    update_incident(rca.incident_id, {"pr_branch": pr_ref.branch, "pr_url": pr_ref.pr_url or "", "status": "PR_OPENED"})
    return pr_ref.model_dump()


def mark_needs_human_handler(event: Dict[str, Any], context: Optional[Any] = None, github: Optional[Any] = None) -> Dict[str, Any]:
    """Lambda entry point for Step Functions MarkNeedsHuman state."""
    logger.info("MarkNeedsHuman invoked with event keys: %s", list(event.keys()))
    pr_data = dict(event.get("pr") or {})
    pr_number = pr_data.get("pr_number")
    if not pr_number:
        raise ValueError("MarkNeedsHuman requires pr.pr_number; refusing to label an arbitrary PR")
    if github is None:
        github = get_scm_client()
    if hasattr(github, "mark_needs_human"):
        github.mark_needs_human(int(pr_number))  # CodeCommit: title prefix + PR comment
    else:
        github.add_labels(int(pr_number), ["needs-human"])
    pr_data["status"] = "needs_human"
    return pr_data
