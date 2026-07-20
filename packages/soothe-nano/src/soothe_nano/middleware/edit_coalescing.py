"""Edit coalescing middleware for batched file operations (IG-517).

Collects parallel edit tool calls within a detection window, groups them by file,
and merges same-file edits into a single batched operation. This eliminates:
- Race conditions from concurrent edits to the same file
- Middleware overhead (batched calls skip ~12 middleware via fast path)
- Redundant file reads (single read per file for all merged edits)

Architecture:
    Position: After policy/skill, before NetworkToolErrorsMiddleware (position ~3)
    Detection Window: 50ms to collect incoming edits
    Merge Strategy: deletions → insertions → replacements (descending by line)
    Conflict Handling: Reject overlapping edits with EditConflictError
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from soothe_nano.filesystem._lock_registry import FileEditLockRegistry
from soothe_nano.filesystem.protocol import BatchedEditOperation

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain.agents.middleware.types import ToolCallRequest
    from langgraph.types import Command

logger = logging.getLogger(__name__)

# Detection window in milliseconds
DEFAULT_DETECTION_WINDOW_MS: int = 50

# Default staging buffer limits
DEFAULT_STAGING_BUFFER_MAX_ENTRIES: int = 64
DEFAULT_STAGING_BUFFER_EVICTION_POLICY: str = "reject_newest"

# Edit tools that are coalesced
EDIT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "edit_file",
        "edit_lines",
        "insert_lines",
        "delete_lines",
    }
)

# Path argument keys to extract file path from tool args
_PATH_ARG_KEYS: tuple[str, ...] = ("path", "file_path", "filepath", "file")

# Valid eviction policies for the staging buffer
_VALID_EVICTION_POLICIES: frozenset[str] = frozenset({"reject_newest", "evict_oldest"})

_EDIT_RETRY_HINT = " Re-read the file with read_file and retry with exact surrounding context including whitespace."


def _edit_old_string_not_found_message(file_path: str, old_string: str) -> str:
    return (
        f"Error: EDIT_OLD_STRING_NOT_FOUND in {file_path}. "
        f"old_string not found (len={len(old_string)}).{_EDIT_RETRY_HINT}"
    )


def _edit_multiple_matches_message(file_path: str, count: int) -> str:
    return (
        f"Error: EDIT_MULTIPLE_MATCHES in {file_path} ({count} matches). "
        "Add more surrounding context to old_string or set replace_all=true."
    )


@dataclass
class PendingEdit:
    """A pending edit operation waiting to be coalesced."""

    tool_call_id: str
    tool_name: str
    file_path: str
    args: dict[str, Any]
    result_future: asyncio.Future[ToolMessage | Command[Any]]
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    request: ToolCallRequest


def _resolve_edit_future(
    edit: PendingEdit,
    result: ToolMessage | Command[Any],
) -> None:
    """Deliver a coalesced tool result unless the graph stream already resolved the waiter."""
    if edit.result_future.done():
        logger.debug(
            "Coalesced edit result dropped for %s (future already resolved)",
            edit.tool_call_id,
        )
        return
    edit.result_future.set_result(result)


@dataclass
class StringReplacement:
    """A single string-replacement operation for the staging buffer.

    Attributes:
        old_string: The exact text to find in the file.
        new_string: The replacement text.
        replace_all: If True, replace all occurrences; if False, the
            old_string must be unique in the file.
        tool_call_id: ID of the original tool call this replacement came from.
    """

    old_string: str
    new_string: str
    replace_all: bool = False
    tool_call_id: str = ""


@dataclass
class EditCoalescingConfig:
    """Configuration for edit coalescing middleware.

    Attributes:
        detection_window_ms: Detection window in milliseconds during which
            incoming edit tool calls are collected before being batched.
        staging_buffer_max_entries: Maximum number of string-replacement
            entries the staging buffer can hold per file before eviction
            kicks in.
        staging_buffer_eviction_policy: Policy when the staging buffer
            exceeds max entries. ``reject_newest`` rejects the incoming
            entry (default); ``evict_oldest`` drops the oldest entry.
    """

    detection_window_ms: int = DEFAULT_DETECTION_WINDOW_MS
    staging_buffer_max_entries: int = DEFAULT_STAGING_BUFFER_MAX_ENTRIES
    staging_buffer_eviction_policy: str = DEFAULT_STAGING_BUFFER_EVICTION_POLICY

    def __post_init__(self) -> None:
        """Validate config fields after initialization."""
        if self.detection_window_ms <= 0:
            raise ValueError(
                f"detection_window_ms must be positive, got {self.detection_window_ms}"
            )
        if self.staging_buffer_max_entries <= 0:
            raise ValueError(
                f"staging_buffer_max_entries must be positive, "
                f"got {self.staging_buffer_max_entries}"
            )
        if self.staging_buffer_eviction_policy not in _VALID_EVICTION_POLICIES:
            raise ValueError(
                f"staging_buffer_eviction_policy must be one of "
                f"{sorted(_VALID_EVICTION_POLICIES)}, "
                f"got {self.staging_buffer_eviction_policy!r}"
            )


@dataclass
class EditBatch:
    """A batch of edits for a single file."""

    file_path: str
    edits: list[PendingEdit] = field(default_factory=list)

    def to_operations(self) -> list[BatchedEditOperation]:
        """Convert pending edits to BatchedEditOperation list.

        Operations are ordered: deletions → insertions → replacements.
        Replacements are sorted by line number descending.
        """
        deletions = []
        insertions = []
        replacements = []

        for edit in self.edits:
            if edit.tool_name == "delete_lines":
                deletions.append(
                    BatchedEditOperation(
                        operation_type="delete",
                        start_line=edit.args.get("start", 1),
                        end_line=edit.args.get("end", 1),
                        original_call_id=edit.tool_call_id,
                    )
                )
            elif edit.tool_name == "insert_lines":
                insertions.append(
                    BatchedEditOperation(
                        operation_type="insert",
                        start_line=edit.args.get("line", 1),
                        end_line=edit.args.get("line", 1) - 1,  # Insert mode marker
                        content=edit.args.get("content", ""),
                        original_call_id=edit.tool_call_id,
                    )
                )
            elif edit.tool_name == "edit_lines":
                replacements.append(
                    BatchedEditOperation(
                        operation_type="replace",
                        start_line=edit.args.get("start", 1),
                        end_line=edit.args.get("end", 1),
                        content=edit.args.get("new_content", ""),
                        original_call_id=edit.tool_call_id,
                    )
                )

        # Sort replacements by line number descending (bottom-to-top preserves indices)
        replacements.sort(key=lambda op: op.start_line, reverse=True)

        # Return in order: deletions → insertions → replacements
        return deletions + insertions + replacements


class EditConflictError(Exception):
    """Raised when edits have overlapping ranges.

    This covers both line-range overlaps (for edit_lines / insert_lines /
    delete_lines) and string-replacement overlaps (for edit_file where one
    edit's old_string spans text that another edit also modifies).
    """

    def __init__(
        self,
        file_path: str,
        conflicting_ranges: list[tuple[int, int]],
        edit_ids: list[str],
    ) -> None:
        self.file_path = file_path
        self.conflicting_ranges = conflicting_ranges
        self.edit_ids = edit_ids
        super().__init__(f"Edit conflict in {file_path}: overlapping ranges {conflicting_ranges}")


class EditCoalescingMiddleware(AgentMiddleware):
    """Coalesces parallel edits to same file into batched operations.

    Eliminates race conditions and reduces middleware overhead for parallel
    file edits by collecting, grouping, and merging operations.

    Detection Window:
        - Collects incoming edit tool calls for detection_window_ms
        - Groups edits by target file path
        - Merges same-file edits into single batched operation

    Staging Buffer (edit_file string replacements):
        - edit_file calls accumulate (old_string, new_string, replace_all)
          tuples in a per-file staging buffer during the detection window
        - After the window, all replacements for a file are applied in a
          single read-modify-write cycle via the backend's atomic write path
        - Overlapping string replacements are rejected with EditConflictError

    Fast Path:
        - Batched calls dispatched with `_batched=True` metadata
        - Downstream middleware skip non-essential work for batched ops

    Conflict Handling:
        - Overlapping line ranges → reject with EditConflictError
        - Overlapping string replacements → reject with EditConflictError
        - Successful edits proceed, failed edits get error ToolMessage

    Lock Serialization:
        - FileEditLockRegistry serializes batch dispatch per-file, ensuring
          the coalesced write is protected from concurrent non-coalesced writes
    """

    name = "EditCoalescingMiddleware"

    def __init__(
        self,
        *,
        config: EditCoalescingConfig | None = None,
        lock_registry: FileEditLockRegistry | None = None,
    ) -> None:
        """Initialize edit coalescing middleware.

        Args:
            config: Configuration object. If None, a default
                ``EditCoalescingConfig`` is used.
            lock_registry: External ``FileEditLockRegistry`` for serializing
                per-file batch dispatch. If None, a new registry is created.
        """
        self._config = config or EditCoalescingConfig()

        self._detection_window_ms = self._config.detection_window_ms
        self._pending_edits: dict[str, list[PendingEdit]] = {}
        # Staging buffer: path -> list of (old_string, new_string, replace_all)
        self._staging_buffer: dict[str, list[StringReplacement]] = {}
        self._window_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._lock_registry = lock_registry or FileEditLockRegistry()

    def _is_edit_tool(self, tool_name: str) -> bool:
        """Check if tool is an edit operation that should be coalesced."""
        return tool_name in EDIT_TOOL_NAMES

    def _extract_file_path(self, tool_args: dict[str, Any]) -> str | None:
        """Extract file path from tool arguments."""
        for key in _PATH_ARG_KEYS:
            path = tool_args.get(key)
            if isinstance(path, str) and path:
                return path
        return None

    def _get_context_backend(self) -> Any | None:
        """Get cached backend for the current workspace context."""
        from soothe_nano.workspace.workspace_filesystem import get_workspace_backend
        from soothe_nano.workspace.workspace_runtime import get_workspace_context

        ctx = get_workspace_context()
        if ctx.workspace is None:
            return None

        return get_workspace_backend(
            workspace=ctx.workspace,
            virtual_mode=ctx.virtual_mode,
        )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Intercept edit tool calls and coalesce them.

        Non-edit tools pass through immediately.
        edit_file (string-replacement) calls are accumulated in the staging
        buffer and dispatched as a single atomic batch after the detection
        window.
        Other edit tools (edit_lines, insert_lines, delete_lines) are
        collected, grouped, and batched after the detection window.

        Args:
            request: Tool call request.
            handler: Next handler in middleware chain.

        Returns:
            ToolMessage or Command from batched execution.
        """
        tool_call = request.tool_call or {}
        tool_name = str(tool_call.get("name", ""))

        # Non-edit tools pass through immediately
        if not self._is_edit_tool(tool_name):
            return await handler(request)

        # Extract file path from tool args
        tool_args = tool_call.get("args", {})
        if not isinstance(tool_args, dict):
            return await handler(request)

        file_path = self._extract_file_path(tool_args)
        if not file_path:
            return await handler(request)

        tool_call_id = str(tool_call.get("id", ""))

        # edit_file uses the string-replacement staging buffer
        if tool_name == "edit_file":
            old_string = str(tool_args.get("old_string", ""))
            new_string = str(tool_args.get("new_string", ""))
            replace_all = bool(tool_args.get("replace_all", False))

            # Create future for result (will be filled after batch execution)
            result_future: asyncio.Future[ToolMessage | Command[Any]] = asyncio.Future()

            pending_edit = PendingEdit(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                file_path=file_path,
                args=tool_args,
                result_future=result_future,
                handler=handler,
                request=request,
            )

            async with self._lock:
                # Check staging buffer capacity / eviction
                entries = self._staging_buffer.setdefault(file_path, [])
                if len(entries) >= self._config.staging_buffer_max_entries:
                    policy = self._config.staging_buffer_eviction_policy
                    if policy == "reject_newest":
                        result_future.set_result(
                            ToolMessage(
                                content=(
                                    f"Error: Staging buffer full for {file_path}. "
                                    f"Maximum {self._config.staging_buffer_max_entries} "
                                    f"entries. Submit edits sequentially."
                                ),
                                tool_call_id=tool_call_id,
                                name=tool_name,
                                status="error",
                            )
                        )
                        return await result_future
                    elif policy == "evict_oldest":
                        entries.pop(0)
                        logger.debug(
                            "Evicted oldest staging buffer entry for %s",
                            file_path,
                        )

                entries.append(
                    StringReplacement(
                        old_string=old_string,
                        new_string=new_string,
                        replace_all=replace_all,
                        tool_call_id=tool_call_id,
                    )
                )

                # Also track in pending_edits so _process_after_window picks it up
                if file_path not in self._pending_edits:
                    self._pending_edits[file_path] = []
                self._pending_edits[file_path].append(pending_edit)

                # Start detection window if not running
                if self._window_task is None:
                    self._window_task = asyncio.create_task(self._process_after_window())

            # Wait for result (filled by batch execution)
            return await result_future

        # Other edit tools (edit_lines, insert_lines, delete_lines)
        # Create future for result (will be filled after batch execution)
        result_future: asyncio.Future[ToolMessage | Command[Any]] = asyncio.Future()

        # Add to pending queue
        pending_edit = PendingEdit(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            file_path=file_path,
            args=tool_args,
            result_future=result_future,
            handler=handler,
            request=request,
        )

        async with self._lock:
            if file_path not in self._pending_edits:
                self._pending_edits[file_path] = []
            self._pending_edits[file_path].append(pending_edit)

            # Start detection window if not running
            if self._window_task is None:
                self._window_task = asyncio.create_task(self._process_after_window())

        # Wait for result (filled by batch execution)
        return await result_future

    async def _process_after_window(self) -> None:
        """Process pending edits after detection window closes."""
        await asyncio.sleep(self._detection_window_ms / 1000.0)

        async with self._lock:
            pending = self._pending_edits.copy()
            self._pending_edits.clear()
            staging = self._staging_buffer.copy()
            self._staging_buffer.clear()
            self._window_task = None

        if not pending:
            return

        # Process each file's batch
        for file_path, edits in pending.items():
            # Separate edit_file (string replacement) from line-based edits
            string_edits = [e for e in edits if e.tool_name == "edit_file"]
            line_edits = [e for e in edits if e.tool_name != "edit_file"]

            # Dispatch string-replacement batch if any
            if string_edits:
                if len(string_edits) == 1:
                    await self._dispatch_single_string_edit(string_edits[0])
                else:
                    replacements = staging.get(file_path, [])
                    await self._dispatch_string_replacements(file_path, string_edits, replacements)

            # Dispatch line-based batch if any
            if line_edits:
                await self._dispatch_batched_edits(file_path, line_edits)

    async def _dispatch_single_string_edit(self, edit: PendingEdit) -> None:
        """Pass a lone edit_file call through to the direct handler."""
        try:
            result = await edit.handler(edit.request)
        except Exception as e:
            logger.warning("Single edit_file pass-through failed for %s: %s", edit.file_path, e)
            result = ToolMessage(
                content=f"Error: {e}",
                tool_call_id=edit.tool_call_id,
                name=edit.tool_name,
                status="error",
            )
        _resolve_edit_future(edit, result)

    async def _dispatch_string_replacements(
        self,
        file_path: str,
        edits: list[PendingEdit],
        replacements: list[StringReplacement],
    ) -> None:
        """Dispatch coalesced string-replacement edits for a single file.

        Reads the file once, applies all string replacements sequentially in
        memory, and writes the result via a single atomic write. The entire
        read-modify-write cycle is protected by the per-file lock from
        ``FileEditLockRegistry``.

        Args:
            file_path: Target file path.
            edits: List of pending edit_file edits for this file.
            replacements: Staged string replacements for this file.
        """
        try:
            async with self._lock_registry.acquire(file_path):
                content = await self._read_file_for_batch(file_path)

                # Detect overlap against the authoritative in-lock content.
                if self._find_string_overlaps(content, replacements):
                    for edit in edits:
                        _resolve_edit_future(
                            edit,
                            ToolMessage(
                                content=(
                                    f"Error: Edit conflict in {file_path}. "
                                    "Overlapping string replacements detected. "
                                    "Submit edits sequentially to avoid conflicts."
                                ),
                                tool_call_id=edit.tool_call_id,
                                name=edit.tool_name,
                                status="error",
                            ),
                        )
                    return

                outcomes: dict[str, tuple[bool, str]] = {}
                applied_any = False
                for replacement in replacements:
                    old_string = replacement.old_string
                    new_string = replacement.new_string
                    replace_all = replacement.replace_all
                    call_id = replacement.tool_call_id or ""
                    if old_string not in content:
                        outcomes[call_id] = (
                            False,
                            _edit_old_string_not_found_message(file_path, old_string),
                        )
                        continue
                    count = content.count(old_string)
                    if count > 1 and not replace_all:
                        outcomes[call_id] = (
                            False,
                            _edit_multiple_matches_message(file_path, count),
                        )
                        continue
                    if replace_all:
                        content = content.replace(old_string, new_string)
                    else:
                        content = content.replace(old_string, new_string, 1)
                    applied_any = True
                    outcomes[call_id] = (
                        True,
                        f"String replacement applied to {file_path}.",
                    )

                if applied_any:
                    await self._atomic_write(file_path, content)

            replacement_by_call_id = {r.tool_call_id: r for r in replacements}
            for edit in edits:
                call_id = edit.tool_call_id
                if call_id in outcomes:
                    ok, message = outcomes[call_id]
                elif call_id in replacement_by_call_id:
                    ok, message = (
                        False,
                        _edit_old_string_not_found_message(
                            file_path,
                            replacement_by_call_id[call_id].old_string,
                        ),
                    )
                else:
                    ok, message = (
                        False,
                        f"Error: EDIT_OLD_STRING_NOT_FOUND in {file_path}. No replacement staged.",
                    )
                _resolve_edit_future(
                    edit,
                    ToolMessage(
                        content=message,
                        tool_call_id=edit.tool_call_id,
                        name=edit.tool_name,
                        status="error" if not ok else "success",
                    ),
                )

        except Exception as e:
            logger.warning("Batched string replacement failed for %s: %s", file_path, e)
            for edit in edits:
                _resolve_edit_future(
                    edit,
                    ToolMessage(
                        content=f"Error: {e}",
                        tool_call_id=edit.tool_call_id,
                        name=edit.tool_name,
                        status="error",
                    ),
                )

    async def _read_file_for_batch(self, file_path: str) -> str:
        """Read file content for batch processing.

        Uses workspace backend when context is available; otherwise reads directly.

        Args:
            file_path: Path to the file to read.

        Returns:
            File content as a string.

        Raises:
            Exception: If the file cannot be read.
        """
        backend = self._get_context_backend()
        if backend is not None:
            result = await backend.aread(file_path)
            error = getattr(result, "error", None)
            if error:
                raise RuntimeError(str(error))

            file_data = getattr(result, "file_data", None)
            if isinstance(file_data, dict):
                return str(file_data.get("content", ""))
            if isinstance(file_data, str):
                return file_data

            content = getattr(result, "content", None)
            if isinstance(content, str):
                return content

            return ""

        # Direct file read fallback
        import aiofiles

        async with aiofiles.open(file_path, encoding="utf-8") as f:
            return await f.read()

    async def _atomic_write(self, file_path: str, content: str) -> None:
        """Write content atomically via the backend's write path.

        Uses workspace backend's ``awrite`` when context is available; otherwise
        falls back to direct temp-file + ``os.replace``.

        Args:
            file_path: Path to the file to write.
            content: Content to write.

        Raises:
            Exception: If the write fails.
        """
        backend = self._get_context_backend()
        if backend is not None:
            result = await backend.awrite(file_path, content)
            error = getattr(result, "error", None)
            if error:
                raise RuntimeError(str(error))
            return

        # Direct write fallback (still atomic via temp + rename)
        import os
        import tempfile

        dir_path = os.path.dirname(os.path.abspath(file_path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".edit_coalesce_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, file_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _find_string_overlaps(
        self,
        content: str,
        replacements: list[StringReplacement],
    ) -> tuple[set[str], list[tuple[int, int]]] | None:
        """Detect overlapping string-replacement ranges.

        For each replacement, the character range of ``old_string`` in the
        content is computed. If two replacements' ranges overlap (one edit's
        old_string spans text that another edit also modifies), the batch is
        considered conflicting.

        Args:
            content: Original file content.
            replacements: Staged string replacements for the file.

        Returns:
            Tuple of (conflicting call_ids, conflicting char ranges) if a
            conflict is found, otherwise None.
        """
        # Compute character ranges for each replacement
        ranges: list[tuple[int, int, str]] = []
        cursor = 0
        for replacement in replacements:
            old_string = replacement.old_string
            replace_all = replacement.replace_all
            call_id = replacement.tool_call_id
            if not old_string:
                continue
            if old_string not in content:
                # String not found — can't compute range, skip
                ranges.append((-1, -1, call_id))
                continue
            if replace_all:
                # For replace_all, find all occurrences and treat the full
                # span (first start to last end) as the range
                starts: list[int] = []
                search_from = 0
                while True:
                    idx = content.find(old_string, search_from)
                    if idx == -1:
                        break
                    starts.append(idx)
                    search_from = idx + len(old_string)
                if starts:
                    start = starts[0]
                    end = starts[-1] + len(old_string)
                    ranges.append((start, end, call_id))
            else:
                idx = content.find(old_string, cursor)
                if idx == -1:
                    idx = content.find(old_string)
                if idx != -1:
                    end = idx + len(old_string)
                    ranges.append((idx, end, call_id))
                    cursor = end

        # Check pairwise overlaps
        conflicting_ids: set[str] = set()
        conflicting_ranges: list[tuple[int, int]] = []
        for i, (start_a, end_a, id_a) in enumerate(ranges):
            if start_a == -1:
                continue
            for start_b, end_b, id_b in ranges[i + 1 :]:
                if start_b == -1:
                    continue
                if start_a < end_b and start_b < end_a:
                    conflicting_ids.add(id_a)
                    conflicting_ids.add(id_b)
                    conflicting_ranges.append((start_a, end_a))
                    conflicting_ranges.append((start_b, end_b))

        if conflicting_ids:
            return conflicting_ids, conflicting_ranges
        return None

    async def _dispatch_batched_edits(
        self,
        file_path: str,
        edits: list[PendingEdit],
    ) -> None:
        """Dispatch batched edits for a single file.

        Checks for overlaps, converts to operations, and executes via filesystem.

        Args:
            file_path: Target file path.
            edits: List of pending edits for this file.
        """
        # Check for overlapping ranges
        batch = EditBatch(file_path=file_path, edits=edits)
        operations = batch.to_operations()

        # Check overlaps in replacements
        overlaps = self._find_overlaps(operations)
        if overlaps:
            # Reject conflicting edits
            for edit in edits:
                if edit.tool_call_id in overlaps:
                    _resolve_edit_future(
                        edit,
                        ToolMessage(
                            content=f"Error: Edit conflict in {file_path}. "
                            f"Overlapping line ranges detected. "
                            f"Submit edits sequentially to avoid conflicts.",
                            tool_call_id=edit.tool_call_id,
                            name=edit.tool_name,
                            status="error",
                        ),
                    )
                else:
                    # Non-conflicting edits need re-processing
                    # For simplicity, reject entire batch on conflict
                    _resolve_edit_future(
                        edit,
                        ToolMessage(
                            content=f"Error: Edit conflict in {file_path}. "
                            f"Another edit in this batch had overlapping ranges. "
                            f"Submit edits sequentially to avoid conflicts.",
                            tool_call_id=edit.tool_call_id,
                            name=edit.tool_name,
                            status="error",
                        ),
                    )
            return

        # Execute batched operation
        try:
            backend = self._get_context_backend()
            if backend is None:
                # No workspace context, fall back to individual handlers
                for edit in edits:
                    result = await edit.handler(edit.request)
                    _resolve_edit_future(edit, result)
                return

            # Execute batched edit via async filesystem
            result = await backend.aedit_batched(file_path, operations, backup=True)

            # Map results back to original calls
            if result.error:
                # Batch failed - all edits get error
                for edit in edits:
                    _resolve_edit_future(
                        edit,
                        ToolMessage(
                            content=f"Error: {result.error}",
                            tool_call_id=edit.tool_call_id,
                            name=edit.tool_name,
                            status="error",
                        ),
                    )
            else:
                # Batch succeeded
                success_msg = (
                    f"Edit applied to {file_path}. "
                    f"{result.operations_applied} operations, "
                    f"{result.total_lines_changed} lines changed."
                )
                for edit in edits:
                    if result.failed_operations and edit.tool_call_id in result.failed_operations:
                        _resolve_edit_future(
                            edit,
                            ToolMessage(
                                content=f"Error: Operation failed for {file_path}",
                                tool_call_id=edit.tool_call_id,
                                name=edit.tool_name,
                                status="error",
                            ),
                        )
                    else:
                        _resolve_edit_future(
                            edit,
                            ToolMessage(
                                content=success_msg,
                                tool_call_id=edit.tool_call_id,
                                name=edit.tool_name,
                            ),
                        )

        except Exception as e:
            logger.warning("Batched edit failed for %s: %s", file_path, e)
            for edit in edits:
                _resolve_edit_future(
                    edit,
                    ToolMessage(
                        content=f"Error: {e}",
                        tool_call_id=edit.tool_call_id,
                        name=edit.tool_name,
                        status="error",
                    ),
                )

    def _find_overlaps(self, operations: list[BatchedEditOperation]) -> set[str]:
        """Find overlapping edit operations.

        Returns set of original_call_ids that conflict.
        """
        conflicting_ids: set[str] = set()

        # Check replacements for overlaps
        replacements = [op for op in operations if op.operation_type == "replace"]
        for i, op_a in enumerate(replacements):
            for op_b in replacements[i + 1 :]:
                if self._ranges_overlap(op_a, op_b):
                    conflicting_ids.add(op_a.original_call_id or "")
                    conflicting_ids.add(op_b.original_call_id or "")

        return conflicting_ids

    def _ranges_overlap(
        self,
        a: BatchedEditOperation,
        b: BatchedEditOperation,
    ) -> bool:
        """Check if two edit operations have overlapping line ranges."""
        return a.start_line <= b.end_line and b.start_line <= a.end_line


__all__ = [
    "DEFAULT_DETECTION_WINDOW_MS",
    "DEFAULT_STAGING_BUFFER_MAX_ENTRIES",
    "DEFAULT_STAGING_BUFFER_EVICTION_POLICY",
    "EDIT_TOOL_NAMES",
    "EditBatch",
    "EditCoalescingConfig",
    "EditCoalescingMiddleware",
    "EditConflictError",
    "PendingEdit",
    "StringReplacement",
]
