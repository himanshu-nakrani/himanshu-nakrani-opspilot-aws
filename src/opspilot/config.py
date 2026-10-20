"""Explicit runtime mode for OpsPilot.

``OPSPILOT_MODE=live`` (set by CDK on every Lambda) means: real Bedrock,
real AWS, real GitHub/Jira, and any failure raises so Step Functions can
route it. ``OPSPILOT_MODE=replay`` (the default for local runs, tests and
evals) uses the offline/scripted model. Mode is never inferred from
credential env vars.
"""

import os

VALID_MODES = ("live", "replay")


def get_mode() -> str:
    mode = os.environ.get("OPSPILOT_MODE", "replay").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"OPSPILOT_MODE must be one of {VALID_MODES}, got '{mode}'")
    return mode


def is_live() -> bool:
    return get_mode() == "live"
