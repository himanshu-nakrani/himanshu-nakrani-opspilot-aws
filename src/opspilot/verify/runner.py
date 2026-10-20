"""Verification runner for OpsPilot two-phase test validation."""

import logging
from typing import Callable, Optional
from opspilot.contracts import VerificationResult

logger = logging.getLogger(__name__)


def run_two_phase_verification(
    run_repro_on_base: Callable[[], bool],
    run_suite_on_fix: Callable[[], bool],
) -> VerificationResult:
    """Execute two-phase check:

    1. Repro test on base branch MUST FAIL (return False / raise).
       If it fails on base, repro_fails_on_base is TRUE.
       If it passes on base, the reproduction test is invalid.
    2. Full suite + repro test on fix branch MUST PASS (return True).
    """
    # Phase 1: Repro test on base
    try:
        base_passed = run_repro_on_base()
    except Exception:
        base_passed = False

    repro_fails_on_base = not base_passed

    # Phase 2: Full suite on fix branch
    try:
        suite_passed = run_suite_on_fix()
    except Exception:
        suite_passed = False

    suite_passes_on_fix = bool(suite_passed)

    if repro_fails_on_base and suite_passes_on_fix:
        verdict = "verified"
        details = "Two-phase check succeeded: reproduction test failed on base and full suite passed on fix."
    else:
        verdict = "failed"
        details = (
            f"Verification failed: repro_fails_on_base={repro_fails_on_base}, "
            f"suite_passes_on_fix={suite_passes_on_fix}"
        )

    logger.info("Two-phase verification result: %s (%s)", verdict, details)
    return VerificationResult(
        repro_fails_on_base=repro_fails_on_base,
        suite_passes_on_fix=suite_passes_on_fix,
        verdict=verdict,
        details=details,
    )


# --- ParseVerification Lambda -------------------------------------------------
# Step Functions' codebuild:startBuild.sync returns a CodeBuild Build object (or
# an error whose Cause is the Build JSON), not a VerificationResult. This handler
# converts it, reading the phase markers the buildspec exports.

import json as _json
import re as _re
from typing import Any, Dict


def _build_id_from(event: Dict[str, Any]) -> Optional[str]:
    vb = event.get("verify_build") or {}
    if isinstance(vb, dict) and vb.get("build_id"):
        return vb["build_id"]
    err = event.get("verify_error") or {}
    cause = err.get("Cause") if isinstance(err, dict) else None
    if cause:
        try:
            return (_json.loads(cause).get("Build") or {}).get("Id")
        except (ValueError, AttributeError):
            m = _re.search(r'"Id"\s*:\s*"([^"]+)"', cause)
            return m.group(1) if m else None
    return None


def parse_build(build: Dict[str, Any]) -> VerificationResult:
    """Map a CodeBuild Build dict to a VerificationResult using exported variables."""
    exported = {v.get("name"): v.get("value") for v in build.get("exportedEnvironmentVariables", []) or []}
    status = build.get("buildStatus", "UNKNOWN")
    repro_fails = exported.get("REPRO_FAILS_ON_BASE") == "true"
    suite_passes = exported.get("SUITE_PASSES_ON_FIX") == "true"
    if status == "SUCCEEDED" and repro_fails and suite_passes:
        return VerificationResult(repro_fails_on_base=True, suite_passes_on_fix=True, verdict="verified",
                                  details=f"CodeBuild {build.get('id')} succeeded both phases.")
    reason = exported.get("FAILURE_REASON") or f"build status {status}"
    return VerificationResult(repro_fails_on_base=repro_fails, suite_passes_on_fix=suite_passes, verdict="failed",
                              details=f"CodeBuild {build.get('id')}: {reason}")


def parse_verification_handler(event: Dict[str, Any], context: Optional[Any] = None, codebuild_client=None) -> Dict[str, Any]:
    build_id = _build_id_from(event)
    if not build_id:
        return VerificationResult(repro_fails_on_base=False, suite_passes_on_fix=False, verdict="failed",
                                  details=f"Verification did not start: {str(event.get('verify_error'))[:300]}").model_dump()
    import boto3

    client = codebuild_client or boto3.client("codebuild")
    builds = client.batch_get_builds(ids=[build_id]).get("builds", [])
    if not builds:
        raise RuntimeError(f"CodeBuild build {build_id} not found")
    return parse_build(builds[0]).model_dump()
