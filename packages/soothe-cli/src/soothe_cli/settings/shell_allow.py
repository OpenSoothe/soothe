"""Shell command allow-list parsing and safe defaults."""

from __future__ import annotations


class _ShellAllowAll(list):  # noqa: FURB189  # sentinel type, not a general-purpose list subclass
    """Sentinel subclass for unrestricted shell access.

    Using a dedicated type instead of a plain list lets consumers use
    `isinstance` checks, which survive serialization/copy unlike identity
    checks (`is`).
    """


SHELL_ALLOW_ALL: list[str] = _ShellAllowAll(["__ALL__"])
"""Sentinel value returned by `parse_shell_allow_list` for `--shell-allow-list=all`."""


RECOMMENDED_SAFE_SHELL_COMMANDS = (
    # Directory listing
    "ls",
    "dir",
    # File content viewing (read-only)
    "cat",
    "head",
    "tail",
    # Text searching (read-only)
    "grep",
    "wc",
    "strings",
    # Text processing (read-only, no shell execution)
    "cut",
    "tr",
    "diff",
    "md5sum",
    "sha256sum",
    # Path utilities
    "pwd",
    "which",
    # System info (read-only)
    "uname",
    "hostname",
    "whoami",
    "id",
    "groups",
    "uptime",
    "nproc",
    "lscpu",
    "lsmem",
    # Process viewing (read-only)
    "ps",
)
"""Read-only commands auto-approved in non-interactive mode.

Only includes readers and formatters — shells, editors, interpreters, package
managers, network tools, archivers, and anything on GTFOBins/LOOBins is
intentionally excluded.
"""


def parse_shell_allow_list(allow_list_str: str | None) -> list[str] | None:
    """Parse shell allow-list from string.

    Args:
    allow_list_str: Comma-separated list of commands, or `'recommended'`
    for safe defaults, or `'all'` to allow any command.

    `'all'` must be the sole value — it is not recognized inside a
    comma-separated list (unlike `'recommended'`).

    Can also include `'recommended'` in the list to merge with custom
    commands.

    Returns:
    List of allowed commands, `SHELL_ALLOW_ALL` if `'all'` was specified,
    or `None` if no allow-list configured.

    Raises:
    ValueError: If `'all'` is combined with other commands.
    """
    if not allow_list_str:
        return None

    # Special value 'all' allows any shell command
    if allow_list_str.strip().lower() == "all":
        return SHELL_ALLOW_ALL

    # Special value 'recommended' uses our curated safe list
    if allow_list_str.strip().lower() == "recommended":
        return list(RECOMMENDED_SAFE_SHELL_COMMANDS)

    # Split by comma and strip whitespace
    commands = [cmd.strip() for cmd in allow_list_str.split(",") if cmd.strip()]

    # Reject ambiguous input: 'all' mixed with other commands
    if any(cmd.lower() == "all" for cmd in commands):
        msg = (
            "Cannot combine 'all' with other commands in --shell-allow-list. "
            "Use '--shell-allow-list all' alone to allow any command."
        )
        raise ValueError(msg)

    # If "recommended" is in the list, merge with recommended commands
    result: list[str] = []
    for cmd in commands:
        if cmd.lower() == "recommended":
            result.extend(RECOMMENDED_SAFE_SHELL_COMMANDS)
        else:
            result.append(cmd)

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for cmd in result:
        if cmd not in seen:
            seen.add(cmd)
            unique.append(cmd)
    return unique
