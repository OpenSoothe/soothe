"""Unit tests for LLM LoopRail auto-pick (IG-728 / RFC-231 §10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.autopilot.jobs.rail_selection import write_rail_selection
from soothe.rails.catalog import LoopRailCatalog, RailDefinition, load_rail_file
from soothe.rails.selector import (
    RailAutoPicker,
    RailAutoPickResponse,
    RailPickResult,
    filter_auto_pick_candidates,
    format_rail_pick_user_prompt,
    resolve_rail_for_job,
    resolve_rail_id,
)


def _fake_rail(
    rail_id: str,
    *,
    auto_pick: bool = True,
    applies: str = "when testing",
) -> RailDefinition:
    return RailDefinition(
        id=rail_id,
        version="1.0",
        summary=f"Summary for {rail_id}",
        applies_when=applies,
        flow=[{"event": "job_start", "then": "review"}],
        auto_pick=auto_pick,
        integrity_hash=f"hash-{rail_id}",
    )


def test_format_prompt_grows_with_candidates() -> None:
    rails = [_fake_rail("alpha"), _fake_rail("beta")]
    prompt = format_rail_pick_user_prompt("ship a feature", rails)
    assert "Allowed rail_ids" in prompt
    assert "alpha, beta" in prompt
    assert "### alpha" in prompt
    assert "### beta" in prompt
    assert "<catalog_data>" in prompt
    assert "<untrusted_data>" in prompt
    assert "ship a feature" in prompt
    assert "Candidates (2)" in prompt


def test_format_prompt_empty_candidates() -> None:
    prompt = format_rail_pick_user_prompt("anything", [])
    assert "Candidates (0)" in prompt
    assert "(none)" in prompt


def test_filter_excludes_deny_and_auto_pick_false() -> None:
    rails = {
        "feature-dev": _fake_rail("feature-dev"),
        "greenfield-system": _fake_rail("greenfield-system", auto_pick=False),
        "hotfix": _fake_rail("hotfix"),
        "secret": _fake_rail("secret"),
    }
    filtered = filter_auto_pick_candidates(rails, deny=["secret", "greenfield-system"])
    ids = [r.id for r in filtered]
    assert ids == ["feature-dev", "hotfix"]


def test_greenfield_builtin_has_auto_pick_true() -> None:
    rail = LoopRailCatalog().resolve("greenfield-system")
    assert rail.auto_pick is True


def test_format_prompt_truncates_long_description() -> None:
    rails = [_fake_rail("feature-dev")]
    long_job = "A" * 5000
    prompt = format_rail_pick_user_prompt(long_job, rails, max_description_chars=100)
    assert "A" * 97 + "..." in prompt
    assert "A" * 200 not in prompt


@pytest.mark.asyncio
async def test_resolve_explicit_wins_without_picker() -> None:
    result = await resolve_rail_for_job(
        "spike",
        description="anything",
        picker=None,
        default_rail="hotfix",
    )
    assert result.rail_id == "spike"
    assert result.source == "explicit"


@pytest.mark.asyncio
async def test_resolve_explicit_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown rail_id"):
        await resolve_rail_for_job(
            "not-a-real-rail",
            description="x",
            picker=None,
        )


@pytest.mark.asyncio
async def test_resolve_workspace_default_when_no_picker(tmp_path: Path) -> None:
    marker = tmp_path / ".soothe" / "rails"
    marker.mkdir(parents=True)
    (marker / ".rail-default").write_text("spike\n", encoding="utf-8")
    result = await resolve_rail_for_job(
        None,
        description="job",
        workspace=str(tmp_path),
        picker=None,
        default_rail="hotfix",
    )
    assert result.rail_id == "spike"
    assert result.source == "workspace_default"


@pytest.mark.asyncio
async def test_resolve_config_default_when_no_picker() -> None:
    result = await resolve_rail_for_job(
        None,
        description="job",
        picker=None,
        default_rail="pr-review",
        auto_pick=False,
    )
    assert result.rail_id == "pr-review"
    assert result.source == "config_default"


@pytest.mark.asyncio
async def test_resolve_none_when_no_defaults() -> None:
    result = await resolve_rail_for_job(
        None,
        description="job",
        picker=None,
        default_rail=None,
        auto_pick=False,
    )
    assert result.rail_id is None
    assert result.source == "none"


@pytest.mark.asyncio
async def test_llm_high_confidence_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [_fake_rail("bugfix"), _fake_rail("feature-dev")]
    catalog = MagicMock(spec=LoopRailCatalog)
    catalog.load_all.return_value = {c.id: c for c in candidates}
    catalog.resolve.side_effect = lambda rid: next(c for c in candidates if c.id == rid)

    async def fake_pick(
        self: RailAutoPicker,
        description: str,
        cands: Any,
        *,
        max_field_chars: int = 400,
    ) -> RailAutoPickResponse:
        return RailAutoPickResponse(
            rail_id="bugfix",
            confidence=0.9,
            reasoning="matches defect applies_when",
        )

    monkeypatch.setattr(RailAutoPicker, "pick", fake_pick)
    picker = RailAutoPicker(model=object())
    result = await resolve_rail_for_job(
        None,
        description="fix the null pointer crash",
        catalog=catalog,
        picker=picker,
        default_rail="hotfix",
        min_confidence=0.6,
    )
    assert result.rail_id == "bugfix"
    assert result.source == "llm"
    assert result.confidence == 0.9
    assert "bugfix" in result.candidates_considered


@pytest.mark.asyncio
async def test_llm_low_confidence_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [_fake_rail("bugfix")]
    catalog = MagicMock(spec=LoopRailCatalog)
    catalog.load_all.return_value = {c.id: c for c in candidates}

    async def fake_pick(
        self: RailAutoPicker,
        description: str,
        cands: Any,
        *,
        max_field_chars: int = 400,
    ) -> RailAutoPickResponse:
        return RailAutoPickResponse(rail_id="bugfix", confidence=0.2, reasoning="unsure")

    monkeypatch.setattr(RailAutoPicker, "pick", fake_pick)
    result = await resolve_rail_for_job(
        None,
        description="maybe something",
        catalog=catalog,
        picker=RailAutoPicker(model=object()),
        default_rail="hotfix",
        min_confidence=0.6,
    )
    assert result.rail_id == "hotfix"
    assert result.source == "config_default"


@pytest.mark.asyncio
async def test_llm_unknown_id_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [_fake_rail("bugfix")]
    catalog = MagicMock(spec=LoopRailCatalog)
    catalog.load_all.return_value = {c.id: c for c in candidates}

    async def fake_pick(
        self: RailAutoPicker,
        description: str,
        cands: Any,
        *,
        max_field_chars: int = 400,
    ) -> RailAutoPickResponse:
        return RailAutoPickResponse(rail_id="invented", confidence=0.99, reasoning="x")

    monkeypatch.setattr(RailAutoPicker, "pick", fake_pick)
    result = await resolve_rail_for_job(
        None,
        description="job",
        catalog=catalog,
        picker=RailAutoPicker(model=object()),
        default_rail="pr-review",
    )
    assert result.rail_id == "pr-review"
    assert result.source == "config_default"


@pytest.mark.asyncio
async def test_llm_abstain_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [_fake_rail("bugfix")]
    catalog = MagicMock(spec=LoopRailCatalog)
    catalog.load_all.return_value = {c.id: c for c in candidates}

    async def fake_pick(
        self: RailAutoPicker,
        description: str,
        cands: Any,
        *,
        max_field_chars: int = 400,
    ) -> RailAutoPickResponse:
        return RailAutoPickResponse(rail_id=None, confidence=0.85, reasoning="no rail")

    monkeypatch.setattr(RailAutoPicker, "pick", fake_pick)
    result = await resolve_rail_for_job(
        None,
        description="casual chat",
        catalog=catalog,
        picker=RailAutoPicker(model=object()),
        default_rail="hotfix",
        abstain_overrides_defaults=True,
    )
    assert result.rail_id is None
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_llm_abstain_can_fall_through(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [_fake_rail("bugfix")]
    catalog = MagicMock(spec=LoopRailCatalog)
    catalog.load_all.return_value = {c.id: c for c in candidates}

    async def fake_pick(
        self: RailAutoPicker,
        description: str,
        cands: Any,
        *,
        max_field_chars: int = 400,
    ) -> RailAutoPickResponse:
        return RailAutoPickResponse(rail_id=None, confidence=0.85, reasoning="no rail")

    monkeypatch.setattr(RailAutoPicker, "pick", fake_pick)
    result = await resolve_rail_for_job(
        None,
        description="casual chat",
        catalog=catalog,
        picker=RailAutoPicker(model=object()),
        default_rail="hotfix",
        abstain_overrides_defaults=False,
    )
    assert result.rail_id == "hotfix"
    assert result.source == "config_default"


@pytest.mark.asyncio
async def test_skip_llm_if_workspace_default(tmp_path: Path) -> None:
    marker = tmp_path / ".soothe" / "rails"
    marker.mkdir(parents=True)
    (marker / ".rail-default").write_text("spike\n", encoding="utf-8")
    picker = RailAutoPicker(model=object())
    picker.pick = AsyncMock(  # type: ignore[method-assign]
        return_value=RailAutoPickResponse(rail_id="bugfix", confidence=0.99, reasoning="x")
    )
    result = await resolve_rail_for_job(
        None,
        description="job",
        workspace=str(tmp_path),
        picker=picker,
        skip_llm_if_workspace_default=True,
        default_rail="hotfix",
    )
    assert result.rail_id == "spike"
    assert result.source == "workspace_default"
    picker.pick.assert_not_called()


@pytest.mark.asyncio
async def test_max_candidates_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    rails = {f"r{i}": _fake_rail(f"r{i}") for i in range(5)}
    catalog = MagicMock(spec=LoopRailCatalog)
    catalog.load_all.return_value = rails
    picker = RailAutoPicker(model=object())
    picker.pick = AsyncMock()  # type: ignore[method-assign]
    result = await resolve_rail_for_job(
        None,
        description="job",
        catalog=catalog,
        picker=picker,
        max_candidates=3,
        default_rail="hotfix",
    )
    assert result.rail_id == "hotfix"
    picker.pick.assert_not_called()


@pytest.mark.asyncio
async def test_llm_timeout_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    candidates = [_fake_rail("bugfix")]
    catalog = MagicMock(spec=LoopRailCatalog)
    catalog.load_all.return_value = {c.id: c for c in candidates}

    async def slow_pick(
        self: RailAutoPicker,
        description: str,
        cands: Any,
        *,
        max_field_chars: int = 400,
    ) -> RailAutoPickResponse:
        await asyncio.sleep(5)
        return RailAutoPickResponse(rail_id="bugfix", confidence=0.9, reasoning="late")

    monkeypatch.setattr(RailAutoPicker, "pick", slow_pick)
    result = await resolve_rail_for_job(
        None,
        description="job",
        catalog=catalog,
        picker=RailAutoPicker(model=object()),
        timeout_s=0.05,
        default_rail="hotfix",
    )
    assert result.rail_id == "hotfix"
    assert result.source == "config_default"


def test_write_rail_selection(tmp_path: Path) -> None:
    pick = RailPickResult(
        rail_id="bugfix",
        source="llm",
        confidence=0.88,
        reasoning="defect",
        candidates_considered=["bugfix", "feature-dev"],
        catalog_hash="abc",
    )
    path = write_rail_selection(jobs_root=tmp_path, job_id="job123", pick=pick)
    assert path is not None
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "bugfix" in text
    assert "llm" in text


def test_sync_resolve_rail_id_ladder(tmp_path: Path) -> None:
    """Deterministic helper: explicit → .rail-default → config → none."""
    assert resolve_rail_id("feature-dev", default_rail="hotfix") == "feature-dev"
    marker = tmp_path / ".soothe" / "rails"
    marker.mkdir(parents=True)
    (marker / ".rail-default").write_text("# comment\nspike\n", encoding="utf-8")
    assert resolve_rail_id(None, workspace=str(tmp_path), default_rail="hotfix") == "spike"
    assert resolve_rail_id(None, workspace=None, default_rail="pr-review") == "pr-review"
    assert resolve_rail_id(None, workspace=None, default_rail=None) is None


def test_load_rail_auto_pick_false(tmp_path: Path) -> None:
    path = tmp_path / "custom.yml"
    path.write_text(
        """
id: custom
version: "1.0"
auto_pick: false
summary: Custom
applies_when: never auto
flow:
  - event: job_start
    then: review
""".strip(),
        encoding="utf-8",
    )
    rail = load_rail_file(path)
    assert rail.auto_pick is False
