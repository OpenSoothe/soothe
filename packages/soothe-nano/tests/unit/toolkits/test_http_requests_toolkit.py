"""Tests for LangChain Requests toolkit integration (IG-339)."""

from __future__ import annotations

from types import SimpleNamespace

from soothe_nano.toolkits.http_requests import HttpRequestsToolkit


def _make_namespace(
    *, enabled: bool, dangerous: bool, headers: dict | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        tools=SimpleNamespace(
            http_requests=SimpleNamespace(
                enabled=enabled,
                allow_dangerous_requests=dangerous,
                headers=headers or {},
                verify_ssl=True,
            )
        )
    )


class TestHttpRequestsToolkitGating:
    """Verify toolkit respects config gates."""

    def test_no_config_returns_empty(self) -> None:
        toolkit = HttpRequestsToolkit(config=None)
        assert toolkit.get_tools() == []

    def test_disabled_returns_empty(self) -> None:
        toolkit = HttpRequestsToolkit(config=_make_namespace(enabled=False, dangerous=True))
        assert toolkit.get_tools() == []

    def test_allow_dangerous_false_returns_empty(self) -> None:
        toolkit = HttpRequestsToolkit(config=_make_namespace(enabled=True, dangerous=False))
        assert toolkit.get_tools() == []

    def test_enabled_and_opt_in_returns_five_tools(self) -> None:
        toolkit = HttpRequestsToolkit(config=_make_namespace(enabled=True, dangerous=True))
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        assert names == {
            "requests_delete",
            "requests_get",
            "requests_patch",
            "requests_post",
            "requests_put",
        }
