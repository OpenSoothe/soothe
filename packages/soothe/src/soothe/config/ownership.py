"""Ownership validation for split config files.

This module enforces which key paths belong in ``nano.yml`` vs ``soothe.yml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OwnershipViolation:
    """A single ownership rule violation."""

    key_path: str
    source_file: str
    target_file: str
    reason: str


class OwnershipViolationError(ValueError):
    """Raised when a config file contains keys owned by another file."""

    def __init__(self, violations: list[OwnershipViolation]) -> None:
        self.violations = list(violations)
        details = "; ".join(
            f"{v.key_path} in {v.source_file} (move to {v.target_file}: {v.reason})"
            for v in self.violations
        )
        super().__init__(f"Config ownership violation: {details}")


@dataclass(frozen=True, slots=True)
class OwnershipRule:
    """Disallowed key path rule for one source file."""

    path: str
    target_file: str
    reason: str


_NANO_DISALLOWED_RULES: tuple[OwnershipRule, ...] = (
    OwnershipRule("cron", "soothe.yml", "host scheduling service"),
    OwnershipRule("skillify", "soothe.yml", "host semantic skill service"),
    OwnershipRule("agent.loop", "soothe.yml", "host orchestration loop tuning"),
    OwnershipRule("agent.autopilot", "soothe.yml", "host autopilot behavior"),
    OwnershipRule("agent.clarification", "soothe.yml", "host clarification policy"),
    OwnershipRule("agent.veritas", "soothe.yml", "host veritas policy"),
)

_HOST_DISALLOWED_RULES: tuple[OwnershipRule, ...] = (
    OwnershipRule("providers", "nano.yml", "provider definitions are nano-owned"),
    OwnershipRule("router_profiles", "nano.yml", "router profiles are nano-owned"),
    OwnershipRule("embedding_profile", "nano.yml", "embedding profile is nano-owned"),
    OwnershipRule("active_router_profile", "nano.yml", "active router profile is nano-owned"),
    OwnershipRule("tools", "nano.yml", "tool configuration is nano-owned"),
    OwnershipRule("subagents", "nano.yml", "subagent catalog is nano-owned"),
    OwnershipRule("mcp_servers", "nano.yml", "MCP server declarations are nano-owned"),
    OwnershipRule("mcp_builtins", "nano.yml", "MCP builtin declarations are nano-owned"),
    OwnershipRule("progressive_mcp", "nano.yml", "MCP progressive tuning is nano-owned"),
    OwnershipRule("plugins", "nano.yml", "plugin declarations are nano-owned"),
    OwnershipRule("skills", "nano.yml", "skill source paths are nano-owned"),
    OwnershipRule("progressive_skills", "nano.yml", "progressive skill tuning is nano-owned"),
    OwnershipRule("progressive_tools", "nano.yml", "progressive tool tuning is nano-owned"),
    OwnershipRule("memory", "nano.yml", "memory source paths are nano-owned"),
    OwnershipRule("persistence", "nano.yml", "persistence backend settings are nano-owned"),
    OwnershipRule("observability", "nano.yml", "observability settings are nano-owned"),
    OwnershipRule("security", "nano.yml", "security settings are nano-owned"),
    OwnershipRule("filesystem_middleware", "nano.yml", "filesystem middleware is nano-owned"),
    OwnershipRule("workspace_mount", "nano.yml", "workspace mount settings are nano-owned"),
    OwnershipRule("optimization", "nano.yml", "optimization settings are nano-owned"),
    OwnershipRule("vector_stores", "nano.yml", "vector store providers are nano-owned"),
    OwnershipRule("vector_store_router", "nano.yml", "vector store routing is nano-owned"),
    OwnershipRule("agent.protocols", "nano.yml", "protocol backend selection is nano-owned"),
    OwnershipRule("agent.runtime", "nano.yml", "runtime settings are nano-owned"),
    OwnershipRule("agent.middleware", "nano.yml", "core middleware tuning is nano-owned"),
    OwnershipRule("agent.code_interpreter", "nano.yml", "code interpreter settings are nano-owned"),
)


def _path_exists(data: Any, dotted_path: str) -> bool:
    node = data
    for segment in dotted_path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return False
        node = node[segment]
    return True


def _collect_violations(
    data: dict[str, Any],
    *,
    source_file: str,
    rules: tuple[OwnershipRule, ...],
) -> list[OwnershipViolation]:
    violations: list[OwnershipViolation] = []
    for rule in rules:
        if _path_exists(data, rule.path):
            violations.append(
                OwnershipViolation(
                    key_path=rule.path,
                    source_file=source_file,
                    target_file=rule.target_file,
                    reason=rule.reason,
                )
            )
    return violations


def validate_nano_file_ownership(
    data: dict[str, Any],
    *,
    source_file: str = "nano.yml",
) -> None:
    """Validate that ``nano.yml`` does not contain host-owned key paths."""
    violations = _collect_violations(data, source_file=source_file, rules=_NANO_DISALLOWED_RULES)
    if violations:
        raise OwnershipViolationError(violations)


def validate_host_file_ownership(
    data: dict[str, Any],
    *,
    source_file: str = "soothe.yml",
) -> None:
    """Validate that ``soothe.yml`` does not contain nano-owned key paths."""
    violations = _collect_violations(data, source_file=source_file, rules=_HOST_DISALLOWED_RULES)
    if violations:
        raise OwnershipViolationError(violations)


__all__ = [
    "OwnershipViolation",
    "OwnershipViolationError",
    "validate_host_file_ownership",
    "validate_nano_file_ownership",
]
