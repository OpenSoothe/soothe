"""Centralized graph prompt wrapper for unified prompt injection and message projection.

Provides a single assembly point for the ``[SystemMessage, projected_ledger,
HumanMessage]`` pattern used across all LLM-invoking StrangeLoop graph nodes:
plan-assess, plan-generate, plan-gap, continuation-assess, goal-completion
synthesis, and step-completion reporting.

The wrapper centralizes:

1. **Projection mode resolution** — ``new_goal`` vs ``mid_goal`` via
   ``resolve_planner_projection_mode``.
2. **Ledger projection** — delegates to the existing projection functions
   (``project_planner_ledger``, ``project_planner_ledger_for_assess``,
   ``project_continuation_assess_ledger``, ``project_loop_messages_for_synthesis``)
   so all nodes share the same slicing, capping, and boundary-marker logic.
3. **System message assembly** — each call kind maps to its fragment-based
   system prompt; the wrapper applies the response-language hint and
   context-bundle supplementary instructions uniformly.
4. **Human message assembly** — scenario builders produce the closing
   task envelope; the wrapper appends it as a phase-tagged
   ``LoopHumanMessage``.

Nodes that previously built their own message lists independently now
delegate to :class:`GraphPromptWrapper` so projection and injection logic
lives in exactly one place (RFC-214 §4, RFC-206 SYSTEM_CONTEXT + USER_TASK).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from soothe.sloop.prompts.plan_ledger_projection import (
    project_continuation_assess_ledger,
    project_loop_messages_for_synthesis,
    project_planner_ledger,
    project_planner_ledger_for_assess,
    projected_ledger_has_goal_completion,
    resolve_planner_projection_mode,
)
from soothe.sloop.prompts.planner_assembly import (
    goal_preview_text,
)

if TYPE_CHECKING:
    from soothe_sdk.protocols.planner import PlanContext

    from soothe.config import SootheConfig
    from soothe.config.models import PlanPromptLedgerConfig
    from soothe.context.projection import ContextBundle
    from soothe.sloop.engine.scenario_classifier import ScenarioClassification
    from soothe.sloop.state.schemas import LoopState

logger = logging.getLogger(__name__)

GraphCallKind = Literal[
    "continuation",
    "assess",
    "generate",
    "gap",
    "synthesis",
    "step_completion",
]
"""Discriminator for the kind of LLM call the wrapper is assembling messages for.

Extends :data:`PlannerCallKind` with ``synthesis`` (goal-completion report)
and ``step_completion`` (TUI cognition card) so all LLM-invoking nodes share
one assembly path.
"""

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


def _prior_goals_from_checkpoint(
    checkpoint: Any | None,
    *,
    exclude_goal_id: str | None,
) -> list[Any]:
    """Build ``PriorGoalSummary`` rows from checkpoint goal index (metadata only)."""
    from soothe.context.projection import PriorGoalSummary

    if checkpoint is None:
        return []
    out: list[PriorGoalSummary] = []
    for rec in checkpoint.goal_history:
        if exclude_goal_id and rec.goal_id == exclude_goal_id:
            continue
        if rec.status not in ("completed", "cancelled", "failed"):
            continue
        out.append(
            PriorGoalSummary(
                goal_id=rec.goal_id,
                description=rec.goal_id,
                status=rec.status,
                step_summary="",
                completion_text="",
            )
        )
    return out


def _format_dag_context(dag_ctx: Any) -> str:
    """Format DagPlanningContext as plain-text DAG STATUS section for prompt injection."""
    if not dag_ctx or not dag_ctx.has_prior_state:
        return ""
    from soothe.sloop.prompts.user_message import _render_dag_status as _render

    return _render(dag_ctx)


def _messages_text_len(messages: list[BaseMessage]) -> int:
    """Sum extracted text length across messages (for char-budget trimming)."""
    from soothe.sloop.utils.stream_normalize import extract_text_from_message_content

    return sum(len(extract_text_from_message_content(getattr(m, "content", ""))) for m in messages)


@dataclass
class ProjectionResult:
    """Result of centralized ledger projection for one LLM call.

    Attributes:
        messages: Projected ledger messages to inject between system and human.
        mode: Resolved projection mode (``new_goal`` / ``mid_goal``), or ``None``
            for non-planner calls (synthesis, step_completion).
        completion_in_ledger: True when the projected ledger contains a
            ``goal_completion`` AI turn (used by continuation logic).
    """

    messages: list[BaseMessage] = field(default_factory=list)
    mode: str | None = None
    completion_in_ledger: bool = False


class GraphPromptWrapper:
    """Centralized prompt injection and message projection for StrangeLoop graph nodes.

    Wraps the scattered ``[SystemMessage, projected_ledger, HumanMessage]``
    assembly into one class so all LLM-invoking nodes share identical projection
    and injection logic. Each call kind (assess, generate, gap, continuation,
    synthesis, step_completion) maps to its projection function and system-prompt
    builder; the wrapper applies response-language hints and context-bundle
    instructions uniformly.

    This class does **not** replace the fragment-based system prompts or the
    scenario-based user-message builders — it centralizes the *wiring* between
    them and the projection layer so nodes no longer duplicate the assembly
    pipeline.

    Usage::

        wrapper = GraphPromptWrapper(config)
        messages = wrapper.build_messages(
            kind="assess",
            goal=state.goal,
            state=state,
            context=context,
            context_bundle=bundle,
            checkpoint=checkpoint,
        )
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize wrapper with optional config.

        Args:
            config: Optional Soothe configuration for ledger caps and
                assess-prompt settings. ``None`` disables all limits.
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
        """Project the CE ledger for the given call kind.

        Centralizes the projection-function dispatch so all nodes use the same
        slicing, capping, and boundary-marker logic.

        Args:
            kind: Call kind discriminator.
            state: Loop state whose ``loop_messages`` are projected.
            ledger_cfg: Optional caps; ``None`` inherits from config.
            soothe_config: Optional config for cross-goal Slice A settings.

        Returns:
            :class:`ProjectionResult` with projected messages, mode, and
            completion flag.
        """
        cfg = ledger_cfg
        if cfg is None and self.config is not None:
            cfg = self.config.agent.loop.plan_prompt_ledger
        sc = soothe_config if soothe_config is not None else self.config

        if kind == "continuation":
            projected = project_continuation_assess_ledger(state.loop_messages, cfg)
            return ProjectionResult(
                messages=projected,
                mode=None,
                completion_in_ledger=projected_ledger_has_goal_completion(projected),
            )

        if kind in ("assess", "gap"):
            mode = resolve_planner_projection_mode(state)
            projected = project_planner_ledger_for_assess(
                state.loop_messages,
                mode,
                cfg,
                soothe_config=sc,
            )
            return ProjectionResult(
                messages=projected,
                mode=mode,
                completion_in_ledger=projected_ledger_has_goal_completion(projected),
            )

        if kind == "generate":
            mode = resolve_planner_projection_mode(state)
            projected = project_planner_ledger(
                state.loop_messages,
                mode,
                cfg,
                soothe_config=sc,
            )
            return ProjectionResult(
                messages=projected,
                mode=mode,
                completion_in_ledger=projected_ledger_has_goal_completion(projected),
            )

        if kind == "synthesis":
            projected = list(
                project_loop_messages_for_synthesis(state.loop_messages, cfg),
            )
            return ProjectionResult(
                messages=projected,
                mode=None,
                completion_in_ledger=projected_ledger_has_goal_completion(projected),
            )

        # step_completion and any future non-ledger call kinds use no projection.
        return ProjectionResult()

    def build_system_message(
        self,
        *,
        kind: GraphCallKind,
        context: PlanContext | None = None,
        state: LoopState | None = None,
        context_bundle: ContextBundle | None = None,
        response_language: Any | None = None,
        recent_messages: list[str] | None = None,
    ) -> str:
        """Assemble the system message for the given call kind.

        Centralizes fragment selection, response-language hint, and context-bundle
        supplementary instructions so every node applies them uniformly.

        Args:
            kind: Call kind discriminator.
            context: Planning context (workspace, capabilities). ``None`` for
                synthesis / step_completion.
            state: Optional loop state for iteration limits and language.
            context_bundle: Optional ContextBundle for memory instructions.
            response_language: Override for response language hint.
            recent_messages: Prior-conversation XML blocks (plan-generate only).

        Returns:
            Assembled system prompt string.
        """
        from soothe.prompts.system_templates import build_response_language_hint

        language = response_language
        if language is None and state is not None:
            language = getattr(state, "response_language", None)

        parts: list[str] = []

        if kind in ("continuation", "assess", "gap", "generate"):
            parts.append(self._build_planner_system_fragment(kind) + "\n")
        elif kind == "synthesis":
            parts.append(
                self._build_synthesis_system_fragment(context, state, context_bundle) + "\n"
            )
        elif kind == "step_completion":
            parts.append(self._build_step_completion_system_fragment(state) + "\n")

        parts.append(build_response_language_hint(language) + "\n")

        # Context-bundle supplementary instructions (plan-generate only).
        if context_bundle is not None and kind not in ("assess", "gap"):
            if context_bundle.memory_instructions:
                parts.append(
                    "<MEMORY_INSTRUCTIONS>\n"
                    + context_bundle.memory_instructions
                    + "\n</MEMORY_INSTRUCTIONS>\n"
                )

        # Prior-conversation follow-up policy (plan-generate only).
        if recent_messages and kind not in ("assess", "gap"):
            parts.append(
                "<FOLLOW_UP_POLICY>\n"
                'Prior-thread goals: status MUST NOT be "done" until execution produced the '
                "requested output; include at least one execute_steps item that performs the work; "
                "do not claim completion without execution evidence.\n"
                "</FOLLOW_UP_POLICY>\n"
            )

        return "\n".join(parts)

    def build_messages(
        self,
        *,
        kind: GraphCallKind,
        goal: str,
        state: LoopState,
        context: PlanContext | None = None,
        context_bundle: ContextBundle | None = None,
        checkpoint: Any | None = None,
        exclude_goal_id: str | None = None,
        dag_context: str | None = None,
        inline_assessment: Any | None = None,
        plan_gap: Any | None = None,
        plan_coverage: str | None = None,
        omit_prior_progress_hint: bool = True,
        human_content_override: str | None = None,
        recent_messages: list[str] | None = None,
        max_chars: int | None = None,
    ) -> list[BaseMessage]:
        """Assemble the full message list for an LLM call.

        This is the main entry point for planner call kinds (assess, generate,
        gap, continuation). For synthesis and step_completion, use
        :meth:`build_synthesis_messages` / :meth:`build_step_completion_messages`
        which have different assembly shapes.

        The output is always::

            [SystemMessage(system_content)]
              + projected_ledger
              + parsed prior-conversation (LoopHuman/AIMessage, plan-generate only)
              + LoopHumanMessage(human_content, phase=plan_*)

        Args:
            kind: Call kind discriminator.
            goal: User's goal description.
            state: Current loop state.
            context: Planning context (workspace, capabilities).
            context_bundle: Optional ContextBundle from ContextEngine.project().
            checkpoint: Optional checkpoint for prior-goal fallback.
            exclude_goal_id: Goal ID to exclude from prior-goal fallback.
            dag_context: Optional plain-text DAG context for progressive planning.
            inline_assessment: Optional inline assessment for generate.
            plan_gap: Optional plan gap analysis for assess/generate.
            plan_coverage: Optional plan coverage text for assess/gap.
            omit_prior_progress_hint: Whether to omit prior-progress hint.
            human_content_override: If set, use this instead of building from scenario.
            recent_messages: Prior-conversation XML blocks.
            max_chars: Optional total char budget for synthesis-style trimming.

        Returns:
            Assembled message list.
        """
        from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage

        # 1. Projection
        projection = self.project_ledger(kind=kind, state=state)

        # 2. Prior goals
        prior_goals = (
            list(context_bundle.prior_goals)
            if context_bundle and context_bundle.prior_goals
            else []
        )
        if not prior_goals and projection.mode == "new_goal":
            prior_goals = _prior_goals_from_checkpoint(checkpoint, exclude_goal_id=exclude_goal_id)

        # 3. System message
        system_content = self.build_system_message(
            kind=kind,
            context=context,
            state=state,
            context_bundle=None if kind in ("assess", "gap") else context_bundle,
            recent_messages=recent_messages,
        )

        # 4. Human message
        human_content = human_content_override
        if human_content is None:
            human_content = self._build_human_text(
                kind=kind,
                goal=goal,
                state=state,
                context=context,
                dag_context=dag_context,
                context_bundle=context_bundle,
                projection_mode=projection.mode,
                completion_in_ledger=projection.completion_in_ledger,
                prior_goals_override=prior_goals or None,
                inline_assessment=inline_assessment,
                plan_coverage=plan_coverage,
                omit_prior_progress_hint=omit_prior_progress_hint,
                plan_gap=plan_gap,
            )

        # 5. Compose
        out: list[BaseMessage] = [SystemMessage(content=system_content)]
        out.extend(projection.messages)

        if len(projection.messages) != len(state.loop_messages):
            logger.debug(
                "Graph wrapper: ledger projection len=%d (raw=%d) kind=%s mode=%s",
                len(projection.messages),
                len(state.loop_messages),
                kind,
                projection.mode,
            )

        # Prior-conversation (plan-generate only)
        if recent_messages and kind not in ("assess", "gap"):
            for msg_xml in recent_messages:
                parsed = _parse_prior_conversation_xml(msg_xml)
                if parsed is None:
                    continue
                role, content = parsed
                if role == "human":
                    out.append(
                        LoopHumanMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",
                        )
                    )
                else:
                    out.append(
                        LoopAIMessage(
                            content=content,
                            thread_id=state.thread_id,
                            iteration=None,
                            phase="execute_step",
                        )
                    )

        if human_content.strip():
            phase = self._phase_for_kind(kind)
            out.append(
                LoopHumanMessage(
                    content=human_content,
                    thread_id=state.thread_id,
                    iteration=state.iteration,
                    goal_summary=goal[:200],
                    phase=phase,
                )
            )
        return out

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

        Delegates projection to :meth:`project_ledger` and system-prompt
        assembly to :meth:`build_system_message` so synthesis shares the same
        centralized pipeline as planner calls.

        Output shape::

            [SystemMessage(synthesis_system)]
              + projected execute ledger
              + HumanMessage(TASK trigger)
        """
        from soothe.sloop.prompts.user_message import UserMessageBuilder

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
        while budget > 0:
            total = len(system_text) + _messages_text_len(ledger_msgs) + len(human_text)
            if total <= budget:
                break
            if ledger_msgs:
                ledger_msgs.pop(0)
                continue
            break

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

    def _build_planner_system_fragment(self, kind: GraphCallKind) -> str:
        """Select the planner system-prompt fragment for the given kind."""
        from soothe.sloop.prompts.fragments import (
            EXECUTION_POLICIES_FRAGMENT,
            PLAN_ASSESS_INSTRUCTIONS_FRAGMENT,
            PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT,
            PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT,
            PLAN_GENERATE_INSTRUCTIONS_FRAGMENT,
        )

        if kind == "continuation":
            return PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT
        if kind == "assess":
            return PLAN_ASSESS_INSTRUCTIONS_FRAGMENT
        if kind == "gap":
            return PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT
        # generate
        return EXECUTION_POLICIES_FRAGMENT + "\n" + PLAN_GENERATE_INSTRUCTIONS_FRAGMENT

    def _build_synthesis_system_fragment(
        self,
        context: PlanContext | None,
        state: LoopState | None,
        context_bundle: ContextBundle | None,
    ) -> str:
        """Render the synthesis system-prompt fragment (delegates to synthesis_projection)."""
        from soothe.sloop.engine.scenario_classifier import ScenarioClassification
        from soothe.sloop.engine.synthesis_projection import render_synthesis_system_prompt

        # When called from build_system_message directly (no classification),
        # produce a minimal synthesis template. Full classification is handled
        # by build_synthesis_messages which calls render_synthesis_system_prompt
        # with the ScenarioClassification object.
        user_goal = ""
        if state is not None:
            user_goal = (state.goal or "").strip()
        workspace = getattr(state, "workspace", None) if state is not None else None
        language = getattr(state, "response_language", None) if state is not None else None
        # Minimal classification for direct calls
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
        return (
            "You write brief step-completion status lines for the user watching progress.\n"
            "Given the execute-step input and assistant output, respond with exactly one "
            "first-person sentence (I/we) of at most {max_words} words.\n"
            "No preamble, quotes, or bullet points."
        )

    def _build_human_text(
        self,
        *,
        kind: GraphCallKind,
        goal: str,
        state: LoopState,
        context: PlanContext | None,
        dag_context: str | None,
        context_bundle: ContextBundle | None,
        projection_mode: str | None,
        completion_in_ledger: bool,
        prior_goals_override: list[Any] | None,
        inline_assessment: Any | None,
        plan_coverage: str | None,
        omit_prior_progress_hint: bool,
        plan_gap: Any | None,
    ) -> str:
        """Build the closing human-message text for planner call kinds."""
        from soothe.sloop.prompts.user_message import UserMessageBuilder
        from soothe.sloop.state.schemas import next_goal_local_step_id_start

        builder = UserMessageBuilder()
        mode = projection_mode or resolve_planner_projection_mode(state)

        if kind == "continuation":
            return builder.build_plan_continuation_message(
                goal,
                context_bundle=context_bundle,
                display_goal=goal_preview_text(goal) if mode == "new_goal" else None,
                completion_in_ledger=completion_in_ledger,
                prior_goals_override=prior_goals_override,
            )

        step_id_hint = None
        step_anchor_registry = None
        if kind == "generate":
            from soothe.sloop.prompts.step_anchor_registry import (
                build_step_anchor_registry,
            )

            goal_node = context_bundle.active_goal if context_bundle is not None else None
            if goal_node is not None or state.step_results:
                step_anchor_registry = build_step_anchor_registry(
                    goal_node=goal_node,
                    state=state,
                )
            nxt = next_goal_local_step_id_start(state)
            if nxt > 1:
                width = max(2, len(str(nxt + 1)))
                ex_a = str(nxt).zfill(width)
                ex_b = str(nxt + 1).zfill(width)
                step_id_hint = (
                    f"This goal already used lower step indices; use the next unused local "
                    f"step ids starting with {ex_a} (e.g. {ex_a}, {ex_b}, …), not 01/02 again."
                )

        common_kwargs = dict(
            goal=goal,
            dag_context=dag_context,
            skill_context=state.skill_context,
            prior_progress=getattr(state, "prior_progress", None),
            current_iteration=state.iteration,
            context_bundle=context_bundle,
            display_goal=goal_preview_text(goal) if mode == "new_goal" else None,
            projection_mode=mode,
            completion_in_ledger=completion_in_ledger,
            prior_goals_override=prior_goals_override,
        )

        if kind == "assess":
            last_assessment = None
            if context_bundle is not None and context_bundle.active_goal is not None:
                last_assessment = context_bundle.active_goal.last_assessment
            return builder.build_plan_assess_message(
                **common_kwargs,
                plan_coverage=plan_coverage,
                omit_prior_progress_hint=omit_prior_progress_hint,
                last_assessment=last_assessment,
                plan_gap=plan_gap,
            )
        if kind == "gap":
            return builder.build_plan_gap_message(
                goal=goal,
                prior_progress=getattr(state, "prior_progress", None),
                current_iteration=state.iteration,
                projection_mode=mode,
                plan_coverage=plan_coverage,
                omit_prior_progress_hint=omit_prior_progress_hint,
            )
        # generate
        generate_kwargs: dict[str, Any] = {
            **common_kwargs,
            "step_id_hint": step_id_hint,
            "step_anchor_registry": step_anchor_registry,
        }
        if inline_assessment is not None:
            generate_kwargs["assessment_status"] = getattr(inline_assessment, "status", None)
            generate_kwargs["assessment_progress"] = getattr(
                inline_assessment, "goal_progress", None
            )
        if plan_gap is not None:
            generate_kwargs["plan_gap"] = plan_gap
        approved_md = getattr(state, "approved_plan_markdown", None)
        if (approved_md or "").strip():
            generate_kwargs["approved_plan_markdown"] = approved_md
            generate_kwargs["approved_plan_path"] = getattr(state, "approved_plan_path", None)
        return builder.build_plan_generate_message(**generate_kwargs)

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
        from soothe.sloop.prompts.user_message import _goal_text

        text = _goal_text(goal)
        if text == "No goal specified":
            return "No request specified"
        return text

    @staticmethod
    def _phase_for_kind(kind: GraphCallKind) -> str:
        """Map call kind to the ledger phase tag for the closing human message."""
        if kind == "gap":
            return "plan_gap_analysis"
        if kind in ("assess", "continuation"):
            return "plan_assess"
        if kind == "generate":
            return "plan_generate"
        if kind == "synthesis":
            return "goal_completion"
        return "execute_step"


__all__ = [
    "GraphCallKind",
    "GraphPromptWrapper",
    "ProjectionResult",
]
