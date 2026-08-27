"""Tests for veritas system/user prompt builders (RFC-622)."""

from __future__ import annotations

from pathlib import Path

from soothe.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
)
from soothe.subagents.veritas.prompts import (
    build_veritas_system_prompt,
    build_veritas_user_prompt,
)


def _request(workspace_summary: str | None = None) -> ClarificationRequest:
    return ClarificationRequest(
        questions=("which package first?",),
        origin_node="execute",
        origin_interrupt_id="i",
        loop_state=LoopStateView(
            goal_id="g",
            goal_description="refine the auth module",
            user_request="please refine auth",
            iteration=2,
            intent_classification="agentic",
            plan_summary="explored auth/",
            recent_step_outputs=("read auth/main.py",),
            workspace_summary=workspace_summary,
            active_skills=("platonic-coding",),
            active_mcp_servers=(),
        ),
    )


def test_system_prompt_mentions_project_instructions_rule() -> None:
    """Hard rule 6 instructs veritas to respect AGENTS.md / CLAUDE.md."""
    prompt = build_veritas_system_prompt()
    assert "Project instructions" in prompt
    assert "authoritative rules" in prompt


def test_system_prompt_defers_preference_questions() -> None:
    """Hard rule 9: preference-soliciting questions must defer, not pick a default."""
    prompt = build_veritas_system_prompt()
    assert "preference" in prompt.lower()
    # A "(Recommended)" label is a UI affordance, not evidence of user intent.
    assert "(Recommended)" in prompt
    assert "NOT" in prompt
    # Few-shot anchor: the loop-97bf scenario is an explicit Good defer.
    assert "What two topics would you like me to ask you about?" in prompt


def test_user_prompt_inlines_agents_md(tmp_path: Path) -> None:
    """AGENTS.md at the workspace root is inlined as a project instructions block."""
    (tmp_path / "AGENTS.md").write_text(
        "# Rules\nPut code in src/auth/. Never use keyword heuristics.\n",
        encoding="utf-8",
    )
    prompt = build_veritas_user_prompt(_request(workspace_summary=str(tmp_path)))
    assert "=== Project instructions ===" in prompt
    assert "Put code in src/auth/" in prompt
    assert "Never use keyword heuristics" in prompt


def test_user_prompt_inlines_claude_md_fallback(tmp_path: Path) -> None:
    """When no AGENTS.md exists, CLAUDE.md is loaded as fallback."""
    (tmp_path / "CLAUDE.md").write_text(
        "# Project guide\nUse structured output only.\n",
        encoding="utf-8",
    )
    prompt = build_veritas_user_prompt(_request(workspace_summary=str(tmp_path)))
    assert "=== Project instructions ===" in prompt
    assert "Use structured output only" in prompt


def test_user_prompt_skips_project_instructions_when_no_file(tmp_path: Path) -> None:
    """No AGENTS.md / CLAUDE.md → the section is omitted, not rendered empty."""
    prompt = build_veritas_user_prompt(_request(workspace_summary=str(tmp_path)))
    assert "=== Project instructions ===" not in prompt


def test_user_prompt_skips_project_instructions_when_workspace_missing() -> None:
    """No workspace path → loader returns None, section omitted."""
    prompt = build_veritas_user_prompt(_request(workspace_summary=None))
    assert "=== Project instructions ===" not in prompt
    # other sections still render
    assert "=== Original user request ===" in prompt
    assert "=== Questions to answer ===" in prompt


def test_user_prompt_respects_headline_char_cap(tmp_path: Path) -> None:
    """Large AGENTS.md is truncated under the headline cap to bound token cost."""
    (tmp_path / "AGENTS.md").write_text("A" * 20_000, encoding="utf-8")
    prompt = build_veritas_user_prompt(
        _request(workspace_summary=str(tmp_path)),
        agent_instructions_max_chars=2000,
    )
    assert "=== Project instructions ===" in prompt
    # Truncation marker from the shared loader (partial inline or read_file note)
    assert 'inlined="partial"' in prompt or "<NOTE>" in prompt


def test_user_prompt_loads_full_agents_md_by_default(tmp_path: Path) -> None:
    """Default cap (25,000) inlines a typical AGENTS.md verbatim — no truncation."""
    body = "# Rules\n\n" + "Put code in src/auth/. " * 100 + "\nTail marker line.\n"
    (tmp_path / "AGENTS.md").write_text(body, encoding="utf-8")
    prompt = build_veritas_user_prompt(_request(workspace_summary=str(tmp_path)))
    assert "=== Project instructions ===" in prompt
    assert 'inlined="full"' in prompt


def test_system_prompt_mentions_reasoning_field() -> None:
    """System prompt instructs the model to fill the reasoning field."""
    prompt = build_veritas_system_prompt()
    assert "reasoning" in prompt
    assert "chain-of-thought" in prompt.lower() or "analyze" in prompt.lower()


def test_system_prompt_mentions_answer_is_question() -> None:
    """System prompt instructs the model to self-classify answers."""
    prompt = build_veritas_system_prompt()
    assert "answer_is_question" in prompt
    assert "Self-classify" in prompt or "self-classify" in prompt.lower()


def test_system_prompt_contains_examples() -> None:
    """Few-shot examples are present in the system prompt."""
    prompt = build_veritas_system_prompt()
    assert "Examples:" in prompt
    assert "Good answer" in prompt
    assert "Bad answer" in prompt


def test_user_prompt_filters_trivial_step_outputs() -> None:
    """Empty and '(none)' step outputs are filtered out."""
    request = ClarificationRequest(
        questions=("which package?",),
        origin_node="execute",
        origin_interrupt_id="i",
        loop_state=LoopStateView(
            goal_id="g",
            goal_description="refine auth",
            user_request="please refine auth",
            iteration=2,
            intent_classification="agentic",
            plan_summary="explored auth/",
            recent_step_outputs=("read auth/main.py", "", "   ", "(none)"),
            workspace_summary=None,
            active_skills=(),
            active_mcp_servers=(),
        ),
    )
    prompt = build_veritas_user_prompt(request)
    assert "non-trivial" in prompt
    assert "read auth/main.py" in prompt
    # The trivial outputs should not appear as step entries
    assert "--- step 1 ---\n\n" not in prompt
    assert "(none)" not in prompt.split("=== Iteration ===")[0]


def test_user_prompt_includes_prior_clarifications() -> None:
    """Prior clarifications are rendered when present."""
    request = ClarificationRequest(
        questions=("which database?",),
        origin_node="execute",
        origin_interrupt_id="i",
        loop_state=LoopStateView(
            goal_id="g",
            goal_description="build a feature",
            user_request="build a feature",
            iteration=3,
            intent_classification="agentic",
            plan_summary="explored schema",
            recent_step_outputs=(),
            workspace_summary=None,
            active_skills=(),
            active_mcp_servers=(),
            prior_clarifications=("Q: which package?\nA: soothe (source=veritas, conf=0.80)",),
        ),
    )
    prompt = build_veritas_user_prompt(request)
    assert "=== Prior clarifications (this goal) ===" in prompt
    assert "Q: which package?" in prompt
    assert "A: soothe" in prompt


def test_user_prompt_omits_prior_clarifications_when_empty() -> None:
    """No prior_clarifications section when the tuple is empty."""
    request = ClarificationRequest(
        questions=("which database?",),
        origin_node="execute",
        origin_interrupt_id="i",
        loop_state=LoopStateView(
            goal_id="g",
            goal_description="build a feature",
            user_request="build a feature",
            iteration=1,
            intent_classification=None,
            plan_summary=None,
            recent_step_outputs=(),
            workspace_summary=None,
            active_skills=(),
            active_mcp_servers=(),
        ),
    )
    prompt = build_veritas_user_prompt(request)
    assert "=== Prior clarifications" not in prompt
