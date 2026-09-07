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
PipelineStage = Literal["deny_rule", "allowlist", "safety_check", "default_approve"]

# Tool args fields that identify the action operand for allowlist signatures.
_COMMAND_TOOLS = frozenset({"run_command"})
_PATH_TOOLS = frozenset({"edit_file", "write_file", "delete"})


def signature_for(tool_name: str, args: Mapping[str, Any]) -> str | None:
    """Stable per-action signature (``command`` or ``file_path``), or ``None``."""
    if tool_name in _COMMAND_TOOLS:
        return str(args.get("command") or "").strip() or None
    if tool_name in _PATH_TOOLS:
        return str(args.get("file_path") or args.get("path") or "").strip() or None
    return None


def approval_record(tool_name: str, args: Mapping[str, Any]) -> dict[str, str] | None:
    """Allowlist record `{"tool", "signature"}`, or `None` if not signable."""
    sig = signature_for(tool_name, args)
    if sig is None:
        return None
    return {"tool": tool_name, "signature": sig}


@dataclass(frozen=True)
class ApprovalResult:
    """Decision returned by the pipeline for a batch of action requests."""

    decision: ApprovalDecision
    stage: PipelineStage
    reason: str = ""
    rule_id: str | None = None


class ToolApprovalPipeline:
    """Deny-list-first evaluator: deny → allowlist → safety → default-approve.

    First deciding stage wins.  Deny rules are absolute; the allowlist
    overrides safety-escalated actions a human approved earlier in the loop.
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
        allowlist: list[Mapping[str, Any]] | None = None,
    ) -> ApprovalResult | None:
        """Run deny → allowlist → safety stages.  Returns ``None`` to defer.

        Args:
            action_requests: Batched HITL action requests.
            workspace_root: Per-request workspace root (``<workspace>`` token).
            auto_approve: When True, passing actions are auto-approved.
                When False (manual), they defer to the human.
            bypass_security: Skip all checks and approve.
            allowlist: Loop-scoped ``{"tool", "signature"}`` records from
                prior human approvals.
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

            allowlisted = False
            for ar in action_requests:
                name = str(ar.get("name") or "")
                args = ar.get("args") or {}
                if not isinstance(args, Mapping):
                    args = {}

                # Stage 1: deny rules — absolute.
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

                # Stage 2: loop allowlist — prior human approval.
                if allowlist and self._matches_allowlist(name, args, allowlist):
                    allowlisted = True
                    continue

                # Stage 3: safety checks (delegated to nano).
                safety_result = self._check_safety(name, args, workspace_root)
                if safety_result is not None:
                    reason, rule_id = safety_result
                    if allowlist and self._rule_approved(rule_id, allowlist):
                        allowlisted = True
                        logger.info(
                            "[%s] safety rule=%s overridden by prior human approval",
                            "tool_approval",
                            rule_id,
                        )
                        continue
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

            if allowlisted:
                result = ApprovalResult(
                    "approve",
                    "allowlist",
                    "matched loop-scoped approval",
                )
                logger.info("[%s] %s by stage=%s", "tool_approval", result.decision, result.stage)
                return result
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

    def _matches_allowlist(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        allowlist: list[Mapping[str, Any]],
    ) -> bool:
        """True when `(tool_name, signature)` is in the loop allowlist."""
        sig = signature_for(tool_name, args)
        if sig is None:
            return False
        for rec in allowlist:
            if not isinstance(rec, Mapping):
                continue
            if str(rec.get("tool") or "") == tool_name and str(rec.get("signature") or "") == sig:
                return True
        return False

    @staticmethod
    def _rule_approved(
        rule_id: str | None,
        allowlist: list[Mapping[str, Any]],
    ) -> bool:
        """True when the human already approved this rule's family this loop."""
        if not rule_id:
            return False
        from soothe_nano.security.operation_guard import rule_family

        approved = rule_family(rule_id)
        for rec in allowlist:
            if isinstance(rec, Mapping) and str(rec.get("rule") or "") in approved:
                return True
        return False

    def _check_safety(
        self,
        name: str,
        args: Mapping[str, Any],
        workspace_root: str | None,
    ) -> tuple[str, str | None] | None:
        """Run safety checks via nano's OperationSecurity.  Returns ``(reason, rule_id)`` if denied."""
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
        """Check if a tool action matches any rule in the list."""
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


__all__ = [
    "ApprovalResult",
    "ToolApprovalPipeline",
    "approval_record",
    "signature_for",
]
