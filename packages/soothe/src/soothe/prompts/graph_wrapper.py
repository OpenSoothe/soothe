"""Centralized graph prompt wrapper for synthesis and step-completion injection.

Provides a single assembly point for the ``[SystemMessage, projected_ledger,
HumanMessage]`` pattern used by StrangeLoop LLM nodes that still go through
this wrapper: goal-completion synthesis and step-completion reporting
(RFC-904).

The wrapper centralizes:

1. **Ledger projection** — synthesis delegates to
   ``project_loop_messages_for_synthesis`` so capping and slicing stay shared.
2. **System message assembly** — synthesis and step_completion use their
   fragment helpers / ``render_synthesis_system_prompt``.
3. **Human / task envelope** — synthesis closes with the shared TASK human
   message; step_completion uses the step input/output pair.

Nodes that previously built message lists independently now delegate to
:class:`GraphPromptWrapper` so projection and injection logic lives in one
place (RFC-904 synthesis / step_completion).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from soothe.prompts.plan_ledger_projection import (
    project_loop_messages_for_synthesis,
    projected_ledger_has_goal_completion,
)

if TYPE_CHECKING:
    from soothe_sdk.protocols.planner import PlanContext

    from soothe.config import SootheConfig
    from soothe.config.models import PlanPromptLedgerConfig
    from soothe.context.projection import ContextBundle
    from soothe.sloop.engine.scenario_classifier import ScenarioClassification
    from soothe.sloop.state.schemas import LoopState

GraphCallKind = Literal["synthesis", "step_completion"]
"""Discriminator for LLM calls assembled by this wrapper (RFC-904)."""

_PRIOR_CONVERSATION_TAGS: tuple[tuple[str, Literal["human", "ai"]], ...] = (
    ("USER", "human"),
    ("ASSISTANT", "ai"),
)


def _parse_prior_conversation_xml(msg_xml: str) -> tuple[Literal["human", "ai"], str] | None:
    """Parse ``<USER>`` / ``<ASSISTANT>`` blocks from prior conversation projection."""
    msg_xml = msg_xml.strip()
    for tag, role in _PRIOR_CONVERSATION_TAGS:
        open_tag, close_tag = f"<{tag}>", f"</{tag}>"
        if msg_xml.startswith(open_tag) and msg_xml.endswith(close_tag):
            return role, msg_xml[len(open_tag) : -len(close_tag)].strip()
    return None


def _format_dag_context(dag_ctx: Any) -> str:
    """Format DagPlanningContext as plain-text DAG STATUS section for prompt injection."""
    if not dag_ctx or not dag_ctx.has_prior_state:
        return ""
    from soothe.prompts.user_message import _render_dag_status as _render

    return _render(dag_ctx)


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
            projected = list(
                project_loop_messages_for_synthesis(state.loop_messages, cfg),
            )
            return ProjectionResult(
                messages=projected,
                mode=None,
                completion_in_ledger=projected_ledger_has_goal_completion(projected),
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

    def _build_synthesis_system_fragment(
        self,
        context: PlanContext | None,
        state: LoopState | None,
        context_bundle: ContextBundle | None,
    ) -> str:
        """Render the synthesis system-prompt fragment (delegates to synthesis_projection)."""
        _ = context, context_bundle
        from soothe.sloop.engine.scenario_classifier import ScenarioClassification
        from soothe.sloop.engine.synthesis_projection import render_synthesis_system_prompt

        # When called without a ScenarioClassification, produce a minimal
        # synthesis template. Full classification is handled by
        # build_synthesis_messages via _render_synthesis_system_prompt.
        user_goal = ""
        if state is not None:
            user_goal = (state.goal or "").strip()
        workspace = getattr(state, "workspace", None) if state is not None else None
        language = getattr(state, "response_language", None) if state is not None else None
        dummy = ScenarioClassification(
            scenario="general",
            sections=[],
            contextual_focus=[],
            evidence_emphasis="",
        )
        return render_synthesis_system_prompt(
            dummy,
            user_goal=user_goal,
            workspace=workspace,
            response_language=language,
        )

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
        from soothe.sloop.engine.synthesis_projection import render_synthesis_system_prompt

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
