"""Tests for nano.yml provider merge and wizard soft-fail path."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from soothe_daemon.setup.env_keys import normalize_api_key_for_yaml, upsert_dotenv_value
from soothe_daemon.setup.provider import (
    ProviderSetupCancelledError,
    fetch_models,
    load_yaml_dict,
    merge_provider_from_env,
    run_provider_wizard,
    update_config_for_model,
)
from soothe_daemon.setup.scaffold import scaffold_configs


def test_update_config_preserves_unrelated_keys() -> None:
    existing = {
        "providers": [{"name": "openai", "api_key": "${OPENAI_API_KEY}", "models": ["gpt-4o"]}],
        "tools": {"execution": {"enabled": True}},
        "router_profiles": [
            {
                "name": "default",
                "router": {"default": "openai:gpt-4o-mini", "think": "openai:o3-mini"},
            }
        ],
        "active_router_profile": "default",
    }
    updated = update_config_for_model(
        existing,
        provider_name="openai",
        endpoint="https://api.openai.com/v1",
        api_key="${OPENAI_API_KEY}",
        model="gpt-4o",
    )
    assert updated["tools"]["execution"]["enabled"] is True
    assert updated["router_profiles"][0]["router"]["think"] == "openai:o3-mini"
    assert updated["router_profiles"][0]["router"]["default"] == "openai:gpt-4o"
    assert "gpt-4o" in updated["providers"][0]["models"]


def test_normalize_api_key_writes_dotenv(tmp_path: Path) -> None:
    yaml_key = normalize_api_key_for_yaml(
        "sk-test-secret",
        soothe_home=tmp_path,
        env_var="OPENAI_API_KEY",
    )
    assert yaml_key == "${OPENAI_API_KEY}"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-test-secret" in env_text


def test_normalize_keeps_placeholder_and_ollama(tmp_path: Path) -> None:
    assert (
        normalize_api_key_for_yaml(
            "${OPENAI_API_KEY}", soothe_home=tmp_path, env_var="OPENAI_API_KEY"
        )
        == "${OPENAI_API_KEY}"
    )
    assert (
        normalize_api_key_for_yaml("ollama", soothe_home=tmp_path, env_var="OPENAI_API_KEY")
        == "ollama"
    )
    assert not (tmp_path / ".env").exists()


def test_upsert_dotenv_replaces_existing(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=old\nFOO=bar\n", encoding="utf-8")
    upsert_dotenv_value(env_path, "OPENAI_API_KEY", "new")
    text = env_path.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=new" in text
    assert "FOO=bar" in text
    assert "old" not in text


def test_soft_fail_model_fetch_accepts_manual(tmp_path: Path, monkeypatch) -> None:
    scaffold_configs(tmp_path, stdout=StringIO())
    nano = tmp_path / "nano.yml"
    home = tmp_path / "home"
    home.mkdir()

    def boom(_endpoint: str, _key: str) -> list[str]:
        raise RuntimeError("connection refused")

    # Select existing provider 1, accept defaults for endpoint/key, then manual model.
    class _LineIO(StringIO):
        def __init__(self) -> None:
            super().__init__()
            self._lines = ["1\n", "\n", "\n", "my-custom-model\n"]
            self._i = 0

        def readline(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
            if self._i >= len(self._lines):
                return ""
            line = self._lines[self._i]
            self._i += 1
            return line

    out = StringIO()
    err = StringIO()
    updated = run_provider_wizard(
        nano,
        soothe_home=home,
        stdin=_LineIO(),
        stdout=out,
        stderr=err,
        fetch_models_fn=boom,
    )
    assert "could not fetch models" in err.getvalue()
    assert updated["router_profiles"][0]["router"]["default"].endswith(":my-custom-model")
    saved = load_yaml_dict(nano)
    assert "my-custom-model" in saved["providers"][0]["models"]


def test_merge_provider_from_env_when_empty(tmp_path: Path, monkeypatch) -> None:
    nano = tmp_path / "nano.yml"
    nano.write_text("providers: []\nrouter_profiles: []\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    updated = merge_provider_from_env(nano)
    assert updated is not None
    assert updated["providers"][0]["name"] == "openai"
    assert updated["providers"][0]["api_key"] == "${OPENAI_API_KEY}"


def test_merge_provider_from_env_noop_when_providers_exist(tmp_path: Path, monkeypatch) -> None:
    scaffold_configs(tmp_path, stdout=StringIO())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert merge_provider_from_env(tmp_path / "nano.yml") is None


def test_cancel_leaves_scaffold(tmp_path: Path) -> None:
    scaffold_configs(tmp_path, stdout=StringIO())
    nano = tmp_path / "nano.yml"
    before = nano.read_text(encoding="utf-8")

    class _CancelIO(StringIO):
        def readline(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
            return "q\n"

    try:
        run_provider_wizard(
            nano,
            soothe_home=tmp_path,
            stdin=_CancelIO(),
            stdout=StringIO(),
            stderr=StringIO(),
            fetch_models_fn=lambda *_a, **_k: [],
        )
        raise AssertionError("expected cancel")
    except ProviderSetupCancelledError:
        pass

    assert nano.read_text(encoding="utf-8") == before
    assert (tmp_path / "soothe.yml").is_file()
    assert (tmp_path / "daemon.yml").is_file()


def test_fetch_models_parses_openai_payload(monkeypatch) -> None:
    class _Resp:
        def read(self) -> bytes:
            return b'{"data":[{"id":"m1"},{"id":"m2"}]}'

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args) -> None:  # noqa: ANN002
            return None

    monkeypatch.setattr(
        "soothe_daemon.setup.provider.request.urlopen",
        lambda *_a, **_k: _Resp(),
    )
    models = fetch_models("http://127.0.0.1:9/v1", "k")
    assert models == ["m1", "m2"]
