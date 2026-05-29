"""Tests for executor skill-activation bridge helpers (RFC-105)."""

from __future__ import annotations

from soothe.core.loop.engine.executor import Executor
from soothe.core.loop.state.schemas import LoopState


class TestSeedSkillActivation:
    def test_returns_none_when_empty(self) -> None:
        state = LoopState(goal="g", thread_id="t1")
        result = Executor._seed_skill_activation(state)
        assert result is None

    def test_returns_dict_when_activated(self) -> None:
        state = LoopState(goal="g", thread_id="t1")
        state.activated_skill_names = {"py-skill"}
        result = Executor._seed_skill_activation(state)
        assert result is not None
        assert "py-skill" in result["activated"]
        assert result["just_invoked"] == set()

    def test_includes_invoked_bodies(self) -> None:
        state = LoopState(goal="g", thread_id="t1")
        state.invoked_skill_names = {"a"}
        state.invoked_skill_bodies = {"a": "body text"}
        result = Executor._seed_skill_activation(state)
        assert result is not None
        assert result["invoked_bodies"] == {"a": "body text"}


class TestSnapshotSkillActivation:
    def test_snapshots_activated(self) -> None:
        loop_state = LoopState(goal="g", thread_id="t1")
        graph_output = {
            "skill_activation": {
                "sent": {"a"},
                "activated": {"b", "c"},
                "invoked": {"d"},
                "invoked_bodies": {"d": "body"},
            }
        }
        Executor._snapshot_skill_activation(graph_output, loop_state)
        assert loop_state.sent_skill_names == {"a"}
        assert loop_state.activated_skill_names == {"b", "c"}
        assert loop_state.invoked_skill_names == {"d"}
        assert loop_state.invoked_skill_bodies == {"d": "body"}

    def test_skips_none_output(self) -> None:
        loop_state = LoopState(goal="g", thread_id="t1")
        Executor._snapshot_skill_activation(None, loop_state)
        assert loop_state.activated_skill_names == set()

    def test_skips_missing_skill_activation(self) -> None:
        loop_state = LoopState(goal="g", thread_id="t1")
        Executor._snapshot_skill_activation({"messages": []}, loop_state)
        assert loop_state.activated_skill_names == set()

    def test_skips_malformed_skill_activation(self) -> None:
        loop_state = LoopState(goal="g", thread_id="t1")
        Executor._snapshot_skill_activation({"skill_activation": "bad"}, loop_state)
        assert loop_state.activated_skill_names == set()


class TestExecuteGraphInput:
    def test_includes_skill_activation(self) -> None:
        result = Executor._execute_graph_input(
            [],
            skill_activation={"activated": {"x"}},
        )
        assert result["skill_activation"] == {"activated": {"x"}}

    def test_omits_skill_activation_when_none(self) -> None:
        result = Executor._execute_graph_input([])
        assert "skill_activation" not in result
