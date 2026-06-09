"""Ablation harness for plan-assess stability (trace 19c3ed3 follow-up).

Background: in the trace `19c3ed340552149f2aa95616cf375226`, plan-assess #2 read
the full ledger left behind by plan-assess #1 + plan-generate #1 + 2 execute
steps, yet emitted assessment_reasoning that echoed the iter=0 text. This
module reproduces the same 8-turn ledger shape the model actually saw and
measures how candidate ablations change the prompt:

- char/approx-token count of the prompt
- cache-prefix stability across iterations (sha256 of the system message)
- presence of the iter=0 `assessment_reasoning` text (anchor signal)
- number of duplicated `<USER_QUERY>` blocks

These are *structural* signals — they don't run an LLM. A real LLM-based pass
can be wired in later by feeding the rendered messages of each condition into
`StatusAssessment` with structured output; the harness exposes the rendered
messages directly so that is a one-liner.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

import soothe.foundation.loop.state.schemas  # noqa: F401 — break circular import at import time
from soothe.foundation.loop.state.schemas import (
    LoopState,
    PriorProgressDigest,
    ToolCallHead,
)
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.foundation.loop.prompts import PromptBuilder
from soothe.protocols.planner import PlanContext

# ---------------------------------------------------------------------------
# Fixture: realistic 2nd plan-assess input
# ---------------------------------------------------------------------------

GOAL = "count only valid source code of @packages, count production and tests code respectively"
THREAD_ID = "019e87d8-d490-7a70-94d9-3d14d8763d02"

# Iter=0 plan-assess wrote this reasoning text. The bug is that the model echoes it.
ITER0_ASSESSMENT_REASONING = (
    "Initial assessment: no prior evidence; need to enumerate packages "
    "and disambiguate src/ from tests/ before any counting."
)
ITER0_ASSESSMENT_DUMP = (
    "{'status': 'replan', 'goal_progress': 'none', "
    f"'assessment_reasoning': {ITER0_ASSESSMENT_REASONING!r}, "
    "'require_goal_completion': False}"
)

ITER0_PLAN_GENERATE_DUMP = (
    "{'plan_action': 'new', 'type': 'execute_steps', "
    "'steps': [{'id': '01', 'description': 'List packages and identify src/ vs tests/'}, "
    "{'id': '02', 'description': 'Run wc on src/ and tests/ per package'}], "
    "'execution_mode': 'parallel', "
    "'reasoning': 'Two parallel exploration steps before consolidation.'}"
)

EXECUTE_STEP_AI_TEXTS = [
    # Step 01 AI content (final + <LAST_TOOL_RESULT>)
    (
        "I enumerated packages/{soothe,soothe-cli,soothe-daemon,soothe-sdk}/src and tests/.\n"
        "<LAST_TOOL_RESULT>\n"
        "find packages/*/src -name '*.py' | wc -l → 1247 files\n"
        "find packages/*/tests -name '*.py' | wc -l → 612 files\n"
        "</LAST_TOOL_RESULT>"
    ),
    # Step 02 AI content
    (
        "Per-package line counts collected via wc -l. Production totals dominate; "
        "tests are ~30% of production.\n"
        "<LAST_TOOL_RESULT>\n"
        "soothe/src: 90870  soothe/tests: 47738\n"
        "soothe-cli/src: 37303  soothe-cli/tests: 6798\n"
        "soothe-daemon/src: 32499  soothe-daemon/tests: 16176\n"
        "soothe-sdk/src: 6474  soothe-sdk/tests: 3456\n"
        "</LAST_TOOL_RESULT>"
    ),
]


def _plan_context_human(content: str, *, iteration: int, phase: str) -> LoopHumanMessage:
    return LoopHumanMessage(
        content=content,
        thread_id=THREAD_ID,
        iteration=iteration,
        goal_summary=GOAL[:200],
        phase=phase,
    )


def _build_baseline_ledger() -> list[LoopHumanMessage | LoopAIMessage]:
    """The 8-turn ledger that plan-assess #2 sees (RFC-214 projection)."""
    # iter=0 plan-assess turn (envelope text is built by PromptBuilder in production;
    # here we use a representative envelope-shaped string so the anchor test is realistic).
    iter0_plan_assess_human = _plan_context_human(
        f"<USER_QUERY>\n{GOAL}\n</USER_QUERY>\n"
        "<CONTEXT_INFO>\n<timestamp>2026-06-02T10:19:55Z</timestamp>\n<date>2026-06-02</date>\n</CONTEXT_INFO>",
        iteration=0,
        phase="plan_assess",
    )
    iter0_plan_assess_ai = LoopAIMessage(
        content=ITER0_ASSESSMENT_DUMP,
        thread_id=THREAD_ID,
        iteration=0,
        phase="plan_assess",
    )
    iter0_plan_generate_human = _plan_context_human(
        f"<USER_QUERY>\n{GOAL}\n</USER_QUERY>\n"
        "<CONTEXT_INFO>\n<timestamp>2026-06-02T10:19:58Z</timestamp>\n<date>2026-06-02</date>\n</CONTEXT_INFO>",
        iteration=0,
        phase="plan_generate",
    )
    iter0_plan_generate_ai = LoopAIMessage(
        content=ITER0_PLAN_GENERATE_DUMP,
        thread_id=THREAD_ID,
        iteration=0,
        phase="plan_generate",
    )

    step_pairs: list[LoopHumanMessage | LoopAIMessage] = []
    for i, ai_text in enumerate(EXECUTE_STEP_AI_TEXTS, start=1):
        sid = f"{i:02d}"
        step_pairs.append(
            LoopHumanMessage(
                content=f"Execute: {'List packages …' if i == 1 else 'Run wc on src/ and tests/ …'}",
                thread_id=THREAD_ID,
                iteration=0,
                goal_summary=GOAL[:200],
                phase="execute_step",
                step_id=sid,
            )
        )
        step_pairs.append(
            LoopAIMessage(
                content=ai_text,
                thread_id=THREAD_ID,
                iteration=0,
                phase="execute_step",
                step_id=sid,
            )
        )

    return [
        iter0_plan_assess_human,
        iter0_plan_assess_ai,
        iter0_plan_generate_human,
        iter0_plan_generate_ai,
        *step_pairs,
    ]


def _build_prior_progress() -> PriorProgressDigest:
    return PriorProgressDigest(
        iteration=0,
        wave_index=0,
        steps_completed=2,
        steps_failed=0,
        tool_calls=[
            ToolCallHead(name="run_command", head="find packages/*/src -name '*.py' | wc -l"),
            ToolCallHead(name="run_command", head="find packages/*/tests -name '*.py' | wc -l"),
            ToolCallHead(name="run_command", head="wc -l packages/*/src/**/*.py"),
        ],
        evidence_excerpts=[
            "packages enumerated; need to disambiguate src vs tests",
            "raw counts collected; need de-dup of generated files",
        ],
        derived_progress_hint="medium",
    )


def _build_state(
    ledger: list[LoopHumanMessage | LoopAIMessage] | None = None,
    *,
    iteration: int = 1,
    include_prior_progress: bool = True,
) -> LoopState:
    state = LoopState(
        goal=GOAL,
        thread_id=THREAD_ID,
        iteration=iteration,
        prior_progress=_build_prior_progress() if include_prior_progress else None,
    )
    state.loop_messages = list(ledger) if ledger is not None else _build_baseline_ledger()
    return state


# ---------------------------------------------------------------------------
# Ablation transforms (pure functions over the ledger)
# ---------------------------------------------------------------------------

Ledger = list[LoopHumanMessage | LoopAIMessage]


def ablation_baseline(ledger: Ledger) -> Ledger:
    return list(ledger)


def ablation_a1_drop_plan_assess_turns(ledger: Ledger) -> Ledger:
    return [m for m in ledger if getattr(m, "phase", None) != "plan_assess"]


def ablation_a2_compress_plan_assess_ai(ledger: Ledger) -> Ledger:
    """Strip `assessment_reasoning` from the prior plan-assess AI dump."""
    out: Ledger = []
    for m in ledger:
        if isinstance(m, LoopAIMessage) and m.phase == "plan_assess":
            out.append(
                m.model_copy(update={"content": "{'status': 'replan', 'goal_progress': 'none'}"})
            )
        else:
            out.append(m)
    return out


def ablation_b1_drop_all_planning_turns(ledger: Ledger) -> Ledger:
    return [m for m in ledger if getattr(m, "phase", None) not in {"plan_assess", "plan_generate"}]


def ablation_b2_keep_only_prior_progress(ledger: Ledger) -> Ledger:
    """Drop *all* ledger — model relies on PRIOR_PROGRESS digest alone."""
    return []


def ablation_c1_strip_volatile_context_from_recorded(ledger: Ledger) -> Ledger:
    """Remove `<CONTEXT_INFO>` blocks from recorded planning humans.

    Models the cache-friendly version that doesn't burn the prefix on every turn.
    """
    out: Ledger = []
    for m in ledger:
        if (
            isinstance(m, LoopHumanMessage)
            and m.phase in {"plan_assess", "plan_generate"}
            and isinstance(m.content, str)
            and "<CONTEXT_INFO>" in m.content
        ):
            head, _, rest = m.content.partition("<CONTEXT_INFO>")
            _, _, tail = rest.partition("</CONTEXT_INFO>")
            cleaned = (head + tail).strip()
            out.append(m.model_copy(update={"content": cleaned}))
        else:
            out.append(m)
    return out


def ablation_d1_collapse_user_query_in_recorded(ledger: Ledger) -> Ledger:
    """Replace `<USER_QUERY>...</USER_QUERY>` in recorded planning humans with a recap tag.

    Eliminates the duplicated-goal anchoring (the recap appears in past turns;
    the current turn still carries `<USER_QUERY>`).
    """
    out: Ledger = []
    for m in ledger:
        if (
            isinstance(m, LoopHumanMessage)
            and m.phase in {"plan_assess", "plan_generate"}
            and isinstance(m.content, str)
            and "<USER_QUERY>" in m.content
        ):
            replaced = m.content.replace("<USER_QUERY>", "<GOAL_RECAP>").replace(
                "</USER_QUERY>", "</GOAL_RECAP>"
            )
            out.append(m.model_copy(update={"content": replaced}))
        else:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptMetrics:
    name: str
    total_chars: int
    approx_tokens: int  # chars/4 (rough English-mix heuristic)
    system_sha: str
    anchor_present: bool
    duplicated_user_query_count: int
    message_count: int


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _measure(name: str, msgs: list) -> PromptMetrics:
    system_content = msgs[0].content if msgs else ""
    all_content = "\n".join(getattr(m, "content", "") for m in msgs)
    # `<USER_QUERY>` appears in PLAN_ASSESS_INSTRUCTIONS as documentation; only count
    # occurrences *outside* the system message so the metric reflects ledger pollution.
    ledger_content = "\n".join(getattr(m, "content", "") for m in msgs[1:])
    return PromptMetrics(
        name=name,
        total_chars=len(all_content),
        approx_tokens=_approx_tokens(all_content),
        system_sha=hashlib.sha256(system_content.encode("utf-8")).hexdigest()[:12],
        anchor_present=ITER0_ASSESSMENT_REASONING in all_content,
        duplicated_user_query_count=ledger_content.count("<USER_QUERY>"),
        message_count=len(msgs),
    )


def _render(state: LoopState) -> list:
    return PromptBuilder().build_plan_messages(GOAL, state, PlanContext(), plan_phase="assess")


# ---------------------------------------------------------------------------
# Ablation table — runnable as a structured test that also prints a report
# ---------------------------------------------------------------------------

CONDITIONS: list[tuple[str, Callable[[Ledger], Ledger]]] = [
    ("baseline", ablation_baseline),
    ("A1_drop_plan_assess", ablation_a1_drop_plan_assess_turns),
    ("A2_compress_plan_assess_ai", ablation_a2_compress_plan_assess_ai),
    ("B1_drop_all_planning", ablation_b1_drop_all_planning_turns),
    ("B2_only_prior_progress", ablation_b2_keep_only_prior_progress),
    ("C1_strip_volatile_context", ablation_c1_strip_volatile_context_from_recorded),
    ("D1_collapse_user_query", ablation_d1_collapse_user_query_in_recorded),
]


def _run_all_conditions() -> dict[str, PromptMetrics]:
    baseline_ledger = _build_baseline_ledger()
    results: dict[str, PromptMetrics] = {}
    for name, transform in CONDITIONS:
        mutated = transform(baseline_ledger)
        state = _build_state(mutated, iteration=1)
        msgs = _render(state)
        results[name] = _measure(name, msgs)
    return results


# ---------------------------------------------------------------------------
# Structural assertions: each ablation must move the metrics it claims to move
# ---------------------------------------------------------------------------


def test_baseline_carries_anchor_and_duplicated_goal() -> None:
    """The bug shape: prior assessment_reasoning text and duplicated <USER_QUERY> are both present."""
    results = _run_all_conditions()
    base = results["baseline"]
    assert base.anchor_present, "baseline must contain the iter=0 assessment_reasoning text"
    # 2 recorded planning humans + 1 current plan-context human = 3 occurrences.
    assert base.duplicated_user_query_count >= 3, (
        f"baseline should show duplicated <USER_QUERY>; got {base.duplicated_user_query_count}"
    )


def test_a1_removes_anchor_and_drops_planning_pair() -> None:
    results = _run_all_conditions()
    a1 = results["A1_drop_plan_assess"]
    base = results["baseline"]
    assert not a1.anchor_present, "A1 must remove the iter=0 assessment_reasoning text"
    assert a1.message_count == base.message_count - 2
    # plan_generate still uses <USER_QUERY>, plus current turn = 2 occurrences.
    assert a1.duplicated_user_query_count == 2


def test_a2_removes_anchor_keeps_pair() -> None:
    """A2 only compresses the AI dump — fewer-token mitigation; planning pair stays."""
    results = _run_all_conditions()
    a2 = results["A2_compress_plan_assess_ai"]
    base = results["baseline"]
    assert not a2.anchor_present
    assert a2.message_count == base.message_count
    assert a2.total_chars < base.total_chars


def test_b1_drops_all_planning_turns() -> None:
    results = _run_all_conditions()
    b1 = results["B1_drop_all_planning"]
    base = results["baseline"]
    assert not b1.anchor_present
    # Drop 4 (2 plan_assess + 2 plan_generate).
    assert b1.message_count == base.message_count - 4
    # Only the current plan-context human carries <USER_QUERY>.
    assert b1.duplicated_user_query_count == 1


def test_b2_minimal_ledger_just_digest() -> None:
    results = _run_all_conditions()
    b2 = results["B2_only_prior_progress"]
    base = results["baseline"]
    # 1 system + 1 plan-context human (no ledger turns).
    assert b2.message_count == 2
    assert b2.total_chars < base.total_chars
    assert not b2.anchor_present
    assert b2.duplicated_user_query_count == 1


def test_c1_makes_recorded_humans_cache_stable() -> None:
    """Recorded planning humans must lose their volatile <CONTEXT_INFO>."""
    baseline_ledger = _build_baseline_ledger()
    c1_ledger = ablation_c1_strip_volatile_context_from_recorded(baseline_ledger)
    base_recorded_humans = [
        m
        for m in baseline_ledger
        if isinstance(m, LoopHumanMessage) and m.phase in {"plan_assess", "plan_generate"}
    ]
    c1_recorded_humans = [
        m
        for m in c1_ledger
        if isinstance(m, LoopHumanMessage) and m.phase in {"plan_assess", "plan_generate"}
    ]
    assert all("<CONTEXT_INFO>" in m.content for m in base_recorded_humans)
    assert all("<CONTEXT_INFO>" not in m.content for m in c1_recorded_humans)
    # Anchor still present (C1 targets cache, not anchor).
    assert ITER0_ASSESSMENT_REASONING in "\n".join(m.content for m in c1_ledger)


def test_d1_dedupes_user_query() -> None:
    results = _run_all_conditions()
    d1 = results["D1_collapse_user_query"]
    # Only the current plan-context human still carries <USER_QUERY>.
    assert d1.duplicated_user_query_count == 1
    # Anchor still present (D1 targets recency anchor, not the prior-reasoning anchor).
    assert d1.anchor_present


def test_system_sha_is_identical_across_ablations() -> None:
    """All conditions share the same system prompt (changes are ledger-only).

    Confirms cache_read should be high if the system block is reused across calls.
    Mirrors the trace observation that plan-assess #3 hit cache (1536) but #2 did not.
    """
    results = _run_all_conditions()
    shas = {r.system_sha for r in results.values()}
    assert len(shas) == 1, f"system message must be identical across conditions; got {shas}"


def test_ablation_report_summary(capsys) -> None:
    """Print a comparison table for the engineer reading the run output."""
    results = _run_all_conditions()
    base = results["baseline"]
    lines = [
        "",
        f"{'condition':<30} {'msgs':>4} {'chars':>6} {'~tok':>5} "
        f"{'anchor':>6} {'<UQ>':>4}  delta_chars",
        "-" * 80,
    ]
    for name, _ in CONDITIONS:
        r = results[name]
        delta = r.total_chars - base.total_chars
        delta_str = f"{delta:+d}" if name != "baseline" else "—"
        lines.append(
            f"{r.name:<30} {r.message_count:>4} {r.total_chars:>6} "
            f"{r.approx_tokens:>5} {str(r.anchor_present):>6} "
            f"{r.duplicated_user_query_count:>4}  {delta_str}"
        )
    print("\n".join(lines))
    captured = capsys.readouterr()
    assert "baseline" in captured.out
