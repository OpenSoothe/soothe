"""Tests for executor skill-activation bridge helpers (RFC-105)."""

from __future__ import annotations

from soothe.sloop.engine.executor import Executor
from soothe.sloop.state.schemas import LoopState


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

    def test_slash_invocation_registers_via_mark_invoked(self) -> None:
        """Slash invocation signal seeds skill_activation with mark_invoked."""
        state = LoopState(goal="shanghai tomorrow", thread_id="t1")
        state.slash_invoked_skill_name = "weather"
        state.slash_invoked_skill_body = "Weather skill body text"
        result = Executor._seed_skill_activation(state)
        assert result is not None
        assert "weather" in result["invoked"]
        assert "weather" in result["just_invoked"]
        assert result["invoked_bodies"]["weather"] == "Weather skill body text"

    def test_slash_invocation_with_prior_activated(self) -> None:
        """Slash invocation merges with existing activated skills."""
        state = LoopState(goal="g", thread_id="t1")
        state.activated_skill_names = {"py-skill"}
        state.slash_invoked_skill_name = "weather"
        state.slash_invoked_skill_body = "Weather body"
        result = Executor._seed_skill_activation(state)
        assert result is not None
        assert "py-skill" in result["activated"]
        assert "weather" in result["invoked"]
        assert "weather" in result["just_invoked"]

    def test_slash_invocation_missing_body_returns_none(self) -> None:
        """Slash name without body does not trigger activation."""
        state = LoopState(goal="g", thread_id="t1")
        state.slash_invoked_skill_name = "weather"
        # No slash_invoked_skill_body
        result = Executor._seed_skill_activation(state)
        assert result is None


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

    def test_clears_slash_invocation_signal(self) -> None:
        """Snapshot clears slash invocation signal fields (consumed once)."""
        loop_state = LoopState(goal="g", thread_id="t1")
        loop_state.slash_invoked_skill_name = "weather"
        loop_state.slash_invoked_skill_body = "body"
        graph_output = {"skill_activation": {"sent": set(), "activated": set(), "invoked": set()}}
        Executor._snapshot_skill_activation(graph_output, loop_state)
        assert loop_state.slash_invoked_skill_name is None
        assert loop_state.slash_invoked_skill_body is None


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
