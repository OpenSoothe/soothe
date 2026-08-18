"""Tests for ConcurrencyPolicy."""

from soothe_sdk.protocols.concurrency import ConcurrencyPolicy


def test_defaults() -> None:
    policy = ConcurrencyPolicy()
    assert policy.max_parallel_steps == 2
    assert policy.max_parallel_subagents == 4
    assert policy.global_max_llm_calls == 5
    assert policy.step_parallelism == "dependency"
    assert not hasattr(policy, "max_parallel_goals")


def test_ignores_legacy_max_parallel_goals() -> None:
    policy = ConcurrencyPolicy.model_validate(
        {
            "max_parallel_goals": 9,
            "max_parallel_steps": 3,
            "step_parallelism": "sequential",
        }
    )
    assert not hasattr(policy, "max_parallel_goals")
    assert policy.max_parallel_steps == 3
    assert policy.step_parallelism == "sequential"
