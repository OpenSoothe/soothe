"""IG-379: dependency-mode residual step logging."""

from __future__ import annotations

import logging

import pytest

from soothe.core.agent_loop.execution.executor import _log_dependency_execution_residual
from soothe.core.agent_loop.state.schemas import AgentDecision, StepAction


def test_log_dependency_execution_residual_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Never-started steps emit a structured warning with unresolved dependency ids."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="P-01", description="done", expected_output="o"),
            StepAction(
                id="P-02",
                description="blocked",
                expected_output="o",
                dependencies=["P-99"],
            ),
        ],
        execution_mode="dependency",
        reasoning="t",
    )
    local_done = {"P-01"}
    failed_sticky: set[str] = set()
    with caplog.at_level(logging.WARNING):
        _log_dependency_execution_residual(
            decision, local_done=local_done, failed_sticky=failed_sticky
        )
    assert "never started" in caplog.text
    assert "P-02" in caplog.text
    assert "P-99" in caplog.text


def test_log_dependency_execution_residual_silent_when_complete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No warning when every step id is either succeeded or failed."""
    decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="P-01", description="a", expected_output="o"),
        ],
        execution_mode="dependency",
        reasoning="t",
    )
    with caplog.at_level(logging.WARNING):
        _log_dependency_execution_residual(decision, local_done={"P-01"}, failed_sticky=set())
    assert not caplog.records
