"""Conditional ``interrupt_on`` predicates for the HITL middleware.

Each predicate returns ``True`` when the tool call is dangerous enough to
warrant a human-facing interrupt, and ``False`` when it is safe to execute
silently. This keeps safe in-workspace edits and routine commands off the
clarification queue entirely — only genuinely dangerous operations
(out-of-workspace writes, destructive commands) trigger the interrupt.

The predicates are intentionally conservative: when the workspace root or
command cannot be inspected, they return ``True`` (fail-safe — interrupt).
The nano security evaluator (``WorkspaceToolOperationSecurity``) and the
deny-rule pipeline still run as belt-and-suspenders regardless of these
predicates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain.agents.middleware.types import ToolCallRequest

# ── Command patterns that are always dangerous ─────────────────────────

# These overlap with the nano security evaluator's ``_BANNED_COMMAND_PATTERNS``
# and the deny rules in ``ToolApprovalConfig``. The predicate checks them here
# so the interrupt fires *before* execution — the safety layer is a
# belt-and-suspenders that rejects if the interrupt is approved anyway.
_DANGEROUS_COMMAND_RE = re.compile(
    r"|".join(
        [
            r"\bsudo\b",
            r"\bsu\b\s",
            r"\bdoas\b",
            r"\brm\s+-rf?\b",
            r"\bmkfs\b",
            r"\bdd\s+if=",
            r"\bdd\s+of=/dev/",
            r"\bshred\b",
            r"\bchmod\s+-?R\b",
            r"\bchown\s+-?R\b",
            r"\bchgrp\s+-?R\b",
            r"\bchmod\s+\d{3,4}\b.*\s+/",  # chmod against root paths
            r"\b(apt|apt-get|brew|pip)\b.*\b(install|uninstall|remove)\b",
            r"\bnpm\s+install\s+-g\b",
            r"\b(fdisk|diskutil)\b",
            r"\b(shutdown|reboot|halt)\b",
            r"\bgit\s+push\s+(-f|--force)\b",
            r"\b(curl|wget)\b.*\|\s*(sh|bash)",
            r">\s*/(etc|bin|sbin|usr|System|Library)(/|$)",
        ]
    ),
    re.IGNORECASE,
)

# System directories that are never inside a user workspace.
_SYSTEM_PATH_PREFIXES = (
    "/etc",
    "/bin",
    "/sbin",
    "/usr",
    "/System",
    "/Library",
    "/private/etc",
    "/var",
    "/root",
    "/dev",
)

# Dangerous dotfiles / config files that compromise the shell or toolchain.
_DANGEROUS_DOTFILES = frozenset(
    {
        ".bashrc",
        ".bash_profile",
        ".zshrc",
        ".zprofile",
        ".profile",
        ".gitconfig",
        ".gitmodules",
        ".ssh",
        ".gnupg",
        ".env",
        ".aws",
        ".docker",
        ".npmrc",
        ".pypirc",
        ".netrc",
    }
)


def _workspace_from_config(config: dict[str, Any] | None) -> str | None:
    """Extract the workspace root from LangGraph configurable."""
    if not config:
        return None
    configurable = config.get("configurable") or {}
    if not isinstance(configurable, dict):
        return None
    ws = configurable.get("workspace")
    if isinstance(ws, str) and ws.strip():
        return ws
    return None


def _is_path_outside_workspace(path_str: str, workspace: str) -> bool:
    """True when ``path_str`` resolves outside the workspace root."""
    # Check for dangerous dotfiles by name against the raw path so symlinks
    # (e.g. macOS /home → /System/Volumes/Data/home) don't false-positive.
    raw_path = path_str.strip()
    raw_parts = Path(raw_path).parts
    for part in raw_parts:
        if part in _DANGEROUS_DOTFILES:
            return True
    # System paths are always outside workspace — check the raw path before
    # resolution to avoid macOS synthetic link false positives (/home → /System/...).
    if any(raw_path.startswith(p) for p in _SYSTEM_PATH_PREFIXES):
        return True
    try:
        target = Path(raw_path).expanduser().resolve()
        ws = Path(workspace).expanduser().resolve()
    except (OSError, ValueError):
        return True  # fail-safe: unresolved path → interrupt
    return ws not in target.parents and target != ws


def _should_interrupt_path_tool(
    req: ToolCallRequest,
    *,
    arg_keys: tuple[str, ...] = ("file_path", "path", "directory"),
) -> bool:
    """Predicate for ``edit_file`` / ``write_file`` / ``delete``.

    Returns ``True`` (interrupt) when the target path is outside the
    workspace or targets a dangerous dotfile/config. In-workspace
    writes are safe and do not interrupt.
    """
    args = req.tool_call.get("args") or {}
    if not isinstance(args, dict):
        return True
    workspace = _workspace_from_config(req.runtime.config)
    if not workspace:
        return True  # fail-safe
    for key in arg_keys:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            if _is_path_outside_workspace(val, workspace):
                return True
    return False


def _should_interrupt_run_command(req: ToolCallRequest) -> bool:
    """Predicate for ``run_command``.

    Returns ``True`` (interrupt) when the command matches a dangerous
    pattern (privilege escalation, destructive ops, system package
    installs, force-push, etc.) or writes to a system path. Safe routine
    commands do not interrupt.
    """
    args = req.tool_call.get("args") or {}
    if not isinstance(args, dict):
        return True
    command = str(args.get("command") or "")
    if not command.strip():
        return False
    if _DANGEROUS_COMMAND_RE.search(command):
        return True
    # Check for redirects to system paths (already covered by regex, but
    # also catch explicit file_path args on run_command wrappers).
    return False


def when_edit_file(req: ToolCallRequest) -> bool:
    """Interrupt only on out-of-workspace or dangerous-path edits."""
    return _should_interrupt_path_tool(req)


def when_write_file(req: ToolCallRequest) -> bool:
    """Interrupt only on out-of-workspace or dangerous-path writes."""
    return _should_interrupt_path_tool(req)


def when_delete(req: ToolCallRequest) -> bool:
    """Interrupt only on out-of-workspace or dangerous-path deletes."""
    return _should_interrupt_path_tool(req, arg_keys=("path", "file_path", "directory"))


def when_run_command(req: ToolCallRequest) -> bool:
    """Interrupt only on dangerous command patterns."""
    return _should_interrupt_run_command(req)


__all__ = [
    "when_delete",
    "when_edit_file",
    "when_run_command",
    "when_write_file",
]
