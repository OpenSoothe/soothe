"""DreamingCoordinator - LLM-driven multi-mode memory distillation (RFC-625).

Coordinates 4 distillation modes:
- episodic: Transform goals into narrative episode summaries
- procedure: Extract reusable procedures (Skills)
- semantic: Update project MEMORY.md
- profile: Extract user preferences and patterns

Triggered by:
1. DAG completion (all goals terminal)
2. Timer interval (configurable)

Uses DreamingDistillationReasoner for structured LLM calls.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from soothe.foundation.autopilot.monitor.dreaming_reasoner import (
    DreamingDistillationReasoner,
    EpisodicDistillationContext,
    ProcedureDistillationContext,
    ProfileDistillationContext,
    SemanticDistillationContext,
)
from soothe.foundation.autopilot.monitor.models import (
    DreamingContext,
    DreamingMode,
    DreamingScope,
)
from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.models import EpisodeSummary

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.foundation.events.internal_bus import InternalEventBus

logger = logging.getLogger(__name__)

DreamingState = Literal["idle", "active"]


class DreamingCoordinator:
    """LLM-driven multi-mode memory distillation.

    Orchestrates episodic, procedure, semantic, and profile distillation
    using LLM reasoning to extract structured knowledge from goal execution.

    Args:
        ce: ContextEngine instance for goal access.
        config: SootheConfig for LLM model access.
        bus: Optional InternalEventBus for events.

    Attributes:
        _reasoner: DreamingDistillationReasoner for LLM calls.
    """

    def __init__(
        self,
        ce: ContextEngine,
        config: SootheConfig,
        bus: InternalEventBus | None = None,
    ) -> None:
        """Initialize coordinator.

        Args:
            ce: ContextEngine instance
            config: SootheConfig for LLM model access
            bus: Optional InternalEventBus for events
        """
        self._ce = ce
        self._config = config
        self._bus = bus
        self._dreaming_state: DreamingState = "idle"
        self._reasoner = DreamingDistillationReasoner(config)

    async def enter_dreaming_mode(
        self,
        modes: list[DreamingMode] | None = None,
        scope: DreamingScope = "loop",
    ) -> None:
        """Enter dreaming mode and run LLM-driven distillation.

        Args:
            modes: Optional list of modes to run (default: all enabled)
            scope: Dreaming scope (loop, workspace, topic)
        """
        if self._dreaming_state == "active":
            logger.warning("Already in dreaming mode")
            return

        self._dreaming_state = "active"
        if self._bus:
            await self._bus.emit("dreaming_mode_entered", {})

        enabled_modes = modes or self._get_enabled_modes()
        context = await self._gather_dreaming_context(scope)

        logger.info("Entering dreaming mode with modes: %s", enabled_modes)

        for mode in enabled_modes:
            try:
                result = await self._run_mode(mode, context)
                await self._apply_distillation_result(mode, result)
                logger.info("Dreaming mode %s completed successfully", mode)
            except Exception:
                logger.exception("Dreaming mode %s failed", mode)

        self._dreaming_state = "idle"
        if self._bus:
            await self._bus.emit("dreaming_mode_exited", {})

    def _get_enabled_modes(self) -> list[DreamingMode]:
        """Get list of enabled dreaming modes from config."""
        # Default all modes enabled
        cfg = getattr(self._config.agent.autonomous, "dreaming_modes", None)
        if cfg:
            enabled = []
            if getattr(cfg.episodic, "enabled", True):
                enabled.append("episodic")
            if getattr(cfg.procedure, "enabled", True):
                enabled.append("procedure")
            if getattr(cfg.semantic, "enabled", True):
                enabled.append("semantic")
            if getattr(cfg.profile, "enabled", True):
                enabled.append("profile")
            return enabled
        return ["episodic", "procedure", "semantic", "profile"]

    async def _gather_dreaming_context(self, scope: DreamingScope) -> DreamingContext:
        """Gather goals and ledger based on scope.

        Args:
            scope: loop, workspace, or topic

        Returns:
            DreamingContext with goals, ledger, and scope_id
        """
        if scope == "loop":
            goals = self._ce.get_goals_by_status(None)
            ledger = self._ce.get_ledger_entries()
            scope_id = self._ce._dag.goals.keys().__iter__().__next__() if goals else "unknown"

        elif scope == "workspace":
            # TODO: Aggregate across workspace
            goals = self._ce.get_goals_by_status(None)
            ledger = self._ce.get_ledger_entries()
            scope_id = "workspace"

        else:  # topic
            # TODO: Filter by topic tag
            goals = self._ce.get_goals_by_status(None)
            ledger = self._ce.get_ledger_entries()
            scope_id = "topic"

        return DreamingContext(goals=goals, ledger=ledger, scope_id=scope_id)

    async def _run_mode(self, mode: DreamingMode, context: DreamingContext) -> Any:
        """Run LLM distillation for a specific mode.

        Args:
            mode: Distillation mode
            context: Dreaming context with goals and ledger

        Returns:
            Distillation result for the mode
        """
        logger.info(
            "Running %s distillation on %d goals",
            mode,
            len(context.goals),
        )

        try:
            if mode == "episodic":
                episodic_context = EpisodicDistillationContext.from_context(
                    context,
                    max_episodes=self._get_max_episodes(),
                )
                return await self._reasoner.distill_episodic(episodic_context)

            elif mode == "procedure":
                procedure_context = ProcedureDistillationContext.from_context(
                    context,
                    min_success_rate=self._get_min_success_rate(),
                )
                return await self._reasoner.distill_procedure(procedure_context)

            elif mode == "semantic":
                semantic_context = SemanticDistillationContext.from_context(context)
                return await self._reasoner.distill_semantic(semantic_context)

            elif mode == "profile":
                profile_context = ProfileDistillationContext.from_context(context)
                return await self._reasoner.distill_profile(profile_context)

            else:
                logger.warning("Unknown dreaming mode: %s", mode)
                return None

        except Exception:
            logger.exception("LLM distillation failed for mode %s", mode)
            return None

    def _get_max_episodes(self) -> int:
        """Get max episodes from config."""
        cfg = getattr(self._config.agent.autonomous, "dreaming_modes", None)
        if cfg:
            return getattr(cfg.episodic, "max_episodes", 10)
        return 10

    def _get_min_success_rate(self) -> float:
        """Get min success rate for procedure extraction from config."""
        cfg = getattr(self._config.agent.autonomous, "dreaming_modes", None)
        if cfg:
            return getattr(cfg.procedure, "min_success_rate", 0.8)
        return 0.8

    async def _apply_distillation_result(self, mode: DreamingMode, result: Any) -> None:
        """Apply distillation result to appropriate store.

        Args:
            mode: Distillation mode
            result: Structured result from distillation
        """
        if result is None:
            return

        if mode == "episodic":
            # Store episodes in CE episodic memory
            episodes = []
            for ep in result.episodes:
                episodes.append(
                    EpisodeSummary(
                        goal_id=ep.goal_id,
                        description=ep.description,
                        outcome_summary=ep.outcome_summary,
                        key_steps=list(ep.key_steps),
                        lessons_learned=ep.lessons_learned,
                    )
                )
            if episodes:
                await self._ce.record_episodic_memory(episodes)
                logger.info("Stored %d episodes in episodic memory", len(episodes))

        elif mode == "procedure":
            # TODO: Create Skill definitions
            logger.info(
                "Procedure distillation extracted %s procedures: %s",
                len(result.procedures),
                [p.name for p in result.procedures],
            )

        elif mode == "semantic":
            # TODO: Update MEMORY.md
            logger.info(
                "Semantic distillation: %s additions, %s modifications",
                len(result.additions),
                len(result.modifications),
            )

        elif mode == "profile":
            # TODO: Update user profile store
            logger.info(
                "Profile distillation: style=%s, expertise=%s",
                result.communication_style,
                result.expertise_level,
            )
