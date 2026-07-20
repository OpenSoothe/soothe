"""Tests for ``soothe.skills.corpus_match``."""

from __future__ import annotations

from soothe_nano.skills.corpus_match import earliest_corpus_match, match_variants_for_token


class TestEarliestCorpusMatch:
    def test_clawhub_matches_spaced_claw_hub(self) -> None:
        goal = "is there skill of drawio on claw hub"
        pos = earliest_corpus_match(goal, "clawhub", skill_name="clawhub")
        assert pos is not None
        assert goal[pos : pos + 8] == "claw hub"

    def test_clawhub_tag_matches_spaced_phrase(self) -> None:
        goal = "search claw hub for a postgres skill"
        pos = earliest_corpus_match(goal, "claw hub", skill_name="clawhub")
        assert pos is not None

    def test_skill_creator_matches_hyphen_and_space(self) -> None:
        for goal in ("help me create a skill creator guide", "update the skill-creator docs"):
            pos = earliest_corpus_match(goal, "skill-creator", skill_name="skill-creator")
            assert pos is not None, goal

    def test_github_matches_git_hub(self) -> None:
        goal = "check ci on git hub for soothe repo"
        pos = earliest_corpus_match(goal, "github", skill_name="github")
        assert pos is not None

    def test_weather_chinese_tag(self) -> None:
        goal = "上海今天的天气"
        pos = earliest_corpus_match(goal, "天气", skill_name="weather")
        assert pos is not None

    def test_no_false_positive_short_compact(self) -> None:
        assert earliest_corpus_match("hi", "gh", skill_name="github") is None

    def test_short_tags_require_word_boundaries(self) -> None:
        continuation = (
            "execution task:\n"
            "address the follow-up request: what subagents do you have. "
            "use the prior goal's projected completion report as authoritative background."
        )
        assert earliest_corpus_match(continuation, "pr", skill_name="github") is None
        assert earliest_corpus_match(continuation, "ci", skill_name="github") is None
        assert earliest_corpus_match("make a decision soon", "ci", skill_name="github") is None
        assert (
            earliest_corpus_match("list open pr on git hub", "pr", skill_name="github") is not None
        )

    def test_match_variants_include_builtin_aliases(self) -> None:
        variants = match_variants_for_token("clawhub", skill_name="clawhub")
        assert "claw hub" in variants


class TestBuiltinSkillCorpusPrefetch:
    """Integration-style checks against real built-in skill frontmatter tags."""

    def test_all_core_builtins_match_natural_queries(self) -> None:
        from soothe_nano.skills.index import SkillIndex
        from soothe_nano.skills.registry import (
            DEFAULT_CORE_SKILL_NAMES,
            ProgressiveSkillRegistry,
        )

        idx = SkillIndex()
        entries = idx.rebuild_if_stale()
        reg = ProgressiveSkillRegistry()
        core, _ = reg.partition_core_deferred(entries, DEFAULT_CORE_SKILL_NAMES)
        by_name = {entry.name: entry for entry in core}

        cases = {
            "clawhub": "is there skill of drawio on claw hub",
            "github": "list open prs on git hub for soothe",
            "skill-creator": "help me create a skill for linting",
            "weather": "北京今天的天气",
        }
        for name, goal in cases.items():
            matches = reg.match_deferred_in_corpus(
                goal,
                [by_name[name]],
                discovered=set(),
                limit=1,
            )
            assert [entry.name for entry in matches] == [name], goal

    def test_github_not_matched_by_continuation_boilerplate(self) -> None:
        from soothe_nano.skills.index import SkillIndex
        from soothe_nano.skills.registry import (
            DEFAULT_CORE_SKILL_NAMES,
            ProgressiveSkillRegistry,
        )

        idx = SkillIndex()
        entries = idx.rebuild_if_stale()
        reg = ProgressiveSkillRegistry()
        core, _ = reg.partition_core_deferred(entries, DEFAULT_CORE_SKILL_NAMES)
        github = next(entry for entry in core if entry.name == "github")
        continuation = (
            "EXECUTION TASK:\n"
            "Address the follow-up request: what subagents do you have. "
            "Use the prior goal's projected completion report as authoritative background. "
            "Do not re-run prior goal execute steps or redo finished analysis; "
            "build on what was already concluded and produce concrete output for this request."
        )
        matches = reg.match_deferred_in_corpus(
            continuation,
            [github],
            discovered=set(),
            limit=1,
        )
        assert matches == []
