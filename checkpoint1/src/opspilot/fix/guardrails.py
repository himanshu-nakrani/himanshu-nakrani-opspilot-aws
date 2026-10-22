"""Patch guardrails and safety limit enforcement.

Enforces rules from docs/ARCHITECTURE.md:
- At most 3 files modified.
- At most 80 changed lines (additions + deletions).
- No changes to CI configs, IaC, or dependency manifests.
- If patch breaks limits, reject and open no PR.
"""

import re
from typing import List, Tuple

from opspilot.agentcore.policy import AgentCorePolicy, PolicyViolationError

MAX_CHANGED_FILES = 3
MAX_CHANGED_LINES = 80

FORBIDDEN_FILE_PATTERNS = [
    re.compile(r"^\.github/"),
    re.compile(r"^buildspec"),
    re.compile(r"^infra/"),
    re.compile(r"^statemachine/"),
    re.compile(r"^contracts/"),
    re.compile(r"^Makefile$"),
    re.compile(r"^requirements.*\.txt$"),
    re.compile(r"^pyproject\.toml$"),
    re.compile(r"^setup\.py$"),
    re.compile(r"^Pipfile"),
]


class PatchRejectedException(Exception):
    """Raised when a proposed patch violates architectural safety limits."""
    pass


_DEFAULT_POLICY = AgentCorePolicy()


def parse_unified_diff(diff_text: str) -> Tuple[List[str], int, int]:
    """Parse a unified diff into modified file list, additions, and deletions."""
    return _DEFAULT_POLICY.parse_unified_diff(diff_text)


def validate_patch_limits(
    diff_text: str,
    extra_files: List[str] = None,
    extra_lines: int = 0,
) -> Tuple[bool, str]:
    """Validate patch limits using Bedrock AgentCore Policy.

    Returns (is_valid, message).
    Raises PatchRejectedException if limits are violated.
    """
    try:
        return _DEFAULT_POLICY.enforce_patch_policy(diff_text, extra_files=extra_files, extra_lines=extra_lines)
    except PolicyViolationError as e:
        raise PatchRejectedException(str(e)) from e
