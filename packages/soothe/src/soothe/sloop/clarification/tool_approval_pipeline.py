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

ApprovalDecision = Literal["approve", "reject", "escalate"]
PipelineStage = Literal["deny_rule", "safety_check", "default_approve"]


@dataclass(frozen=True)
class ApprovalResult:
    """Decision returned by the pipeline for a batch of action requests.

    ``escalate`` means a banned safety rule blocked the action — a human
    should decide whether to allow it or steer the model to an alternative.
    """

    decision: ApprovalDecision
    stage: PipelineStage
    reason: str = ""
    rule_id: str | None = None


class ToolApprovalPipeline:
    """Deny-list-first tool-approval evaluator.

    Two stages run cheapest-first: deny rules → safety checks. The first
    stage that returns a decision wins. Actions that pass both are
    auto-approved in auto mode (absence of deny = implicit allow).

    Safety property: deny rules and safety checks always run before
    default-approve. No configuration can override a safety denial.
    """

    def __init__(
        self,
        config: ToolApprovalConfig,
        *,
        security_config: Any = None,
        bypass_security: bool = False,
    ) -> None:
        self._deny_rules = config.deny_rules
        self._security_config = security_config
        self._bypass_security = bypass_security
        self._security_evaluator: Any = None  # lazy-init in _check_safety

    def evaluate(
        self,
        action_requests: list[Mapping[str, Any]],
        *,
        workspace_root: str | None = None,
        auto_approve: bool = True,
        bypass_security: bool | None = None,
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
            bypass_security: When `True` (bypass mode), skip all checks and return approve.
        """
        try:
            if not action_requests:
                return None  # nothing to evaluate → defer to veritas

            if bypass_security is None:
                bypass_security = self._bypass_security
            if bypass_security:
                result = ApprovalResult(
                    "approve",
                    "default_approve",
                    "bypass mode — all security rules skipped",
                )
                logger.info(
                    "[%s] %s by stage=%s (bypass)", "tool_approval", result.decision, result.stage
                )
                return result

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

                # Stage 2: safety checks (delegated to nano)
                safety_result = self._check_safety(name, args, workspace_root)
                if safety_result is not None:
                    reason, rule_id = safety_result
                    # Banned safety rules are deterministic — escalate to a
                    # human instead of silently auto-rejecting.
                    result = ApprovalResult(
                        "escalate",
                        "safety_check",
                        reason,
                        rule_id=rule_id,
                    )
                    logger.info(
                        "[%s] %s by stage=%s rule=%s",
                        "tool_approval",
                        result.decision,
                        result.stage,
                        rule_id,
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
    ) -> tuple[str, str | None] | None:
        """Run safety checks via nano's OperationSecurity.

        Returns ``(reason, rule_id)`` if denied, else ``None``.
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
            return decision.reason, decision.rule_id
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
