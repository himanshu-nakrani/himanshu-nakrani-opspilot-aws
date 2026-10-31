"""Unit tests for patch guardrails and architectural limits."""

import pytest
from opspilot.fix.guardrails import (
    PatchRejectedException,
    validate_patch_limits,
)


def test_valid_patch_passes_limits():
    valid_diff = """--- a/sample_service/app.py
+++ b/sample_service/app.py
@@ -10,2 +10,4 @@
 def get_order(order_id: str):
+    if not order:
+        raise HTTPException(404)
"""
    is_valid, msg = validate_patch_limits(valid_diff, extra_files=[], extra_lines=15)
    assert is_valid is True


def test_reject_more_than_three_files():
    multi_file_diff = """--- a/f1.py
+++ b/f1.py
@@ -1 +1 @@
-a
+b
--- a/f2.py
+++ b/f2.py
@@ -1 +1 @@
-a
+b
--- a/f3.py
+++ b/f3.py
@@ -1 +1 @@
-a
+b
--- a/f4.py
+++ b/f4.py
@@ -1 +1 @@
-a
+b
"""
    with pytest.raises(PatchRejectedException, match="maximum allowed is 3"):
        validate_patch_limits(multi_file_diff)


def test_reject_more_than_eighty_lines():
    large_patch = "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,85 @@\n" + "\n".join([f"+line {i}" for i in range(85)])
    with pytest.raises(PatchRejectedException, match="maximum allowed is 80"):
        validate_patch_limits(large_patch)


def test_reject_changes_to_ci_config():
    ci_patch = """--- a/.github/workflows/deploy.yml
+++ b/.github/workflows/deploy.yml
@@ -1 +1 @@
-run: test
+run: bypass
"""
    with pytest.raises(PatchRejectedException, match="CI/IaC/manifests are prohibited"):
        validate_patch_limits(ci_patch)


def test_reject_changes_to_infra_iac():
    iac_patch = """--- a/infra/core_stack.py
+++ b/infra/core_stack.py
@@ -1 +1 @@
-old
+new
"""
    with pytest.raises(PatchRejectedException, match="CI/IaC/manifests are prohibited"):
        validate_patch_limits(iac_patch)


def test_reject_changes_to_dependency_manifests():
    dep_patch = """--- a/requirements.txt
+++ b/requirements.txt
@@ -1 +1 @@
-boto3
+boto3==99.0
"""
    with pytest.raises(PatchRejectedException, match="CI/IaC/manifests are prohibited"):
        validate_patch_limits(dep_patch)
