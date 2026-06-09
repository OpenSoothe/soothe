"""
Security Layer Usage Examples

This file demonstrates how to use the security layer for path validation
and policy enforcement.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from soothe.foundation.core.security import SecurityEnforcer
from soothe.foundation.core.security.enforcement import SecurityContext, SecurityError, create_enforcer
from soothe.foundation.core.security.integration import SecureFilesystemWrapper
from soothe.foundation.core.security.policy import (
    PERMISSIVE_POLICY,
    STRICT_POLICY,
    SecurityPolicy,
)
from soothe.foundation.core.security.validator import (
    create_strict_validator,
)


def example_basic_validation() -> None:
    """Example 1: Basic path validation."""
    print("\n=== Example 1: Basic Path Validation ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        validator = create_strict_validator(tmpdir)

        # Valid path
        result = validator.validate("src/main.py")
        print(f"Valid path 'src/main.py': {result.is_valid}")

        # Invalid path - traversal
        result = validator.validate("../etc/passwd")
        print(f"Invalid path '../etc/passwd': {result.is_valid}")
        print(f"  Violation: {result.violation_type}")
        print(f"  Message: {result.message}")


def example_policy_evaluation() -> None:
    """Example 2: Policy evaluation."""
    print("\n=== Example 2: Policy Evaluation ===")

    policy = SecurityPolicy(
        name="example",
        allow_traversal=False,
        allow_absolute=False,
        blocked_extensions={".exe", ".dll"},
        allowed_operations={"read", "ls"},
    )

    # Allowed operation
    decision = policy.evaluate("file.txt", "read")
    print(f"Read file.txt: {decision.allowed}")

    # Blocked operation
    decision = policy.evaluate("file.txt", "write")
    print(f"Write file.txt: {decision.allowed}")
    if decision.violations:
        print(f"  Reason: {decision.violations[0].message}")

    # Blocked extension
    decision = policy.evaluate("malware.exe", "read")
    print(f"Read malware.exe: {decision.allowed}")


def example_enforcer() -> None:
    """Example 3: Security enforcer with audit logging."""
    print("\n=== Example 3: Security Enforcer ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        enforcer = SecurityEnforcer(
            workspace=tmpdir,
            policy=STRICT_POLICY,
            enable_audit_log=True,
        )

        # Create a test file
        Path(tmpdir, "test.txt").write_text("Hello, World!")

        # Safe access
        try:
            safe_path = enforcer.get_safe_path("test.txt", "read")
            print(f"Safe path: {safe_path}")
            content = safe_path.read_text()
            print(f"Content: {content}")
        except SecurityError as e:
            print(f"Security error: {e}")

        # Blocked access
        try:
            enforcer.get_safe_path("../etc/passwd", "read")
        except SecurityError as e:
            print(f"Blocked: {e}")

        # Check audit log
        stats = enforcer.get_stats()
        print(f"Total operations: {stats['total_operations']}")
        print(f"Blocked operations: {stats['blocked_operations']}")


def example_predefined_policies() -> None:
    """Example 4: Using predefined policies."""
    print("\n=== Example 4: Predefined Policies ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Strict policy
        strict = create_enforcer(tmpdir, policy_name="strict")
        print(f"Strict policy blocks traversal: {strict.check_access('../test', 'read').is_denied}")

        # Readonly policy
        readonly = create_enforcer(tmpdir, policy_name="readonly")
        print(f"Readonly blocks write: {readonly.check_access('test.txt', 'write').is_denied}")
        print(f"Readonly allows read: {readonly.check_access('test.txt', 'read').allowed}")

        # Sandbox policy
        sandbox = create_enforcer(tmpdir, policy_name="sandbox")
        print(f"Sandbox blocks .exe: {sandbox.check_access('file.exe', 'read').is_denied}")


def example_secure_wrapper() -> None:
    """Example 5: Secure filesystem wrapper."""
    print("\n=== Example 5: Secure Filesystem Wrapper ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        from deepagents.backends.filesystem import FilesystemBackend

        # Create backend
        backend = FilesystemBackend(tmpdir)

        # Wrap with security
        secure = SecureFilesystemWrapper(
            backend,
            workspace=tmpdir,
            policy=STRICT_POLICY,
        )

        # Create test file
        Path(tmpdir, "test.txt").write_text("Hello")

        # Safe operation
        try:
            content = secure.read("test.txt")
            print(f"Read successful: {content[:20]}...")
        except SecurityError as e:
            print(f"Security error: {e}")

        # Blocked operation
        try:
            secure.read("../etc/passwd")
        except SecurityError as e:
            print(f"Blocked: {e}")


def example_decorator() -> None:
    """Example 6: Using secure_operation decorator."""
    print("\n=== Example 6: Secure Operation Decorator ===")

    # Note: This requires setting up workspace context
    # For demonstration, we'll show the pattern

    print("Decorator pattern:")
    print("""
    @secure_operation("read")
    def read_file(path: str) -> str:
        with open(path) as f:
            return f.read()

    # Automatically validated
    content = read_file("../etc/passwd")  # Raises SecurityError
    """)


def example_context_manager() -> None:
    """Example 7: Temporary policy with context manager."""
    print("\n=== Example 7: Security Context Manager ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        enforcer = SecurityEnforcer(
            workspace=tmpdir,
            policy=STRICT_POLICY,
        )

        # Normal policy blocks absolute
        decision = enforcer.check_access("/tmp/test", "read")
        print(f"Strict blocks absolute: {decision.is_denied}")

        # Temporarily use permissive policy
        with SecurityContext(enforcer, PERMISSIVE_POLICY):
            decision = enforcer.check_access("/tmp/test", "read")
            print(f"Permissive allows absolute: {decision.allowed}")

        # Policy restored
        decision = enforcer.check_access("/tmp/test", "read")
        print(f"Restored to strict: {decision.is_denied}")


def example_rate_limiting() -> None:
    """Example 8: Rate limiting."""
    print("\n=== Example 8: Rate Limiting ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        policy = STRICT_POLICY.with_restrictions(
            max_operations_per_minute=3,
        )

        enforcer = SecurityEnforcer(
            workspace=tmpdir,
            policy=policy,
            enable_rate_limiting=True,
        )

        # First 3 should succeed
        for i in range(5):
            decision = enforcer.check_access(f"file{i}.txt", "read")
            status = "allowed" if decision.allowed else "blocked"
            print(f"Operation {i + 1}: {status}")


def example_custom_policy() -> None:
    """Example 9: Custom policy with validators."""
    print("\n=== Example 9: Custom Policy ===")

    def block_temp_files(path: str, operation: str) -> None:
        """Custom validator that blocks temp files."""
        if "temp" in path.lower():
            from soothe.foundation.core.security.policy import PolicyAction, PolicyDecision

            return PolicyDecision(
                allowed=False,
                action=PolicyAction.DENY,
                reason="Temp files not allowed",
            )
        return None

    policy = SecurityPolicy(
        name="custom",
        custom_validators=[block_temp_files],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        enforcer = SecurityEnforcer(
            workspace=tmpdir,
            policy=policy,
        )

        # Normal file allowed
        decision = enforcer.check_access("file.txt", "read")
        print(f"file.txt: {decision.allowed}")

        # Temp file blocked
        decision = enforcer.check_access("temp_file.txt", "read")
        print(f"temp_file.txt: {decision.allowed}")


def example_audit_analysis() -> None:
    """Example 10: Analyzing audit logs."""
    print("\n=== Example 10: Audit Log Analysis ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        enforcer = SecurityEnforcer(
            workspace=tmpdir,
            policy=STRICT_POLICY,
            enable_audit_log=True,
        )

        # Generate some operations
        enforcer.check_access("file1.txt", "read")
        enforcer.check_access("../etc/passwd", "read")  # Blocked
        enforcer.check_access("file2.txt", "write")  # May be blocked

        # Analyze
        all_ops = enforcer.get_audit_log()
        blocked = enforcer.get_audit_log(allowed_only=False)
        violations = enforcer.get_violations()

        print(f"Total operations: {len(all_ops)}")
        print(f"Blocked operations: {len(blocked)}")
        print(f"Total violations: {len(violations)}")

        # Statistics
        stats = enforcer.get_stats()
        print(f"Violation types: {list(stats.get('violation_counts', {}).keys())}")


def main() -> None:
    """Run all examples."""
    print("=" * 60)
    print("Security Layer Examples")
    print("=" * 60)

    example_basic_validation()
    example_policy_evaluation()
    example_enforcer()
    example_predefined_policies()
    example_secure_wrapper()
    example_decorator()
    example_context_manager()
    example_rate_limiting()
    example_custom_policy()
    example_audit_analysis()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
