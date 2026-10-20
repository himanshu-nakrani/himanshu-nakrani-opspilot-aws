"""PII and secret redaction for OpsPilot.

Redacts emails, IP addresses, AWS credentials, GitHub tokens, Bearer tokens,
and generic secrets before sending log payloads to Bedrock or saving audit logs.
"""

import re
from typing import Any, Dict, List, Union

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
AWS_KEY_PATTERN = re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b")
GITHUB_TOKEN_PATTERN = re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{16,255}\b")
BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*")
GENERIC_SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?([^\s'\"]{8,})['\"]?")


def redact_text(text: str) -> str:
    """Scrub PII and sensitive credentials from text."""
    if not text:
        return text

    text = AWS_KEY_PATTERN.sub("[REDACTED_AWS_KEY]", text)
    text = GITHUB_TOKEN_PATTERN.sub("[REDACTED_GITHUB_TOKEN]", text)
    text = BEARER_PATTERN.sub("Bearer [REDACTED_TOKEN]", text)
    text = GENERIC_SECRET_PATTERN.sub(r"\1: [REDACTED_SECRET]", text)
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = IPV4_PATTERN.sub("[REDACTED_IP]", text)
    return text


def redact_payload(data: Union[str, Dict[str, Any], List[Any]]) -> Any:
    """Recursively scrub sensitive information from dictionaries, lists, or strings."""
    if isinstance(data, str):
        return redact_text(data)
    elif isinstance(data, dict):
        return {k: redact_payload(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_payload(item) for item in data]
    return data
