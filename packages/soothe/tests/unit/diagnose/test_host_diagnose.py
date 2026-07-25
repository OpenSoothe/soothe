"""Unit tests for soothe host diagnose."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe.diagnose import diagnose
from soothe.diagnose.host import check_host
from soothe.diagnose.models import CheckStatus


@pytest.mark.asyncio
async def test_diagnose_returns_host_dict() -> None:
    results = await diagnose(None, categories=["host"])
    assert len(results) == 1
    assert results[0]["category"] == "host"
    assert "status" in results[0]
    assert isinstance(results[0]["checks"], list)


@pytest.mark.asyncio
async def test_host_ok_with_full_config() -> None:
    config = SimpleNamespace(
        agent=SimpleNamespace(
            autopilot=SimpleNamespace(enabled=False),
            loop=SimpleNamespace(),
        ),
        cron=SimpleNamespace(max_jobs=100),
        skillify=SimpleNamespace(enabled=False, model_role="embedding"),
    )
    result = await check_host(config)
    assert result.category == "host"
    names = {c.name: c for c in result.checks}
    assert names["autopilot"].status == CheckStatus.OK
    assert names["loop"].status == CheckStatus.OK
    assert names["cron"].status == CheckStatus.OK
    assert names["skillify"].status == CheckStatus.SKIPPED


@pytest.mark.asyncio
async def test_skillify_enabled_requires_sdk() -> None:
    config = SimpleNamespace(
        agent=SimpleNamespace(
            autopilot=SimpleNamespace(enabled=True),
            loop=SimpleNamespace(),
        ),
        cron=SimpleNamespace(max_jobs=10),
        skillify=SimpleNamespace(enabled=True, model_role="embedding"),
    )
    result = await check_host(config)
    skillify = next(c for c in result.checks if c.name == "skillify")
    assert skillify.status in (CheckStatus.OK, CheckStatus.ERROR)
