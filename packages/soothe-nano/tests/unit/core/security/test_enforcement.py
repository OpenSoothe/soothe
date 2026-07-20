"""Tests for SecurityEnforcer security layer."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from soothe_nano.security.policy_models import (
    PolicyAction,
    PolicyDecision,
    PolicyViolation,
)
from soothe_nano.security.policy_profiles import (
    PERMISSIVE_POLICY,
    STRICT_POLICY,
)
from soothe_nano.security.security_enforcer import (
    RateLimiter,
    SecurityContext,
    SecurityEnforcer,
    SecurityError,
    create_enforcer,
)


class TestRateLimiter:
    """Test cases for RateLimiter."""

    def test_rate_limiter_allows_under_limit(self) -> None:
        """Test that operations are allowed under the limit."""
        limiter = RateLimiter(window_seconds=60)

        allowed, count = limiter.check_rate("read", 10)

        assert allowed is True
        assert count == 0

    def test_rate_limiter_blocks_over_limit(self) -> None:
        """Test that operations are blocked over the limit."""
        limiter = RateLimiter(window_seconds=60)

        # Record 10 operations
        for _ in range(10):
            limiter.record("read", "/test.txt")

        allowed, count = limiter.check_rate("read", 10)

        assert allowed is False
        assert count == 10

    def test_rate_limiter_resets_after_window(self) -> None:
        """Test that rate limit resets after time window."""
        limiter = RateLimiter(window_seconds=0.1)  # 100ms window

        # Record operations
        for _ in range(10):
            limiter.record("read", "/test.txt")

        # Wait for window to pass
        time.sleep(0.15)

        # Should be allowed again
        allowed, count = limiter.check_rate("read", 10)
        assert allowed is True
        assert count == 0

    def test_rate_limiter_per_path(self) -> None:
        """Test per-path rate limiting."""
        limiter = RateLimiter(window_seconds=60)

        # Record 5 operations on one path
        for _ in range(5):
            limiter.record("read", "/file1.txt")

        # Check rate for different path
        allowed, count = limiter.check_rate("read", 5, "/file2.txt")

        # Should be allowed (different path)
        assert allowed is True

    def test_rate_limiter_get_stats(self) -> None:
        """Test getting rate limiter statistics."""
        limiter = RateLimiter(window_seconds=60)

        limiter.record("read", "/test.txt")
        limiter.record("write", "/test.txt")

        stats = limiter.get_stats()

        assert "operations" in stats
        assert "paths" in stats
        assert stats["operations"].get("read", 0) == 1


class TestSecurityEnforcer:
    """Test cases for SecurityEnforcer."""

    @pytest.fixture()
    def workspace(self) -> Path:
        """Create a temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir).resolve()

    @pytest.fixture()
    def enforcer(self, workspace: Path) -> SecurityEnforcer:
        """Create a security enforcer."""
        return SecurityEnforcer(
            workspace=workspace,
            policy=STRICT_POLICY,
            enable_audit_log=True,
            enable_rate_limiting=True,
        )

    def test_enforcer_allows_safe_path(self, enforcer: SecurityEnforcer) -> None:
        """Test that safe paths are allowed."""
        decision = enforcer.check_access("src/main.py", "read")

        assert decision.allowed is True
        assert decision.action == PolicyAction.ALLOW

    def test_enforcer_blocks_traversal(self, enforcer: SecurityEnforcer) -> None:
        """Test that traversal is blocked."""
        decision = enforcer.check_access("../etc/passwd", "read")

        assert decision.is_denied is True
        assert len(decision.violations) > 0

    def test_enforcer_blocks_absolute(self, enforcer: SecurityEnforcer) -> None:
        """Test that absolute paths are blocked."""
        decision = enforcer.check_access("/etc/passwd", "read")

        assert decision.is_denied is True

    def test_enforcer_get_safe_path_success(
        self, enforcer: SecurityEnforcer, workspace: Path
    ) -> None:
        """Test getting safe path for valid path."""
        # Create the file
        (workspace / "test.txt").write_text("test")

        safe_path = enforcer.get_safe_path("test.txt", "read")

        assert safe_path == workspace / "test.txt"

    def test_enforcer_get_safe_path_failure(self, enforcer: SecurityEnforcer) -> None:
        """Test that get_safe_path raises on invalid path."""
        with pytest.raises(SecurityError) as exc_info:
            enforcer.get_safe_path("../etc/passwd", "read")

        assert "Access denied" in str(exc_info.value)

    def test_enforcer_audit_log(self, enforcer: SecurityEnforcer) -> None:
        """Test that operations are logged to audit log."""
        # Perform an operation
        enforcer.check_access("test.txt", "read")

        # Check audit log
        log = enforcer.get_audit_log()

        assert len(log) == 1
        assert log[0].operation == "read"
        assert log[0].path == "test.txt"

    def test_enforcer_audit_log_filtered(self, enforcer: SecurityEnforcer) -> None:
        """Test filtering audit log."""
        # Perform operations
        enforcer.check_access("file1.txt", "read")
        enforcer.check_access("file2.txt", "write")

        # Filter by operation
        log = enforcer.get_audit_log(operation="read")

        assert len(log) == 1
        assert log[0].operation == "read"

    def test_enforcer_get_violations(self, enforcer: SecurityEnforcer) -> None:
        """Test getting violations from audit log."""
        # Perform blocked operation
        enforcer.check_access("../etc/passwd", "read")

        violations = enforcer.get_violations()

        assert len(violations) > 0

    def test_enforcer_get_stats(self, enforcer: SecurityEnforcer) -> None:
        """Test getting security statistics."""
        # Perform operations
        enforcer.check_access("file1.txt", "read")
        enforcer.check_access("../etc/passwd", "read")

        stats = enforcer.get_stats()

        assert stats["total_operations"] == 2
        assert stats["blocked_operations"] == 1
        assert stats["policy_name"] == "strict"

    def test_enforcer_clear_audit_log(self, enforcer: SecurityEnforcer) -> None:
        """Test clearing audit log."""
        enforcer.check_access("test.txt", "read")
        assert len(enforcer.audit_log) == 1

        enforcer.clear_audit_log()

        assert len(enforcer.audit_log) == 0

    def test_enforcer_update_policy(self, enforcer: SecurityEnforcer) -> None:
        """Test updating security policy."""
        old_name = enforcer.policy.name

        enforcer.update_policy(PERMISSIVE_POLICY)

        assert enforcer.policy.name == "permissive"
        assert enforcer.policy.name != old_name

    def test_enforcer_rate_limiting(self, workspace: Path) -> None:
        """Test rate limiting in enforcer."""
        # Create policy with low rate limit
        policy = STRICT_POLICY.with_restrictions(
            max_operations_per_minute=2,
        )

        enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=policy,
            enable_rate_limiting=True,
        )

        # First two should succeed
        d1 = enforcer.check_access("file1.txt", "read")
        d2 = enforcer.check_access("file2.txt", "read")

        assert d1.allowed is True
        assert d2.allowed is True

        # Third should be rate limited
        d3 = enforcer.check_access("file3.txt", "read")

        assert d3.is_denied is True
        assert any(v.violation_type == "rate_limit_exceeded" for v in d3.violations)

    def test_enforcer_violation_callback(self, workspace: Path) -> None:
        """Test violation callback."""
        violations: list[PolicyViolation] = []

        def callback(v: PolicyViolation) -> None:
            violations.append(v)

        enforcer = SecurityEnforcer(
            workspace=workspace,
            policy=STRICT_POLICY,
            violation_callback=callback,
        )

        # Trigger violation
        enforcer.check_access("../etc/passwd", "read")

        assert len(violations) > 0


class TestSecurityContext:
    """Test cases for SecurityContext context manager."""

    @pytest.fixture()
    def workspace(self) -> Path:
        """Create a temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir).resolve()

    @pytest.fixture()
    def enforcer(self, workspace: Path) -> SecurityEnforcer:
        """Create a security enforcer."""
        return SecurityEnforcer(
            workspace=workspace,
            policy=STRICT_POLICY,
        )

    def test_security_context_temp_policy(self, enforcer: SecurityEnforcer) -> None:
        """Test temporary policy change with context manager."""
        original_policy = enforcer.policy.name

        with SecurityContext(enforcer, PERMISSIVE_POLICY):
            # Policy should be permissive inside context
            assert enforcer.policy.name == "permissive"

        # Policy should be restored after context
        assert enforcer.policy.name == original_policy

    def test_security_context_restores_on_exception(self, enforcer: SecurityEnforcer) -> None:
        """Test that policy is restored even if exception occurs."""
        original_policy = enforcer.policy.name

        try:
            with SecurityContext(enforcer, PERMISSIVE_POLICY):
                assert enforcer.policy.name == "permissive"
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Policy should still be restored
        assert enforcer.policy.name == original_policy


class TestCreateEnforcer:
    """Test cases for create_enforcer factory function."""

    @pytest.fixture()
    def workspace(self) -> Path:
        """Create a temporary workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir).resolve()

    def test_create_strict_enforcer(self, workspace: Path) -> None:
        """Test creating strict enforcer."""
        enforcer = create_enforcer(workspace, policy_name="strict")

        assert enforcer.policy.name == "strict"

        # Should block traversal
        decision = enforcer.check_access("../etc/passwd", "read")
        assert decision.is_denied is True

    def test_create_permissive_enforcer(self, workspace: Path) -> None:
        """Test creating permissive enforcer."""
        enforcer = create_enforcer(workspace, policy_name="permissive")

        assert enforcer.policy.name == "permissive"

    def test_create_readonly_enforcer(self, workspace: Path) -> None:
        """Test creating readonly enforcer."""
        enforcer = create_enforcer(workspace, policy_name="readonly")

        assert enforcer.policy.name == "readonly"

        # Should block write
        decision = enforcer.check_access("file.txt", "write")
        assert decision.is_denied is True

    def test_create_sandbox_enforcer(self, workspace: Path) -> None:
        """Test creating sandbox enforcer."""
        enforcer = create_enforcer(workspace, policy_name="sandbox")

        assert enforcer.policy.name == "sandbox"

    def test_create_enforcer_unknown_policy_defaults_to_strict(self, workspace: Path) -> None:
        """Test that unknown policy name defaults to strict."""
        enforcer = create_enforcer(workspace, policy_name="unknown")

        assert enforcer.policy.name == "strict"


class TestSecurityError:
    """Test cases for SecurityError exception."""

    def test_security_error_with_violations(self) -> None:
        """Test SecurityError with violations."""
        error = SecurityError(
            message="Access denied",
            violations="traversal, absolute_path",
        )

        assert str(error) == "Access denied"
        assert error.violations == "traversal, absolute_path"

    def test_security_error_with_decision(self) -> None:
        """Test SecurityError with decision."""
        decision = PolicyDecision(
            allowed=False,
            action=PolicyAction.DENY,
            reason="Test reason",
        )

        error = SecurityError(
            message="Access denied",
            decision=decision,
        )

        assert error.decision == decision


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
