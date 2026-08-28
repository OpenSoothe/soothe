"""Unit tests for tool-approval rule pattern matching (RFC-622 §9b)."""

from __future__ import annotations

from soothe.sloop.clarification.tool_rule_matcher import (
    match_command_rule,
    match_path_rule,
    split_compound_command,
)

# ---------------------------------------------------------------------------
# Compound command splitting
# ---------------------------------------------------------------------------


class TestSplitCompoundCommand:
    def test_single_command(self) -> None:
        assert split_compound_command("git status") == ["git status"]

    def test_cd_prefix_stripped(self) -> None:
        result = split_compound_command("cd /path && git status")
        assert result == ["git status"]

    def test_cd_prefix_no_semicolon(self) -> None:
        result = split_compound_command("cd /path; git status")
        assert result == ["git status"]

    def test_multiple_and(self) -> None:
        result = split_compound_command("cd /path && git status && git diff")
        assert result == ["git status", "git diff"]

    def test_pipe_separator(self) -> None:
        result = split_compound_command("git log | head -10")
        assert result == ["git log", "head -10"]

    def test_or_separator(self) -> None:
        result = split_compound_command("false || true")
        assert result == ["false", "true"]

    def test_pushd_stripped(self) -> None:
        result = split_compound_command("pushd /path && make && popd")
        assert result == ["make"]

    def test_empty_after_strip(self) -> None:
        result = split_compound_command("cd /path")
        assert result == []

    def test_empty_command(self) -> None:
        assert split_compound_command("") == []

    def test_whitespace_only(self) -> None:
        assert split_compound_command("   ") == []


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
# Compound command matching
# ---------------------------------------------------------------------------


class TestCompoundCommandMatching:
    """Compound commands split into sub-commands; all must match."""

    def test_cd_and_git_status_matches(self) -> None:
        assert match_command_rule("cd /path && git status", "git status*") is True

    def test_cd_and_git_diff_matches(self) -> None:
        assert match_command_rule("cd /path && git diff", "git diff*") is True

    def test_cd_and_ls_matches(self) -> None:
        assert match_command_rule("cd /path && ls -la", "ls *") is True

    def test_cd_and_pytest_matches(self) -> None:
        assert (
            match_command_rule("cd /path && python3 -m pytest -xvs", "python3 -m pytest*") is True
        )

    def test_compound_mixed_match_no_match(self) -> None:
        """cd && git status && curl — curl doesn't match git status pattern."""
        assert (
            match_command_rule("cd /path && git status && curl https://example.com", "git status*")
            is False
        )

    def test_cd_and_git_log_piped_to_head(self) -> None:
        """cd && git log | head — both sub-commands must match the pattern."""
        assert (
            match_command_rule("cd /path && git log --oneline | head -10", "git log*") is False
        )  # head doesn't match git log*

    def test_cd_only_stripped_to_empty(self) -> None:
        assert match_command_rule("cd /path", "git status") is False

    def test_multiple_cd_segments(self) -> None:
        assert match_command_rule("cd /a && cd /b && git status", "git status*") is True


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
