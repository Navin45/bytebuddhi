"""Unit tests for RedactionPolicy and DataBoundingPolicy privacy boundaries."""

from app.domain.models.observability import DataBoundingPolicy, RedactionPolicy


def test_redaction_sensitive_keys() -> None:
    """Verify sensitive keys are detected accurately."""
    assert RedactionPolicy.is_sensitive_key("authorization")
    assert RedactionPolicy.is_sensitive_key("Authorization")
    assert RedactionPolicy.is_sensitive_key("api_key")
    assert RedactionPolicy.is_sensitive_key("x-api-key")
    assert RedactionPolicy.is_sensitive_key("password")
    assert RedactionPolicy.is_sensitive_key("client_secret")
    assert RedactionPolicy.is_sensitive_key("access_token")
    assert RedactionPolicy.is_sensitive_key("set-cookie")

    # Non-sensitive keys
    assert not RedactionPolicy.is_sensitive_key("agent_role")
    assert not RedactionPolicy.is_sensitive_key("tool_name")
    assert not RedactionPolicy.is_sensitive_key("status")


def test_redaction_sensitive_string_patterns() -> None:
    """Verify bearer tokens and private keys embedded in text are sanitized."""
    text_with_token = "Request sent with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz.abc"
    sanitized = RedactionPolicy.sanitize_string(text_with_token)
    assert "[REDACTED]" in sanitized
    assert "eyJhbGciOiJIUzI1Ni" not in sanitized

    text_with_key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...==\n-----END RSA PRIVATE KEY-----"
    sanitized_key = RedactionPolicy.sanitize_string(text_with_key)
    assert sanitized_key == "[REDACTED]"


def test_redaction_sanitize_attributes_deep() -> None:
    """Verify deep dictionary and list sanitization."""
    payload = {
        "user_id": "user-123",
        "api_key": "sk-live-1234567890",
        "nested": {
            "token": "secret-token-abc",
            "safe": "visible",
            "list": ["clean", "Bearer secret-token-xyz-123"],
        },
    }
    sanitized = RedactionPolicy.sanitize_attributes(payload)
    assert sanitized["user_id"] == "user-123"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["nested"]["safe"] == "visible"
    assert sanitized["nested"]["list"][0] == "clean"
    assert sanitized["nested"]["list"][1] == "[REDACTED]"


def test_data_bounding_attribute_truncation() -> None:
    """Verify oversized strings are truncated gracefully."""
    huge_string = "A" * 500
    bounded = DataBoundingPolicy.bound_attribute_value(huge_string)
    assert len(bounded) < 250
    assert "[truncated]" in bounded


def test_metric_cardinality_whitelist_filter() -> None:
    """Verify high-cardinality and arbitrary dimensions are rejected from metrics."""
    raw_attrs = {
        "agent_role": "researcher",
        "tool_name": "read_file",
        "unbounded_uuid": "123e4567-e89b-12d3-a456-426614174000",
        "user_prompt_text": "tell me a secret",
        "status_code": "200",
    }
    bounded = DataBoundingPolicy.sanitize_and_bound_metric_attributes(raw_attrs)
    assert "agent_role" in bounded
    assert "tool_name" in bounded
    assert "status_code" in bounded
    assert "unbounded_uuid" not in bounded
    assert "user_prompt_text" not in bounded
