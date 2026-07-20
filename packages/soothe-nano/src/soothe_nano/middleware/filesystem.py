"""SootheFilesystemMiddleware -- surgical file operations."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from langchain.tools import ToolRuntime
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from soothe_deepagents.backends.protocol import BackendProtocol
from soothe_deepagents.middleware.filesystem import FilesystemMiddleware

from soothe_nano.filesystem.discovery_hints import GLOB_TOOL_DESCRIPTION

if TYPE_CHECKING:
    from soothe_deepagents.middleware.filesystem import ApplyDiffSchema as ApplyDiffSchema

__all__ = [
    "ApplyDiffSchema",
    "SootheFilesystemMiddleware",
    "coerce_provider_safe_tool_message",
]
logger = logging.getLogger(__name__)


def __getattr__(name: str) -> Any:
    """Lazy-export `ApplyDiffSchema` so module import does not hard-fail early.

    Daemon startup imports `SootheFilesystemMiddleware` only. Requiring
    `ApplyDiffSchema` at import time crashed environments that still had
    older soothe-deepagents installed even when the class was unused.
    """
    if name == "ApplyDiffSchema":
        try:
            from soothe_deepagents.middleware.filesystem import (
                ApplyDiffSchema,
            )
        except ImportError as exc:
            raise ImportError(_apply_diff_requirement_message()) from exc
        return ApplyDiffSchema
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _installed_deepagents_version() -> str:
    try:
        return version("soothe-deepagents")
    except PackageNotFoundError:
        return "unknown"


def _apply_diff_requirement_message() -> str:
    return (
        "Soothe filesystem tools require soothe-deepagents with "
        "ApplyDiffSchema / apply_diff support. "
        f"Installed soothe-deepagents version: {_installed_deepagents_version()}. "
        "Upgrade with: pip install -U soothe-deepagents"
    )


def _ensure_upstream_apply_diff_support() -> None:
    """Fail fast with a clear upgrade hint when apply_diff is unavailable."""
    filesystem_mod = getattr(FilesystemMiddleware, "__module__", "")
    try:
        from soothe_deepagents.middleware import filesystem as da_filesystem
    except ImportError as exc:
        raise ImportError(_apply_diff_requirement_message()) from exc

    if not hasattr(da_filesystem, "ApplyDiffSchema") or not hasattr(
        FilesystemMiddleware, "_create_apply_diff_tool"
    ):
        logger.warning(
            "Missing deepagents apply_diff support. %s", _apply_diff_requirement_message()
        )
        raise ImportError(f"{_apply_diff_requirement_message()} (module={filesystem_mod!r})")


# OpenAI-compatible chat APIs used by many Soothe providers (e.g. coding-plan) reject
# LangChain ``file`` / ``audio`` tool-result blocks. ``read_file`` on PDFs returns those.
_PROVIDER_SAFE_TOOL_BLOCK_TYPES = frozenset(
    {"text", "image", "image_url", "video", "video_url"},
)


def coerce_provider_safe_tool_message(
    message: ToolMessage | Command[Any],
) -> ToolMessage | Command[Any]:
    """Replace unsupported multimodal tool blocks with plain-text guidance.

    Deepagents ``read_file`` returns ``file`` blocks for PDFs and ``audio`` blocks for
    audio files. Providers that only accept ``text``, ``image_url``, and ``video*``
    then fail the next model turn with ``Invalid value: file``.

    Args:
        message: Tool result from filesystem middleware (or a Command wrapper).

    Returns:
        A copy of the message with unsafe blocks converted to text, or the original
        value when no conversion is needed.
    """
    if not isinstance(message, ToolMessage):
        return message

    blocks = message.content_blocks
    if not blocks:
        return message

    safe_blocks: list[dict[str, Any]] = []
    converted = False
    for block in blocks:
        block_type = block.get("type") if isinstance(block, dict) else None
        if block_type in _PROVIDER_SAFE_TOOL_BLOCK_TYPES:
            safe_blocks.append(block)
            continue

        converted = True
        path = message.additional_kwargs.get("read_file_path", "")
        mime = block.get("mime_type") if isinstance(block, dict) else None
        mime_part = f", mime_type={mime}" if mime else ""
        path_part = f" at {path}" if path else ""
        safe_blocks.append(
            {
                "type": "text",
                "text": (
                    "System reminder: read_file returned a document or media file"
                    f"{path_part} (block type={block_type!r}{mime_part}) that cannot be "
                    "sent inline to this chat model. Use goal attachment text, "
                    "run_command (e.g. pdftotext or a PDF parser), or paginated text "
                    "reads on extracted files instead of read_file on this path."
                ),
            }
        )

    if not converted:
        return message

    return message.model_copy(update={"content": safe_blocks})


class SootheFilesystemMiddleware(FilesystemMiddleware):
    """Extended filesystem middleware with surgical file operations.

    Inherits from FilesystemMiddleware and adds:
    - apply_diff: Apply unified diff patches

    All tools follow standard patterns:
    - Schema validation with XxxSchema(BaseModel)
    - ToolRuntime injection for backend access
    - Path validation with validate_path()
    - StructuredTool.from_function() with infer_schema=False

    IG-328: Supports thread workspace resolution via runtime.state["workspace"]
    without using deprecated callable backend pattern.

    Args:
        backup_enabled: Backward-compatible no-op parameter retained for callers.
        backup_dir: Backward-compatible no-op parameter retained for callers.
        workspace_root: Root directory for workspace operations.
        workspace_backend_factory: Optional factory for creating workspace backends.
        **kwargs: Additional arguments passed to FilesystemMiddleware.
    """

    def __init__(
        self,
        *,
        backup_enabled: bool = True,
        backup_dir: str | None = None,
        workspace_root: str | None = None,
        workspace_backend_factory: Callable[[str], BackendProtocol] | None = None,
        **kwargs,
    ) -> None:
        """Initialize SootheFilesystemMiddleware.

        Args:
            backup_enabled: Enable automatic backup before deletion.
            backup_dir: Custom backup directory path (legacy no-op).
            workspace_root: Workspace root directory for path resolution.
            workspace_backend_factory: Factory function that takes a workspace path
                and returns a BackendProtocol instance. Used for thread workspace
                resolution without callable backend deprecation.
            **kwargs: Passed to FilesystemMiddleware (backend, system_prompt, etc.)
        """
        _ensure_upstream_apply_diff_support()
        custom_descriptions = dict(kwargs.pop("custom_tool_descriptions", None) or {})
        custom_descriptions.setdefault("glob", GLOB_TOOL_DESCRIPTION)
        kwargs["custom_tool_descriptions"] = custom_descriptions
        kwargs.setdefault(
            "tools",
            [
                "ls",
                "read_file",
                "write_file",
                "edit_file",
                "delete",
                "glob",
                "grep",
                "file_info",
                "edit_lines",
                "insert_lines",
                "delete_lines",
                "apply_diff",
            ],
        )
        kwargs.setdefault("large_tool_results_prefix", ".soothe/large_tool_results")
        kwargs.setdefault("conversation_history_prefix", ".soothe/conversation_history")
        super().__init__(**kwargs)
        if not any(getattr(tool, "name", None) == "apply_diff" for tool in self.tools):
            raise ImportError(_apply_diff_requirement_message())

        # Retain constructor compatibility while delegating delete behavior upstream.
        _ = backup_enabled, backup_dir
        self._workspace_root = workspace_root
        self._workspace_backend_factory = workspace_backend_factory

    def _get_backend(self, runtime: ToolRuntime | None = None) -> BackendProtocol:
        """Get backend, resolving the effective stream workspace when available.

        Args:
            runtime: Tool runtime with config/state containing potential thread workspace.

        Returns:
            BackendProtocol instance for the effective workspace.
        """
        from soothe_nano.workspace.workspace_api import (
            resolve_workspace_for_tool_execution,
        )
        from soothe_nano.workspace.workspace_filesystem import get_workspace_backend

        workspace = resolve_workspace_for_tool_execution(
            runtime=runtime,
            fallback=self._workspace_root,
            use_langgraph_config=True,
        )
        if workspace is None:
            return self.backend

        ws_str = str(workspace)
        if self._workspace_backend_factory is not None:
            return self._workspace_backend_factory(ws_str)

        virtual_mode = bool(getattr(self.backend, "virtual_mode", False))
        max_mb = 10
        if runtime is not None and isinstance(getattr(runtime, "config", None), dict):
            configurable = runtime.config.get("configurable") or {}
            if isinstance(configurable, dict):
                soothe_config = configurable.get("soothe_config")
                if soothe_config is not None:
                    from soothe_nano.workspace.workspace_paths import (
                        filesystem_virtual_mode_from_soothe_config,
                        max_file_size_mb_for_filesystem_backend,
                    )

                    virtual_mode = filesystem_virtual_mode_from_soothe_config(soothe_config)
                    max_mb = max_file_size_mb_for_filesystem_backend(soothe_config)

        return get_workspace_backend(
            workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_mb,
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Evict oversized tool results and coerce unsupported multimodal blocks.

        Keep this shim until upstream deepagents adds provider-safe coercion for
        unsupported tool-result block types.
        """
        result = super().wrap_tool_call(request, handler)
        return coerce_provider_safe_tool_message(result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Async variant of provider-safe multimodal block coercion shim."""
        result = await super().awrap_tool_call(request, handler)
        return coerce_provider_safe_tool_message(result)
