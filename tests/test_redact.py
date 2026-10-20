"""Unit tests for PII and credential scrubbing."""

from opspilot.redact import redact_payload, redact_text


def test_redact_emails():
    text = "Error occurred for user alice.smith@corp.example.com when processing request."
    redacted = redact_text(text)
    assert "alice.smith@corp.example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted


def test_redact_ip_addresses():
    text = "Request from client IP 192.168.1.105 failed with 500."
    redacted = redact_text(text)
    assert "192.168.1.105" not in redacted
    assert "[REDACTED_IP]" in redacted


def test_redact_aws_and_github_keys():
    text = "Failed with AKIAIOSFODNN7EXAMPLE and token ghp_1234567890abcdef1234567890abcdef."
    redacted = redact_text(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "[REDACTED_AWS_KEY]" in redacted
    assert "ghp_1234567890abcdef1234567890abcdef" not in redacted
    assert "[REDACTED_GITHUB_TOKEN]" in redacted


def test_redact_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    redacted = redact_text(text)
    assert "eyJhbGciOiJIUzI1Ni" not in redacted
    assert "Bearer [REDACTED_TOKEN]" in redacted


def test_redact_nested_payload():
    data = {
        "user": {"email": "dev@example.org"},
        "logs": ["Failed for 10.0.0.12 with secret: 'supersecretpassword123'"],
    }
    redacted = redact_payload(data)
    assert redacted["user"]["email"] == "[REDACTED_EMAIL]"
    assert "10.0.0.12" not in redacted["logs"][0]
    assert "[REDACTED_IP]" in redacted["logs"][0]
