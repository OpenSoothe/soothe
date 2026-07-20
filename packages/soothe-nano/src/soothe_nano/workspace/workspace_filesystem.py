"""Workspace-aware filesystem backends and framework singleton."""

from __future__ import annotations

import logging
from contextvars import Token
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_deepagents.backends.protocol import (
    EditResult,
    FileData,
    LsResult,
    ReadResult,
    WriteResult,
)

if TYPE_CHECKING:
    from soothe_deepagents.backends.protocol import BackendProtocol

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_DEFAULT_READ_LINE_LIMIT = 2000


def _coerce_fs_grep_to_da_matches(result: Any) -> list[dict[str, Any]]:
    from soothe_nano.filesystem.protocol import GrepResult as FsGrepResult

    matches: list[dict[str, Any]] = []
    if isinstance(result, FsGrepResult):
        for match in result.matches:
            matches.append(
                {
                    "path": match.path,
                    "line": match.line_number,
                    "text": match.line_content,
                }
            )
    elif isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                matches.append(item)
            elif isinstance(item, str):
                matches.append({"path": item, "line": 0, "text": ""})
    elif isinstance(result, str) and result:
        for line in result.split("\n"):
            if line:
                matches.append({"path": line, "line": 0, "text": ""})
    return matches


def _read_result_for_path(
    fs: Any,
    normalized: str,
    *,
    offset: int,
    limit: int,
    display_path: str,
) -> ReadResult:
    from soothe_nano.filesystem.exceptions import (
        FilesystemError,
        NotAFileError,
        PathNotFoundError,
    )

    try:
        raw = fs.read(normalized)
    except PathNotFoundError:
        return ReadResult(error=f"File '{display_path}' not found")
    except NotAFileError:
        return ReadResult(error=f"File '{display_path}' not found")
    except FilesystemError as exc:
        return ReadResult(error=str(exc))

    if raw.is_binary:
        return ReadResult(file_data=FileData(content=raw.content, encoding="base64"))

    content = raw.content
    if not content:
        return ReadResult(file_data=FileData(content="", encoding="utf-8"))

    lines = content.splitlines(keepends=True)
    start_idx = max(offset, 0)
    end_idx = min(start_idx + limit, len(lines))
    if start_idx >= len(lines):
        return ReadResult(
            error=(
                f"Line offset {offset} exceeds file length ({len(lines)} lines). "
                f"Offset is 0-indexed: use offset={max(len(lines) - 1, 0)} to read the last line."
            ),
        )
    return ReadResult(
        file_data=FileData(content="".join(lines[start_idx:end_idx]), encoding="utf-8")
    )


class NormalizedPathBackend:
    """Wrapper that normalizes paths to workspace-relative."""

    def __init__(
        self,
        root_dir: Path,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        self._root_dir = Path(root_dir)
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb

        from soothe_nano.filesystem.workspace import WorkspaceFilesystem

        self._fs = WorkspaceFilesystem(
            workspace=root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    @property
    def cwd(self) -> str:
        return str(self._root_dir)

    @property
    def virtual_mode(self) -> bool:
        return self._virtual_mode

    def _normalize_path(self, path: str) -> str:
        if not path or path.strip() in {"", ".", "/"}:
            return "."

        expanded = Path(path.strip()).expanduser()
        if expanded.is_absolute():
            abs_str = str(expanded.resolve())
            try:
                rel = expanded.resolve().relative_to(self._root_dir.resolve())
            except ValueError:
                if self._virtual_mode:
                    from soothe_nano.workspace.workspace_paths import (
                        should_use_virtual_path_resolution,
                    )

                    if should_use_virtual_path_resolution(path.strip(), self._root_dir):
                        relative = abs_str.lstrip("/")
                        return relative or "."
                    return abs_str
                return abs_str
            if self._virtual_mode:
                return rel.as_posix()
            return abs_str
        return path.strip()

    def resolve_os_path(self, path: str) -> Path:
        normalized = self._normalize_path(path)
        return self._fs.resolve_path(normalized, allow_host_absolute=True)

    def read(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        normalized = self._normalize_path(path)
        line_limit = limit if limit is not None else _DEFAULT_READ_LINE_LIMIT
        return _read_result_for_path(
            self._fs,
            normalized,
            offset=offset,
            limit=line_limit,
            display_path=path,
        )

    async def aread(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        normalized = self._normalize_path(path)
        line_limit = limit if limit is not None else _DEFAULT_READ_LINE_LIMIT
        return _read_result_for_path(
            self._fs,
            normalized,
            offset=offset,
            limit=line_limit,
            display_path=path,
        )

    def write(self, path: str, content: str | bytes) -> WriteResult:
        from soothe_nano.filesystem.exceptions import FilesystemError

        normalized = self._normalize_path(path)
        try:
            result = self._fs.write(normalized, content)
        except FilesystemError as exc:
            return WriteResult(error=str(exc))
        return WriteResult(path=result.path)

    async def awrite(self, path: str, content: str | bytes) -> WriteResult:
        from soothe_nano.filesystem.exceptions import FilesystemError

        normalized = self._normalize_path(path)
        try:
            result = await self._fs.awrite(normalized, content)
        except FilesystemError as exc:
            return WriteResult(error=str(exc))
        return WriteResult(path=result.path)

    def edit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        edits: list[dict[str, Any]] | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        normalized = self._normalize_path(path)
        try:
            if edits:
                total_occurrences = 0
                for edit_item in edits:
                    old = edit_item.get("old_string", "")
                    new = edit_item.get("new_string", "")
                    result = self._fs.edit(normalized, old, new)
                    if hasattr(result, "error") and result.error:
                        return EditResult(error=result.error)
                    total_occurrences += 1
                return EditResult(path=normalized, occurrences=total_occurrences)
            if old_string is not None and new_string is not None:
                result = self._fs.edit(normalized, old_string, new_string)
                if hasattr(result, "error") and result.error:
                    return EditResult(error=result.error)
                return EditResult(path=normalized, occurrences=1)
            return EditResult(error="No edits provided")
        except Exception as e:
            logger.warning("edit error for %s: %s", path, e)
            return EditResult(error=str(e))

    async def aedit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        edits: list[dict[str, Any]] | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        normalized = self._normalize_path(path)
        try:
            if edits:
                total_occurrences = 0
                for edit_item in edits:
                    old = edit_item.get("old_string", "")
                    new = edit_item.get("new_string", "")
                    result = await self._fs.aedit(normalized, old, new)
                    if hasattr(result, "error") and result.error:
                        return EditResult(error=result.error)
                    total_occurrences += 1
                return EditResult(path=normalized, occurrences=total_occurrences)
            if old_string is not None and new_string is not None:
                result = await self._fs.aedit(normalized, old_string, new_string)
                if hasattr(result, "error") and result.error:
                    return EditResult(error=result.error)
                return EditResult(path=normalized, occurrences=1)
            return EditResult(error="No edits provided")
        except Exception as e:
            logger.warning("aedit error for %s: %s", path, e)
            return EditResult(error=str(e))

    async def aedit_batched(
        self,
        path: str,
        operations: list[Any],
        *,
        backup: bool = True,
    ) -> Any:
        from soothe_nano.filesystem.protocol import BatchedEditResult

        normalized = self._normalize_path(path)
        try:
            return await self._fs.aedit_batched(normalized, operations, backup=backup)
        except Exception as e:
            logger.warning("aedit_batched error for %s: %s", path, e)
            return BatchedEditResult(path=normalized, error=str(e))

    def ls(self, path: str = ".") -> LsResult:
        normalized = self._normalize_path(path)
        try:
            result = self._fs.ls(normalized, include_info=True)
            if isinstance(result, list) and result:
                entries = [
                    {
                        "path": item.path if hasattr(item, "path") else str(item),
                        "is_dir": item.is_dir if hasattr(item, "is_dir") else False,
                        "size": item.size if hasattr(item, "size") else 0,
                        "modified_at": (
                            item.modified_at.isoformat()
                            if hasattr(item, "modified_at") and item.modified_at
                            else None
                        ),
                    }
                    for item in result
                ]
            else:
                entries = []
            return LsResult(entries=entries)
        except Exception as e:
            logger.warning("ls error for %s: %s", path, e)
            return LsResult(error=str(e), entries=[])

    async def als(self, path: str = ".") -> LsResult:
        normalized = self._normalize_path(path)
        try:
            result = await self._fs.als(normalized, include_info=True)
            if isinstance(result, list) and result:
                entries = [
                    {
                        "path": item.path if hasattr(item, "path") else str(item),
                        "is_dir": item.is_dir if hasattr(item, "is_dir") else False,
                        "size": item.size if hasattr(item, "size") else 0,
                        "modified_at": (
                            item.modified_at.isoformat()
                            if hasattr(item, "modified_at") and item.modified_at
                            else None
                        ),
                    }
                    for item in result
                ]
            else:
                entries = []
            return LsResult(entries=entries)
        except Exception as e:
            logger.warning("als error for %s: %s", path, e)
            return LsResult(error=str(e), entries=[])

    def ls_info(self, path: str = ".") -> list[dict[str, Any]]:
        normalized = self._normalize_path(path)
        result = self._fs.ls(normalized, include_info=True)
        if not result:
            return []
        if isinstance(result[0], str):
            return [{"path": p, "is_dir": False} for p in result]
        return [
            {
                "path": item.path,
                "is_dir": item.is_dir,
                "size": item.size,
                "modified_at": item.modified_at.isoformat() if item.modified_at else None,
            }
            for item in result
        ]

    async def als_info(self, path: str = ".") -> list[dict[str, Any]]:
        normalized = self._normalize_path(path)
        result = await self._fs.als(normalized, include_info=True)
        if not result:
            return []
        if isinstance(result[0], str):
            return [{"path": p, "is_dir": False} for p in result]
        return [
            {
                "path": item.path,
                "is_dir": item.is_dir,
                "size": item.size,
                "modified_at": item.modified_at.isoformat() if item.modified_at else None,
            }
            for item in result
        ]

    def glob(self, pattern: str, path: str = "/") -> Any:
        from soothe_deepagents.backends.protocol import GlobResult as DaGlobResult

        normalized = self._normalize_path(path)
        result = self._fs.glob(pattern, path=normalized)
        file_infos = [{"path": p, "is_dir": False} for p in (result.matches or [])]
        return DaGlobResult(error=result.error, matches=file_infos)

    async def aglob(self, pattern: str, path: str = "/") -> Any:
        from soothe_deepagents.backends.protocol import GlobResult as DaGlobResult

        normalized = self._normalize_path(path)
        result = await self._fs.aglob(pattern, path=normalized)
        file_infos = [{"path": p, "is_dir": False} for p in (result.matches or [])]
        return DaGlobResult(error=result.error, matches=file_infos)

    def grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        from soothe_deepagents.backends.protocol import GrepResult as DaGrepResult

        from soothe_nano.filesystem.protocol import GrepResult as FsGrepResult

        normalized = self._normalize_path(path)
        try:
            result = self._fs.grep(pattern, path=normalized, glob=glob, output_mode=output_mode)
            matches = _coerce_fs_grep_to_da_matches(result)
            error: str | None = None
            if isinstance(result, FsGrepResult):
                error = result.error
            return DaGrepResult(error=error, matches=matches)
        except Exception as e:
            logger.warning("grep error for %s: %s", path, e)
            return DaGrepResult(error=str(e), matches=None)

    async def agrep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        from soothe_deepagents.backends.protocol import GrepResult as DaGrepResult

        from soothe_nano.filesystem.protocol import GrepResult as FsGrepResult

        normalized = self._normalize_path(path)
        try:
            result = await self._fs.agrep(
                pattern, path=normalized, glob=glob, output_mode=output_mode
            )
            matches = _coerce_fs_grep_to_da_matches(result)
            error: str | None = None
            if isinstance(result, FsGrepResult):
                error = result.error
            return DaGrepResult(error=error, matches=matches)
        except Exception as e:
            logger.warning("agrep error for %s: %s", path, e)
            return DaGrepResult(error=str(e), matches=None)

    def delete(self, path: str) -> str:
        normalized = self._normalize_path(path)
        self._fs.delete(normalized)
        return normalized

    async def adelete(self, path: str) -> str:
        normalized = self._normalize_path(path)
        await self._fs.adelete(normalized)
        return normalized

    def exists(self, path: str) -> bool:
        return self._fs.exists(self._normalize_path(path))

    def is_file(self, path: str) -> bool:
        return self._fs.is_file(self._normalize_path(path))

    def is_dir(self, path: str) -> bool:
        return self._fs.is_dir(self._normalize_path(path))


class WorkspaceAwareBackend:
    """Filesystem backend that resolves workspace from context."""

    def __init__(
        self,
        default_root_dir: Path,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        self._default_root_dir = default_root_dir
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb
        self._default_backend = NormalizedPathBackend(
            root_dir=default_root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    def __call__(self, runtime: Any) -> NormalizedPathBackend:
        from soothe_nano.workspace.workspace_api import resolve_workspace_for_tool_execution

        workspace = resolve_workspace_for_tool_execution(
            runtime=runtime,
            fallback=self._default_backend._root_dir,
            use_langgraph_config=True,
        )
        if workspace is not None:
            return get_workspace_backend(
                workspace=workspace,
                virtual_mode=self._virtual_mode,
                max_file_size_mb=self._max_file_size_mb,
            )
        return self._default_backend

    def _get_backend(self) -> NormalizedPathBackend:
        from soothe_nano.workspace.workspace_runtime import get_workspace_context

        current_workspace = get_workspace_context().workspace
        if current_workspace:
            return get_workspace_backend(
                workspace=current_workspace,
                virtual_mode=self._virtual_mode,
                max_file_size_mb=self._max_file_size_mb,
            )
        return self._default_backend

    def read(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        return self._get_backend().read(path, offset, limit)

    async def aread(self, path: str, offset: int = 0, limit: int | None = None) -> ReadResult:
        return await self._get_backend().aread(path, offset, limit)

    def write(self, path: str, content: str | bytes) -> WriteResult:
        return self._get_backend().write(path, content)

    async def awrite(self, path: str, content: str | bytes) -> WriteResult:
        return await self._get_backend().awrite(path, content)

    def edit(
        self,
        path: str,
        edits: list[dict[str, Any]] | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        if edits:
            return self._get_backend().edit(path, edits=edits, replace_all=replace_all)
        return self._get_backend().edit(
            path, old_string=old_string, new_string=new_string, replace_all=replace_all
        )

    async def aedit(
        self,
        path: str,
        edits: list[dict[str, Any]] | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        if edits:
            return await self._get_backend().aedit(path, edits=edits, replace_all=replace_all)
        return await self._get_backend().aedit(
            path, old_string=old_string, new_string=new_string, replace_all=replace_all
        )

    def ls(self, path: str = ".") -> LsResult:
        return self._get_backend().ls(path)

    async def als(self, path: str = ".") -> LsResult:
        return await self._get_backend().als(path)

    def ls_info(self, path: str = ".") -> list[dict[str, Any]]:
        return self._get_backend().ls_info(path)

    async def als_info(self, path: str = ".") -> list[dict[str, Any]]:
        return await self._get_backend().als_info(path)

    def glob(self, pattern: str, path: str = "/") -> Any:
        return self._get_backend().glob(pattern, path)

    async def aglob(self, pattern: str, path: str = "/") -> Any:
        return await self._get_backend().aglob(pattern, path)

    def grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        return self._get_backend().grep(pattern, path, output_mode, glob)

    async def agrep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        return await self._get_backend().agrep(pattern, path, output_mode, glob)

    def delete(self, path: str) -> str:
        return self._get_backend().delete(path)

    async def adelete(self, path: str) -> str:
        return await self._get_backend().adelete(path)


_backend_cache: dict[str, NormalizedPathBackend] = {}


def get_workspace_backend(
    workspace: Path,
    virtual_mode: bool = False,
    max_file_size_mb: int = 10,
) -> NormalizedPathBackend:
    """Get or create a cached NormalizedPathBackend for a workspace."""
    cache_key = f"{workspace}:{virtual_mode}:{max_file_size_mb}"
    if cache_key not in _backend_cache:
        _backend_cache[cache_key] = NormalizedPathBackend(
            root_dir=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
    return _backend_cache[cache_key]


def clear_workspace_backend_cache() -> None:
    """Clear the workspace backend cache."""
    _backend_cache.clear()


class FrameworkFilesystem:
    """Singleton filesystem backend for framework operations."""

    _instance: BackendProtocol | None = None

    @classmethod
    def initialize(
        cls,
        config: SootheConfig,
        policy: object | None = None,
    ) -> BackendProtocol:
        from soothe_nano.workspace.workspace_paths import (
            config_workspace_root,
            max_file_size_mb_for_filesystem_backend,
        )
        from soothe_nano.workspace.workspace_runtime import resolve_process_workspace_root

        configured_root = config_workspace_root(config)
        resolved_workspace = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else resolve_process_workspace_root()
        )
        virtual_mode = not config.security.allow_paths_outside_workspace
        max_file_size_mb = max_file_size_mb_for_filesystem_backend(config)
        cls._instance = WorkspaceAwareBackend(
            default_root_dir=resolved_workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        logger.info(
            "FrameworkFilesystem initialized: root=%s virtual_mode=%s (workspace-aware)",
            resolved_workspace,
            virtual_mode,
        )
        return cls._instance

    @classmethod
    def get(cls) -> BackendProtocol:
        if cls._instance is None:
            raise RuntimeError("FrameworkFilesystem not initialized. Call initialize() first.")
        return cls._instance

    @classmethod
    def set_current_workspace(cls, workspace: Path | str) -> Token:
        from soothe_nano.workspace.workspace_runtime import (
            get_workspace_context,
            set_workspace_context,
        )

        ws_path = Path(workspace) if isinstance(workspace, str) else workspace
        ctx = get_workspace_context()
        return set_workspace_context(workspace=ws_path, virtual_mode=ctx.virtual_mode)

    @classmethod
    def get_current_workspace(cls) -> Path | None:
        from soothe_nano.workspace.workspace_runtime import get_workspace_context

        return get_workspace_context().workspace

    @classmethod
    def clear_current_workspace(cls, token: Token | None = None) -> None:
        from soothe_nano.workspace.workspace_runtime import reset_workspace_context

        reset_workspace_context(token)
