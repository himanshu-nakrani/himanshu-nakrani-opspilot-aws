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
