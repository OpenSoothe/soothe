"""Tests for daemon MessageRouter skill RPCs."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from soothe.config import SootheConfig
from soothe.daemon.message_router import MessageRouter


@pytest.mark.asyncio
async def test_skills_list_response_shape(tmp_path: Any) -> None:
    skill_dir = tmp_path / "router_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: router_skill\ndescription: From router test\n---\n# B\n",
        encoding="utf-8",
    )
    cfg = SootheConfig()
    cfg.skills = [str(skill_dir)]

    sent: list[tuple[Any, dict[str, Any]]] = []
    q: asyncio.Queue = asyncio.Queue()

    class _FakeDaemon:
        _config = cfg
        _query_running = False
        _active_threads: set[Any] = set()
        _runner = SimpleNamespace(current_thread_id="t-router")
        _current_input_queue = q

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            sent.append((client_id, msg))

    router = MessageRouter(_FakeDaemon())
    await router.dispatch("client-a", {"type": "skills_list", "request_id": "rid-skills"})

    assert sent
    payload = sent[-1][1]
    assert payload["type"] == "skills_list_response"
    assert payload["request_id"] == "rid-skills"
    skills = payload.get("skills", [])
    assert isinstance(skills, list)
    match = next(
        (s for s in skills if isinstance(s, dict) and s.get("name") == "router_skill"), None
    )
    assert match is not None
    assert match.get("description")
    assert "path" not in match


@pytest.mark.asyncio
async def test_invoke_skill_response_then_queued_input(tmp_path: Any) -> None:
    skill_dir = tmp_path / "invoke_rpc"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: invoke_rpc\ndescription: Invoke me\n---\n## Instructions\nRun.\n",
        encoding="utf-8",
    )
    cfg = SootheConfig()
    cfg.skills = [str(skill_dir)]

    sent: list[tuple[Any, dict[str, Any]]] = []
    q: asyncio.Queue = asyncio.Queue()

    class _FakeDaemon:
        _config = cfg
        _query_running = False
        _active_threads: set[Any] = set()
        _runner = SimpleNamespace(current_thread_id="t-inv")
        _current_input_queue = q

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            sent.append((client_id, msg))

    router = MessageRouter(_FakeDaemon())
    await router.dispatch(
        "client-b",
        {"type": "invoke_skill", "skill": "invoke_rpc", "args": "go", "request_id": "rid-inv"},
    )

    types_in_order = [m[1].get("type") for m in sent]
    assert "invoke_skill_response" in types_in_order
    resp = next(m[1] for m in sent if m[1].get("type") == "invoke_skill_response")
    assert resp.get("request_id") == "rid-inv"
    echo = resp.get("echo")
    assert isinstance(echo, dict)
    assert echo.get("skill_name") == "invoke_rpc"
    assert echo.get("args") == "go"

    queued = await asyncio.wait_for(q.get(), timeout=2.0)
    assert queued["type"] == "input"
    assert "invoke_rpc" in queued["text"]
