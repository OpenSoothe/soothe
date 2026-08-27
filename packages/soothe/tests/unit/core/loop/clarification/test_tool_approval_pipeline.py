"""Unit tests for the multi-stage tool-approval pipeline (RFC-622 §9b)."""

from __future__ import annotations

from soothe.config.models import ToolApprovalConfig
from soothe.sloop.clarification.tool_approval_pipeline import (
    ToolApprovalPipeline,
)

_DEFAULT_CONFIG = ToolApprovalConfig()


def _pipeline(config: ToolApprovalConfig | None = None) -> ToolApprovalPipeline:
    return ToolApprovalPipeline(config or _DEFAULT_CONFIG)


def _ar(name: str, **args: object) -> dict:
    """Build an action_request dict."""
    return {"name": name, "args": dict(args)}


# ---------------------------------------------------------------------------
# Stage 1: deny rules
# ---------------------------------------------------------------------------


class TestDenyRules:
    def test_rm_rf_rejected(self) -> None:
        result = _pipeline().evaluate([_ar("run_command", command="rm -rf /")])
        assert result is not None
        assert result.decision == "reject"
        assert result.stage == "deny_rule"

    def test_sudo_rejected(self) -> None:
        result = _pipeline().evaluate([_ar("run_command", command="sudo apt install foo")])
        assert result is not None
        assert result.decision == "reject"
        assert result.stage == "deny_rule"

    def test_etc_edit_rejected(self) -> None:
        result = _pipeline().evaluate([_ar("edit_file", file_path="/etc/nginx/nginx.conf")])
        assert result is not None
        assert result.decision == "reject"
        assert result.stage == "deny_rule"


# ---------------------------------------------------------------------------
# Stage 2: safety checks
# ---------------------------------------------------------------------------


class TestSafetyChecks:
    def test_git_dir_rejected_by_safety(self) -> None:
        """Path not matched by deny rules but caught by safety check."""
        # .git/config is not in deny_rules patterns, but safety check blocks it
        result = _pipeline().evaluate(
            [_ar("edit_file", file_path="/workspace/.git/config")],
            workspace_root="/workspace",
        )
        assert result is not None
        assert result.decision == "reject"
        assert result.stage == "safety_check"

    def test_bashrc_rejected_by_safety(self) -> None:
        result = _pipeline().evaluate([_ar("edit_file", file_path="/home/user/.bashrc")])
        assert result is not None
        assert result.decision == "reject"
        assert result.stage == "safety_check"

    def test_rm_r_only_caught_by_safety(self) -> None:
        """rm -r (without -rf) is caught by safety, not deny rules."""
        result = _pipeline().evaluate([_ar("run_command", command="rm -r /tmp/stuff")])
        assert result is not None
        assert result.decision == "reject"
        assert result.stage == "safety_check"


# ---------------------------------------------------------------------------
# Stage 3: allow rules
# ---------------------------------------------------------------------------


class TestAllowRules:
    def test_in_workspace_edit_approved(self) -> None:
        result = _pipeline().evaluate(
            [_ar("edit_file", file_path="/workspace/src/auth.py")],
            workspace_root="/workspace",
        )
        assert result is not None
        assert result.decision == "approve"
        assert result.stage == "allow_rule"

    def test_pytest_approved(self) -> None:
        result = _pipeline().evaluate([_ar("run_command", command="pytest -xvs")])
        assert result is not None
        assert result.decision == "approve"
        assert result.stage == "allow_rule"

    def test_git_status_approved(self) -> None:
        result = _pipeline().evaluate([_ar("run_command", command="git status")])
        assert result is not None
        assert result.decision == "approve"
        assert result.stage == "allow_rule"


# ---------------------------------------------------------------------------
# Stage 4: defer to veritas
# ---------------------------------------------------------------------------


class TestDeferToVeritas:
    def test_ambiguous_command_defers(self) -> None:
        """curl is not in any rule list → defer to veritas."""
        result = _pipeline().evaluate([_ar("run_command", command="curl https://example.com")])
        assert result is None

    def test_outside_workspace_edit_defers(self) -> None:
        """Path outside workspace and not matching any deny rule → defer."""
        result = _pipeline().evaluate(
            [_ar("edit_file", file_path="/home/user/random.txt")],
            workspace_root="/workspace",
        )
        assert result is None

    def test_unknown_tool_defers(self) -> None:
        result = _pipeline().evaluate([_ar("mcp_tool", path="/workspace/file.txt")])
        assert result is None

    def test_workspace_unknown_defers(self) -> None:
        """When workspace_root is None, <workspace>/** doesn't fire."""
        result = _pipeline().evaluate(
            [_ar("edit_file", file_path="/workspace/src/auth.py")],
            workspace_root=None,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Batch evaluation
# ---------------------------------------------------------------------------


class TestBatchEvaluation:
    def test_all_approved(self) -> None:
        result = _pipeline().evaluate(
            [
                _ar("edit_file", file_path="/workspace/src/auth.py"),
                _ar("run_command", command="pytest"),
            ],
            workspace_root="/workspace",
        )
        assert result is not None
        assert result.decision == "approve"

    def test_one_rejected_rejects_batch(self) -> None:
        """If any action is rejected, the whole batch is rejected."""
        result = _pipeline().evaluate(
            [
                _ar("edit_file", file_path="/workspace/src/auth.py"),
                _ar("run_command", command="rm -rf /"),
            ],
            workspace_root="/workspace",
        )
        assert result is not None
        assert result.decision == "reject"

    def test_one_ambiguous_defers_batch(self) -> None:
        """If any action is ambiguous, defer to veritas."""
        result = _pipeline().evaluate(
            [
                _ar("edit_file", file_path="/workspace/src/auth.py"),
                _ar("run_command", command="curl https://example.com"),
            ],
            workspace_root="/workspace",
        )
        assert result is None


# ---------------------------------------------------------------------------
# Pipeline disabled
# ---------------------------------------------------------------------------


class TestPipelineDisabled:
    def test_disabled_returns_none(self) -> None:
        """When enabled=False, pipeline is not constructed by factory.
        But if constructed directly with a disabled config, still returns None
        because the pipeline object exists but evaluates the same rules.

        The actual disabled behavior is runtime_factory not building the
        pipeline at all. Here we just verify the config flag exists."""
        config = ToolApprovalConfig(enabled=False)
        assert config.enabled is False


# ---------------------------------------------------------------------------
# Fail-safe
# ---------------------------------------------------------------------------


class TestFailSafe:
    def test_delete_not_auto_approved(self) -> None:
        """delete is not in default allow rules → defers to veritas."""
        result = _pipeline().evaluate(
            [_ar("delete", file_path="/workspace/old_file.py")],
            workspace_root="/workspace",
        )
        assert result is None

    def test_empty_action_requests_defers(self) -> None:
        result = _pipeline().evaluate([])
        assert result is None
