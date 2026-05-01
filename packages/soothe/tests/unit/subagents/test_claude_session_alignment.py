"""Tests for Soothe thread ↔ Claude SDK session alignment (IG-202)."""

from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.protocols.durability import ThreadInfo, ThreadMetadata
from soothe.subagents.claude.session_bridge import (
    record_claude_session,
    resolve_resume_session_id,
)


@pytest.fixture(autouse=True)
def _clear_session_bridge_memory() -> None:
    """Isolate tests that touch the in-process Claude session cache."""
    import soothe.subagents.claude.session_bridge as bridge

    bridge._memory_claude_sessions.clear()
    bridge._locks.clear()
    yield
    bridge._memory_claude_sessions.clear()
    bridge._locks.clear()


@pytest.mark.asyncio
async def test_resolve_prefers_memory_over_config() -> None:
    """After record, memory wins over configurable snapshot."""
    await record_claude_session(
        thread_id="t1",
        cwd="/tmp/ws",
        session_id="mem-uuid",
        durability=None,
    )
    out = await resolve_resume_session_id(
        thread_id="t1",
        cwd="/tmp/ws",
        claude_sessions_from_config={"/tmp/ws": "cfg-uuid"},
    )
    assert out == "mem-uuid"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_config() -> None:
    """Configurable claude_sessions used when memory empty."""
    out = await resolve_resume_session_id(
        thread_id="t1",
        cwd="/proj/a",
        claude_sessions_from_config={"/proj/a": "from-meta"},
    )
    assert out == "from-meta"


@pytest.mark.asyncio
async def test_record_updates_durability() -> None:
    """Persist merges cwd keys into ThreadMetadata.claude_sessions."""
    now = datetime.now(tz=UTC)
    d = MagicMock()
    d.get_thread = AsyncMock(
        return_value=ThreadInfo(
            thread_id="tid",
            status="active",
            created_at=now,
            updated_at=now,
            metadata=ThreadMetadata(claude_sessions={"/other": "u0"}),
        )
    )
    d.update_thread_metadata = AsyncMock()
    await record_claude_session(
        thread_id="tid",
        cwd="/proj",
        session_id="new-sid",
        durability=d,
    )
    d.update_thread_metadata.assert_called_once()
    call_args = d.update_thread_metadata.call_args[0]
    assert call_args[0] == "tid"
    merged = call_args[1]
    assert merged.claude_sessions["/proj"] == "new-sid"
    assert merged.claude_sessions["/other"] == "u0"


@pytest.mark.asyncio
async def test_run_claude_sets_resume_and_records_session() -> None:
    """_run_claude_async passes resume and persists session id from ResultMessage."""
    last_options: list[object] = []

    def _install_fake_claude_sdk() -> None:
        m = types.ModuleType("claude_agent_sdk")

        class AssistantMessage:
            pass

        class TextBlock:
            pass

        class ToolUseBlock:
            pass

        class ClaudeAgentOptions:
            def __init__(
                self,
                *,
                permission_mode: str = "bypassPermissions",
                max_turns: int = 25,
            ) -> None:
                self.permission_mode = permission_mode
                self.max_turns = max_turns
                self.model = None
                self.system_prompt = None
                self.allowed_tools = None
                self.disallowed_tools = None
                self.cwd = None
                self.resume = None

        class ResultMessage:
            def __init__(self) -> None:
                self.total_cost_usd = 0.0
                self.duration_ms = 1
                self.session_id = "sess-from-sdk"

        async def query(*, prompt: str, options: object) -> object:
            last_options.append(options)
            yield ResultMessage()

        m.AssistantMessage = AssistantMessage
        m.TextBlock = TextBlock
        m.ToolUseBlock = ToolUseBlock
        m.ClaudeAgentOptions = ClaudeAgentOptions
        m.ResultMessage = ResultMessage
        m.query = query
        sys.modules["claude_agent_sdk"] = m

    _install_fake_claude_sdk()
    try:
        with (
            patch(
                "soothe.subagents.claude.implementation._resolve_claude_cwd",
                return_value="/ws",
            ),
            patch(
                "soothe.subagents.claude.implementation._get_soothe_thread_id",
                return_value="thr1",
            ),
            patch(
                "soothe.subagents.claude.implementation._get_claude_sessions_from_config",
                return_value={"/ws": "pre-resume"},
            ),
            patch(
                "soothe.subagents.claude.implementation._get_soothe_durability",
                return_value=None,
            ),
            patch("soothe.utils.progress.emit_progress", lambda *a, **k: None),
        ):
            from langchain_core.messages import HumanMessage

            from soothe.subagents.claude.implementation import _build_claude_graph

            g = _build_claude_graph(cwd="/fallback")
            await g.ainvoke({"messages": [HumanMessage(content="hi")]})
    finally:
        sys.modules.pop("claude_agent_sdk", None)

    assert last_options
    assert getattr(last_options[0], "resume", None) == "pre-resume"

    import soothe.subagents.claude.session_bridge as bridge

    assert bridge._memory_claude_sessions[("thr1", "/ws")] == "sess-from-sdk"
