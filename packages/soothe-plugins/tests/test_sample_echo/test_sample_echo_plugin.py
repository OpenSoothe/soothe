"""Tests for the sample_echo community subagent (no Soothe daemon)."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

pytest.importorskip("soothe_plugins.sample_echo", reason="soothe-plugins not installed")


def test_manifest_and_spec() -> None:
    from soothe_plugins.sample_echo import SampleEchoPlugin, create_echo_subagent_spec

    plugin = SampleEchoPlugin()
    assert plugin.manifest.name == "sample_echo"
    spec = create_echo_subagent_spec()
    assert spec["name"] == "sample_echo"
    assert "runnable" in spec


@pytest.mark.asyncio
async def test_echo_graph() -> None:
    from soothe_plugins.sample_echo import create_echo_subagent_spec

    spec = create_echo_subagent_spec()
    runnable = spec["runnable"]
    out = await runnable.ainvoke({"messages": [HumanMessage(content="hello-community")]})
    last = out["messages"][-1]
    assert "hello-community" in last.content
    assert "sample_echo" in last.content
