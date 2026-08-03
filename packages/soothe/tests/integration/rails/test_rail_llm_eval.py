"""Real-LLM LoopRail guard evaluation (integration).

Uses ``LLMGuardEvaluator`` (structured LLM + structural short-circuit) with
in-memory CE and pseudo goal execution.

Run::

    uv run pytest packages/soothe/tests/integration/rails -q --run-integration
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from support.rail_harness import RailHarness, write_evaluation_report

from soothe.autopilot.rail import LLMGuardEvaluator, export_trace_evaluation
from soothe.autopilot.rail.guards import GuardContext
from soothe.config import SootheConfig
from soothe.context.models import GoalNode

EVAL_REPORT_PATH = Path(__file__).resolve().parent / "llm_evaluation_results.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _load_llm_config() -> SootheConfig:
    env_path = os.environ.get("SOOTHE_INTEGRATION_BASE_CONFIG", "").strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(Path.home() / ".soothe" / "config" / "nano.yml")
    candidates.append(_repo_root() / "config" / "develop" / "nano.yml")

    cfg: SootheConfig | None = None
    for path in candidates:
        if path.is_file():
            cfg = SootheConfig.from_yaml_file(str(path))
            break
    if cfg is None:
        cfg = SootheConfig()
    cfg.propagate_env()
    return cfg


@pytest.fixture
def llm_guard(requires_llm_api: None) -> LLMGuardEvaluator:
    cfg = _load_llm_config()
    try:
        model = cfg.create_chat_model("fast")
    except Exception:
        model = cfg.create_chat_model("default")
    return LLMGuardEvaluator(
        model=model,
        min_confidence=0.55,
        structural_short_circuit=True,
    )


@pytest.mark.integration
@pytest.mark.requires_llm_api
@pytest.mark.asyncio
async def test_llm_guard_direct_structured_call(llm_guard: LLMGuardEvaluator) -> None:
    """Prove the live model returns structured GuardResult (no short-circuit)."""
    llm_guard.structural_short_circuit = False
    ctx = GuardContext(
        job_id="job",
        event="goal_completed",
        goal_id="g1",
        condition_name="needs_review",
        condition_text=("An implementation goal just finished and the changes should be reviewed."),
        goal_summary="Implement OAuth login callback handler",
        sibling_statuses={"g1": "completed", "scout1": "completed"},
        tags_by_goal={"g1": ["implementation"], "scout1": ["exploration"]},
        retry_count=0,
        extras={
            "trigger_tags": ["implementation"],
            "structural": {
                "all_exploration_terminal": True,
                "implementation_goal_ids": ["g1"],
                "pending_or_active_count": 0,
            },
        },
    )
    result = await llm_guard.evaluate(ctx)
    assert llm_guard.llm_calls >= 1
    assert result.confidence >= 0.0
    assert isinstance(result.matched, bool)
    assert result.reasoning
    # Implementation completed → should need review
    assert result.matched is True, result


@pytest.mark.integration
@pytest.mark.requires_llm_api
@pytest.mark.asyncio
async def test_suite_exports_llm_evaluation_json(llm_guard: LLMGuardEvaluator) -> None:
    """feature-dev + spike multi-turn with LLM evaluator; write evaluation JSON."""
    reports: list[dict] = []

    h1 = RailHarness()
    await h1.submit(
        "Add OAuth login",
        rail_id="feature-dev",
        scout_count=2,
        guard_evaluator=llm_guard,
    )

    async def c1(goal: GoalNode, turn: int) -> None:
        await h1.pseudo_complete(goal.id)

    await h1.run_turns(c1, max_turns=40)
    exp1 = [
        "decompose_parallel",
        "plan_and_implement",
        "review",
        "qa_verify",
        "complete_job",
    ]
    r1 = export_trace_evaluation(h1.job_id or "", h1.trace, expected_builtins=exp1)
    r1["scenario"] = "feature-dev-llm"
    r1["mode"] = "real_llm_guards"
    r1["llm_calls"] = llm_guard.llm_calls
    r1["short_circuit_calls"] = llm_guard.short_circuit_calls
    r1["pipeline_ok"] = all(b in h1.successful_builtins() for b in exp1)
    r1["builtins_match_expected"] = bool(r1["pipeline_ok"])
    reports.append(r1)
    assert r1["pipeline_ok"], r1

    # Reset counters for spike leg
    llm_guard.llm_calls = 0
    llm_guard.short_circuit_calls = 0

    h2 = RailHarness()
    await h2.submit(
        "Spike architecture choice",
        rail_id="spike",
        scout_count=2,
        guard_evaluator=llm_guard,
    )

    async def c2(goal: GoalNode, turn: int) -> None:
        await h2.pseudo_complete(goal.id)

    await h2.run_turns(c2, max_turns=20)
    await h2.user_intervention()
    exp2 = ["decompose_parallel", "pause_for_user", "complete_job"]
    r2 = export_trace_evaluation(h2.job_id or "", h2.trace, expected_builtins=exp2)
    r2["scenario"] = "spike-llm"
    r2["mode"] = "real_llm_guards"
    r2["llm_calls"] = llm_guard.llm_calls
    r2["short_circuit_calls"] = llm_guard.short_circuit_calls
    r2["pipeline_ok"] = all(b in h2.successful_builtins() for b in exp2)
    r2["builtins_match_expected"] = bool(r2["pipeline_ok"])
    reports.append(r2)
    assert r2["pipeline_ok"], r2

    path = write_evaluation_report(EVAL_REPORT_PATH, reports)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["passed"] is True, data
    print(f"\nLLM LoopRail evaluation written to: {path}")
    for s in data["scenarios"]:
        print(
            f"  - {s['scenario']}: match={s['builtins_match_expected']} "
            f"fired={s['fired_builtins']} "
            f"llm_calls={s.get('llm_calls')} short={s.get('short_circuit_calls')}"
        )
