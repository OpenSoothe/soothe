"""Debug tracing for loop token events in the CLI TUI.

Enable with ``logging_level: DEBUG`` in CLI config (``~/.soothe/config/cli.yml``)
or ``SOOTHE_LOG_LEVEL=DEBUG``. Grep ``cli.log`` for ``[token-events]``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("soothe_cli.token_events")


@dataclass
class TokenEventTrace:
    """Per-turn counters for token-related daemon/TUI events."""

    stream_chunks: int = 0
    plan_phase_events: int = 0
    plan_phase_with_total_field: int = 0
    plan_phase_missing_total_field: int = 0
    step_completed_events: int = 0
    step_completed_with_total_field: int = 0
    authoritative_applied: int = 0
    display_refreshes: int = 0
    anomalies: list[str] = field(default_factory=list)

    def reset(self) -> None:
        """Clear counters for a new turn."""
        self.stream_chunks = 0
        self.plan_phase_events = 0
        self.plan_phase_with_total_field = 0
        self.plan_phase_missing_total_field = 0
        self.step_completed_events = 0
        self.step_completed_with_total_field = 0
        self.authoritative_applied = 0
        self.display_refreshes = 0
        self.anomalies.clear()

    def note_stream_usage(
        self, *, input_tokens: int, output_tokens: int, total_tokens: int
    ) -> None:
        """Record a messages-stream chunk carrying provider usage."""
        self.stream_chunks += 1
        logger.debug(
            "[token-events] stream usage chunk #%d in=%d out=%d total=%d",
            self.stream_chunks,
            input_tokens,
            output_tokens,
            total_tokens,
        )

    def note_plan_phase(
        self, *, label: str, total_tokens_used: int | None, has_total_field: bool
    ) -> None:
        """Record a StrangeLoop plan-phase lifecycle event."""
        self.plan_phase_events += 1
        if has_total_field:
            self.plan_phase_with_total_field += 1
        else:
            self.plan_phase_missing_total_field += 1
            self.anomalies.append(f"plan_phase missing total_tokens_used ({label!r})")
        logger.debug(
            "[token-events] plan_phase label=%r total=%s has_total_field=%s",
            label,
            total_tokens_used if has_total_field else "—",
            has_total_field,
        )

    def note_step_completed(
        self, *, step_id: str, total_tokens_used: int | None, has_total_field: bool
    ) -> None:
        """Record step.completed with optional backend loop total."""
        self.step_completed_events += 1
        if has_total_field:
            self.step_completed_with_total_field += 1
        logger.debug(
            "[token-events] step_completed step_id=%s total=%s has_total_field=%s",
            step_id or "—",
            total_tokens_used if has_total_field else "—",
            has_total_field,
        )

    def note_authoritative_merge(
        self,
        *,
        source: str,
        goal_run_total: int,
        previous_goal_run: int,
        applied: bool,
        display_total: int,
    ) -> None:
        """Record backend total merged into the TUI loop counter."""
        if applied:
            self.authoritative_applied += 1
        logger.debug(
            "[token-events] authoritative source=%s goal_run=%d prev_goal_run=%d applied=%s display=%d",
            source,
            goal_run_total,
            previous_goal_run,
            applied,
            display_total,
        )

    def note_display_refresh(self, *, display_total: int, target: str) -> None:
        """Record a push to the thinking row or status bar."""
        self.display_refreshes += 1
        logger.debug(
            "[token-events] display refresh target=%s total=%d refresh#%d",
            target,
            display_total,
            self.display_refreshes,
        )

    def finish_turn(
        self,
        *,
        loop_id: str | None,
        baseline: int,
        goal_run: int,
        display_total: int,
        turn_input: int,
        turn_output: int,
        approximate: bool,
    ) -> None:
        """Emit one summary line per turn; flags missing events."""
        has_stream = self.stream_chunks > 0
        has_backend_total = (
            self.plan_phase_with_total_field > 0 or self.step_completed_with_total_field > 0
        )
        has_any_usage = display_total > 0 or turn_input > 0 or turn_output > 0

        if has_any_usage and not has_stream and not has_backend_total:
            self.anomalies.append("usage visible but no stream or backend total events")
        if self.plan_phase_events > 0 and self.plan_phase_missing_total_field > 0:
            self.anomalies.append(
                f"{self.plan_phase_missing_total_field}/{self.plan_phase_events} plan_phase "
                "events lacked total_tokens_used"
            )
        if not has_any_usage and (self.plan_phase_events or self.step_completed_events):
            self.anomalies.append("lifecycle events seen but display total still zero")

        status = "ok"
        if self.anomalies:
            status = "anomaly"
        elif not has_stream and not has_backend_total and not has_any_usage:
            status = "no_events"

        logger.debug(
            "[token-events] turn summary loop=%s status=%s baseline=%d goal_run=%d "
            "display=%d turn_in=%d turn_out=%d stream_chunks=%d plan_phase=%d "
            "step_completed=%d authoritative_applied=%d approximate=%s anomalies=%s",
            loop_id or "—",
            status,
            baseline,
            goal_run,
            display_total,
            turn_input,
            turn_output,
            self.stream_chunks,
            self.plan_phase_events,
            self.step_completed_events,
            self.authoritative_applied,
            approximate,
            "; ".join(self.anomalies) if self.anomalies else "none",
        )


__all__ = ["TokenEventTrace", "logger"]
