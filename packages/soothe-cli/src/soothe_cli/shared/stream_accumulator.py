"""Unified streaming text accumulator with boundary preservation (RFC-614)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StreamingAccumState:
    """State for a single streaming output stream.

    Attributes:
        accumulated_text: Accumulated content from all chunks.
        chunk_count: Number of chunks received.
        is_active: Stream is still active (expecting more chunks).
        namespace: Namespace for this stream (avoid interleaving).
    """

    accumulated_text: str = ""
    """Accumulated content from all chunks."""

    chunk_count: int = 0
    """Number of chunks received."""

    is_active: bool = True
    """Stream is still active (expecting more chunks)."""

    namespace: tuple[str, ...] = ()
    """Namespace for this stream (avoid interleaving)."""


@dataclass
class StreamingTextAccumulator:
    """Accumulates streaming text chunks with boundary preservation.

    Architecture Pattern (RFC-614, mirrors tool call accumulation from RFC-211):
    - Track by (event_type + namespace) to prevent interleaving concurrent streams
    - Preserve whitespace boundaries for markdown formatting
    - Finalize on non-chunk event or turn completion
    - Clear state after finalization

    Attributes:
        streams: Dict mapping (event_type, namespace) -> StreamingAccumState
        boundary_preserve_enabled: Whether to preserve leading/trailing whitespace
    """

    streams: dict[tuple[str, tuple[str, ...]], StreamingAccumState] = field(default_factory=dict)

    boundary_preserve_enabled: bool = True
    """Preserve whitespace boundaries for proper concatenation."""

    @staticmethod
    def _normalize_heading_prefix(text: str) -> str:
        """Normalize markdown heading prefix when chunks start with ``#`` markers.

        Examples:
        - ``###1. Title`` -> ``### 1. Title``
        - ``##Summary`` -> ``## Summary``
        """
        if not text or text[0] != "#":
            return text

        hash_count = 0
        for ch in text:
            if ch == "#" and hash_count < 6:
                hash_count += 1
            else:
                break

        if hash_count == 0 or hash_count >= len(text):
            return text

        next_char = text[hash_count]
        if next_char.isspace():
            return text

        return f"{text[:hash_count]} {text[hash_count:]}"

    @classmethod
    def _stitch_boundary(cls, previous: str, incoming: str) -> str:
        """Stitch chunk boundaries with minimal semantic separators.

        This prevents cross-chunk markdown/token glue like ``Report##`` or
        ``first10`` while preserving explicit whitespace from the model.
        """
        if not incoming:
            return incoming

        normalized = cls._normalize_heading_prefix(incoming)
        if not previous:
            return normalized

        prev_last = previous[-1]
        next_first = normalized[0]
        last_line = previous.rsplit("\n", 1)[-1].strip()

        # Respect explicit boundaries from the model.
        if prev_last.isspace() or next_first.isspace():
            return normalized

        # If previous chunk ended on a markdown heading line, start a new paragraph.
        # Guard against split heading words like ``## Key Find`` + ``ings``.
        if last_line.startswith("#"):
            heading_marks = len(last_line) - len(last_line.lstrip("#"))
            if 1 <= heading_marks <= 6:
                if prev_last.isalpha() and next_first.isalpha() and next_first.islower():
                    return normalized
                return "\n\n" + normalized

        # Preserve markdown/html boundaries.
        if next_first in "#<":
            return "\n" + normalized

        # Keep markdown list/table structures readable across chunk boundaries.
        if normalized.startswith(("|", "- ", "* ", "+ ")):
            return "\n" + normalized

        # Preserve readable token boundaries after markdown delimiters.
        if previous.endswith("**") and next_first.isalnum():
            return " " + normalized

        # Heading marker split across chunks, e.g. "###" + "1. ..."
        if prev_last == "#" and (next_first.isdigit() or next_first.isalpha()):
            return " " + normalized

        # Human-readable token boundaries.
        if (prev_last.isalpha() and next_first.isdigit()) or (
            prev_last.isdigit() and next_first.isalpha()
        ):
            return " " + normalized

        return normalized

    def accumulate(
        self,
        event_type: str,
        content: str,
        *,
        namespace: tuple[str, ...] = (),
        is_chunk: bool = True,
    ) -> str | None:
        """Accumulate streaming chunk and return displayable text.

        Boundary Preservation:
        - is_chunk=True: Return raw content (preserve boundaries)
        - is_chunk=False: Return accumulated text (final message)

        Args:
            event_type: Event type string (RFC-403 naming).
            content: Raw content chunk (may have boundary whitespace).
            namespace: Namespace tuple for concurrent stream isolation.
            is_chunk: True if partial chunk, False if final message.

        Returns:
            Displayable text with preserved boundaries, or None if empty.
        """
        key = (event_type, namespace)

        # Initialize new stream if needed
        if key not in self.streams:
            self.streams[key] = StreamingAccumState(namespace=namespace)

        state = self.streams[key]

        # Handle final message (non-chunk)
        if not is_chunk:
            state.is_active = False
            # Accumulate final content
            if content:
                stitched = self._stitch_boundary(state.accumulated_text, content)
                state.accumulated_text += stitched
                state.chunk_count += 1
            # Return full accumulated text
            return state.accumulated_text.strip() if state.accumulated_text else None

        # Handle streaming chunk
        if not state.is_active:
            return None  # Stream already finalized

        # Accumulate chunk content
        if content:
            stitched = self._stitch_boundary(state.accumulated_text, content)
            state.accumulated_text += stitched
            state.chunk_count += 1

            # Return chunk with boundary preservation
            if self.boundary_preserve_enabled:
                return stitched  # Preserve/repair boundaries at stream edge only
            else:
                return stitched.strip()  # Clean boundaries

        return None

    def finalize_stream(
        self,
        event_type: str,
        *,
        namespace: tuple[str, ...] = (),
    ) -> str | None:
        """Finalize stream and return final accumulated text.

        Args:
            event_type: Event type string.
            namespace: Namespace tuple.

        Returns:
            Final accumulated text or None if stream empty.
        """
        key = (event_type, namespace)
        if key not in self.streams:
            return None

        state = self.streams[key]
        state.is_active = False

        return state.accumulated_text.strip() if state.accumulated_text else None

    def finalize_all(self) -> None:
        """Finalize all active streams (call on turn end)."""
        for state in self.streams.values():
            state.is_active = False

    def clear(self) -> None:
        """Clear all accumulated state (call after finalizing)."""
        self.streams.clear()
