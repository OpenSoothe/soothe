"""Unit tests for tool-approval rule pattern matching (RFC-622 §9b)."""

from __future__ import annotations

from soothe.sloop.clarification.tool_rule_matcher import (
    match_command_rule,
    match_path_rule,
)

# ---------------------------------------------------------------------------
# Command pattern matching
# ---------------------------------------------------------------------------


class TestMatchCommandRule:
    def test_exact_match(self) -> None:
        assert match_command_rule("git status", "git status") is True

    def test_exact_match_case_insensitive(self) -> None:
        assert match_command_rule("GIT STATUS", "git status") is True

    def test_exact_no_match(self) -> None:
        assert match_command_rule("git push", "git status") is False

    def test_prefix_match(self) -> None:
        assert match_command_rule("grep -r foo", "grep:*") is True

    def test_prefix_match_exact(self) -> None:
        assert match_command_rule("grep", "grep:*") is True

    def test_prefix_no_match(self) -> None:
        assert match_command_rule("rg foo", "grep:*") is False

    def test_wildcard_match(self) -> None:
        assert match_command_rule("pytest -xvs", "pytest*") is True

    def test_wildcard_match_no_args(self) -> None:
        assert match_command_rule("pytest", "pytest*") is True

    def test_wildcard_no_match(self) -> None:
        assert match_command_rule("ls -la", "pytest*") is False

    def test_wildcard_middle(self) -> None:
        assert match_command_rule("git push -f origin", "git push *") is True

    def test_empty_command(self) -> None:
        assert match_command_rule("", "git status") is False

    def test_empty_pattern(self) -> None:
        assert match_command_rule("git status", "") is False


# ---------------------------------------------------------------------------
# Path pattern matching
# ---------------------------------------------------------------------------


class TestMatchPathRule:
    def test_workspace_recursive(self) -> None:
        assert match_path_rule("/workspace/src/auth.py", "<workspace>/**", "/workspace") is True

    def test_workspace_nested(self) -> None:
        assert (
            match_path_rule(
                "/workspace/packages/soothe/src/main.py", "<workspace>/**", "/workspace"
            )
            is True
        )

    def test_outside_workspace(self) -> None:
        assert match_path_rule("/etc/passwd", "<workspace>/**", "/workspace") is False

    def test_workspace_root_unknown(self) -> None:
        """When workspace_root is None, <workspace> patterns fail-safe."""
        assert match_path_rule("/workspace/src/auth.py", "<workspace>/**", None) is False

    def test_absolute_pattern(self) -> None:
        assert match_path_rule("/etc/nginx.conf", "/etc/**", None) is True

    def test_absolute_no_match(self) -> None:
        assert match_path_rule("/home/user/file.txt", "/etc/**", None) is False

    def test_empty_path(self) -> None:
        assert match_path_rule("", "<workspace>/**", "/workspace") is False

    def test_empty_pattern(self) -> None:
        assert match_path_rule("/workspace/src/auth.py", "", "/workspace") is False
