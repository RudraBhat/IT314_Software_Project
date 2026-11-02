"""Tests for Claude Code failure classification and secret redaction."""

from __future__ import annotations

import os
from unittest.mock import patch

from pipeline.claude_runner import (
    ClaudeFailureKind,
    classify_failure,
    redact_secrets,
)


def test_classify_quota_exhausted():
    samples = [
        "Error: You have exceeded your current quota.",
        "HTTP 429 Too Many Requests: Rate limit reached.",
        "Your credit balance is too low to access the Claude API.",
        "Claude Code usage limit reached for this billing period.",
        "API error: rate_limit_error: System is overloaded.",
    ]
    for s in samples:
        kind = classify_failure(1, "", s)
        assert kind == ClaudeFailureKind.QUOTA_EXHAUSTED, f"Expected QUOTA_EXHAUSTED for: {s}"


def test_classify_model_unavailable():
    samples = [
        "Error: model not found: claude-experimental",
        "Invalid model specified in command line arguments.",
        "Your account does not have access to model claude-3-opus.",
        "API error: model_not_found",
    ]
    for s in samples:
        kind = classify_failure(1, "", s)
        assert kind == ClaudeFailureKind.MODEL_UNAVAILABLE, f"Expected MODEL_UNAVAILABLE for: {s}"


def test_quota_takes_precedence_over_model_unavailable():
    # Ambiguous message containing both rate limit and model keywords
    ambiguous = "Rate limit reached for requested model claude-3-5-sonnet. Please check quota."
    kind = classify_failure(1, "", ambiguous)
    assert kind == ClaudeFailureKind.QUOTA_EXHAUSTED


def test_classify_auth_required():
    samples = [
        "Not authenticated. Please log in first.",
        "Error: unauthorized (401): invalid api key",
        "Token expired. Run claude to sign in again.",
    ]
    for s in samples:
        kind = classify_failure(1, "", s)
        assert kind == ClaudeFailureKind.AUTH_REQUIRED, f"Expected AUTH_REQUIRED for: {s}"


def test_classify_permission_denied():
    samples = [
        "Permission denied while reading /root/.claude",
        "HTTP 403 Forbidden",
    ]
    for s in samples:
        kind = classify_failure(1, "", s)
        assert kind == ClaudeFailureKind.PERMISSION_DENIED


def test_classify_timeout():
    assert classify_failure(-1, "", "Process killed") == ClaudeFailureKind.TIMEOUT
    assert classify_failure(1, "", "Command timed out after 300 seconds") == ClaudeFailureKind.TIMEOUT


def test_classify_fails_closed_to_other_error():
    assert classify_failure(1, "", "Some strange unknown crash") == ClaudeFailureKind.OTHER_ERROR
    assert classify_failure(137, "", "SIGKILL") == ClaudeFailureKind.OTHER_ERROR


def test_redact_secrets_api_key():
    raw = "Failed while connecting with sk-ant-api03-abcdef12345678901234567890"
    redacted = redact_secrets(raw)
    assert "sk-ant-api03-" not in redacted
    assert "[REDACTED_API_KEY]" in redacted


def test_redact_secrets_bearer_token():
    raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.secret"
    redacted = redact_secrets(raw)
    assert "eyJhbGci" not in redacted
    assert "Bearer [REDACTED_TOKEN]" in redacted


def test_redact_secrets_environment_variable():
    with patch.dict(os.environ, {"MY_TEST_SECRET": "SuperSecretVal123"}):
        raw = "Failed with password SuperSecretVal123 in call"
        redacted = redact_secrets(raw)
        assert "SuperSecretVal123" not in redacted
        assert "[REDACTED_MY_TEST_SECRET]" in redacted

