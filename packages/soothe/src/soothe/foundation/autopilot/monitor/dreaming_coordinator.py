"""DreamingCoordinator - LLM-driven multi-mode memory distillation (RFC-625).

Coordinates 4 distillation modes:
- episodic: Transform goals into narrative episode summaries
- procedure: Extract reusable procedures (Skills)
- semantic: Update project MEMORY.md
- profile: Extract user preferences and patterns

Triggered by:
1. DAG completion (all goals terminal)
2. Timer interval (configurable)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from soothe.foundation.autopilot.monitor.models import (
    DreamingContext,
    DreamingMode,
    DreamingScope,
    EpisodeSpec,
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
        # TODO: Initialize DreamingDistillationReasoner

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
        # TODO: LLM integration per RFC-625 spec
        logger.info(
            "Running %s distillation on %d goals",
            mode,
            len(context.goals),
        )
        return None

    async def _apply_distillation_result(self, mode: DreamingMode, result: Any) -> None:
        """Apply distillation result to appropriate store.

        Args:
            mode: Distillation mode
            result: Structured result from distillation
        """
        if mode == "episodic" and result:
            # Store episodes in CE episodic memory
            if isinstance(result, list):
                episodes = [
                    EpisodeSummary(
                        goal_id=ep.goal_id,
                        description=ep.description,
                        outcome_summary=ep.outcome_summary,
                        key_steps=ep.key_steps,
                        lessons_learned=ep.lessons_learned,
                    )
                    for ep in result
                    if isinstance(ep, EpisodeSpec)
                ]
                await self._ce.record_episodic_memory(episodes)

        elif mode == "procedure" and result:
            # TODO: Create Skill definitions
            logger.info(
                "Procedure distillation result: %s procedures",
                len(result) if isinstance(result, list) else 0,
            )

        elif mode == "semantic" and result:
            # TODO: Update MEMORY.md
            logger.info("Semantic distillation result: %s", result)

        elif mode == "profile" and result:
            # TODO: Update user profile store
            logger.info("Profile distillation result: %s", result)
