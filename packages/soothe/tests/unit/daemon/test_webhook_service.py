"""Tests for Autopilot webhook service (soothe.cognition.goal_engine.webhooks)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.cognition.goal_engine.webhooks import (
    AUTONOTIFY_EVENTS,
    WebhookConfig,
    WebhookService,
)


class TestWebhookConfig:
    """Tests for WebhookConfig dataclass."""

    def test_defaults(self) -> None:
        cfg = WebhookConfig(url="https://example.com/hook")
        assert cfg.url == "https://example.com/hook"
        assert cfg.events == AUTONOTIFY_EVENTS
        assert cfg.timeout == 10.0
        assert cfg.retries == 3

    def test_custom_settings(self) -> None:
        events = frozenset({"goal_completed"})
        cfg = WebhookConfig(url="https://example.com/hook", events=events, timeout=5.0, retries=1)
        assert cfg.events == events
        assert cfg.timeout == 5.0
        assert cfg.retries == 1


@pytest.mark.asyncio
class TestWebhookService:
    """Tests for WebhookService notification behavior."""

    async def test_noop_when_no_configs(self) -> None:
        service = WebhookService(webhooks={})
        await service.notify("goal_completed", {"goal_id": "abc"})
        # Should not raise

    async def test_sends_webhook_for_configured_event(self) -> None:
        cfg = WebhookConfig(url="https://example.com/hook", retries=1)
        service = WebhookService(webhooks={"goal_completed": [cfg]})

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        with patch("soothe.cognition.goal_engine.webhooks._get_http_session", return_value=mock_session):
            await service.notify("goal_completed", {"goal_id": "abc123"})

        mock_session.post.assert_called_once()

    async def test_webhook_includes_timestamp(self) -> None:
        cfg = WebhookConfig(url="https://example.com/hook", retries=1)
        service = WebhookService(webhooks={"goal_completed": [cfg]})

        captured_payload: dict = {}
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)
        mock_cm = AsyncMock(return_value=mock_response)

        mock_session = MagicMock()
        mock_session.post = mock_cm

        with patch("soothe.cognition.goal_engine.webhooks._get_http_session", return_value=mock_session):
            await service.notify("goal_completed", {"goal_id": "abc"})

        call_kwargs = mock_cm.call_args[1]
        data = call_kwargs.get("data", "")
        import json

        captured_payload.update(json.loads(data))
        assert "timestamp" in captured_payload
        assert captured_payload["event"] == "goal_completed"

    async def test_retries_on_failure(self) -> None:
        cfg = WebhookConfig(url="https://example.com/hook", retries=2)
        service = WebhookService(webhooks={"goal_completed": [cfg]})

        call_count = 0

        # Build a proper async context manager that raises on entry
        class FailingContextManager:
            async def __aenter__(self) -> None:
                nonlocal call_count
                call_count += 1
                raise ConnectionError("Connection refused")

            async def __aexit__(self, *args: object) -> None:
                pass

        mock_session = MagicMock()
        mock_session.post = lambda *a, **k: FailingContextManager()  # type: ignore[assignment]

        with patch("soothe.cognition.goal_engine.webhooks._get_http_session", return_value=mock_session):
            await service.notify("goal_completed", {"goal_id": "abc"})

        assert call_count == 2  # retries=2

    async def test_ignores_unconfigured_event(self) -> None:
        cfg = WebhookConfig(url="https://example.com/hook", events=frozenset({"goal_completed"}))
        service = WebhookService(webhooks={"goal_completed": [cfg]})

        mock_session = AsyncMock()

        with patch("soothe.cognition.goal_engine.webhooks._get_http_session", return_value=mock_session):
            await service.notify("dreaming_entered", {})

        mock_session.post.assert_not_called()

    async def test_multiple_webhooks_same_event(self) -> None:
        cfg1 = WebhookConfig(url="https://a.com/hook", retries=1)
        cfg2 = WebhookConfig(url="https://b.com/hook", retries=1)
        service = WebhookService(webhooks={"goal_completed": [cfg1, cfg2]})

        call_count = 0

        class SuccessContextManager:
            async def __aenter__(self) -> MagicMock:
                nonlocal call_count
                call_count += 1
                resp = MagicMock()
                resp.status = 200
                return resp

            async def __aexit__(self, *args: object) -> None:
                pass

        mock_session = MagicMock()
        mock_session.post = lambda *a, **k: SuccessContextManager()  # type: ignore[assignment]

        with patch("soothe.cognition.goal_engine.webhooks._get_http_session", return_value=mock_session):
            await service.notify("goal_completed", {"goal_id": "abc"})

        assert call_count == 2


class TestFallbackHttp:
    """Tests for fallback HTTP client."""

    @pytest.mark.asyncio
    async def test_fallback_noop(self) -> None:
        from soothe.cognition.goal_engine.webhooks import _FallbackHttp

        client = _FallbackHttp()
        result = await client.post("https://example.com/hook")
        assert result.status == 200
