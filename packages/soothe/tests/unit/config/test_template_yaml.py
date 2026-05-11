"""Regression: full ``config.template.yml`` matches Pydantic defaults (except documented examples)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.config.models import BrowserSubagentConfig
from soothe.subagents.explore.schemas import ExploreSubagentConfig
from soothe.subagents.plan.schemas import PlanSubagentConfig


def _repo_config_template_path() -> Path:
    # packages/soothe/tests/unit/config/test_template_yaml.py → repo root
    return Path(__file__).resolve().parents[5] / "config" / "config.template.yml"


def _normalize_for_default_compare(data: dict) -> dict:
    """Strip example-only keys and subagent config dicts that equal schema defaults."""
    out = copy.deepcopy(data)
    out.pop("providers", None)
    out.pop("vector_stores", None)
    out.pop("vector_store_router", None)
    subs = out.get("subagents") or {}
    for name, sub in list(subs.items()):
        if not isinstance(sub, dict):
            continue
        cfg = sub.get("config") or {}
        if name == "explore" and ExploreSubagentConfig(**cfg) == ExploreSubagentConfig():
            sub["config"] = {}
        if name == "plan" and PlanSubagentConfig(**cfg) == PlanSubagentConfig():
            sub["config"] = {}
        if name == "browser" and BrowserSubagentConfig(**cfg) == BrowserSubagentConfig():
            sub["config"] = {}
        subs[name] = sub
    return out


@pytest.mark.skipif(not _repo_config_template_path().is_file(), reason="template not in checkout")
def test_config_template_matches_pydantic_defaults() -> None:
    """Template mirrors ``SootheConfig`` defaults; only providers / vector examples differ."""
    path = _repo_config_template_path()
    loaded = SootheConfig.from_yaml_file(str(path))
    baseline = SootheConfig()

    ld = loaded.model_dump(mode="python")
    bd = baseline.model_dump(mode="python")
    assert _normalize_for_default_compare(ld) == _normalize_for_default_compare(bd)

    assert ExploreSubagentConfig(**loaded.subagents["explore"].config) == ExploreSubagentConfig()
    assert PlanSubagentConfig(**loaded.subagents["plan"].config) == PlanSubagentConfig()
    assert BrowserSubagentConfig(**loaded.subagents["browser"].config) == BrowserSubagentConfig()
    assert len(loaded.providers) >= 1
    assert loaded.vector_store_router.default is not None
