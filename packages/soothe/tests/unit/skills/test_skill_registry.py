"""Tests for ``soothe.skills.registry`` (RFC-105)."""

from __future__ import annotations

from soothe.skills.index import SkillIndexEntry
from soothe.skills.registry import ProgressiveSkillRegistry


def _entry(name: str, *, paths: tuple[str, ...] | None = None) -> SkillIndexEntry:
    return SkillIndexEntry(
        name=name,
        description=f"{name} skill",
        tags="test",
        source="user",
        path="/tmp",
        mtime=0.0,
        paths=paths,
    )


class TestPartition:
    def test_partition_unconditional(self) -> None:
        reg = ProgressiveSkillRegistry()
        entries = [_entry("a"), _entry("b", paths=("*.py",))]
        unconditional, conditional = reg.partition(entries)
        assert len(unconditional) == 1
        assert unconditional[0].name == "a"
        assert len(conditional) == 1
        assert conditional[0].name == "b"

    def test_partition_empty(self) -> None:
        reg = ProgressiveSkillRegistry()
        unconditional, conditional = reg.partition([])
        assert unconditional == []
        assert conditional == []


class TestInitActivationState:
    def test_default_keys(self) -> None:
        state = ProgressiveSkillRegistry.init_activation_state()
        assert "sent" in state
        assert "activated" in state
        assert "invoked" in state
        assert "invoked_bodies" in state
        assert isinstance(state["sent"], set)
        assert isinstance(state["activated"], set)


class TestMatchPaths:
    def test_match_simple_glob(self, tmp_path) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        workspace = tmp_path
        (workspace / "test.py").write_text("print('hi')")

        conditional = [_entry("python-skill", paths=("*.py",))]
        matches = reg.match_paths(state, workspace, ["test.py"], conditional)
        assert len(matches) == 1
        assert matches[0][0] == "python-skill"

    def test_no_match_different_extension(self, tmp_path) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        workspace = tmp_path
        (workspace / "test.js").write_text("console.log('hi')")

        conditional = [_entry("python-skill", paths=("*.py",))]
        matches = reg.match_paths(state, workspace, ["test.js"], conditional)
        assert matches == []

    def test_already_activated_skipped(self, tmp_path) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        state["activated"].add("python-skill")
        workspace = tmp_path
        (workspace / "test.py").write_text("print('hi')")

        conditional = [_entry("python-skill", paths=("*.py",))]
        matches = reg.match_paths(state, workspace, ["test.py"], conditional)
        assert matches == []

    def test_match_directory_pattern(self, tmp_path) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        workspace = tmp_path
        src = workspace / "src"
        src.mkdir()
        (src / "main.py").write_text("pass")

        conditional = [_entry("src-skill", paths=("src/**/*.py",))]
        matches = reg.match_paths(state, workspace, ["src/main.py"], conditional)
        assert len(matches) == 1


class TestMarkMethods:
    def test_mark_sent(self) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        reg.mark_sent(state, ["a", "b"])
        assert state["sent"] == {"a", "b"}

    def test_mark_activated(self) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        reg.mark_activated(state, ["a"])
        assert state["activated"] == {"a"}

    def test_mark_invoked(self) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        reg.mark_invoked(state, "a", "body content")
        assert state["invoked"] == {"a"}
        assert state["invoked_bodies"] == {"a": "body content"}

    def test_cache_body(self) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        reg.cache_body(state, "a", "body content")
        assert state["invoked_bodies"] == {"a": "body content"}
