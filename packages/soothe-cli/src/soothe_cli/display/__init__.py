"""Display utilities shared by TUI and non-TUI code.

This subpackage holds presentation helpers (path display, preview limits,
unicode security) that are consumed by both the TUI layer and the runtime /
CLI execution layer. Keeping them here preserves the one-way dependency
direction: ``runtime`` and ``cli`` must not import from ``tui``.
"""
