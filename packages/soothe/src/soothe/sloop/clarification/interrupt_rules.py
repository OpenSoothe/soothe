"""Conditional ``interrupt_on`` predicates for the HITL middleware.

Each predicate returns ``True`` when the tool call is dangerous enough to
warrant a human interrupt, ``False`` when safe to execute silently.  Fail-safe:
when the workspace or command can't be inspected, returns ``True``.

Also consults the loop-scoped ``tool_approval_allowlist`` (via ``configurable``)
so an already-approved command or safety-rule family does not re-interrupt.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_nano.security.operation_guard import (
    dangerous_command_rule_id as _dangerous_command_rule_id,
)
from soothe_nano.security.operation_guard import (
    rule_family as _rule_family,
)

if TYPE_CHECKING:
    from langchain.agents.middleware.types import ToolCallRequest

# ── Command patterns that are always dangerous ─────────────────────────

# Overlaps with the nano security evaluator's banned patterns and the deny
# rules in ToolApprovalConfig — checked here so the interrupt fires *before*
# execution.
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


def _allowlist_from_config(config: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Extract the loop-scoped tool-approval allowlist from configurable."""
    if not config:
        return None
    configurable = config.get("configurable") or {}
    if not isinstance(configurable, dict):
        return None
    allowlist = configurable.get("tool_approval_allowlist")
    if isinstance(allowlist, list):
        return allowlist
    return None


def _signature_approved(
    tool_name: str,
    args: dict[str, Any],
    allowlist: list[dict[str, Any]] | None,
) -> bool:
    """True when the exact command/path signature is in the loop allowlist."""
    if not allowlist:
        return False
    if tool_name in _COMMAND_TOOLS:
        sig = str(args.get("command") or "").strip()
    elif tool_name in _PATH_TOOLS:
        sig = str(args.get("file_path") or args.get("path") or "").strip()
    else:
        return False
    if not sig:
        return False
    return any(
        isinstance(rec, dict)
        and str(rec.get("tool") or "") == tool_name
        and str(rec.get("signature") or "") == sig
        for rec in allowlist
    )


def _rule_approved(
    command: str,
    allowlist: list[dict[str, Any]] | None,
) -> bool:
    """True when a prior human approval overrode this command's safety rule family."""
    if not allowlist or not command:
        return False
    approved_rules = {
        str(rec.get("rule") or "") for rec in allowlist if isinstance(rec, dict) and rec.get("rule")
    }
    if not approved_rules:
        return False
    rule_id = _dangerous_command_rule_id(command)
    if not rule_id:
        return False
    return bool(_rule_family(rule_id) & approved_rules)


_COMMAND_TOOLS = frozenset({"run_command"})
_PATH_TOOLS = frozenset({"edit_file", "write_file", "delete"})


def _is_path_outside_workspace(path_str: str, workspace: str) -> bool:
    """True when `path_str` resolves outside the workspace root."""
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
    """Interrupt when the target path is outside the workspace or targets a
    dangerous dotfile/config.  Already-approved exact paths don't re-interrupt."""
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
                # Outside workspace → would interrupt, unless the human
                # already approved this exact path signature this loop.
                allowlist = _allowlist_from_config(req.runtime.config)
                tool_name = str(req.tool_call.get("name") or "")
                if _signature_approved(tool_name, args, allowlist):
                    return False
                return True
    return False


def _should_interrupt_run_command(req: ToolCallRequest) -> bool:
    """Interrupt when the command matches a dangerous pattern.  Already-approved
    commands (exact signature or prior rule-family override) don't re-interrupt."""
    args = req.tool_call.get("args") or {}
    if not isinstance(args, dict):
        return True
    command = str(args.get("command") or "")
    if not command.strip():
        return False
    if _DANGEROUS_COMMAND_RE.search(command):
        allowlist = _allowlist_from_config(req.runtime.config)
        # Exact-signature approval → execute silently (no re-interrupt).
        if _signature_approved("run_command", args, allowlist):
            return False
        # Rule-level override → the human already approved this safety rule
        # for a different command in this loop; don't re-interrupt.
        if _rule_approved(command, allowlist):
            return False
        return True
    return False


def when_edit_file(req: ToolCallRequest) -> bool:
    return _should_interrupt_path_tool(req)


def when_write_file(req: ToolCallRequest) -> bool:
    return _should_interrupt_path_tool(req)


def when_delete(req: ToolCallRequest) -> bool:
    return _should_interrupt_path_tool(req, arg_keys=("path", "file_path", "directory"))


def when_run_command(req: ToolCallRequest) -> bool:
    return _should_interrupt_run_command(req)


__all__ = [
    "when_delete",
    "when_edit_file",
    "when_run_command",
    "when_write_file",
]
