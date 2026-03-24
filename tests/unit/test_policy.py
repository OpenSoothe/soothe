"""Tests for policy implementation (ConfigDrivenPolicy)."""

from soothe.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyProfile,
)
from soothe.safety.config_driven import (
    DEFAULT_PROFILES,
    PRIVILEGED_PROFILE,
    READONLY_PROFILE,
    STANDARD_PROFILE,
    ConfigDrivenPolicy,
    _extract_required_permission,
)


class TestPermission:
    """Tests for Permission class."""

    def test_permission_creation(self) -> None:
        """Test creating a permission."""
        perm = Permission("fs", "read", "/path/to/file")

        assert perm.category == "fs"
        assert perm.action == "read"
        assert perm.scope == "/path/to/file"

    def test_permission_matches_exact(self) -> None:
        """Test permission matching with exact scope."""
        perm = Permission("fs", "read", "/path/to/file")

        assert perm.matches(Permission("fs", "read", "/path/to/file"))
        assert not perm.matches(Permission("fs", "read", "/other/file"))

    def test_permission_matches_wildcard(self) -> None:
        """Test permission matching with wildcard scope."""
        perm = Permission("fs", "read", "*")

        assert perm.matches(Permission("fs", "read", "/any/path"))
        assert perm.matches(Permission("fs", "read", "/another/path"))

    def test_permission_matches_category_action(self) -> None:
        """Test permission matching requires same category and action."""
        perm = Permission("fs", "read", "*")

        assert not perm.matches(Permission("fs", "write", "*"))
        assert not perm.matches(Permission("shell", "read", "*"))


class TestPermissionSet:
    """Tests for PermissionSet class."""

    def test_contains_permission(self) -> None:
        """Test that PermissionSet contains check works."""
        perm_set = PermissionSet(
            frozenset(
                [
                    Permission("fs", "read", "*"),
                    Permission("fs", "write", "/specific/path"),
                ]
            )
        )

        assert perm_set.contains(Permission("fs", "read", "/any/path"))
        assert perm_set.contains(Permission("fs", "write", "/specific/path"))
        assert not perm_set.contains(Permission("fs", "write", "/other/path"))
        assert not perm_set.contains(Permission("shell", "execute", "*"))

    def test_narrow_restrictions(self) -> None:
        """Test narrowing a permission set."""
        parent_set = PermissionSet(
            frozenset(
                [
                    Permission("fs", "read", "*"),
                    Permission("fs", "write", "*"),
                    Permission("shell", "execute", "*"),
                ]
            )
        )

        restrictions = frozenset(
            [
                Permission("fs", "read", "/safe/path"),
                Permission("fs", "read", "*"),  # Keep read permission
            ]
        )

        child_set = parent_set.narrow(restrictions)

        # Child should have intersection of permissions
        assert child_set.contains(Permission("fs", "read", "/safe/path"))
        assert child_set.contains(Permission("fs", "read", "*"))
        assert not child_set.contains(Permission("shell", "execute", "*"))


class TestExtractRequiredPermission:
    """Tests for _extract_required_permission function."""

    def test_extract_fs_read_permission(self) -> None:
        """Test extracting file read permission."""
        action = ActionRequest(
            action_type="tool_call",
            tool_name="read_file",
            tool_args={"path": "/path/to/file"},
        )

        perm = _extract_required_permission(action)

        assert perm is not None
        assert perm.category == "fs"
        assert perm.action == "read"
        assert perm.scope == "/path/to/file"

    def test_extract_fs_write_permission(self) -> None:
        """Test extracting file write permission."""
        action = ActionRequest(
            action_type="tool_call",
            tool_name="write_file",
            tool_args={"path": "/path/to/file"},
        )

        perm = _extract_required_permission(action)

        assert perm is not None
        assert perm.category == "fs"
        assert perm.action == "write"

    def test_extract_shell_execute_permission(self) -> None:
        """Test extracting shell execute permission."""
        action = ActionRequest(
            action_type="tool_call",
            tool_name="execute",
            tool_args={"command": "ls -la"},
        )

        perm = _extract_required_permission(action)

        assert perm is not None
        assert perm.category == "shell"
        assert perm.action == "execute"
        assert perm.scope == "ls"

    def test_extract_subagent_spawn_permission(self) -> None:
        """Test extracting subagent spawn permission."""
        action = ActionRequest(
            action_type="subagent_spawn",
            tool_name="research",
        )

        perm = _extract_required_permission(action)

        assert perm is not None
        assert perm.category == "subagent"
        assert perm.action == "spawn"

    def test_extract_mcp_connect_permission(self) -> None:
        """Test extracting MCP connect permission."""
        action = ActionRequest(
            action_type="mcp_connect",
            tool_name="filesystem",
        )

        perm = _extract_required_permission(action)

        assert perm is not None
        assert perm.category == "mcp"
        assert perm.action == "connect"

    def test_extract_unknown_action(self) -> None:
        """Test extracting permission for unknown action."""
        action = ActionRequest(
            action_type="unknown",
        )

        perm = _extract_required_permission(action)

        assert perm is None


class TestConfigDrivenPolicy:
    """Unit tests for ConfigDrivenPolicy."""

    def test_initialization_with_defaults(self) -> None:
        """Test initialization with default profiles."""
        policy = ConfigDrivenPolicy()

        assert policy._profiles == DEFAULT_PROFILES
        assert "standard" in policy._profiles
        assert "readonly" in policy._profiles
        assert "privileged" in policy._profiles

    def test_initialization_with_custom_profiles(self) -> None:
        """Test initialization with custom profiles."""
        custom_profile = PolicyProfile(
            name="custom",
            permissions=PermissionSet(frozenset([Permission("fs", "read", "*")])),
            approvable=PermissionSet(frozenset()),
            deny_rules=[],
        )

        policy = ConfigDrivenPolicy(profiles={"custom": custom_profile})

        assert policy._profiles == {"custom": custom_profile}

    def test_check_allows_permitted_action(self) -> None:
        """Test that check allows a permitted action."""
        policy = ConfigDrivenPolicy()

        action = ActionRequest(
            action_type="tool_call",
            tool_name="read_file",
            tool_args={"path": "/any/path"},
        )

        context = PolicyContext(
            thread_id="thread_1",
            active_permissions=STANDARD_PROFILE.permissions,
        )

        decision = policy.check(action, context)

        assert decision.verdict == "allow"
        assert "Permitted by grant" in decision.reason

    def test_check_denies_missing_permission(self) -> None:
        """Test that check denies an action without permission."""
        policy = ConfigDrivenPolicy()

        action = ActionRequest(
            action_type="tool_call",
            tool_name="execute",
            tool_args={"command": "rm -rf /"},
        )

        # Create a custom permission set with no shell execute
        no_execute_permissions = PermissionSet(
            frozenset(
                [
                    Permission("fs", "read", "*"),
                    Permission("net", "outbound", "*"),
                ]
            )
        )

        context = PolicyContext(
            thread_id="thread_1",
            active_permissions=no_execute_permissions,
        )

        decision = policy.check(action, context)

        assert decision.verdict == "deny"
        assert "No matching permission" in decision.reason

    def test_check_requests_approval_for_approvable(self) -> None:
        """Test that check requests approval for approvable actions."""
        policy = ConfigDrivenPolicy()

        action = ActionRequest(
            action_type="tool_call",
            tool_name="write_file",
            tool_args={"path": "/protected/path"},
        )

        context = PolicyContext(
            thread_id="thread_1",
            active_permissions=READONLY_PROFILE.permissions,
        )

        decision = policy.check(action, context)

        assert decision.verdict == "need_approval"
        assert "Requires approval" in decision.reason

    def test_check_denies_by_deny_rule(self) -> None:
        """Test that check denies explicitly denied actions."""
        deny_profile = PolicyProfile(
            name="deny_test",
            permissions=PermissionSet(frozenset([Permission("fs", "write", "*")])),
            approvable=PermissionSet(frozenset()),
            deny_rules=[Permission("fs", "write", "/forbidden")],
        )

        policy = ConfigDrivenPolicy(profiles={"deny_test": deny_profile})

        action = ActionRequest(
            action_type="tool_call",
            tool_name="write_file",
            tool_args={"path": "/forbidden"},
        )

        context = PolicyContext(
            thread_id="thread_1",
            active_permissions=deny_profile.permissions,
        )

        decision = policy.check(action, context)

        assert decision.verdict == "deny"
        assert "Explicitly denied" in decision.reason

    def test_check_no_permission_required(self) -> None:
        """Test check when no permission is required."""
        policy = ConfigDrivenPolicy()

        action = ActionRequest(
            action_type="unknown",
        )

        context = PolicyContext(
            thread_id="thread_1",
            active_permissions=STANDARD_PROFILE.permissions,
        )

        decision = policy.check(action, context)

        assert decision.verdict == "allow"
        assert "No permission required" in decision.reason

    def test_narrow_for_child_with_restrictions(self) -> None:
        """Test narrowing permissions for a child subagent."""
        child_restrictions = {
            "research": frozenset(
                [
                    Permission("fs", "read", "/safe"),
                    Permission("fs", "read", "*"),  # Need to include this for intersection
                ]
            ),
        }

        policy = ConfigDrivenPolicy(child_restrictions=child_restrictions)

        parent_permissions = PermissionSet(
            frozenset(
                [
                    Permission("fs", "read", "*"),
                    Permission("fs", "write", "*"),
                ]
            )
        )

        child_permissions = policy.narrow_for_child(parent_permissions, "research")

        # Child should have intersection of permissions
        assert child_permissions.contains(Permission("fs", "read", "/safe"))
        assert child_permissions.contains(Permission("fs", "read", "*"))
        assert not child_permissions.contains(Permission("fs", "write", "*"))

    def test_narrow_for_child_without_restrictions(self) -> None:
        """Test narrowing when no specific restrictions exist."""
        policy = ConfigDrivenPolicy()

        parent_permissions = PermissionSet(
            frozenset(
                [
                    Permission("fs", "read", "*"),
                    Permission("fs", "write", "*"),
                ]
            )
        )

        child_permissions = policy.narrow_for_child(parent_permissions, "unknown_child")

        # Should return same permissions
        assert child_permissions == parent_permissions

    def test_get_profile_existing(self) -> None:
        """Test getting an existing profile."""
        policy = ConfigDrivenPolicy()

        profile = policy.get_profile("standard")

        assert profile is not None
        assert profile.name == "standard"

    def test_get_profile_nonexistent(self) -> None:
        """Test getting a nonexistent profile."""
        policy = ConfigDrivenPolicy()

        profile = policy.get_profile("nonexistent")

        assert profile is None


class TestStandardProfile:
    """Tests for the STANDARD profile."""

    def test_allows_common_actions(self) -> None:
        """Test that standard profile allows common actions."""
        ConfigDrivenPolicy()

        # Should allow fs read/write
        assert STANDARD_PROFILE.permissions.contains(Permission("fs", "read", "*"))
        assert STANDARD_PROFILE.permissions.contains(Permission("fs", "write", "*"))

        # Should allow shell execute
        assert STANDARD_PROFILE.permissions.contains(Permission("shell", "execute", "*"))

        # Should allow network outbound
        assert STANDARD_PROFILE.permissions.contains(Permission("net", "outbound", "*"))

        # Should allow MCP connect
        assert STANDARD_PROFILE.permissions.contains(Permission("mcp", "connect", "*"))

        # Should allow subagent spawn
        assert STANDARD_PROFILE.permissions.contains(Permission("subagent", "spawn", "*"))


class TestReadonlyProfile:
    """Tests for the READONLY profile."""

    def test_allows_read_only(self) -> None:
        """Test that readonly profile allows read actions."""
        # Should allow fs read
        assert READONLY_PROFILE.permissions.contains(Permission("fs", "read", "*"))

        # Should NOT allow fs write
        assert not READONLY_PROFILE.permissions.contains(Permission("fs", "write", "*"))

        # Should NOT allow shell execute
        assert not READONLY_PROFILE.permissions.contains(Permission("shell", "execute", "*"))

    def test_requires_approval_for_write(self) -> None:
        """Test that readonly profile requires approval for write."""
        # Write should be approvable
        assert READONLY_PROFILE.approvable.contains(Permission("fs", "write", "*"))

        # Shell execute should be approvable
        assert READONLY_PROFILE.approvable.contains(Permission("shell", "execute", "*"))


class TestPrivilegedProfile:
    """Tests for the PRIVILEGED profile."""

    def test_allows_all_actions(self) -> None:
        """Test that privileged profile allows all common actions."""
        # Should allow all file operations
        assert PRIVILEGED_PROFILE.permissions.contains(Permission("fs", "read", "*"))
        assert PRIVILEGED_PROFILE.permissions.contains(Permission("fs", "write", "*"))

        # Should allow shell execute
        assert PRIVILEGED_PROFILE.permissions.contains(Permission("shell", "execute", "*"))

        # Should allow network
        assert PRIVILEGED_PROFILE.permissions.contains(Permission("net", "outbound", "*"))

    def test_no_approvable_actions(self) -> None:
        """Test that privileged profile has no approvable actions."""
        assert len(PRIVILEGED_PROFILE.approvable.permissions) == 0
