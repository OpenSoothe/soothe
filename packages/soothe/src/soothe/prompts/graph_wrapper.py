"""Centralized graph prompt wrapper for synthesis and step-completion injection.

Single assembly point for the ``[SystemMessage, projected_ledger,
HumanMessage]`` pattern used by StrangeLoop LLM nodes that go through this
wrapper: goal-completion synthesis and step-completion reporting.

The wrapper centralizes:

1. **Ledger projection** — synthesis delegates to
   ``project_loop_messages_for_synthesis`` so capping and slicing stay shared.
2. **System message assembly** — synthesis and step_completion use their
   fragment helpers / ``render_synthesis_system_prompt``.
3. **Human / task envelope** — synthesis closes with the shared TASK human
   message; step_completion uses the step input/output pair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.config.models import PlanPromptLedgerConfig
    from soothe.sloop.engine.completion.scenario_classifier import ScenarioClassification
    from soothe.sloop.state.schemas import LoopState

GraphCallKind = Literal["synthesis", "step_completion"]
"""Discriminator for LLM calls assembled by this wrapper (RFC-904)."""


@dataclass
class ProjectionResult:
    """Result of centralized ledger projection for one LLM call.

    Attributes:
        messages: Projected ledger messages to inject between system and human.
        mode: Resolved projection mode when applicable; ``None`` for synthesis /
            step_completion.
        completion_in_ledger: True when the projected ledger contains a
            ``goal_completion`` AI turn.
    """

    messages: list[BaseMessage] = field(default_factory=list)
    mode: str | None = None
    completion_in_ledger: bool = False


class GraphPromptWrapper:
    """Prompt injection and message projection for synthesis / step_completion.

    Assembles ``[SystemMessage, projected_ledger, HumanMessage]`` (or the
    step-completion triple) so RFC-904 nodes share projection and wiring.

    Usage::

        wrapper = GraphPromptWrapper(config)
        messages = wrapper.build_synthesis_messages(
            state=state,
            classification=classification,
        )
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize wrapper with optional config.

        Args:
            config: Optional Soothe configuration for ledger caps.
                ``None`` disables all limits.
        """
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def project_ledger(
        self,
        *,
        kind: GraphCallKind,
        state: LoopState,
        ledger_cfg: PlanPromptLedgerConfig | None = None,
        soothe_config: Any | None = None,
    ) -> ProjectionResult:
        """Project the CE ledger for synthesis (step_completion has no ledger).

        Args:
            kind: Call kind discriminator.
            state: Loop state whose ``loop_messages`` are projected.
            ledger_cfg: Optional caps; ``None`` inherits from config.
            soothe_config: Unused for synthesis/step_completion; retained for
                call-site compatibility.

        Returns:
            :class:`ProjectionResult` with projected messages and completion flag.
        """
        _ = soothe_config
        cfg = ledger_cfg
        if cfg is None and self.config is not None:
            cfg = self.config.agent.loop.plan_prompt_ledger

        if kind == "synthesis":
            from soothe.sloop.context_projection import LoopContextProjector, ProjectionSpec

            projector = LoopContextProjector(self.config)
            projected = projector.project(
                state.loop_messages,
                ProjectionSpec(phase="synthesis"),
                plan_cfg=cfg,
            )
            return ProjectionResult(
                messages=list(projected.messages),
                mode=None,
                completion_in_ledger=projected.completion_in_ledger,
            )

        # step_completion uses no projection.
        return ProjectionResult()

    def build_synthesis_messages(
        self,
        *,
        state: LoopState,
        classification: ScenarioClassification,
        user_query: str | None = None,
        max_chars: int = 0,
        ledger_cfg: PlanPromptLedgerConfig | None = None,
        agent_instructions_max_chars: int = 8000,
    ) -> list[BaseMessage]:
        """Assemble messages for goal-completion synthesis.

        Delegates projection to :meth:`project_ledger`.

        Output shape::

            [SystemMessage(synthesis_system)]
              + projected execute ledger
              + HumanMessage(TASK trigger)
        """
        from soothe.prompts.user_message import UserMessageBuilder

        user_goal = self._normalize_user_query(user_query if user_query is not None else state.goal)

        system_text = self._render_synthesis_system_prompt(
            classification,
            user_goal=user_goal,
            workspace=state.workspace,
            agent_instructions_max_chars=agent_instructions_max_chars,
            response_language=getattr(state, "response_language", None),
        )

        projection = self.project_ledger(kind="synthesis", state=state, ledger_cfg=ledger_cfg)
        ledger_msgs = list(projection.messages)

        human_text = UserMessageBuilder().build_synthesis_message()

        budget = max_chars
        if budget > 0:
            # Single-pass O(N): precompute fixed costs and per-message lengths,
            # then find the cut index without re-summing on each iteration.
            from soothe.sloop.utils.stream_normalize import (
                extract_text_from_message_content,
            )

            fixed = len(system_text) + len(human_text)
            msg_lengths = [
                len(extract_text_from_message_content(getattr(m, "content", "")))
                for m in ledger_msgs
            ]
            ledger_total = sum(msg_lengths)
            total = fixed + ledger_total
            if total > budget:
                start = 0
                while start < len(ledger_msgs) and total > budget:
                    total -= msg_lengths[start]
                    start += 1
                ledger_msgs = ledger_msgs[start:]

        out: list[BaseMessage] = [SystemMessage(content=system_text)]
        out.extend(ledger_msgs)
        out.append(HumanMessage(content=human_text))
        return out

    def build_step_completion_messages(
        self,
        *,
        human_content: str,
        ai_content: str,
        max_words: int = 50,
    ) -> list[BaseMessage]:
        """Assemble messages for step-completion TUI cognition cards.

        Output shape::

            [
                SystemMessage(step_completion_system),
                HumanMessage(step_input),
                AIMessage(step_output),
            ]
        """
        from langchain_core.messages import AIMessage

        system = self._build_step_completion_system_fragment(None).format(max_words=max_words)
        human = (human_content or "").strip()[:8000]
        ai = (ai_content or "").strip()[:8000]
        return [
            SystemMessage(content=system),
            HumanMessage(content=human or "(no step input)"),
            AIMessage(content=ai or "(no step output)"),
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_step_completion_system_fragment(self, state: LoopState | None) -> str:
        """Return the step-completion system-prompt template (with {max_words} placeholder)."""
        _ = state
        return (
            "You write brief step-completion status lines for the user watching progress.\n"
            "Given the execute-step input and assistant output, respond with exactly one "
            "first-person sentence (I/we) of at most {max_words} words.\n"
            "No preamble, quotes, or bullet points."
        )

    def _render_synthesis_system_prompt(
        self,
        classification: ScenarioClassification,
        *,
        user_goal: str,
        workspace: str | None = None,
        agent_instructions_max_chars: int = 8000,
        response_language: object | None = None,
    ) -> str:
        """Delegate to synthesis_projection.render_synthesis_system_prompt."""
        from soothe.sloop.engine.completion.synthesis_projection import (
            render_synthesis_system_prompt,
        )

        return render_synthesis_system_prompt(
            classification,
            user_goal=user_goal,
            workspace=workspace,
            agent_instructions_max_chars=agent_instructions_max_chars,
            response_language=response_language,
        )

    def _normalize_user_query(self, goal: str | None) -> str:
        """Normalize stored goal text for the user-facing synthesis request."""
        from soothe.prompts.user_message import _goal_text

        text = _goal_text(goal)
        if text == "No goal specified":
            return "No request specified"
        return text


__all__ = [
    "GraphCallKind",
    "GraphPromptWrapper",
    "ProjectionResult",
]
