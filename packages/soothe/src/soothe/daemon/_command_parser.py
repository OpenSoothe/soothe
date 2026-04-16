"""Local command parsing helpers for daemon (no CLI dependency).

These functions are local copies to avoid importing from CLI package,
which would create a circular dependency and bring in Rich UI library.
"""


def _parse_autonomous_command_local(cmd: str) -> tuple[int | None, str] | None:
    """Parse `/autopilot` command payload (local copy for daemon)."""
    stripped = cmd.strip()
    if not stripped.startswith("/autopilot"):
        return None

    parts = stripped.split(maxsplit=2)
    if len(parts) == 1:
        return None

    if len(parts) == 2:
        single = parts[1].strip()
        if not single or single.isdigit():
            return None
        return (None, single)

    maybe_num = parts[1].strip()
    if maybe_num.isdigit():
        prompt = parts[2].strip()
        if not prompt:
            return None
        max_iterations = int(maybe_num)
        return (max_iterations if max_iterations > 0 else None, prompt)

    prompt = f"{parts[1]} {parts[2]}".strip()
    return (None, prompt) if prompt else None


__all__ = ["_parse_autonomous_command_local"]
