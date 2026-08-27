"""Multi-stage tool-approval pipeline evaluator (RFC-622 §9b).

Stages run cheapest-first; the first stage that returns a decision wins.
Veritas LLM is the final stage for ambiguous cases — this pipeline returns
``None`` to defer to veritas.

Safety property: deny rules and safety checks always run before allow rules.
No allow rule can override a safety denial.
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
PipelineStage = Literal["deny_rule", "safety_check", "allow_rule"]


@dataclass(frozen=True)
class ApprovalResult:
    """Decision returned by the pipeline for a batch of action requests."""

    decision: ApprovalDecision
    stage: PipelineStage
    reason: str = ""


class ToolApprovalPipeline:
    """Multi-stage tool-approval evaluator.

    Stages run cheapest-first; the first stage that returns a decision wins.
    Veritas LLM is the final stage for ambiguous cases — this pipeline
    returns ``None`` to defer to veritas.

    Safety property: deny rules and safety checks always run before allow
    rules. No allow rule can override a safety denial. Fail-safe: any
    exception in stages 1–3 returns ``None`` (defer to veritas), never
    auto-approves on error.

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
    ) -> ApprovalResult | None:
        """Run all stages. Returns ``None`` = defer to veritas.

        Evaluates per action request. If any request is rejected, the whole
        batch is rejected. If all are approved by allow rules, the batch is
        approved. If any are ambiguous (no rule matched), defer to veritas.
        """
        try:
            if not action_requests:
                return None  # nothing to evaluate → defer to veritas

            any_ambiguous = False

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

                # Stage 3: allow rules
                if self._matches_any_rule(name, args, self._allow_rules, workspace_root):
                    continue  # this action is approved, check next

                # No rule matched — ambiguous
                any_ambiguous = True

            if any_ambiguous:
                return None  # defer to veritas

            # All action requests matched allow rules
            result = ApprovalResult(
                "approve",
                "allow_rule",
                "all actions matched allow rules",
            )
            self._log_decision(result)
            return result

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
