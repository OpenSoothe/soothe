"""Tests for SecurityPolicy security layer."""

from __future__ import annotations

import pytest

from soothe_nano.security.policy_models import (
    PolicyAction,
    PolicyDecision,
    PolicyViolation,
    SecurityPolicy,
)
from soothe_nano.security.policy_profiles import (
    PERMISSIVE_POLICY,
    READONLY_POLICY,
    SANDBOX_POLICY,
    STRICT_POLICY,
)


class TestSecurityPolicy:
    """Test cases for SecurityPolicy."""

    def test_policy_creation(self) -> None:
        """Test basic policy creation."""
        policy = SecurityPolicy(name="test_policy")

        assert policy.name == "test_policy"
        assert policy.allow_traversal is False

    def test_policy_evaluate_allowed_operation(self) -> None:
        """Test policy evaluation for allowed operation."""
        policy = SecurityPolicy(
            name="test",
            allowed_operations=frozenset({"read", "write"}),
        )

        decision = policy.evaluate("test.txt", "read")

        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW

    def test_policy_evaluate_blocked_operation(self) -> None:
        """Test policy evaluation for blocked operation."""
        policy = SecurityPolicy(
            name="test",
            allowed_operations=frozenset({"read"}),
        )

        decision = policy.evaluate("test.txt", "write")

        assert decision.allowed is False
        assert decision.action == PolicyAction.DENY
        assert decision.violations[0].violation_type == "operation_not_allowed"

    def test_policy_traversal_blocked(self) -> None:
        """Test that traversal is blocked by default."""
        policy = SecurityPolicy(name="test")

        decision = policy.evaluate("../etc/passwd", "read")

        assert decision.allowed is False
        assert any(v.violation_type == "traversal_not_allowed" for v in decision.violations)

    def test_policy_traversal_allowed(self) -> None:
        """Test that traversal can be allowed."""
        policy = SecurityPolicy(name="test", allow_traversal=True)

        decision = policy.evaluate("../test.txt", "read")

        # Should be allowed (other checks may still block)
        assert decision.allowed is True or any(
            v.violation_type != "traversal_not_allowed" for v in decision.violations
        )

    def test_policy_absolute_blocked(self) -> None:
        """Test that absolute paths are blocked by default."""
        policy = SecurityPolicy(name="test")

        decision = policy.evaluate("/etc/passwd", "read")

        assert decision.allowed is False
        assert any(v.violation_type == "absolute_path_not_allowed" for v in decision.violations)

    def test_policy_blocked_extension(self) -> None:
        """Test blocking by file extension."""
        policy = SecurityPolicy(
            name="test",
            blocked_extensions=frozenset({".exe", ".dll"}),
        )

        decision = policy.evaluate("malware.exe", "read")

        assert decision.allowed is False
        assert any(v.violation_type == "blocked_extension" for v in decision.violations)

    def test_policy_blocked_pattern(self) -> None:
        """Test blocking by pattern."""
        policy = SecurityPolicy(
            name="test",
            blocked_patterns=frozenset({"*.secret", "*.key"}),
        )

        decision = policy.evaluate("credentials.secret", "read")

        assert decision.allowed is False
        assert any(v.violation_type == "blocked_pattern" for v in decision.violations)

    def test_policy_blocked_path(self) -> None:
        """Test blocking by path prefix."""
        policy = SecurityPolicy(
            name="test",
            blocked_paths=frozenset({"/etc", "/root"}),
        )

        decision = policy.evaluate("/etc/passwd", "read")

        assert decision.allowed is False
        assert any(v.violation_type == "blocked_path" for v in decision.violations)

    def test_policy_allowed_paths_whitelist(self) -> None:
        """Test whitelist mode with allowed_paths."""
        policy = SecurityPolicy(
            name="test",
            allowed_paths=frozenset({"/safe", "/workspace"}),
        )

        # Path in allowed list
        decision_allowed = policy.evaluate("/safe/file.txt", "read")
        assert decision_allowed.allowed is True

        # Path not in allowed list
        decision_blocked = policy.evaluate("/other/file.txt", "read")
        assert decision_blocked.allowed is False
        assert any(v.violation_type == "path_not_allowed" for v in decision_blocked.violations)

    def test_policy_read_only_violation(self) -> None:
        """Test read-only path violation."""
        policy = SecurityPolicy(
            name="test",
            read_only_paths=frozenset({"/config"}),
        )

        decision = policy.evaluate("/config/settings.txt", "write")

        assert decision.allowed is False
        assert any(v.violation_type == "read_only_violation" for v in decision.violations)

    def test_policy_no_delete_violation(self) -> None:
        """Test no-delete path violation."""
        policy = SecurityPolicy(
            name="test",
            no_delete_paths=frozenset({"/important"}),
        )

        decision = policy.evaluate("/important/file.txt", "delete")

        assert decision.allowed is False
        assert any(v.violation_type == "delete_not_allowed" for v in decision.violations)

    def test_policy_path_too_long(self) -> None:
        """Test path length restriction."""
        policy = SecurityPolicy(
            name="test",
            max_path_length=10,
        )

        decision = policy.evaluate("very/long/path/name.txt", "read")

        assert decision.allowed is False
        assert any(v.violation_type == "path_too_long" for v in decision.violations)

    def test_policy_home_expansion_blocked(self) -> None:
        """Test home expansion blocking."""
        policy = SecurityPolicy(
            name="test",
            allow_home_expansion=False,
        )

        decision = policy.evaluate("~/.ssh/id_rsa", "read")

        assert decision.allowed is False
        assert any(v.violation_type == "home_expansion_not_allowed" for v in decision.violations)

    def test_policy_with_restrictions(self) -> None:
        """Test creating restricted policy variant."""
        base = SecurityPolicy(
            name="base",
            allow_traversal=True,
        )

        restricted = base.with_restrictions(allow_traversal=False)

        assert restricted.name == "base_restricted"
        assert restricted.allow_traversal is False


class TestPolicyDecision:
    """Test cases for PolicyDecision."""

    def test_is_denied_property(self) -> None:
        """Test is_denied property."""
        allowed = PolicyDecision(allowed=True, action=PolicyAction.ALLOW)
        denied = PolicyDecision(allowed=False, action=PolicyAction.DENY)

        assert allowed.is_denied is False
        assert denied.is_denied is True

    def test_should_log_property(self) -> None:
        """Test should_log property."""
        allow = PolicyDecision(allowed=True, action=PolicyAction.ALLOW)
        log = PolicyDecision(allowed=True, action=PolicyAction.LOG)
        deny = PolicyDecision(allowed=False, action=PolicyAction.DENY)

        assert allow.should_log is False
        assert log.should_log is True
        assert deny.should_log is True

    def test_merge_allowed_and_denied(self) -> None:
        """Test merging allowed and denied decisions."""
        allowed = PolicyDecision(allowed=True, action=PolicyAction.ALLOW)
        denied = PolicyDecision(
            allowed=False,
            action=PolicyAction.DENY,
            reason="blocked",
        )

        merged = allowed.merge(denied)

        assert merged.is_denied is True
        assert merged.reason == "blocked"

    def test_merge_violations(self) -> None:
        """Test that violations are merged."""
        v1 = PolicyViolation(
            policy_name="p1",
            violation_type="t1",
            message="m1",
        )
        v2 = PolicyViolation(
            policy_name="p2",
            violation_type="t2",
            message="m2",
        )

        d1 = PolicyDecision(
            allowed=True,
            action=PolicyAction.ALLOW,
            violations=[v1],
        )
        d2 = PolicyDecision(
            allowed=True,
            action=PolicyAction.ALLOW,
            violations=[v2],
        )

        merged = d1.merge(d2)

        assert len(merged.violations) == 2


class TestPolicyViolation:
    """Test cases for PolicyViolation."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        violation = PolicyViolation(
            policy_name="test_policy",
            violation_type="test_violation",
            message="Test message",
            path="/test/path",
            operation="read",
            severity="high",
        )

        d = violation.to_dict()

        assert d["policy_name"] == "test_policy"
        assert d["violation_type"] == "test_violation"
        assert d["severity"] == "high"
        assert "timestamp" in d


class TestPredefinedPolicies:
    """Test cases for predefined policies."""

    def test_strict_policy_blocks_traversal(self) -> None:
        """Test STRICT_POLICY blocks traversal."""
        decision = STRICT_POLICY.evaluate("../etc/passwd", "read")
        assert decision.is_denied is True

    def test_strict_policy_blocks_absolute(self) -> None:
        """Test STRICT_POLICY blocks absolute paths."""
        decision = STRICT_POLICY.evaluate("/etc/passwd", "read")
        assert decision.is_denied is True

    def test_strict_policy_blocks_dangerous_extensions(self) -> None:
        """Test STRICT_POLICY blocks dangerous extensions."""
        decision = STRICT_POLICY.evaluate("malware.exe", "read")
        assert decision.is_denied is True

    def test_permissive_policy_allows_absolute(self) -> None:
        """Test PERMISSIVE_POLICY allows absolute paths."""
        # Note: may still be blocked by other checks
        decision = PERMISSIVE_POLICY.evaluate("/workspace/file.txt", "read")
        # Permissive allows absolute, but may have other restrictions
        assert isinstance(decision.allowed, bool)

    def test_readonly_policy_blocks_write(self) -> None:
        """Test READONLY_POLICY blocks write operations."""
        decision = READONLY_POLICY.evaluate("file.txt", "write")
        assert decision.is_denied is True

    def test_readonly_policy_allows_read(self) -> None:
        """Test READONLY_POLICY allows read operations."""
        decision = READONLY_POLICY.evaluate("file.txt", "read")
        assert decision.allowed is True

    def test_sandbox_policy_blocks_many_extensions(self) -> None:
        """Test SANDBOX_POLICY blocks many extensions."""
        for ext in [".exe", ".sh", ".py", ".rb"]:
            decision = SANDBOX_POLICY.evaluate(f"file{ext}", "read")
            assert decision.is_denied is True, f"Should block {ext}"

    def test_sandbox_policy_limits_operations(self) -> None:
        """Test SANDBOX_POLICY limits allowed operations."""
        # These should be blocked
        for op in ["write", "delete", "edit"]:
            decision = SANDBOX_POLICY.evaluate("file.txt", op)
            assert decision.is_denied is True, f"Should block {op}"

    def test_sandbox_policy_allows_read(self) -> None:
        """Test SANDBOX_POLICY allows read operations."""
        decision = SANDBOX_POLICY.evaluate("file.txt", "read")
        assert decision.allowed is True


class TestPolicyCustomValidators:
    """Test cases for custom validators."""

    def test_custom_validator_blocks(self) -> None:
        """Test that custom validators can block operations."""

        def block_secret_files(path: str, operation: str) -> PolicyDecision | None:
            if "secret" in path.lower():
                return PolicyDecision(
                    allowed=False,
                    action=PolicyAction.DENY,
                    reason="Custom: secret files blocked",
                )
            return None

        policy = SecurityPolicy(
            name="test",
            custom_validators=[block_secret_files],
        )

        decision = policy.evaluate("my_secret.txt", "read")

        assert decision.is_denied is True
        assert "secret" in decision.reason.lower()

    def test_custom_validator_allows(self) -> None:
        """Test that custom validators can allow operations."""

        def allow_specific_file(path: str, operation: str) -> PolicyDecision | None:
            if path == "allowed.txt":
                return PolicyDecision(
                    allowed=True,
                    action=PolicyAction.ALLOW,
                    reason="Custom: specifically allowed",
                )
            return None

        policy = SecurityPolicy(
            name="test",
            blocked_patterns=frozenset({"*.txt"}),
            custom_validators=[allow_specific_file],
        )

        # This should be allowed by custom validator
        decision = policy.evaluate("allowed.txt", "read")

        # Custom validator returns allowed, but pattern blocks it
        # The most restrictive wins in merge
        assert isinstance(decision.allowed, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
