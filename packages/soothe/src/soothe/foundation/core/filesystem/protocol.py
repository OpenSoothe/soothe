"""Protocol types for UnifiedFilesystem interface.

These types define the data structures used for filesystem operations,
providing a consistent interface across different backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FileInfo:
    """Information about a file or directory.

    Attributes:
        path: The file path (relative or absolute depending on context).
        is_dir: Whether this is a directory.
        size: File size in bytes (0 for directories).
        modified_at: Last modification time.
        created_at: Creation time (if available).
        permissions: File permissions as octal string (e.g., "644").
        mime_type: MIME type if detectable.
    """

    path: str
    is_dir: bool = False
    size: int = 0
    modified_at: datetime | None = None
    created_at: datetime | None = None
    permissions: str | None = None
    mime_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "path": self.path,
            "is_dir": self.is_dir,
            "size": self.size,
        }
        if self.modified_at:
            result["modified_at"] = self.modified_at.isoformat()
        if self.created_at:
            result["created_at"] = self.created_at.isoformat()
        if self.permissions:
            result["permissions"] = self.permissions
        if self.mime_type:
            result["mime_type"] = self.mime_type
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileInfo:
        """Create FileInfo from dictionary."""
        modified_at = None
        if data.get("modified_at"):
            modified_at = datetime.fromisoformat(data["modified_at"])
        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(data["created_at"])
        return cls(
            path=data["path"],
            is_dir=data.get("is_dir", False),
            size=data.get("size", 0),
            modified_at=modified_at,
            created_at=created_at,
            permissions=data.get("permissions"),
            mime_type=data.get("mime_type"),
        )


@dataclass(frozen=True)
class GlobResult:
    """Result of a glob operation.

    Attributes:
        matches: List of matching file paths.
        truncated: Whether results were truncated due to limits.
        total_count: Total number of matches before truncation.
        error: Error message if glob failed.
    """

    matches: list[str]
    truncated: bool = False
    total_count: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "matches": self.matches,
            "truncated": self.truncated,
        }
        if self.total_count is not None:
            result["total_count"] = self.total_count
        if self.error:
            result["error"] = self.error
        return result


@dataclass(frozen=True)
class ReadResult:
    """Result of a file read operation.

    Attributes:
        content: The file content (text or base64-encoded binary).
        is_binary: Whether the content is binary.
        encoding: The encoding used for text content.
        truncated: Whether content was truncated.
        total_size: Total file size before truncation.
        mime_type: MIME type of the file.
    """

    content: str
    is_binary: bool = False
    encoding: str = "utf-8"
    truncated: bool = False
    total_size: int | None = None
    mime_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "content": self.content,
            "is_binary": self.is_binary,
            "encoding": self.encoding,
            "truncated": self.truncated,
        }
        if self.total_size is not None:
            result["total_size"] = self.total_size
        if self.mime_type:
            result["mime_type"] = self.mime_type
        return result


@dataclass(frozen=True)
class WriteResult:
    """Result of a file write operation.

    Attributes:
        path: The path that was written.
        bytes_written: Number of bytes written.
        created: Whether a new file was created.
        backup_path: Path to backup if one was created.
    """

    path: str
    bytes_written: int
    created: bool = True
    backup_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "path": self.path,
            "bytes_written": self.bytes_written,
            "created": self.created,
        }
        if self.backup_path:
            result["backup_path"] = self.backup_path
        return result


@dataclass(frozen=True)
class EditResult:
    """Result of a file edit operation.

    Attributes:
        path: The path that was edited.
        old_hash: Hash of content before edit.
        new_hash: Hash of content after edit.
        lines_changed: Number of lines changed.
        backup_path: Path to backup if one was created.
    """

    path: str
    old_hash: str | None = None
    new_hash: str | None = None
    lines_changed: int = 0
    backup_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "path": self.path,
            "lines_changed": self.lines_changed,
        }
        if self.old_hash:
            result["old_hash"] = self.old_hash
        if self.new_hash:
            result["new_hash"] = self.new_hash
        if self.backup_path:
            result["backup_path"] = self.backup_path
        return result


@dataclass(frozen=True)
class GrepMatch:
    """A single grep match result.

    Attributes:
        path: File path where match was found.
        line_number: Line number of the match (1-indexed).
        line_content: Content of the matching line.
        match_start: Start position of match in line.
        match_end: End position of match in line.
    """

    path: str
    line_number: int
    line_content: str
    match_start: int
    match_end: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "path": self.path,
            "line_number": self.line_number,
            "line_content": self.line_content,
            "match_start": self.match_start,
            "match_end": self.match_end,
        }


@dataclass(frozen=True)
class GrepResult:
    """Result of a grep operation.

    Attributes:
        matches: List of grep matches.
        files_searched: Number of files searched.
        total_matches: Total number of matches found.
        truncated: Whether results were truncated.
    """

    matches: list[GrepMatch]
    files_searched: int = 0
    total_matches: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "matches": [m.to_dict() for m in self.matches],
            "files_searched": self.files_searched,
            "total_matches": self.total_matches,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class DeleteResult:
    """Result of a delete operation.

    Attributes:
        path: Path that was deleted.
        was_directory: Whether a directory was deleted.
        backup_path: Path to backup if one was created.
    """

    path: str
    was_directory: bool = False
    backup_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "path": self.path,
            "was_directory": self.was_directory,
        }
        if self.backup_path:
            result["backup_path"] = self.backup_path
        return result
