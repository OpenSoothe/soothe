"""Unit tests for IG-670 auto-resume eligibility classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from soothe_daemon.runtime.auto_resume import (
    AutoResumeDecision,
    checkpoint_supports_valid_resume,
    classify_incomplete_loop,
)


def _cp(*, status: str = "running", idx: int = 0, goals: int = 1) -> SimpleNamespace:
    history = [SimpleNamespace(goal_id=f"g{i}", status="running") for i in range(goals)]
    return SimpleNamespace(status=status, current_goal_index=idx, goal_history=history)


def test_checkpoint_supports_valid_resume() -> None:
    assert checkpoint_supports_valid_resume(_cp()) is True
    assert checkpoint_supports_valid_resume(_cp(status="idle")) is False
    assert checkpoint_supports_valid_resume(_cp(idx=-1)) is False
    assert checkpoint_supports_valid_resume(None) is False


def test_skip_autopilot_worker() -> None:
    result = classify_incomplete_loop(
        loop_id="autopilot__w0",
        updated_at_raw=datetime.now(UTC).isoformat(),
        checkpoint=_cp(),
        active_runner=False,
    )
    assert result.decision == AutoResumeDecision.SKIP
    assert result.reason == "autopilot_owned"


def test_skip_active_runner() -> None:
    result = classify_incomplete_loop(
        loop_id="019f-loop",
        updated_at_raw=datetime.now(UTC).isoformat(),
        checkpoint=_cp(),
        active_runner=True,
    )
    assert result.decision == AutoResumeDecision.SKIP
    assert result.reason == "active_runner"


def test_cancel_by_age_wins() -> None:
    now = datetime.now(UTC)
    old = (now - timedelta(hours=48)).isoformat()
    result = classify_incomplete_loop(
        loop_id="019f-old",
        updated_at_raw=old,
        checkpoint=_cp(),
        active_runner=False,
        auto_cancel=True,
        cancel_max_age_hours=24.0,
        resume_max_age_hours=72.0,
        now=now,
    )
    assert result.decision == AutoResumeDecision.CANCEL


def test_skip_resume_age_when_not_cancelled() -> None:
    now = datetime.now(UTC)
    mid = (now - timedelta(hours=30)).isoformat()
    result = classify_incomplete_loop(
        loop_id="019f-mid",
        updated_at_raw=mid,
        checkpoint=_cp(),
        active_runner=False,
        auto_cancel=False,
        resume_max_age_hours=24.0,
        now=now,
    )
    assert result.decision == AutoResumeDecision.SKIP
    assert "resume_age" in result.reason


def test_skip_non_resumable_checkpoint() -> None:
    result = classify_incomplete_loop(
        loop_id="019f-idle",
        updated_at_raw=datetime.now(UTC).isoformat(),
        checkpoint=_cp(status="idle"),
        active_runner=False,
    )
    assert result.decision == AutoResumeDecision.SKIP
    assert result.reason == "checkpoint_not_resumable"


def test_skip_clarification_when_policy_skip() -> None:
    result = classify_incomplete_loop(
        loop_id="019f-clar",
        updated_at_raw=datetime.now(UTC).isoformat(),
        checkpoint=_cp(),
        active_runner=False,
        clarification_pending=True,
        clarifications_policy="skip",
    )
    assert result.decision == AutoResumeDecision.SKIP
    assert result.reason == "clarification_pending"


def test_reannounce_clarification() -> None:
    result = classify_incomplete_loop(
        loop_id="019f-clar2",
        updated_at_raw=datetime.now(UTC).isoformat(),
        checkpoint=_cp(),
        active_runner=False,
        clarification_pending=True,
        clarifications_policy="reannounce",
        resume_topic="Finish the report",
    )
    assert result.decision == AutoResumeDecision.RESUME
    assert result.reason == "clarification_reannounce"
    assert result.resume_prompt == "Finish the report"


def test_eligible_uses_default_prompt() -> None:
    result = classify_incomplete_loop(
        loop_id="019f-ok",
        updated_at_raw=datetime.now(UTC).isoformat(),
        checkpoint=_cp(),
        active_runner=False,
    )
    assert result.decision == AutoResumeDecision.RESUME
    assert result.reason == "eligible"
    assert result.resume_prompt == "continue this loop"


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("Build the API", "Build the API"),
        ("  ", "continue this loop"),
        (None, "continue this loop"),
    ],
)
def test_resume_topic_prompt(topic: str | None, expected: str) -> None:
    result = classify_incomplete_loop(
        loop_id="019f-topic",
        updated_at_raw=datetime.now(UTC).isoformat(),
        checkpoint=_cp(),
        active_runner=False,
        resume_topic=topic,
    )
    assert result.decision == AutoResumeDecision.RESUME
    assert result.resume_prompt == expected


@pytest.mark.asyncio
async def test_recover_enqueues_when_auto_resume_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import contextlib
    from types import SimpleNamespace

    from soothe_daemon.runtime import auto_resume as mod

    now = datetime.now(UTC)
    loop_id = "019f-resume-me"
    enqueued: list[tuple[str, dict]] = []

    class _Dispatcher:
        async def enqueue(self, lid: str, payload: dict) -> None:
            enqueued.append((lid, payload))

    class _Persistence:
        async def list_loops(self, status_filter: str | None = None, **_kw: object):
            assert status_filter == "running"
            return [
                {
                    "loop_id": loop_id,
                    "updated_at": now.isoformat(),
                    "resume_topic": "Ship the feature",
                }
            ]

        async def heartbeat_loop(self, lid: str) -> None:
            assert lid == loop_id

        async def update_loop_metadata(self, *_a, **_k) -> None:
            raise AssertionError("should not cancel")

    daemon = SimpleNamespace(
        _config=SimpleNamespace(
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    checkpoint=SimpleNamespace(
                        auto_resume_on_start=True,
                        auto_resume_max_loops=4,
                        auto_resume_max_age_hours=24.0,
                        auto_resume_clarifications="skip",
                    )
                )
            )
        ),
        _daemon_config=SimpleNamespace(
            auto_cancel_on_startup=True,
            thread_max_age_hours=24,
            loop_status_reconciliation=SimpleNamespace(stale_running_seconds=180),
        ),
        _persistence_manager=_Persistence(),
        _loop_input_dispatcher=_Dispatcher(),
        _active_stream_loop_ids=set(),
        _loops_with_active_query=set(),
        _query_engine=None,
        _auto_resume_protected_loop_ids=set(),
    )

    async def _peek_cp(_daemon: object, lid: str):
        assert lid == loop_id
        return _cp()

    async def _peek_clar(_daemon: object, _lid: str) -> bool:
        return False

    monkeypatch.setattr(mod, "peek_strange_loop_checkpoint", _peek_cp)
    monkeypatch.setattr(mod, "peek_clarification_pending", _peek_clar)
    import soothe_daemon.bootstrap.logging as blog

    monkeypatch.setattr(blog, "set_loop_id", lambda *_a, **_k: None)

    results = await mod.recover_incomplete_loops(daemon)
    assert len(results) == 1
    assert results[0].decision == AutoResumeDecision.RESUME
    assert enqueued == [
        (
            loop_id,
            {
                "type": "input",
                "text": "Ship the feature",
                "client_id": None,
                "autonomous": False,
                "resume_interrupted": True,
            },
        )
    ]
    assert loop_id in daemon._auto_resume_protected_loop_ids
    task = getattr(daemon, "_auto_resume_release_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_recover_does_not_enqueue_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from soothe_daemon.runtime import auto_resume as mod

    now = datetime.now(UTC)
    enqueued: list[object] = []

    class _Dispatcher:
        async def enqueue(self, *_a, **_k) -> None:
            enqueued.append(True)

    class _Persistence:
        async def list_loops(self, status_filter: str | None = None, **_kw: object):
            return [
                {
                    "loop_id": "019f-manual",
                    "updated_at": now.isoformat(),
                    "resume_topic": "",
                }
            ]

    daemon = SimpleNamespace(
        _config=SimpleNamespace(
            agent=SimpleNamespace(
                loop=SimpleNamespace(
                    checkpoint=SimpleNamespace(
                        auto_resume_on_start=False,
                        auto_resume_max_loops=4,
                        auto_resume_max_age_hours=24.0,
                        auto_resume_clarifications="skip",
                    )
                )
            )
        ),
        _daemon_config=SimpleNamespace(
            auto_cancel_on_startup=False,
            thread_max_age_hours=24,
            loop_status_reconciliation=SimpleNamespace(stale_running_seconds=180),
        ),
        _persistence_manager=_Persistence(),
        _loop_input_dispatcher=_Dispatcher(),
        _active_stream_loop_ids=set(),
        _loops_with_active_query=set(),
        _query_engine=None,
        _auto_resume_protected_loop_ids=set(),
    )

    async def _peek_cp(_d: object, _lid: str):
        return _cp()

    async def _peek_clar(_d: object, _lid: str):
        return None

    monkeypatch.setattr(mod, "peek_strange_loop_checkpoint", _peek_cp)
    monkeypatch.setattr(mod, "peek_clarification_pending", _peek_clar)
    import soothe_daemon.bootstrap.logging as blog

    monkeypatch.setattr(blog, "set_loop_id", lambda *_a, **_k: None)

    results = await mod.recover_incomplete_loops(daemon)
    assert results[0].decision == AutoResumeDecision.RESUME
    assert enqueued == []
