"""Keep API secrets out of YAML by preferring ``$SOOTHE_HOME/.env``."""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def is_env_placeholder(value: str) -> bool:
    """Return True when *value* is a bare ``${VAR}`` placeholder."""
    return bool(re.fullmatch(r"\$\{\w+\}", value.strip()))


def looks_like_secret(value: str) -> bool:
    """Heuristic: raw API keys are not env placeholders and not empty."""
    stripped = value.strip()
    if not stripped:
        return False
    if is_env_placeholder(stripped):
        return False
    # Common local dummy keys stay in YAML (ollama / empty placeholder).
    if stripped.lower() in {"ollama", "none", "null", "dummy"}:
        return False
    return True


def default_env_var_for_provider(provider_name: str, provider_type: str = "openai") -> str:
    """Pick a conventional env var name for the provider's API key."""
    name = provider_name.strip().lower()
    if provider_type == "anthropic" or name == "anthropic":
        return "ANTHROPIC_API_KEY"
    if name in {"openai", "local", "ollama"}:
        return "OPENAI_API_KEY"
    # Custom OpenAI-compatible providers share OPENAI_API_KEY by convention
    # unless a more specific name is already used.
    slug = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    if slug and slug not in {"OPENAI", "LOCAL", "OLLAMA"}:
        return f"{slug}_API_KEY"
    return "OPENAI_API_KEY"


def normalize_api_key_for_yaml(
    api_key: str,
    *,
    soothe_home: Path,
    env_var: str,
) -> str:
    """Return YAML-safe key reference; persist raw secrets to ``.env``.

    If *api_key* is already ``${VAR}``, return it unchanged.
    If it looks like a raw secret, write/update ``$SOOTHE_HOME/.env`` and
    return ``${env_var}``. Dummy local keys (``ollama``) stay literal.

    Args:
        api_key: User-entered key or placeholder.
        soothe_home: Soothe home directory.
        env_var: Environment variable name to use for raw secrets.

    Returns:
        Value to store in ``nano.yml`` ``api_key``.
    """
    stripped = api_key.strip()
    if is_env_placeholder(stripped) or not looks_like_secret(stripped):
        return stripped

    env_path = soothe_home.expanduser() / ".env"
    upsert_dotenv_value(env_path, env_var, stripped)
    os.environ.setdefault(env_var, stripped)
    return f"${{{env_var}}}"


def upsert_dotenv_value(env_path: Path, key: str, value: str) -> None:
    """Create or update ``KEY=value`` in a dotenv file (no export keyword)."""
    env_path = env_path.expanduser()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    escaped = _escape_dotenv_value(value)
    assignment = f"{key}={escaped}"
    replaced = False
    new_lines: list[str] = []
    for line in lines:
        match = _ENV_ASSIGN_RE.match(line.strip())
        if match and match.group(1) == key:
            new_lines.append(assignment)
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(assignment)

    text = "\n".join(new_lines)
    if not text.endswith("\n"):
        text += "\n"
    # Atomic-ish: write then replace
    tmp = env_path.with_name(f"{env_path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(env_path)


def _escape_dotenv_value(value: str) -> str:
    """Quote values that contain whitespace or shell-sensitive characters."""
    if re.search(r'[\s#"\'\\$`]', value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value
