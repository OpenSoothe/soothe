"""Integration: soothe-plugins ``sample_echo`` subagent via resolver and CoreAgent."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from soothe.config import SootheConfig
from soothe.config.models import SubagentConfig, ToolsConfig
from soothe.foundation.core.agent import create_soothe_agent
from soothe.plugin.global_registry import load_plugins
from soothe.runner.resolver import resolve_subagents

pytest.importorskip("soothe_plugins.sample_echo", reason="soothe-plugins not installed")


@pytest.fixture(autouse=True)
def _reset_plugin_registry_between_tests() -> None:
    """Avoid cross-test pollution from the global plugin singleton."""
    import asyncio

    from soothe.plugin.global_registry import is_plugins_loaded, shutdown_plugins

    async def _shutdown() -> None:
        if is_plugins_loaded():
            await shutdown_plugins()

    def _run_shutdown() -> None:
        try:
            asyncio.run(_shutdown())
        except asyncio.CancelledError:
            pass

    _run_shutdown()
    yield
    _run_shutdown()


def _minimal_config_sample_echo_only() -> SootheConfig:
    """Disable built-in subagents and heavy tools; enable only ``sample_echo``."""
    cfg = SootheConfig()
    cfg.tools = ToolsConfig(
        execution={"enabled": False},
        file_ops={"enabled": False},
        wizsearch={"enabled": False},
        datetime={"enabled": False},
        data={"enabled": False},
        http_requests={"enabled": False},
    )
    for key in list(cfg.subagents.keys()):
        entry = cfg.subagents[key]
        cfg.subagents[key] = SubagentConfig(
            enabled=False,
            model=entry.model,
            transport=entry.transport,
            url=entry.url,
            config=dict(entry.config),
            runtime_dir=entry.runtime_dir,
        )
    cfg.subagents["sample_echo"] = SubagentConfig(enabled=True)
    # Disable memory protocol to avoid embedding resolution (no credentials for default OpenAI)
    cfg.agent.protocols.memory.enabled = False
    return cfg


def _subagent_names(specs: list) -> list[str]:
    out: list[str] = []
    for s in specs:
        if isinstance(s, dict):
            n = s.get("name")
        else:
            n = getattr(s, "name", None)
        if isinstance(n, str):
            out.append(n)
    return out


def test_resolve_sample_echo_after_plugin_load() -> None:
    cfg = _minimal_config_sample_echo_only()
    asyncio.run(load_plugins(cfg))
    fake = FakeListChatModel(responses=["stub"])
    specs = resolve_subagents(cfg, default_model=fake, lazy=False)
    assert "sample_echo" in _subagent_names(specs)


def test_create_soothe_agent_includes_sample_echo() -> None:
    cfg = _minimal_config_sample_echo_only()
    fake = FakeListChatModel(responses=["stub"])
    agent = create_soothe_agent(cfg, model=fake)
    names = _subagent_names(list(agent.subagents))
    assert "sample_echo" in names


@pytest.mark.asyncio
async def test_sample_echo_runnable_invocation() -> None:
    cfg = _minimal_config_sample_echo_only()
    await load_plugins(cfg)
    fake = FakeListChatModel(responses=["stub"])
    specs = resolve_subagents(cfg, default_model=fake, lazy=False)
    spec = next(
        s for s in specs if (s.get("name") if isinstance(s, dict) else None) == "sample_echo"
    )
    runnable = spec["runnable"]
    out = await runnable.ainvoke({"messages": [HumanMessage(content="framework-check")]})
    body = out["messages"][-1].content
    assert "framework-check" in body
    assert "sample_echo" in body
