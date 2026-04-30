"""Regression: explore subagent must receive SootheConfig and context from resolver."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig, SubagentConfig
from soothe.core.resolver._resolver_tools import resolve_subagents


def test_resolve_subagents_passes_config_and_context_to_explore() -> None:
    """YAML explore options must not be spread as factory kwargs (IG-style regression)."""
    cfg = SootheConfig()
    for name in cfg.subagents:
        cfg.subagents[name] = SubagentConfig(enabled=(name == "explore"))
    cfg.subagents["explore"] = SubagentConfig(
        enabled=True,
        config={
            "thoroughness": "quick",
            "max_read_lines": 40,
        },
    )

    with patch(
        "soothe.subagents.explore.implementation.build_explore_engine",
        return_value=MagicMock(),
    ):
        specs = resolve_subagents(cfg, lazy=False)

    assert len(specs) == 1
    spec = specs[0]
    name = spec.get("name") if isinstance(spec, dict) else getattr(spec, "name", None)
    assert name == "explore"
