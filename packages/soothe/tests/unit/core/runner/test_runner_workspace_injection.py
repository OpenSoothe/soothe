"""Tests for RunnerState workspace injection before pre-stream (IG-116 follow-up)."""

from __future__ import annotations

from pathlib import Path

from soothe.config import SootheConfig
from soothe.runner._runner_phases import PhasesMixin
from soothe.runner._types import RunnerState


class _PhasesOnly(PhasesMixin):
    """Minimal object to exercise ``_ensure_runner_state_workspace``."""

    def __init__(self, config: SootheConfig) -> None:
        self._config = config


def test_ensure_runner_state_workspace_fills_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = SootheConfig()
    ws_path = str(tmp_path / "ws")
    cfg.filesystem_middleware.workspace_root = ws_path
    Path(ws_path).mkdir()

    r = _PhasesOnly(cfg)
    st = RunnerState()
    r._ensure_runner_state_workspace(st)
    assert Path(st.workspace).resolve() == Path(ws_path).resolve()


def test_ensure_runner_state_workspace_skips_nonempty_string(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "custom"
    custom.mkdir()
    r = _PhasesOnly(SootheConfig())
    st = RunnerState()
    st.workspace = str(custom)
    r._ensure_runner_state_workspace(st)
    assert st.workspace == str(custom)
