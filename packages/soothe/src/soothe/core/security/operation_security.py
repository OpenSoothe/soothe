"""Operation security implementation for workspace + tool execution (RFC-617)."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from soothe.protocols.operation_security import (
    OperationSecurityContext,
    OperationSecurityDecision,
    OperationSecurityProtocol,
    OperationSecurityRequest,
)
from soothe.utils import expand_path

_BANNED_COMMAND_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"rm\s+-rf\s+/", "command.dangerous.rm_root"),
    (r"sudo\s+rm\s+-rf", "command.dangerous.sudo_rm_rf"),
    (r"mkfs(\.|$)", "command.dangerous.mkfs"),
    (r"dd\s+if=", "command.dangerous.dd"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "command.dangerous.fork_bomb"),
)


class WorkspaceToolOperationSecurity(OperationSecurityProtocol):
    """Evaluate workspace filesystem and execution command security."""

    def evaluate(
        self, request: OperationSecurityRequest, context: OperationSecurityContext
    ) -> OperationSecurityDecision:
        if request.operation_kind in {"filesystem_read", "filesystem_write"}:
            if request.target_path:
                return self._check_filesystem(context, request.target_path)
            return OperationSecurityDecision(verdict="allow", reason="No filesystem path provided")

        if request.operation_kind == "shell_execute" and request.command:
            return self._check_command(request.command)

        return OperationSecurityDecision(
            verdict="allow", reason="No operation security rule matched"
        )

    def _check_filesystem(
        self, context: OperationSecurityContext, target_path: str
    ) -> OperationSecurityDecision:
        security = context.security_config
        if security is None:
            return OperationSecurityDecision(verdict="allow", reason="No security config")

        file_path = target_path.strip()
        if not file_path:
            return OperationSecurityDecision(verdict="allow", reason="No file path specified")

        resolved_path = expand_path(file_path)

        for pattern in security.denied_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Path '{file_path}' matches denied pattern '{pattern}'",
                    rule_id="filesystem.denied_path",
                )

        is_allowed = False
        for pattern in security.allowed_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                is_allowed = True
                break
        if not is_allowed:
            return OperationSecurityDecision(
                verdict="deny",
                reason=f"Path '{file_path}' does not match any allowed pattern",
                rule_id="filesystem.allowed_path_miss",
            )

        workspace_root: Path | None = None
        if context.workspace and str(context.workspace).strip():
            workspace_root = expand_path(str(context.workspace).strip())
        if workspace_root is not None:
            try:
                resolved_path.relative_to(workspace_root)
            except ValueError:
                if not security.allow_paths_outside_workspace:
                    return OperationSecurityDecision(
                        verdict="deny",
                        reason=f"Path '{file_path}' is outside workspace",
                        rule_id="filesystem.workspace_boundary",
                    )
                if security.require_approval_for_outside_paths:
                    return OperationSecurityDecision(
                        verdict="need_approval",
                        reason=f"Path '{file_path}' is outside workspace and requires approval",
                        rule_id="filesystem.outside_workspace_approval",
                    )

        file_ext = resolved_path.suffix.lower()
        if file_ext in security.denied_file_types:
            return OperationSecurityDecision(
                verdict="deny",
                reason=f"File type '{file_ext}' is explicitly denied",
                rule_id="filesystem.denied_filetype",
            )
        if file_ext in security.require_approval_for_file_types:
            return OperationSecurityDecision(
                verdict="need_approval",
                reason=f"Access to '{file_ext}' files requires approval",
                rule_id="filesystem.filetype_approval",
            )
        return OperationSecurityDecision(verdict="allow", reason="Filesystem checks passed")

    def _check_command(self, command: str) -> OperationSecurityDecision:
        command_text = command.strip()
        if not command_text:
            return OperationSecurityDecision(verdict="allow", reason="No command provided")

        for pattern, rule_id in _BANNED_COMMAND_PATTERNS:
            if re.search(pattern, command_text, re.IGNORECASE):
                return OperationSecurityDecision(
                    verdict="deny",
                    reason=f"Command blocked by security rule: {pattern}",
                    rule_id=rule_id,
                )
        return OperationSecurityDecision(verdict="allow", reason="Command checks passed")

    def _expand_path_pattern(self, pattern: str) -> str:
        if pattern.startswith("~"):
            return str(Path(pattern).expanduser())
        return pattern

    def _path_matches_pattern(self, path: Path, pattern: str) -> bool:
        path_str = str(path)
        return fnmatch.fnmatch(path_str, pattern) or path_str.startswith(pattern.rstrip("*"))
