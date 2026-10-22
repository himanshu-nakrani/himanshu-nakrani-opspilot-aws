"""Pure classification and confidence router for OpsPilot.

Evaluates RCA output to decide whether the incident qualifies for automated patch proposal
or should be routed directly to notification without generating code changes.
"""

from typing import Literal
from opspilot.contracts import RcaResult

RouteTarget = Literal["propose_fix", "notify"]


# Classes the fix agent can actually patch today. config_regression has no revert agent
# yet, so it files a ticket and notifies instead of opening a PR it cannot verify.
FIXABLE_CLASSES = ("code_defect",)


def determine_route(classification: str, confidence: float, threshold: float = 0.6) -> RouteTarget:
    """Whether this classification is eligible for a suggested diff.

    The state machine does not open a pull request from this result. The incident
    screen does, after the operator chooses Raise PR.

    - code_defect with confidence >= threshold -> propose_fix
    - everything else (config_regression, dependency, resource, insufficient_evidence,
      or low confidence) -> notify, never a PR
    """
    if classification in FIXABLE_CLASSES and confidence >= threshold:
        return "propose_fix"
    return "notify"


def route_rca(rca: RcaResult, threshold: float = 0.6) -> RouteTarget:
    """Route an RcaResult. A PR also needs checkable evidence, not just model confidence:
    a suspected_location and at least one stack_frame evidence item that names it.
    (Bundle-level grounding already ran in opspilot.rca.grounding before this point.)
    """
    if determine_route(rca.classification, rca.confidence, threshold) != "propose_fix":
        return "notify"
    loc = rca.suspected_location
    if loc is None:
        return "notify"
    loc_ref = f"{loc.file}:{loc.line}"
    if not any(e.kind == "stack_frame" and e.ref.strip() == loc_ref for e in rca.evidence):
        return "notify"
    return "propose_fix"
