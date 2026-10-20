"""Single source of truth for RCA evidence grounding and abstention.

Every RCA result, from the Converse loop, the Strands/AgentCore path or a fallback,
goes through `ground_rca` before it reaches the router. The rules:

* log_line evidence must name an exact log line id from the context bundle.
* stack_frame evidence must be an exact `file:line` that appears in the parsed stack trace.
* commit evidence must be a hex SHA (>= 7 chars) that prefixes a commit in `recent_commits`.
* metric evidence cannot be checked against the bundle, so it never counts as grounding.
* suspected_location must match a frame in the parsed stack trace.
* code_defect needs a parsed stack trace AND at least one grounded stack_frame or commit item.
* config_regression only needs exact refs, because it routes to notify (no revert agent yet).

Any violation means OpsPilot abstains (`insufficient_evidence`, confidence <= 0.4), so the
router never opens a PR on an unverifiable claim. We do not just lower confidence and
keep the model's classification, because the model's confidence is not calibrated.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from opspilot.contracts import ContextBundle, EvidenceItem, RcaResult

logger = logging.getLogger(__name__)

ABSTAIN_CONFIDENCE_CAP = 0.4
FIX_CLASSES = ("code_defect", "config_regression")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _safe_log_ref(bundle: ContextBundle) -> str:
    return bundle.log_lines[0].id if bundle.log_lines else "none"


def abstain(bundle: ContextBundle, reason: str, severity: str = "sev3") -> RcaResult:
    """Build a contract-valid abstention. Never routes to a PR."""
    summary = f"Insufficient evidence: {reason}"
    return RcaResult(
        incident_id=bundle.incident_id,
        classification="insufficient_evidence",
        severity=severity,
        confidence=0.0,
        summary=summary[:600],
        evidence=[EvidenceItem(kind="log_line", ref=_safe_log_ref(bundle), claim=reason[:300])],
        ruled_out=[],
        suggested_fix_strategy="Escalate to on-call; gather more telemetry before any automated change.",
    )


def _frame_refs(bundle: ContextBundle) -> set[str]:
    if not bundle.stack_trace:
        return set()
    return {f"{fr.file}:{fr.line}" for fr in bundle.stack_trace.frames}


def check_evidence(bundle: ContextBundle, rca: RcaResult) -> Tuple[List[str], bool]:
    """Return (issues, has_strong_evidence). Strong = grounded stack_frame or commit item."""
    issues: List[str] = []
    strong = False
    log_ids = {line.id for line in bundle.log_lines}
    frames = _frame_refs(bundle)
    commits = [str(c.get("commit", "")) for c in bundle.recent_commits if isinstance(c, dict) and c.get("commit")]

    for item in rca.evidence:
        ref = item.ref.strip()
        if item.kind == "log_line":
            if ref == "none" and rca.classification == "insufficient_evidence":
                continue
            if ref not in log_ids:
                issues.append(f"log_line ref '{ref}' is not a log line id in the bundle")
        elif item.kind == "stack_frame":
            if ref in frames:
                strong = True
            else:
                issues.append(f"stack_frame ref '{ref}' is not a file:line in the parsed stack trace")
        elif item.kind == "commit":
            if _SHA_RE.match(ref) and any(c.startswith(ref) for c in commits):
                strong = True
            else:
                issues.append(f"commit ref '{ref}' is not in recent_commits")
        elif item.kind == "metric":
            # Not verifiable against the bundle: allowed as colour, never as grounding.
            continue

    loc = rca.suspected_location
    if loc is not None and f"{loc.file}:{loc.line}" not in frames:
        issues.append(f"suspected_location {loc.file}:{loc.line} is not a frame in the parsed stack trace")
    return issues, strong


def ground_rca(bundle: ContextBundle, raw: Dict[str, Any] | RcaResult) -> Tuple[RcaResult, List[str]]:
    """Validate a candidate RCA against the contract and the bundle; abstain on any doubt.

    Raises pydantic.ValidationError only when the candidate is not a valid RcaResult, so the
    caller can send the error back to the model for one repair attempt.
    """
    if isinstance(raw, RcaResult):
        rca = raw
    else:
        data = dict(raw)
        data["incident_id"] = bundle.incident_id  # never trust the model with the key
        rca = RcaResult.model_validate(data)

    if rca.incident_id != bundle.incident_id:
        rca = rca.model_copy(update={"incident_id": bundle.incident_id})

    issues, strong = check_evidence(bundle, rca)

    if rca.classification == "code_defect":
        if not (bundle.stack_trace and bundle.stack_trace.frames):
            issues.append("code_defect needs a parsed stack trace; none in the bundle")
        elif not strong:
            issues.append("code_defect needs a grounded stack_frame or commit evidence item")
    # config_regression never opens a PR today (no revert agent; see route.py), so exact
    # log-line refs are enough for it. Re-tighten this when a revert agent lands.

    if issues:
        logger.warning("RCA for %s failed grounding, abstaining: %s", bundle.incident_id, issues)
        if rca.classification == "insufficient_evidence":
            # already abstaining; just make sure confidence and refs are safe
            return abstain(bundle, rca.summary.removeprefix("Insufficient evidence: ")[:400], rca.severity), issues
        return abstain(bundle, "model output failed evidence grounding: " + "; ".join(issues)[:400], rca.severity), issues

    if rca.classification == "insufficient_evidence" and rca.confidence > ABSTAIN_CONFIDENCE_CAP:
        rca = rca.model_copy(update={"confidence": ABSTAIN_CONFIDENCE_CAP})
    return rca, issues


__all__ = ["abstain", "check_evidence", "ground_rca", "ValidationError", "ABSTAIN_CONFIDENCE_CAP"]
