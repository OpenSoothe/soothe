"""Unit tests for builtin MCP server catalog."""

import pytest

from soothe_nano.config import SootheConfig
from soothe_nano.mcp.mcp_config import (
    builtin_mcp_server_names,
    get_builtin_mcp_server,
    get_builtin_mcp_servers,
    resolve_mcp_builtins,
)


def test_builtin_catalog_includes_daily_use_servers() -> None:
    names = builtin_mcp_server_names()
    assert {"playwright", "github", "slack", "postgres", "gdrive"}.issubset(names)


def test_all_builtins_are_deferred() -> None:
    for server in get_builtin_mcp_servers():
        assert server.defer is True


def test_resolve_mcp_builtins_returns_copies() -> None:
    resolved = resolve_mcp_builtins(["github", "playwright"])
    assert len(resolved) == 2
    assert {s.name for s in resolved} == {"github", "playwright"}
    assert resolved[0] is not get_builtin_mcp_server("github")


def test_resolve_unknown_builtin_raises() -> None:
    with pytest.raises(ValueError, match="Unknown mcp_builtins"):
        resolve_mcp_builtins(["not-a-server"])


def test_mcp_builtins_merges_into_soothe_config() -> None:
    cfg = SootheConfig(mcp_builtins=["slack", "postgres"])
    assert len(cfg.mcp_servers) == 2
    assert {s.name for s in cfg.mcp_servers} == {"slack", "postgres"}
    assert all(s.defer for s in cfg.mcp_servers)


def test_mcp_builtins_empty_does_not_connect_servers() -> None:
    cfg = SootheConfig()
    assert cfg.mcp_builtins == []
    assert cfg.mcp_servers == []


def test_mcp_builtins_skips_duplicate_explicit_server() -> None:
    from soothe_nano.config.models import MCPServerConfig

    explicit = MCPServerConfig(name="github", command="echo", args=[])
    cfg = SootheConfig(mcp_servers=[explicit], mcp_builtins=["github", "playwright"])
    assert len(cfg.mcp_servers) == 2
    assert cfg.mcp_servers[0].command == "echo"
