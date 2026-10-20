"""Pure classification and confidence router for OpsPilot.

Evaluates RCA output to decide whether the incident qualifies for automated patch proposal
or should be routed directly to notification without generating code changes.
"""

from typing import Literal
from opspilot.contracts import RcaResult

RouteTarget = Literal["propose_fix", "notify"]


def determine_route(classification: str, confidence: float, threshold: float = 0.6) -> RouteTarget:
    """Evaluate classification and confidence against safety threshold.

    Rules from ARCHITECTURE.md:
    - code_defect (confidence >= 0.6) -> propose_fix
    - config_regression (confidence >= 0.6) -> propose_fix
    - dependency -> notify (never opens PR)
    - resource -> notify (never opens PR)
    - insufficient_evidence -> notify (never opens PR)
    - confidence < threshold -> notify (never opens PR)
    """
    if classification in ("code_defect", "config_regression") and confidence >= threshold:
        return "propose_fix"
    return "notify"


def route_rca(rca: RcaResult, threshold: float = 0.6) -> RouteTarget:
    """Convenience helper accepting RcaResult model."""
    return determine_route(rca.classification, rca.confidence, threshold=threshold)
