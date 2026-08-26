"""``soothecli`` entry point — alias for ``soothe --no-tui``.

Injects ``--no-tui`` into ``sys.argv`` before delegating to the main
Typer ``app`` so the TUI is never launched and all subcommands /
options behave identically to ``soothe --no-tui <args>``.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Entry point that forces headless mode then delegates to the main app."""
    # Only inject once — avoid double if the user also passed --no-tui.
    if "--no-tui" not in sys.argv:
        sys.argv.insert(1, "--no-tui")
    from soothe_cli.cli.main import app

    app()


if __name__ == "__main__":
    main()
