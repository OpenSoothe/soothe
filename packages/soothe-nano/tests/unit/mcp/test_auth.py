"""Unit tests for MCP authentication utilities (RFC-412)."""

import os
from typing import Any

import pytest

from soothe_nano.mcp.mcp_config import (
    StaticHeadersProvider,
    interpolate_auth_headers,
)


def identity_resolver(value: str) -> str:
    """Identity resolver that returns value unchanged."""
    return value


class TestInterpolateAuthHeaders:
    """Tests for interpolate_auth_headers function."""

    def test_empty_headers(self) -> None:
        """Empty dict returns empty dict."""
        result = interpolate_auth_headers({}, identity_resolver)
        assert result == {}

    def test_no_interpolation_needed(self) -> None:
        """Headers without ${...} syntax pass through unchanged."""
        headers = {"Authorization": "Bearer token123", "X-Custom": "value"}
        result = interpolate_auth_headers(headers, identity_resolver)
        assert result == headers

    def test_single_env_var(self) -> None:
        """Single ${ENV_VAR} is resolved."""

        def resolver(value: str) -> str:
            return value.replace("${API_KEY}", "secret123") if "${API_KEY}" in value else value

        headers = {"Authorization": "Bearer ${API_KEY}"}
        result = interpolate_auth_headers(headers, resolver)
        assert result["Authorization"] == "Bearer secret123"

    def test_multiple_keys(self) -> None:
        """Multiple header keys are all resolved."""

        def resolver(value: str) -> str:
            return value.replace("${API_KEY}", "secret123") if "${API_KEY}" in value else value

        headers = {
            "Authorization": "Bearer ${API_KEY}",
            "X-Api-Key": "${API_KEY}",
            "X-Custom": "static-value",
        }
        result = interpolate_auth_headers(headers, resolver)
        assert result == {
            "Authorization": "Bearer secret123",
            "X-Api-Key": "secret123",
            "X-Custom": "static-value",
        }

    def test_resolver_returns_different_value(self) -> None:
        """Resolver can transform values arbitrarily."""

        def resolver(value: str) -> str:
            return "resolved-value"

        headers = {"Authorization": "placeholder"}
        result = interpolate_auth_headers(headers, resolver)
        assert result["Authorization"] == "resolved-value"

    def test_identity_resolver(self) -> None:
        """Identity resolver returns headers unchanged."""
        headers = {"Authorization": "Bearer ${API_KEY}", "X-Token": "static"}
        result = interpolate_auth_headers(headers, identity_resolver)
        assert result == headers

    def test_resolver_raises_value_error(self) -> None:
        """ValueError from resolver propagates."""
        headers = {"Authorization": "Bearer ${MISSING_VAR}"}

        def strict_resolver(value: str) -> str:
            if "${" in value:
                raise ValueError(f"Unresolved env var in: {value}")
            return value

        with pytest.raises(ValueError, match="Unresolved env var"):
            interpolate_auth_headers(headers, strict_resolver)

    def test_resolver_with_default_for_missing(self) -> None:
        """Resolver can provide defaults for missing env vars."""
        headers = {"Authorization": "Bearer ${MISSING}"}

        def lenient_resolver(value: str) -> str:
            # Simplified resolver that provides defaults
            return value.replace("${MISSING}", "default-value")

        result = interpolate_auth_headers(headers, lenient_resolver)
        assert result["Authorization"] == "Bearer default-value"

    def test_special_characters_in_values(self) -> None:
        """Values with special characters are handled correctly."""
        headers = {
            "Authorization": "Bearer token\nwith\nnewlines",
            "X-Quote": 'value with "quotes"',
            "X-Unicode": "unicode: 你好世界",
        }
        result = interpolate_auth_headers(headers, identity_resolver)
        assert result["Authorization"] == "Bearer token\nwith\nnewlines"
        assert result["X-Quote"] == 'value with "quotes"'
        assert result["X-Unicode"] == "unicode: 你好世界"

    def test_special_characters_in_keys(self) -> None:
        """Keys with special characters are preserved."""
        headers = {
            "X-Custom-Header-123": "value1",
            "X-Header.With.Dots": "value2",
        }
        result = interpolate_auth_headers(headers, identity_resolver)
        assert "X-Custom-Header-123" in result
        assert "X-Header.With.Dots" in result

    def test_empty_string_value(self) -> None:
        """Empty string values are handled correctly."""
        headers = {"Authorization": "", "X-Empty": ""}
        result = interpolate_auth_headers(headers, identity_resolver)
        assert result["Authorization"] == ""
        assert result["X-Empty"] == ""

    def test_value_with_dollar_sign_without_braces(self) -> None:
        """Values with $ but not ${...} syntax pass through."""
        headers = {"X-Price": "$100", "X-Var": "$PATH"}
        result = interpolate_auth_headers(headers, identity_resolver)
        assert result["X-Price"] == "$100"
        assert result["X-Var"] == "$PATH"

    def test_value_with_unmatched_braces(self) -> None:
        """Values with malformed braces pass through (resolver's job to handle)."""
        headers = {
            "X-Partial": "${VAR",
            "X-Closing": "VAR}",
            "X-Empty": "${}",
        }
        result = interpolate_auth_headers(headers, identity_resolver)
        assert result["X-Partial"] == "${VAR"
        assert result["X-Closing"] == "VAR}"
        assert result["X-Empty"] == "${}"

    def test_case_sensitive_env_var_names(self) -> None:
        """Resolver handles case sensitivity (env vars are case-sensitive)."""
        headers = {"X-Var": "${My_Var}"}

        def case_resolver(value: str) -> str:
            return value.replace("${My_Var}", "resolved")

        result = interpolate_auth_headers(headers, case_resolver)
        assert result["X-Var"] == "resolved"

    def test_resolver_sees_full_value(self) -> None:
        """Resolver receives the full header value, not just the ${...} part."""
        calls: list[str] = []
        headers = {"Authorization": "Bearer ${API_KEY}"}

        def tracking_resolver(value: str) -> str:
            calls.append(value)
            return value.replace("${API_KEY}", "secret")

        interpolate_auth_headers(headers, tracking_resolver)
        assert calls == ["Bearer ${API_KEY}"]

    def test_resolver_called_for_each_value(self) -> None:
        """Resolver is called once for each header value."""
        call_count = [0]
        headers = {"H1": "v1", "H2": "v2", "H3": "v3"}

        def counting_resolver(value: str) -> str:
            call_count[0] += 1
            return value

        interpolate_auth_headers(headers, counting_resolver)
        assert call_count[0] == 3

    def test_original_headers_not_modified(self) -> None:
        """Original headers dict is not modified (returns new dict)."""
        headers = {"Authorization": "Bearer ${API_KEY}"}
        original_headers = dict(headers)

        def resolver(value: str) -> str:
            return value.replace("${API_KEY}", "resolved")

        result = interpolate_auth_headers(headers, resolver)

        # Original should be unchanged
        assert headers == original_headers
        assert headers["Authorization"] == "Bearer ${API_KEY}"
        # Result should have resolved value
        assert result["Authorization"] == "Bearer resolved"

    def test_multiple_env_vars_in_single_value(self) -> None:
        """Multiple ${VAR} patterns in single value are resolved by resolver."""
        headers = {"X-Config": "${VAR1}:${VAR2}"}

        def multi_resolver(value: str) -> str:
            return value.replace("${VAR1}", "val1").replace("${VAR2}", "val2")

        result = interpolate_auth_headers(headers, multi_resolver)
        assert result["X-Config"] == "val1:val2"

    def test_resolver_can_raise_any_exception(self) -> None:
        """Any exception from resolver propagates."""
        headers = {"Authorization": "Bearer ${API_KEY}"}

        def failing_resolver(value: str) -> str:
            raise RuntimeError("Something went wrong")

        with pytest.raises(RuntimeError, match="Something went wrong"):
            interpolate_auth_headers(headers, failing_resolver)


class TestStaticHeadersProvider:
    """Tests for StaticHeadersProvider class."""

    async def test_headers_returns_copy(self) -> None:
        """headers() returns a copy of internal headers."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token123"})
        headers1 = await provider.headers()
        headers2 = await provider.headers()

        # Each call returns a new dict
        assert headers1 == headers2
        assert headers1 is not headers2

    async def test_headers_empty(self) -> None:
        """Empty headers dict works correctly."""
        provider = StaticHeadersProvider({})
        headers = await provider.headers()
        assert headers == {}

    async def test_on_401_returns_false(self) -> None:
        """Static headers cannot refresh, so on_401 returns False."""
        provider = StaticHeadersProvider({"Authorization": "Bearer token"})
        result = await provider.on_401()
        assert result is False

    async def test_multiple_headers(self) -> None:
        """Multiple headers are preserved."""
        input_headers = {
            "Authorization": "Bearer token123",
            "X-Api-Key": "key123",
            "X-Custom": "value",
        }
        provider = StaticHeadersProvider(input_headers)
        headers = await provider.headers()
        assert headers == input_headers


class TestInterpolateAuthHeadersIntegration:
    """Integration tests with realistic resolver functions."""

    def test_with_resolve_env_style_resolver(self) -> None:
        """Test with resolver that mimics _resolve_env behavior."""
        import re

        env_pattern = re.compile(r"^\$\{(\w+)\}$")

        def resolve_env_style(value: str) -> str:
            m = env_pattern.match(value)
            if m:
                # Simulate returning value unchanged if env var missing
                return os.environ.get(m.group(1), value)
            return value

        # Test with non-matching pattern (no env var)
        headers = {"Authorization": "Bearer static-token"}
        result = interpolate_auth_headers(headers, resolve_env_style)
        assert result["Authorization"] == "Bearer static-token"

    def test_with_prefix_suffix_resolver(self) -> None:
        """Test resolver that handles prefix/suffix around env var."""

        def prefix_suffix_resolver(value: str) -> str:
            # Resolve ${VAR} with prefix/suffix preserved
            if "${" in value and "}" in value:
                # Simplified: just replace known patterns
                return value.replace("${API_KEY}", "my-secret-key")
            return value

        headers = {"Authorization": "Bearer ${API_KEY}", "X-Token": "${API_KEY}"}
        result = interpolate_auth_headers(headers, prefix_suffix_resolver)
        assert result["Authorization"] == "Bearer my-secret-key"
        assert result["X-Token"] == "my-secret-key"

    def test_with_missing_env_var_strict(self, monkeypatch: Any) -> None:
        """Test strict resolver that fails on missing env vars."""

        def strict_resolver(value: str) -> str:
            import re

            pattern = re.compile(r"\$\{(\w+)\}")
            match = pattern.search(value)
            if match:
                var_name = match.group(1)
                raise ValueError(f"Missing environment variable: {var_name}")
            return value

        headers = {"Authorization": "Bearer ${MISSING_VAR}"}
        with pytest.raises(ValueError, match="Missing environment variable"):
            interpolate_auth_headers(headers, strict_resolver)

    def test_with_missing_env_var_lenient(self, monkeypatch: Any) -> None:
        """Test lenient resolver that leaves unresolved vars unchanged."""

        def lenient_resolver(value: str) -> str:
            # Simulate _resolve_env behavior: return original if env var missing
            import re

            pattern = re.compile(r"^\$\{(\w+)\}$")
            m = pattern.match(value)
            if m:
                env_value = os.environ.get(m.group(1))
                return env_value if env_value else value
            return value

        headers = {"Authorization": "Bearer ${UNDEFINED_VAR_12345}"}
        result = interpolate_auth_headers(headers, lenient_resolver)
        # Should preserve original since env var doesn't exist
        assert result["Authorization"] == "Bearer ${UNDEFINED_VAR_12345}"
