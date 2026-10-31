"""Unit tests for patch agent, PR creation, and needs-human marking."""

import os
import shutil
import subprocess
import sys

import pytest
from opspilot.contracts import EvidenceItem, SuspectedLocation
from opspilot.fix.agent import UnsupportedFixTarget, generate_repro_test_and_patch, mark_needs_human_handler, propose_fix, suggested_diff
from opspilot.fix.git_ops import GitHubError, PatchApplyError, apply_unified_diff

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _assert_patched_create_order_returns_422(patch: str) -> None:
    """Apply the diff to a copy of sample_service and execute the repro behavior."""
    import tempfile

    from opspilot.fix.git_ops import apply_unified_diff as apply_diff

    with tempfile.TemporaryDirectory() as tmp:
        pkg = os.path.join(tmp, "sample_service")
        shutil.copytree(os.path.join(REPO_ROOT, "sample_service"), pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        original = open(os.path.join(pkg, "app.py"), encoding="utf-8").read()
        patched = apply_diff(original, patch, "sample_service/app.py")
        with open(os.path.join(pkg, "app.py"), "w", encoding="utf-8") as handle:
            handle.write(patched)
        script = os.path.join(tmp, "check_create_order.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(
                "from fastapi.testclient import TestClient\n"
                "from sample_service.app import app\n"
                "client = TestClient(app, raise_server_exceptions=False)\n"
                "missing = client.post('/orders', json={})\n"
                "assert missing.status_code == 422, (missing.status_code, missing.text)\n"
                "assert missing.json() == {'detail': 'customer_id is required'}\n"
                "ok = client.post('/orders', json={'customer_id': 'c-1'})\n"
                "assert ok.status_code == 200, ok.text\n"
                "assert ok.json()['customer_id'] == 'c-1'\n"
            )
        env = os.environ.copy()
        env["PYTHONPATH"] = tmp + os.pathsep + env.get("PYTHONPATH", "")
        env["FAULT_DB_TIMEOUT_S"] = "0"
        proc = subprocess.run([sys.executable, script], cwd=tmp, env=env, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_suggested_diff_does_not_touch_the_repo(sample_inputs):
    rca, _ticket = sample_inputs
    diff = suggested_diff(rca)
    assert diff and "HTTPException" in diff
    refused = rca.model_copy(update={"classification": "dependency"})
    assert suggested_diff(refused) is None


def test_generate_repro_test_and_patch(sample_inputs):
    rca, ticket = sample_inputs
    repro_code, test_path, patch = generate_repro_test_and_patch(rca, ticket)

    assert "test_opspilot_oi_0a1b2c3d4e5f.py" in test_path
    assert "test_missing_order_returns_404" in repro_code
    assert 'assert response.status_code == 404' in repro_code
    assert "HTTPException" in patch
    assert "status_code=404" in patch
    assert "def get_order" in patch


def _create_order_rca(sample_inputs):
    rca, ticket = sample_inputs
    return rca.model_copy(
        update={
            "summary": "Unhandled KeyError 'customer_id' in create_order()",
            "suspected_location": SuspectedLocation(file="sample_service/app.py", line=28, function="create_order"),
            "suggested_fix_strategy": "Validate the request body and return 422 when customer_id is missing.",
        }
    ), ticket


def test_create_order_patch_validates_customer_id_and_applies(sample_inputs):
    rca, ticket = _create_order_rca(sample_inputs)
    diff = suggested_diff(rca)
    assert diff and 'customer_id is required' in diff and "status_code=422" in diff
    assert "def get_order" not in diff

    repro_code, test_path, patch = generate_repro_test_and_patch(rca, ticket)
    assert "test_missing_customer_id_returns_422" in repro_code
    assert 'assert response.status_code == 422' in repro_code
    assert test_path.endswith("test_opspilot_oi_0a1b2c3d4e5f.py")

    gh = FakeGitHub()
    pr_ref = propose_fix(rca, ticket, github=gh)
    _branch, _base, files = gh.commits[0]
    assert set(files) == {"sample_service/app.py", pr_ref.repro_test_path}
    patched = files["sample_service/app.py"]
    assert 'customer_id = payload.get("customer_id")' in patched
    assert 'HTTPException(status_code=422, detail="customer_id is required")' in patched
    assert "if order is None:" not in patched
    assert "customer_id is required" in files[pr_ref.repro_test_path]
    # The same diff must apply to the file the fake client read, and the result must 422.
    apply_unified_diff(gh.files["sample_service/app.py"], patch, "sample_service/app.py")
    _assert_patched_create_order_returns_422(patch)


class FakeGitHub:
    """In-memory stand-in for GitHubClient that records what was committed."""

    def __init__(self, fail_pr: bool = False):
        with open(os.path.join(REPO_ROOT, "sample_service/app.py")) as f:
            self.files = {"sample_service/app.py": f.read()}
        self.fail_pr = fail_pr
        self.commits = []
        self.labels = []

    def get_file(self, path, ref):
        if path not in self.files:
            with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as handle:
                self.files[path] = handle.read()
        return self.files[path]

    def commit_files_to_branch(self, branch, base, files, message):
        self.commits.append((branch, base, dict(files)))
        return "abc1234"

    def open_pull_request(self, branch, base, title, body):
        if self.fail_pr:
            raise GitHubError("GitHub create pull request failed: HTTP 403")
        return 7, "https://github.com/o/r/pull/7"

    def add_labels(self, number, labels):
        self.labels.append((number, labels))


def test_propose_fix_commits_patched_file_and_opens_pr(sample_inputs):
    rca, ticket = sample_inputs
    gh = FakeGitHub()
    pr_ref = propose_fix(rca, ticket, github=gh)
    assert pr_ref.branch == "opspilot/oi-0a1b2c3d4e5f"
    assert pr_ref.pr_url == "https://github.com/o/r/pull/7" and pr_ref.pr_number == 7
    branch, base, files = gh.commits[0]
    # Only the patched file and the repro test are committed (no `git add .`).
    assert set(files) == {"sample_service/app.py", pr_ref.repro_test_path}
    assert "HTTPException(status_code=404" in files["sample_service/app.py"]


def test_propose_fix_pr_failure_raises_instead_of_fake_url(sample_inputs):
    rca, ticket = sample_inputs
    with pytest.raises(GitHubError):
        propose_fix(rca, ticket, github=FakeGitHub(fail_pr=True))


def test_middleware_frame_still_offers_the_checkout_patch(sample_inputs):
    """The model cited log_requests. The checkout frame in the same trace is the patch."""
    rca, _ticket = sample_inputs
    rca = rca.model_copy(
        update={
            "classification": "code_defect",
            "confidence": 0.98,
            "summary": "KeyError SPRING50 in checkout()",
            "suspected_location": SuspectedLocation(
                file="sample_service/faults.py", line=160, function="log_requests"
            ),
            "evidence": [
                EvidenceItem(
                    kind="stack_frame",
                    ref="sample_service/faults.py:160",
                    claim="log_requests middleware re-raises the endpoint KeyError",
                ),
                EvidenceItem(
                    kind="stack_frame",
                    ref="sample_service/faults.py:209",
                    claim="checkout endpoint indexes COUPONS[coupon] and raises KeyError",
                ),
            ],
        }
    )
    diff = suggested_diff(rca)
    assert diff and "invalid coupon" in diff and "COUPONS.get" in diff


def test_checkout_patch_applies_on_main_and_drops_the_suite_pin(sample_inputs):
    rca, ticket = sample_inputs
    rca = rca.model_copy(
        update={
            "summary": "KeyError SPRING50 in checkout()",
            "suspected_location": SuspectedLocation(file="sample_service/faults.py", line=177, function="checkout"),
            "suggested_fix_strategy": "Return 400 for an unknown coupon.",
        }
    )
    diff = suggested_diff(rca)
    assert diff and "invalid coupon" in diff and "COUPONS.get" in diff
    original = open(os.path.join(REPO_ROOT, "sample_service/faults.py"), encoding="utf-8").read()
    patched = apply_unified_diff(original, diff, "sample_service/faults.py")
    assert "COUPONS.get(coupon)" in patched
    assert "COUPONS[coupon]" not in patched

    gh = FakeGitHub()
    gh.files["sample_service/tests/test_faults.py"] = (
        "def test_planted():\n"
        '    ("/checkout?sku=SKU-1&coupon=SPRING50", "checkout", "KeyError"),\n'
        '    ("/inventory/BULK-42", "inventory", "InventoryDbTimeout"),\n'
    )
    pr = propose_fix(rca, ticket, github=gh)
    _branch, _base, files = gh.commits[0]
    assert "invalid coupon" in files["sample_service/faults.py"]
    assert "test_unknown_coupon_returns_400" in files[pr.repro_test_path]
    suite = files["sample_service/tests/test_faults.py"]
    assert "SPRING50" not in suite and "BULK-42" in suite


def test_payments_patch_skips_the_legacy_delay(sample_inputs):
    rca, ticket = sample_inputs
    rca = rca.model_copy(
        update={
            "summary": "legacy provider blocks payment_status",
            "suspected_location": SuspectedLocation(file="sample_service/faults.py", line=202, function="payment_status"),
        }
    )
    diff = suggested_diff(rca)
    assert diff and "LEGACY_GATEWAY_LATENCY_S" in diff
    original = open(os.path.join(REPO_ROOT, "sample_service/faults.py"), encoding="utf-8").read()
    patched = apply_unified_diff(original, diff, "sample_service/faults.py")
    assert "time.sleep(LEGACY_GATEWAY_LATENCY_S)" not in patched
    assert "pass" in patched
    gh = FakeGitHub()
    pr = propose_fix(rca, ticket, github=gh)
    files = gh.commits[0][2]
    assert "test_legacy_provider_returns_without_delay" in files[pr.repro_test_path]
    assert "sample_service/tests/test_faults.py" not in files


def test_propose_fix_refuses_unsupported_target(sample_inputs):
    rca, ticket = sample_inputs
    other = rca.model_copy(update={"suspected_location": SuspectedLocation(file="billing/service.py", line=3, function="x")})
    with pytest.raises(UnsupportedFixTarget):
        propose_fix(other, ticket, github=FakeGitHub())
    inventory = rca.model_copy(
        update={"suspected_location": SuspectedLocation(file="sample_service/faults.py", line=112, function="inventory")}
    )
    with pytest.raises(UnsupportedFixTarget):
        propose_fix(inventory, ticket, github=FakeGitHub())
    assert suggested_diff(inventory) is None
    report = rca.model_copy(
        update={"suspected_location": SuspectedLocation(file="sample_service/faults.py", line=206, function="export_report")}
    )
    assert suggested_diff(report) is None


def test_patch_that_does_not_match_base_is_rejected():
    with pytest.raises(PatchApplyError):
        apply_unified_diff("a\nb\n", "--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-zzz\n+yyy\n", "f.py")


def test_mark_needs_human_labels_pr(sample_inputs):
    gh = FakeGitHub()
    event = {"pr": {"branch": "opspilot/oi-0a1b2c3d4e5f", "base": "main",
                    "repro_test_path": "sample_service/tests/test_opspilot_oi_0a1b2c3d4e5f.py", "pr_number": 42, "attempt": 1}}
    result = mark_needs_human_handler(event, github=gh)
    assert result["status"] == "needs_human"
    assert gh.labels == [(42, ["needs-human"])]


def test_mark_needs_human_requires_pr_number():
    with pytest.raises(ValueError):
        mark_needs_human_handler({"pr": {"branch": "b"}}, github=FakeGitHub())


def test_propose_fix_refuses_non_code_defect(sample_inputs):
    rca, ticket = sample_inputs
    for cls in ("config_regression", "dependency"):
        with pytest.raises(UnsupportedFixTarget):
            propose_fix(rca.model_copy(update={"classification": cls}), ticket, github=FakeGitHub())
