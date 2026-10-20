"""Amazon Bedrock AgentCore Policy primitive for OpsPilot.

Enforces organizational guardrails, blast-radius boundaries, and safety policies:
1. Patch limits: max 3 files modified, max 80 lines changed (additions + deletions).
2. Protected file paths: CI configs, IaC, contracts, dependency manifests.
3. Grounding policy: evidence references must resolve in context bundle / commits.
4. Abstention policy: absent or inconclusive evidence triggers low confidence (<= 0.40).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Pattern, Tuple

from opspilot.contracts import ContextBundle, EvidenceItem, RcaResult, SuspectedLocation

logger = logging.getLogger(__name__)

# Default policy boundaries
DEFAULT_MAX_FILES_MODIFIED = 3
DEFAULT_MAX_LINES_MODIFIED = 80
DEFAULT_MIN_GROUNDING_CONFIDENCE_PENALTY = 0.40

PROTECTED_PATH_PATTERNS: List[Pattern] = [
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
    re.compile(r"^Dockerfile"),
]


class PolicyViolationError(Exception):
    """Raised when an agent action violates Bedrock AgentCore Policy boundaries."""

    def __init__(self, message: str, policy_name: str = "general", violation_details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.policy_name = policy_name
        self.violation_details = violation_details or {}


class AgentCorePolicy:
    """Bedrock AgentCore Policy manager enforcing boundaries and guardrails."""

    def __init__(
        self,
        max_files_modified: int = DEFAULT_MAX_FILES_MODIFIED,
        max_lines_modified: int = DEFAULT_MAX_LINES_MODIFIED,
        protected_patterns: Optional[List[Pattern]] = None,
        grounding_penalty_threshold: float = DEFAULT_MIN_GROUNDING_CONFIDENCE_PENALTY,
    ):
        self.max_files_modified = max_files_modified
        self.max_lines_modified = max_lines_modified
        self.protected_patterns = protected_patterns or PROTECTED_PATH_PATTERNS
        self.grounding_penalty_threshold = grounding_penalty_threshold
        self.audit_log: List[Dict[str, Any]] = []

    def log_violation(self, policy_name: str, message: str, details: Dict[str, Any]) -> None:
        """Record policy audit event."""
        entry = {
            "policy": policy_name,
            "status": "VIOLATION",
            "message": message,
            "details": details,
        }
        self.audit_log.append(entry)
        logger.warning("AgentCore Policy violation: [%s] %s (details: %s)", policy_name, message, details)

    def parse_unified_diff(self, diff_text: str) -> Tuple[List[str], int, int]:
        """Parse unified diff into list of touched files, additions, and deletions."""
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

    def enforce_patch_policy(
        self,
        diff_text: str,
        extra_files: Optional[List[str]] = None,
        extra_lines: int = 0,
    ) -> Tuple[bool, str]:
        """Verify patch adheres to file limits, line limits, and protected paths.

        Raises PolicyViolationError if policy is breached.
        """
        files, additions, deletions = self.parse_unified_diff(diff_text)
        if extra_files:
            for f in extra_files:
                if f not in files:
                    files.append(f)

        total_changed_lines = additions + deletions + extra_lines

        # 1. File count check
        if len(files) > self.max_files_modified:
            msg = f"Patch modifies {len(files)} files (maximum allowed is {self.max_files_modified} by AgentCore Policy): {files}"
            self.log_violation("blast_radius_files", msg, {"files_count": len(files), "files": files})
            raise PolicyViolationError(msg, policy_name="blast_radius_files", violation_details={"files": files})

        # 2. Line count check
        if total_changed_lines > self.max_lines_modified:
            msg = f"Patch modifies {total_changed_lines} lines (maximum allowed is {self.max_lines_modified} by AgentCore Policy)"
            self.log_violation("blast_radius_lines", msg, {"lines_count": total_changed_lines})
            raise PolicyViolationError(msg, policy_name="blast_radius_lines", violation_details={"total_lines": total_changed_lines})

        # 3. Protected file patterns check
        for f in files:
            for pat in self.protected_patterns:
                if pat.search(f):
                    msg = f"Patch attempts to modify protected file {f} (CI/IaC/manifests are prohibited by AgentCore Policy)"
                    self.log_violation("protected_paths", msg, {"target_file": f})
                    raise PolicyViolationError(msg, policy_name="protected_paths", violation_details={"file": f})

        return True, "Patch passed AgentCore Policy boundaries."

    def enforce_evidence_grounding(
        self,
        bundle: ContextBundle,
        rca_candidate: Dict[str, Any] | RcaResult,
    ) -> Tuple[RcaResult, List[str]]:
        """Verify all evidence refs resolve to actual log lines, stack frames, or commits.

        If ungrounded references are detected, drops confidence to <= 0.40.
        """
        if isinstance(rca_candidate, dict):
            raw = dict(rca_candidate)
        else:
            raw = rca_candidate.model_dump()

        valid_log_ids = {l.id for l in bundle.log_lines}
        valid_commit_shas = {c.get("commit", "") for c in bundle.recent_commits if isinstance(c, dict)}
        valid_frames = []
        if bundle.stack_trace:
            for fr in bundle.stack_trace.frames:
                valid_frames.append(f"{fr.file}:{fr.line}")
                valid_frames.append(fr.file)

        issues: List[str] = []
        evidence_items = raw.get("evidence", [])

        for idx, ev in enumerate(evidence_items):
            kind = ev.get("kind")
            ref = str(ev.get("ref", ""))

            if kind == "log_line":
                if ref not in valid_log_ids and not any(ref in l.message for l in bundle.log_lines):
                    issues.append(f"Ungrounded log_line ref '{ref}' not found in bundle logs")
            elif kind == "stack_frame":
                if not any(fr in ref or ref in fr for fr in valid_frames):
                    issues.append(f"Ungrounded stack_frame ref '{ref}' not in parsed stack trace")
            elif kind == "commit":
                if ref not in valid_commit_shas and not any(ref.startswith(s) for s in valid_commit_shas if s):
                    issues.append(f"Ungrounded commit ref '{ref}' not in recent commits")

        confidence = float(raw.get("confidence", 0.5))
        if issues:
            self.log_violation("evidence_grounding", "Ungrounded evidence references detected", {"issues": issues})
            confidence = min(confidence, self.grounding_penalty_threshold)
            raw["confidence"] = confidence

        # Build clean validated RcaResult
        ev_objs = [EvidenceItem(**item) for item in raw.get("evidence", [])]
        suspected_loc = None
        if raw.get("suspected_location"):
            suspected_loc = SuspectedLocation(**raw["suspected_location"])

        rca_result = RcaResult(
            incident_id=raw.get("incident_id", bundle.incident_id),
            classification=raw.get("classification", "insufficient_evidence"),
            severity=raw.get("severity", "sev3"),
            confidence=confidence,
            summary=raw.get("summary", "Analysis completed."),
            suspected_location=suspected_loc,
            evidence=ev_objs,
            ruled_out=raw.get("ruled_out", []),
            suggested_fix_strategy=raw.get("suggested_fix_strategy", ""),
        )

        return rca_result, issues

    def enforce_abstention_policy(self, bundle: ContextBundle, rca: RcaResult) -> RcaResult:
        """Enforce abstention rule: if evidence is missing/inconclusive, force insufficient_evidence."""
        has_fatal_trace = bool(bundle.stack_trace and bundle.stack_trace.frames)
        full_logs = " ".join(l.message for l in bundle.log_lines).lower()
        has_clear_error = any(
            kw in full_logs
            for kw in [
                "attributeerror",
                "typeerror",
                "keyerror",
                "memoryerror",
                "valueerror",
                "connection pool",
                "out of memory",
                "oom",
                "killed",
                "timeout",
                "gateway",
                "503",
                "config",
                "env",
                "invalid port",
            ]
        )

        if not has_fatal_trace and not has_clear_error:
            if rca.classification != "insufficient_evidence" or rca.confidence > 0.40:
                self.log_violation(
                    "abstention_policy",
                    "Overconfident classification without fatal error; enforcing abstention",
                    {"prior_classification": rca.classification, "prior_confidence": rca.confidence},
                )
                rca.classification = "insufficient_evidence"
                rca.confidence = min(rca.confidence, 0.35)
                rca.severity = "sev4"
                rca.summary = f"Insufficient evidence: {rca.summary}"

        return rca
