"""Tests for ``soothe.skills.registry`` (RFC-105 / IG-543)."""

from __future__ import annotations

from soothe_nano.skills.index import SkillIndexEntry
from soothe_nano.skills.registry import (
    DEFAULT_CORE_SKILL_NAMES,
    ProgressiveSkillRegistry,
    is_core_skill,
    merge_skill_activation,
)


def _entry(
    name: str,
    *,
    paths: tuple[str, ...] | None = None,
    source: str = "user",
    core: bool | None = None,
) -> SkillIndexEntry:
    return SkillIndexEntry(
        name=name,
        description=f"{name} skill",
        tags="test",
        source=source,
        path="/tmp",
        mtime=0.0,
        paths=paths,
        core=core,
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


class TestPartitionCoreDeferred:
    def test_builtin_is_core(self) -> None:
        reg = ProgressiveSkillRegistry()
        entries = [_entry("weather", source="builtin"), _entry("custom")]
        core, deferred = reg.partition_core_deferred(entries, DEFAULT_CORE_SKILL_NAMES)
        assert [entry.name for entry in core] == ["weather"]
        assert [entry.name for entry in deferred] == ["custom"]

    def test_core_frontmatter_overrides_user(self) -> None:
        reg = ProgressiveSkillRegistry()
        entries = [_entry("custom", core=True)]
        core, deferred = reg.partition_core_deferred(entries, DEFAULT_CORE_SKILL_NAMES)
        assert [entry.name for entry in core] == ["custom"]
        assert deferred == []

    def test_core_false_demotes_builtin(self) -> None:
        entry = _entry("weather", source="builtin", core=False)
        assert not is_core_skill(entry, DEFAULT_CORE_SKILL_NAMES)


class TestSearchDeferred:
    def test_finds_by_description(self) -> None:
        reg = ProgressiveSkillRegistry()
        deferred = [_entry("db-migrate")]
        matches = reg.search_deferred("postgres", deferred, discovered=set(), limit=5)
        assert matches == []

        entry = _entry("db-migrate")
        entry_with_tags = SkillIndexEntry(
            name=entry.name,
            description="postgres migration helpers",
            tags=entry.tags,
            source=entry.source,
            path=entry.path,
            mtime=entry.mtime,
        )
        matches = reg.search_deferred("postgres", [entry_with_tags], discovered=set(), limit=5)
        assert len(matches) == 1
        assert matches[0].name == "db-migrate"

    def test_skips_already_discovered(self) -> None:
        reg = ProgressiveSkillRegistry()
        deferred = [_entry("db-migrate")]
        matches = reg.search_deferred("db", deferred, discovered={"db-migrate"}, limit=5)
        assert matches == []

    def test_matches_tag_token_in_query(self) -> None:
        reg = ProgressiveSkillRegistry()
        weather = SkillIndexEntry(
            name="weather",
            description="Get current weather",
            tags="weather, 天气, forecast",
            source="builtin",
            path="/tmp",
            mtime=0.0,
        )
        matches = reg.search_deferred("上海今天的天气", [weather], discovered=set(), limit=5)
        assert [entry.name for entry in matches] == ["weather"]

    def test_match_corpus_finds_tag_token(self) -> None:
        reg = ProgressiveSkillRegistry()
        weather = SkillIndexEntry(
            name="weather",
            description="Get current weather",
            tags="weather, 天气",
            source="builtin",
            path="/tmp",
            mtime=0.0,
        )
        matches = reg.match_deferred_in_corpus(
            "上海今天的天气",
            [weather],
            discovered=set(),
            limit=5,
        )
        assert [entry.name for entry in matches] == ["weather"]

    def test_match_corpus_clawhub_spaced_name(self) -> None:
        reg = ProgressiveSkillRegistry()
        clawhub = SkillIndexEntry(
            name="clawhub",
            description="Search ClawHub registry",
            tags="clawhub, claw hub, skill registry",
            source="builtin",
            path="/tmp",
            mtime=0.0,
        )
        matches = reg.match_deferred_in_corpus(
            "is there skill of drawio on claw hub",
            [clawhub],
            discovered=set(),
            limit=5,
        )
        assert [entry.name for entry in matches] == ["clawhub"]

    def test_match_corpus_skill_creator_hyphen(self) -> None:
        reg = ProgressiveSkillRegistry()
        entry = SkillIndexEntry(
            name="skill-creator",
            description="Create skills",
            tags="skill creator, create skill",
            source="builtin",
            path="/tmp",
            mtime=0.0,
        )
        matches = reg.match_deferred_in_corpus(
            "help me create a skill for testing",
            [entry],
            discovered=set(),
            limit=5,
        )
        assert [entry.name for entry in matches] == ["skill-creator"]

    def test_search_deferred_claw_hub_in_query(self) -> None:
        reg = ProgressiveSkillRegistry()
        clawhub = SkillIndexEntry(
            name="clawhub",
            description="ClawHub registry",
            tags="clawhub, claw hub",
            source="builtin",
            path="/tmp",
            mtime=0.0,
        )
        matches = reg.search_deferred(
            "drawio on claw hub",
            [clawhub],
            discovered=set(),
            limit=5,
        )
        assert [entry.name for entry in matches] == ["clawhub"]


class TestDiscover:
    def test_idempotent(self) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        added = reg.discover(state, ["a"], via="search")
        assert added == ["a"]
        assert reg.discover(state, ["a"], via="search") == []
        assert state["activated"] == {"a"}


class TestInitActivationState:
    def test_default_keys(self) -> None:
        state = ProgressiveSkillRegistry.init_activation_state()
        assert "sent" in state
        assert "activated" in state
        assert "invoked" in state
        assert "invoked_bodies" in state
        assert isinstance(state["sent"], set)
        assert isinstance(state["activated"], set)


class TestMergeSkillActivation:
    def test_unions_sets_and_merges_bodies(self) -> None:
        left = {
            **ProgressiveSkillRegistry.init_activation_state(),
            "invoked": {"clawhub"},
            "invoked_bodies": {"clawhub": "left body"},
        }
        right = {
            **ProgressiveSkillRegistry.init_activation_state(),
            "activated": {"find-skills"},
            "invoked_bodies": {"weather": "right body"},
            "intent_prefetched": True,
        }
        merged = merge_skill_activation(left, right)
        assert merged["invoked"] == {"clawhub"}
        assert merged["activated"] == {"find-skills"}
        assert merged["invoked_bodies"] == {"clawhub": "left body", "weather": "right body"}
        assert merged["intent_prefetched"] is True


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
        assert state["just_invoked"] == {"a"}

    def test_mark_preloaded(self) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        reg.mark_preloaded(state, "weather", "wttr.in body")
        assert state["invoked"] == {"weather"}
        assert state["invoked_bodies"] == {"weather": "wttr.in body"}
        assert state["just_invoked"] == set()

    def test_cache_body(self) -> None:
        reg = ProgressiveSkillRegistry()
        state = ProgressiveSkillRegistry.init_activation_state()
        reg.cache_body(state, "a", "body content")
        assert state["invoked_bodies"] == {"a": "body content"}
