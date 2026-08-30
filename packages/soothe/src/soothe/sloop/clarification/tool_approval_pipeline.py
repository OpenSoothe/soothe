"""Deny-list-first tool-approval pipeline evaluator."""

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

ApprovalDecision = Literal["approve", "reject"]
PipelineStage = Literal["deny_rule", "safety_check", "default_approve"]


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

    Stage 2 delegates to nano's `WorkspaceToolOperationSecurity` — the same
    evaluator used by `SoothePolicyMiddleware` and the tool execution
    layer. This ensures one source of truth for safety constants (banned
    command patterns, dangerous paths/files).
    """

    def __init__(
        self,
        config: ToolApprovalConfig,
        *,
        security_config: Any = None,
    ) -> None:
        self._deny_rules = config.deny_rules
        self._security_config = security_config
        self._security_evaluator: Any = None  # lazy-init in _check_safety

    def evaluate(
        self,
        action_requests: list[Mapping[str, Any]],
        *,
        workspace_root: str | None = None,
        auto_approve: bool = True,
    ) -> ApprovalResult | None:
        """Run deny → safety stages. Returns `None` = defer to the next tier.

        The pipeline is **deny-list-first**: any action that does not match
        a deny rule or fail a safety check is auto-approved (in auto mode).
        There is no allow-list stage — the absence of a deny is an implicit
        allow. This avoids the "piped command" problem where compound
        commands like `git diff ... | tail -5` could never match a single
        allow rule and were always deferred to the human.

        Args:
            action_requests: Batched HITL action requests.
            workspace_root: Per-request workspace root (`<workspace>` token).
            auto_approve: When `True` (auto mode), actions that pass
                deny/safety are auto-approved. When `False` (manual mode),
                passing actions are deferred to the human relay.
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
                    logger.info(
                        "[%s] %s by stage=%s", "tool_approval", result.decision, result.stage
                    )
                    return result

                # Stage 2: safety checks (bypass-immune, delegated to nano)
                safety_result = self._check_safety(name, args, workspace_root)
                if safety_result is not None:
                    result = ApprovalResult(
                        "reject",
                        "safety_check",
                        safety_result,
                    )
                    logger.info(
                        "[%s] %s by stage=%s", "tool_approval", result.decision, result.stage
                    )
                    return result

            # All action requests passed deny + safety checks.
            # In auto mode, default-approve. In manual mode, defer to human.
            if auto_approve:
                result = ApprovalResult(
                    "approve",
                    "default_approve",
                    "no deny rule or safety check matched",
                )
                logger.info("[%s] %s by stage=%s", "tool_approval", result.decision, result.stage)
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

        Delegates to `WorkspaceToolOperationSecurity.evaluate()` — the same
        evaluator used at the policy middleware and tool execution layers.
        Returns reason if denied, else None.
        """
        from soothe_nano.security.operation_guard import (
            WorkspaceToolOperationSecurity,
            build_operation_security_request,
        )
        from soothe_sdk.protocols.operation_security import (
            OperationSecurityContext,
        )

        if self._security_evaluator is None:
            self._security_evaluator = WorkspaceToolOperationSecurity()
        request = build_operation_security_request(name, dict(args))
        ctx = OperationSecurityContext(
            workspace=workspace_root,
            security_config=self._security_config,
        )
        decision = self._security_evaluator.evaluate(request, ctx)
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
        """Check if a tool action matches any rule in the list.

        Selects the matcher function once based on `tool_name` instead of
        re-dispatching inside the loop.
        """
        if tool_name == "run_command":
            val = str(args.get("command") or "")
            for rule in rules:
                if rule.tool != tool_name:
                    continue
                if match_command_rule(val, rule.pattern):
                    return True
            return False

        if tool_name in ("edit_file", "write_file", "delete"):
            val = str(args.get("file_path") or args.get("path") or "")
            for rule in rules:
                if rule.tool != tool_name:
                    continue
                if match_path_rule(val, rule.pattern, workspace_root):
                    return True
            return False

        return False  # unknown tool type — no rule match


__all__ = ["ApprovalResult", "ToolApprovalPipeline"]
