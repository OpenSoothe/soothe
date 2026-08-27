"""Unit tests for tool-approval safety checks (RFC-622 §9b)."""

from __future__ import annotations

from soothe.sloop.clarification.tool_safety_check import (
    DANGEROUS_DIRECTORIES,
    DANGEROUS_FILES,
    DESTRUCTIVE_COMMAND_PATTERNS,
    check_command_safety,
    check_path_safety,
)

# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestCheckPathSafety:
    def test_safe_path(self) -> None:
        result = check_path_safety("src/auth.py")
        assert result.safe

    def test_safe_absolute_path(self) -> None:
        result = check_path_safety("/workspace/src/main.py")
        assert result.safe

    def test_dangerous_file_bashrc(self) -> None:
        result = check_path_safety("/home/user/.bashrc")
        assert not result.safe
        assert "dangerous file" in result.reason.lower()

    def test_dangerous_file_gitconfig(self) -> None:
        result = check_path_safety("/repo/.gitconfig")
        assert not result.safe

    def test_dangerous_directory_git(self) -> None:
        result = check_path_safety("/workspace/.git/config")
        assert not result.safe
        assert "dangerous directory" in result.reason.lower()

    def test_dangerous_directory_vscode(self) -> None:
        result = check_path_safety("/workspace/.vscode/settings.json")
        assert not result.safe

    def test_dangerous_directory_claude(self) -> None:
        result = check_path_safety("/workspace/.claude/settings.json")
        assert not result.safe

    def test_path_traversal(self) -> None:
        result = check_path_safety("../../etc/passwd")
        assert not result.safe
        assert "traversal" in result.reason.lower()

    def test_unc_path_double_slash(self) -> None:
        result = check_path_safety("//server/share/file.txt")
        assert not result.safe
        assert "unc" in result.reason.lower()

    def test_unc_path_backslash(self) -> None:
        result = check_path_safety("\\\\server\\share\\file.txt")
        assert not result.safe

    def test_trailing_dots(self) -> None:
        result = check_path_safety(".git.")
        assert not result.safe
        assert "trailing" in result.reason.lower()

    def test_empty_path_safe(self) -> None:
        result = check_path_safety("")
        assert result.safe

    def test_case_insensitive_dangerous_dir(self) -> None:
        result = check_path_safety("/workspace/.GIT/config")
        assert not result.safe


# ---------------------------------------------------------------------------
# Command safety
# ---------------------------------------------------------------------------


class TestCheckCommandSafety:
    def test_safe_command(self) -> None:
        result = check_command_safety("pytest -xvs")
        assert result.safe

    def test_safe_ls(self) -> None:
        result = check_command_safety("ls -la")
        assert result.safe

    def test_rm_rf(self) -> None:
        result = check_command_safety("rm -rf /")
        assert not result.safe
        assert "rm -rf" in result.reason.lower()

    def test_sudo(self) -> None:
        result = check_command_safety("sudo apt install foo")
        assert not result.safe

    def test_chmod_777(self) -> None:
        result = check_command_safety("chmod 777 /tmp")
        assert not result.safe

    def test_git_force_push(self) -> None:
        result = check_command_safety("git push --force origin main")
        assert not result.safe

    def test_git_push_f(self) -> None:
        result = check_command_safety("git push -f origin main")
        assert not result.safe

    def test_dd(self) -> None:
        result = check_command_safety("dd if=/dev/zero of=/dev/sda")
        assert not result.safe

    def test_mkfs(self) -> None:
        result = check_command_safety("mkfs.ext4 /dev/sda1")
        assert not result.safe

    def test_case_insensitive(self) -> None:
        result = check_command_safety("RM -RF /")
        assert not result.safe

    def test_empty_command_safe(self) -> None:
        result = check_command_safety("")
        assert result.safe


# ---------------------------------------------------------------------------
# Constants exist
# ---------------------------------------------------------------------------


class TestConstants:
    def test_dangerous_files_populated(self) -> None:
        assert ".bashrc" in DANGEROUS_FILES
        assert ".gitconfig" in DANGEROUS_FILES
        assert ".mcp.json" in DANGEROUS_FILES

    def test_dangerous_directories_populated(self) -> None:
        assert ".git" in DANGEROUS_DIRECTORIES
        assert ".vscode" in DANGEROUS_DIRECTORIES
        assert ".claude" in DANGEROUS_DIRECTORIES

    def test_destructive_patterns_populated(self) -> None:
        assert "rm -rf" in DESTRUCTIVE_COMMAND_PATTERNS
        assert "sudo " in DESTRUCTIVE_COMMAND_PATTERNS
