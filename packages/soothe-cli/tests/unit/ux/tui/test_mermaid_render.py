"""Tests for TUI Mermaid diagram expansion (IG-657)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from soothe_cli.tui.markdown_theme import ThemedMarkdownRenderer, build_markdown
from soothe_cli.tui.mermaid_render import is_mermaid_lexer, render_mermaid_art


def test_is_mermaid_lexer_accepts_common_tags() -> None:
    assert is_mermaid_lexer("mermaid")
    assert is_mermaid_lexer("MERMAID")
    assert is_mermaid_lexer("mmd")
    assert is_mermaid_lexer("mermaid flowchart")
    assert not is_mermaid_lexer("python")
    assert not is_mermaid_lexer("")
    assert not is_mermaid_lexer(None)


def test_render_mermaid_art_flowchart() -> None:
    art = render_mermaid_art("flowchart TD\n  A[Start] --> B[End]")
    assert art is not None
    assert "Start" in art
    assert "End" in art
    assert "flowchart" not in art


def test_render_mermaid_art_graph_lr() -> None:
    art = render_mermaid_art("graph LR\n  A --> B")
    assert art is not None
    assert "A" in art
    assert "B" in art


def test_render_mermaid_art_invalid_returns_none() -> None:
    assert render_mermaid_art("not a diagram") is None
    assert render_mermaid_art("") is None
    assert render_mermaid_art("   ") is None


def test_render_mermaid_art_exception_returns_none() -> None:
    with patch(
        "soothe_cli.tui.mermaid_render._render_plain",
        side_effect=RuntimeError("boom"),
    ):
        assert render_mermaid_art("flowchart TD\n  A --> B") is None


def test_render_mermaid_art_compacts_to_max_width() -> None:
    source = "flowchart LR\n  A[AlphaNode] --> B[BetaNode] --> C[GammaNode] --> D[DeltaNode]\n"
    wide = render_mermaid_art(source)
    assert wide is not None
    budget = max(20, max(len(line) for line in wide.splitlines()) // 2)
    compact = render_mermaid_art(source, max_width=budget)
    assert compact is not None
    assert "Alpha" in compact or "A" in compact


def test_themed_markdown_expands_mermaid_fence() -> None:
    markup = "## Summary\n\n- Done\n\n```mermaid\nflowchart TD\n  A[Start] --> B[End]\n```\n"
    renderable = build_markdown(markup)
    assert isinstance(renderable, ThemedMarkdownRenderer)

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80, legacy_windows=False)
    console.print(renderable)
    output = buf.getvalue()

    assert "Start" in output
    assert "End" in output
    assert "```mermaid" not in output
    assert "flowchart TD" not in output


def test_themed_markdown_keeps_non_mermaid_fences() -> None:
    markup = "```python\nprint('hi')\n```\n"
    renderable = build_markdown(markup)
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80, legacy_windows=False)
    console.print(renderable)
    output = buf.getvalue()
    assert "print" in output
    assert "hi" in output


def test_themed_markdown_falls_back_on_bad_mermaid() -> None:
    markup = "```mermaid\nnot a real diagram\n```\n"
    renderable = build_markdown(markup)
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80, legacy_windows=False)
    console.print(renderable)
    output = buf.getvalue()
    assert "not a real diagram" in output
