"""Recognize structured clarifications emitted by CoreAgent / deepagents.

Two interrupt shapes are detected:

1. ``ask_user`` interrupts — emitted by the ``ask_user`` host tool
   or planner-emitted ``kind="ask_user"`` steps. The payload is
   ``{"type": "ask_user", "questions": [...]}``.

2. ``action_requests`` interrupts (tool-approval) — emitted by the deepagents
   ``HumanInTheLoopMiddleware`` when a tool call matches an ``interrupt_on``
   rule or a ``FilesystemPermission(mode="interrupt")`` rule. The payload is
   ``{"action_requests": [{"name": "edit_file", "args": {...}}], ...}``.

Plain-text questions in assistant messages are intentionally *not* detected.
Code paths that want a clarification must emit a structured interrupt;
otherwise the relay does not engage and the model's text is treated as a
normal turn.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from soothe.sloop.clarification.origins import ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import (
    ClarificationOrigin,
    ClarificationRequest,
    LoopStateView,
)

# Tool-call arg keys whose values are most informative for surfacing an
# approval prompt (path, command). Ordered by priority.
_INFORMATIVE_ARG_KEYS: tuple[str, ...] = (
    "file_path",
    "path",
    "directory",
    "command",
    "pattern",
    "target_path",
    "url",
)


class ClarificationDetector:
    """Detect structured clarifications from a LangGraph stream."""

    def from_interrupt(
        self,
        value: Any,
        *,
        interrupt_id: str,
        origin_node: ClarificationOrigin,
        loop_state: LoopStateView,
    ) -> ClarificationRequest | None:
        """Return a request if ``value`` is a structured ``ask_user`` interrupt."""
        if not isinstance(value, Mapping):
            return None
        if value.get("type") != "ask_user":
            return None
        questions = self._extract_questions(value)
        if not questions:
            return None
        return ClarificationRequest(
            questions=questions,
            origin_node=origin_node,
            origin_interrupt_id=interrupt_id,
            loop_state=loop_state,
        )

    def from_tool_approval_interrupt(
        self,
        value: Any,
        *,
        interrupt_id: str,
        loop_state: LoopStateView,
    ) -> ClarificationRequest | None:
        """Return a request if ``value`` is a deepagents ``action_requests`` interrupt.

        Builds an approval question per pending tool call so the TUI can render
        an Approve / Reject prompt. The origin is always ``tool_approval``
        and the request resumes at ``EXECUTE`` (the step that issued the call).
        """
        if not isinstance(value, Mapping):
            return None
        action_requests = value.get("action_requests")
        if not isinstance(action_requests, list) or not action_requests:
            return None
        questions = tuple(
            q
            for q in (
                self._format_action_request(ar) for ar in action_requests if isinstance(ar, Mapping)
            )
            if q
        )
        if not questions:
            return None
        return ClarificationRequest(
            questions=questions,
            origin_node=ORIGIN_TOOL_APPROVAL,
            origin_interrupt_id=interrupt_id,
            loop_state=loop_state,
            metadata={"action_requests": list(action_requests)},
        )

    def detect(
        self,
        value: Any,
        *,
        interrupt_id: str,
        loop_state: LoopStateView,
        origin_node: ClarificationOrigin = "execute",
    ) -> ClarificationRequest | None:
        """Route an interrupt payload to the right request constructor.

        Single entry point replacing the per-shape ``is_*`` + ``from_*``
        branching in the executor. Selection is by payload key:

        - ``"action_requests"`` → tool-approval (origin forced to
          ``ORIGIN_TOOL_APPROVAL``).
        - ``type == "ask_user"`` → execute-origin question (origin from caller).
        - anything else → ``None`` (not a structured clarification).

        ``from_interrupt`` / ``from_tool_approval_interrupt`` remain as public
        delegating constructors; this method just picks between them.
        """
        if not isinstance(value, Mapping):
            return None
        if "action_requests" in value:
            return self.from_tool_approval_interrupt(
                value,
                interrupt_id=interrupt_id,
                loop_state=loop_state,
            )
        if value.get("type") == "ask_user":
            return self.from_interrupt(
                value,
                interrupt_id=interrupt_id,
                origin_node=origin_node,
                loop_state=loop_state,
            )
        return None

    @staticmethod
    def _extract_questions(value: Mapping[str, Any]) -> tuple:
        """Extract questions from an ask_user interrupt payload.

        Preserves structured dicts (QuestionSpec with question,
        header, options) when the payload carries them; falls back to
        plain strings for pre-§9c in-flight interrupts.
        """
        raw = value.get("questions")
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            cleaned: list[str | dict] = []
            for q in raw:
                if isinstance(q, dict):
                    # Structured: preserve if title is non-empty.
                    title = str(q.get("question", "") or "").strip()
                    if title:
                        cleaned.append(q)
                elif str(q).strip():
                    cleaned.append(str(q).strip())
            if cleaned:
                return tuple(cleaned)
        single = value.get("question")
        if isinstance(single, str) and single.strip():
            return (single.strip(),)
        return ()

    # Maximum length of the informative arg value in the approval prompt.
    # Long commands (e.g. multi-line shell pipelines) are truncated with an
    # ellipsis so the TUI card stays readable.
    _MAX_ARG_PREVIEW = 120

    @staticmethod
    def _format_action_request(ar: Mapping[str, Any]) -> str | None:
        """Render one pending tool call as an approval question.

        Surfaces the tool name plus its most informative argument (the file
        path, command, etc.) so the user can see what is about to execute
        without inspecting the full args blob. Long values (e.g. multi-line
        shell commands) are truncated to ``_MAX_ARG_PREVIEW`` chars with an
        ellipsis so the approval card stays readable.
        """
        name = str(ar.get("name") or "").strip()
        if not name:
            return None
        args = ar.get("args")
        detail = ""
        if isinstance(args, Mapping):
            for key in _INFORMATIVE_ARG_KEYS:
                val = args.get(key)
                if isinstance(val, str) and val.strip():
                    detail = f" ({key}={ClarificationDetector._truncate(val.strip())})"
                    break
            if not detail and args:
                # Fall back to the first arg value for non-path tools
                first_val = next(iter(args.values()), None)
                if isinstance(first_val, str) and first_val.strip():
                    detail = f" ({ClarificationDetector._truncate(first_val.strip())})"
        return f"Approve {name}{detail}?"

    @staticmethod
    def _truncate(val: str) -> str:
        """Truncate a long arg value to ``_MAX_ARG_PREVIEW`` chars with ellipsis."""
        max_len = ClarificationDetector._MAX_ARG_PREVIEW
        if len(val) <= max_len:
            return val
        return val[:max_len] + "…"
