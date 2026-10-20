"""Patch guardrails and safety limit enforcement.

Enforces rules from docs/ARCHITECTURE.md:
- At most 3 files modified.
- At most 80 changed lines (additions + deletions).
- No changes to CI configs, IaC, or dependency manifests.
- If patch breaks limits, reject and open no PR.
"""

import re
from typing import List, Tuple

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


def parse_unified_diff(diff_text: str) -> Tuple[List[str], int, int]:
    """Parse a unified diff into modified file list, additions, and deletions."""
    files: List[str] = []
    additions = 0
    deletions = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            file_path = line[6:].strip()
            if file_path not in files:
                files.append(file_path)
        elif line.startswith("--- a/") or line.startswith("diff --git"):
            pass
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    return files, additions, deletions


def validate_patch_limits(
    diff_text: str,
    extra_files: List[str] = None,
    extra_lines: int = 0,
) -> Tuple[bool, str]:
    """Validate patch limits.

    Returns (is_valid, message).
    Raises PatchRejectedException if limits are violated.
    """
    files, additions, deletions = parse_unified_diff(diff_text)
    if extra_files:
        for f in extra_files:
            if f not in files:
                files.append(f)

    total_changed_lines = additions + deletions + extra_lines

    # 1. File count check
    if len(files) > MAX_CHANGED_FILES:
        msg = f"Patch modifies {len(files)} files (maximum allowed is {MAX_CHANGED_FILES}): {files}"
        raise PatchRejectedException(msg)

    # 2. Line count check
    if total_changed_lines > MAX_CHANGED_LINES:
        msg = f"Patch modifies {total_changed_lines} lines (maximum allowed is {MAX_CHANGED_LINES})"
        raise PatchRejectedException(msg)

    # 3. Forbidden file checks
    for f in files:
        for pat in FORBIDDEN_FILE_PATTERNS:
            if pat.search(f):
                msg = f"Patch attempts to modify protected file {f} (CI/IaC/manifests are prohibited)"
                raise PatchRejectedException(msg)

    return True, "Patch passed all safety limits."
