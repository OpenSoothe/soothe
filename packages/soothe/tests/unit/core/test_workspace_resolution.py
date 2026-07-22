"""Unit tests for unified workspace resolution (IG-116)."""

from __future__ import annotations

from pathlib import Path

from soothe.workspace import ResolvedWorkspace, resolve_workspace_for_stream


def test_resolve_prefers_explicit_over_thread_and_daemon(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "a"
    explicit.mkdir()
    thread = tmp_path / "b"
    thread.mkdir()
    r = resolve_workspace_for_stream(
        explicit=str(explicit),
        thread_workspace=str(thread),
        installation_default=str(tmp_path),
    )
    assert r.source == "explicit"
    assert Path(r.path).resolve() == explicit.resolve()


def test_resolve_thread_when_no_explicit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    thread = tmp_path / "proj"
    thread.mkdir()
    r = resolve_workspace_for_stream(
        thread_workspace=str(thread),
        installation_default=str(tmp_path),
    )
    assert r.source == "thread"
    assert Path(r.path).resolve() == thread.resolve()


def test_resolve_daemon_default_when_no_thread(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    default = tmp_path / "daemon_ws"
    default.mkdir()
    r = resolve_workspace_for_stream(
        installation_default=str(default),
    )
    assert r.source == "daemon_default"
    assert Path(r.path).resolve() == default.resolve()


def test_resolve_cwd_when_nothing_else(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = resolve_workspace_for_stream()
    assert r.source == "cwd"
    assert Path(r.path).resolve() == tmp_path.resolve()


def test_blank_explicit_falls_through(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fallback = tmp_path / "fb"
    fallback.mkdir()
    r = resolve_workspace_for_stream(
        explicit="   ",
        installation_default=str(fallback),
    )
    assert r.source == "daemon_default"


def test_frozen_dataclass() -> None:
    w = ResolvedWorkspace(path="/tmp", source="daemon_default")
    assert w.path == "/tmp"
    assert w.source == "daemon_default"
