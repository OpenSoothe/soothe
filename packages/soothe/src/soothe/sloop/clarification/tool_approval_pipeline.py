"""Deny-list-first tool-approval pipeline evaluator.

Two stages run cheapest-first: deny rules → safety checks. Any action
that passes both is auto-approved (absence of deny = implicit allow).
In manual mode, passing actions are deferred to the human relay.

Safety property: deny rules and safety checks always run before the
default-approve. No configuration can override a safety denial.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from soothe.sloop.clarification.tool_rule_matcher import (
    match_command_rule,
    match_path_rule,
)

if TYPE_CHECKING:
    from soothe.config.models import ToolApprovalConfig

logger = logging.getLogger(__name__)

_STAGE_PREFIX = "tool_approval"

ApprovalDecision = Literal["approve", "reject"]
PipelineStage = Literal["deny_rule", "safety_check", "allow_rule", "default_approve"]


@dataclass(frozen=True)
class ApprovalResult:
    """Decision returned by the pipeline for a batch of action requests."""

    decision: ApprovalDecision
    stage: PipelineStage
    reason: str = ""


class ToolApprovalPipeline:
    """Deny-list-first tool-approval evaluator.

    Two stages run cheapest-first: deny rules → safety checks. The first
    stage that returns a decision wins. Any action that passes both stages
    is auto-approved in auto mode (absence of deny = implicit allow).

    Safety property: deny rules and safety checks always run before the
    default-approve. No configuration can override a safety denial.

    Stage 2 delegates to nano's ``WorkspaceToolOperationSecurity`` — the same
    evaluator used by ``SoothePolicyMiddleware`` (Layer 1) and the tool
    execution layer (Layer 3). This ensures one source of truth for safety
    constants (banned command patterns, dangerous paths/files).
    """

    def __init__(
        self,
        config: ToolApprovalConfig,
        *,
        security_config: Any = None,
    ) -> None:
        self._deny_rules = config.deny_rules
        self._allow_rules = config.allow_rules
        self._audit = config.audit
        self._security_config = security_config

    def evaluate(
        self,
        action_requests: list[Mapping[str, Any]],
        *,
        workspace_root: str | None = None,
        include_allow_rules: bool = True,
    ) -> ApprovalResult | None:
        """Run deny → safety stages. Returns ``None`` = defer to the next tier.

        The pipeline is **deny-list-first**: any action that does not match
        a deny rule or fail a safety check is auto-approved (in auto mode).
        There is no allow-list stage — the absence of a deny is an implicit
        allow. This avoids the "piped command" problem where compound
        commands like ``git diff ... | tail -5`` could never match a single
        allow rule and were always deferred to the human.

        Args:
            action_requests: Batched HITL action requests.
            workspace_root: Per-request workspace root (``<workspace>`` token).
            include_allow_rules: Kept for API compatibility. When ``False``
                (manual mode), actions that pass deny/safety are deferred to
                the human instead of being auto-approved.
        """
        try:
            if not action_requests:
                return None  # nothing to evaluate → defer to veritas

            for ar in action_requests:
                name = str(ar.get("name") or "")
                args = ar.get("args") or {}
                if not isinstance(args, Mapping):
                    args = {}

                # Stage 1: deny rules
                if self._matches_any_rule(name, args, self._deny_rules, workspace_root):
                    result = ApprovalResult(
                        "reject",
                        "deny_rule",
                        f"matched deny rule for {name}",
                    )
                    self._log_decision(result)
                    return result

                # Stage 2: safety checks (bypass-immune, delegated to nano)
                safety_result = self._check_safety(name, args, workspace_root)
                if safety_result is not None:
                    result = ApprovalResult(
                        "reject",
                        "safety_check",
                        safety_result,
                    )
                    self._log_decision(result)
                    return result

            # All action requests passed deny + safety checks.
            # In auto mode (include_allow_rules=True), default-approve.
            # In manual mode (include_allow_rules=False), defer to human.
            if include_allow_rules:
                result = ApprovalResult(
                    "approve",
                    "default_approve",
                    "no deny rule or safety check matched",
                )
                self._log_decision(result)
                return result

            return None  # manual mode → defer to human relay

        except Exception:
            logger.exception("[tool_approval] pipeline error; deferring to veritas")
            return None

    def _check_safety(
        self,
        name: str,
        args: Mapping[str, Any],
        workspace_root: str | None,
    ) -> str | None:
        """Run bypass-immune safety checks via nano's OperationSecurity.

        Delegates to ``WorkspaceToolOperationSecurity.evaluate()`` — the same
        evaluator used at Layer 1 (SoothePolicyMiddleware) and Layer 3 (tool
        execution). Returns reason if denied, else None.
        """
        from soothe_nano.security.operation_guard import (
            WorkspaceToolOperationSecurity,
            build_operation_security_request,
        )
        from soothe_sdk.protocols.operation_security import (
            OperationSecurityContext,
        )

        evaluator = WorkspaceToolOperationSecurity()
        request = build_operation_security_request(name, dict(args))
        ctx = OperationSecurityContext(
            workspace=workspace_root,
            security_config=self._security_config,
        )
        decision = evaluator.evaluate(request, ctx)
        if decision.verdict == "deny":
            return decision.reason
        return None

    def _matches_any_rule(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        rules: list,
        workspace_root: str | None,
    ) -> bool:
        """Check if a tool action matches any rule in the list."""
        for rule in rules:
            if rule.tool != tool_name:
                continue
            if tool_name == "run_command":
                cmd = str(args.get("command") or "")
                if match_command_rule(cmd, rule.pattern):
                    return True
            elif tool_name in ("edit_file", "write_file", "delete"):
                path = str(args.get("file_path") or args.get("path") or "")
                if match_path_rule(path, rule.pattern, workspace_root):
                    return True
        return False

    def _log_decision(self, result: ApprovalResult) -> None:
        """Log pipeline decision if audit is enabled."""
        if not self._audit.log_decisions:
            return
        level = getattr(logger, self._audit.log_level, logger.info)
        level(
            "[%s] %s by stage=%s reason=%s",
            _STAGE_PREFIX,
            result.decision,
            result.stage,
            result.reason,
        )


__all__ = [
    "ApprovalResult",
    "ToolApprovalPipeline",
]
