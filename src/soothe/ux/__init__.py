"""User-experience layer: CLI, TUI, shared presentation, and daemon client helpers.

Layout:
    ``shared/`` — Event pipeline, display policy, formatters (no Typer/Textual).
    ``client/`` — WebSocket session bootstrap shared by CLI headless and TUI.
    ``cli/`` — Typer entrypoint and command implementations.
    ``tui/`` — Textual interface; depends on ``shared`` and ``client``, not on CLI commands.
"""
