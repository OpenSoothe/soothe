"""Assistant message widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.events import Click
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import Static

from soothe_cli.tui.config import is_ascii_mode
from soothe_cli.tui.markdown_theme import build_markdown

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer


def _rich_style_with_textual_selection(
    segment_style: Any,
    selection_background: Any,
) -> Any:
    """Blend ``screen--selection`` over a Rich segment like Content visuals do.

    Rich ``Style.__add__`` replaces ``bgcolor`` outright, which makes markdown
    selections look like an opaque block over code blocks. Use the component
    background Color (with alpha from ``$primary 50%``), not ``get_component_rich_style``,
    which pre-multiplies alpha away.
    """
    from rich.style import Style as RichStyle
    from textual.style import Style as TextualStyle

    base = TextualStyle.from_rich_style(segment_style) if segment_style else TextualStyle.null()
    if selection_background is None or getattr(selection_background, "a", 0) == 0:
        return base.rich_style
    selection = TextualStyle(selection_background, None)
    merged: RichStyle = (base + selection).rich_style
    return merged


class _SelectableMarkdownBody(Static):
    """Static body that supports text selection over Rich renderables.

    `Static.update(RichMarkdown(...))` breaks selection in three independent
    places, all rooted in `RichVisual.render_strips` rendering via plain
    `console.render(...)` instead of going through `Content`/`Text`. We patch
    each one in `render_line`:

    1. **Selection capture.** `Compositor.get_widget_and_offset_at` walks
       segments looking for an `offset` style meta. `Content.to_strip` adds it
       via `rich_style_with_offset(x, y)`; `RichVisual` emits none, so click +
       drag never resolves to a content offset and the screen silently drops
       the selection. We re-apply offsets with `Strip.apply_offsets(0, y)`.
    2. **Visual highlight.** `RichVisual.render_strips` ignores
       `options.selection` / `options.selection_style`, so even an active
       selection is invisible on the card. For ``RichVisual`` we overlay
       ``screen--selection`` with Textual alpha blending. Plain ``Content``
       visuals already receive selection styling from ``Visual.to_strips``.
    3. **Copy extraction.** `Widget.get_selection` returns `None` for
       non-`Text`/`Content` visuals. We reconstruct visible text from the
       cached strips.
    """

    def render_line(self, y: int) -> Strip:  # type: ignore[override]
        from rich.segment import Segment as _Segment
        from textual.visual import RichVisual

        line = super().render_line(y).apply_offsets(0, y)
        selection = self.text_selection
        if selection is None:
            return line
        # Plain-string Content visuals already stylize selection in the cache.
        if not isinstance(self.visual, RichVisual):
            return line
        span = selection.get_span(y)
        if span is None:
            return line
        start, end = span
        if end == -1:
            end = line.cell_length
        start = max(0, min(start, line.cell_length))
        end = max(start, min(end, line.cell_length))
        if start == end:
            return line
        selection_bg = self.screen.get_component_styles("screen--selection").background
        left = line.crop(0, start)
        middle = line.crop(start, end)
        right = line.crop(end, line.cell_length)
        middle_segments = [
            _Segment(
                text,
                _rich_style_with_textual_selection(style, selection_bg),
                control,
            )
            for text, style, control in middle
        ]
        return Strip(
            list(left) + middle_segments + list(right),
            line.cell_length,
        )

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:  # type: ignore[override]
        lines = [strip.text for strip in self._render_cache.lines]
        if lines:
            text = "\n".join(lines)
            return selection.extract(text), "\n"
        return super().get_selection(selection)


class AssistantMessage(Vertical):
    """Assistant reply card: markdown or plain text body (no title row).

    When ``render_markdown`` is enabled (default), model output is rendered as
    Markdown via the configured markdown theme preset inside a single
    ``Static`` widget.
    When disabled, output is shown verbatim. This avoids the heavy widget tree
    that ``textual.widgets.Markdown`` creates (one child widget per block).
    """

    ALLOW_SELECT = True
    """Enable text selection for copy functionality."""

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: transparent;
        border-left: wide $cognition;
    }

    AssistantMessage .assistant-body {
        padding: 0;
        margin: 0;
        height: auto;
    }

    AssistantMessage:hover {
        border-left: wide $cognition-hover;
    }
    """

    # Default flush interval (can be overridden by config)
    DEFAULT_STREAM_FLUSH_INTERVAL: float = 0.2  # 200ms batching for streaming

    def __init__(
        self,
        content: str = "",
        *,
        render_markdown: bool | None = None,
        render_ansi: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize an assistant message.

        Args:
            content: Initial assistant text (rendered as Markdown if enabled).
            render_markdown: When set, overrides CLI ``render_markdown`` config for
                this card (e.g. simple-bypass ``plan_direct`` next-action lines).
            render_ansi: When True and markdown is disabled, parse ANSI escape
                sequences in ``content`` via Rich (e.g. TUI shell command output).
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(**kwargs)
        self._content = content
        self._body: Static | None = None
        self._streaming_active: bool = False
        self._render_ansi = render_ansi

        # Batching buffer for streaming content
        self._pending_buffer: str = ""
        self._flush_timer: Timer | None = None
        self._stream_flush_interval: float = self.DEFAULT_STREAM_FLUSH_INTERVAL

        # Determine markdown rendering and flush interval from config
        self._render_markdown: bool = True
        try:
            from soothe_cli.config.loader import load_config

            config = load_config()
            if render_markdown is not None:
                self._render_markdown = render_markdown
            else:
                self._render_markdown = config.render_markdown
            if hasattr(config, "agent"):
                streaming_cfg = config.agent.loop.output_streaming
                self._stream_flush_interval = streaming_cfg.tui_flush_interval_ms / 1000.0
        except Exception:
            if render_markdown is not None:
                self._render_markdown = render_markdown

    def compose(self) -> ComposeResult:  # noqa: PLR6301  # Textual widget method convention
        """Compose the assistant body as a single Static widget."""
        yield _SelectableMarkdownBody(
            "", markup=False, classes="assistant-body", id="assistant-body"
        )

    def on_mount(self) -> None:
        """Wire child widget reference."""
        if is_ascii_mode():
            self.add_class("-ascii")
        self._body = self.query_one("#assistant-body", Static)

    def _render_to_body(self) -> None:
        """Render current content into the body Static widget."""
        if self._body is None:
            return
        if not self._content:
            self._body.update("")
            return
        if self._render_markdown:
            self._body.update(build_markdown(self._content, self))
        elif self._render_ansi:
            from rich.text import Text

            self._body.update(Text.from_ansi(self._content))
        else:
            self._body.update(self._content)

    def on_click(self, event: Click) -> None:
        """Handle click on assistant message."""
        event.stop()

    async def _flush_pending_content(self) -> None:
        """Flush buffered content to body widget (batched update)."""
        self._flush_timer = None
        if not self._pending_buffer:
            return
        self._pending_buffer = ""
        self._render_to_body()

    async def append_content(self, text: str) -> None:
        """Append content to the message (for streaming with batching).

        Uses internal buffering to batch writes and reduce render frequency.
        """
        if not text:
            return

        # Accumulate content
        self._content += text
        self._pending_buffer += text
        self._streaming_active = True

        # Schedule batched flush if not already scheduled
        if self._flush_timer is None:
            self._flush_timer = self.set_timer(
                self._stream_flush_interval,
                self._flush_pending_content,
            )

    async def write_initial_content(self) -> None:
        """Write initial content from constructor and finalize streaming state."""
        if self._content:
            self._streaming_active = True
            self._render_to_body()
            await self.stop_stream()

    async def stop_stream(self) -> None:
        """End streaming batched updates."""
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None

        if self._pending_buffer:
            await self._flush_pending_content()

        self._streaming_active = False
        self._render_to_body()

    async def set_content(self, content: str) -> None:
        """Set the full message content (stops any active stream)."""
        await self.stop_stream()
        self._content = content
        self._pending_buffer = ""
        self._render_to_body()
