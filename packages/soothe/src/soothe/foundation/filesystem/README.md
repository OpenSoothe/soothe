# UnifiedFilesystem

A unified, abstract filesystem interface for Soothe that provides consistent
APIs across different backends and implementations.

## Overview

The `UnifiedFilesystem` interface defines a complete set of filesystem operations
with:

- **Consistent API**: Same interface for sync and async operations
- **Security**: Built-in path traversal protection
- **Error Handling**: Typed exceptions for different failure modes
- **Workspace Isolation**: Virtual mode for sandboxing
- **Backup Support**: Automatic backup before destructive operations

## Quick Start

```python
from soothe.foundation.filesystem import LocalFilesystem

# Create a filesystem instance
fs = LocalFilesystem(
    workspace="/path/to/workspace",
    virtual_mode=True,  # Sandbox paths to workspace
    max_file_size_mb=10,
)

# Read a file
result = fs.read("config.json")
print(result.content)

# Write a file
fs.write("output.txt", "Hello, World!")

# Edit a file
fs.edit("config.json", "old_value", "new_value")

# List directory
entries = fs.ls(".")
for entry in entries:
    print(entry)
```

## Interface Methods

### Path Operations

| Method | Description |
|--------|-------------|
| `resolve_path(path)` | Resolve path within workspace |
| `exists(path)` | Check if path exists |
| `is_file(path)` | Check if path is a file |
| `is_dir(path)` | Check if path is a directory |

### Read Operations

| Method | Description |
|--------|-------------|
| `read(path, offset=0, limit=None)` | Read file contents |
| `aread(path, ...)` | Async read file contents |

### Write Operations

| Method | Description |
|--------|-------------|
| `write(path, content, backup=False)` | Write content to file |
| `awrite(path, content, ...)` | Async write |

### Edit Operations

| Method | Description |
|--------|-------------|
| `edit(path, old, new, backup=True)` | Replace string in file |
| `edit_lines(path, start, end, content)` | Replace line range |
| `insert_lines(path, line, content)` | Insert at line number |
| `delete_lines(path, start, end)` | Delete line range |
| `apply_diff(path, diff)` | Apply unified diff |

### Directory Operations

| Method | Description |
|--------|-------------|
| `ls(path, include_info=False)` | List directory contents |
| `mkdir(path, recursive=False)` | Create directory |
| `rmdir(path, recursive=False)` | Remove directory |

### File Operations

| Method | Description |
|--------|-------------|
| `delete(path, backup=True)` | Delete file |
| `info(path)` | Get file metadata |
| `copy(src, dst, overwrite=False)` | Copy file/directory |
| `move(src, dst, overwrite=False)` | Move/rename file/directory |

### Search Operations

| Method | Description |
|--------|-------------|
| `glob(pattern, path=".")` | Glob pattern matching |
| `grep(pattern, path=".")` | Search for pattern in files |

## Security Features

### Path Traversal Protection

```python
# These will raise PathTraversalError:
fs.read("../etc/passwd")        # Blocked
fs.write("../../outside.txt")   # Blocked
fs.read("subdir/../../../etc/passwd")  # Blocked
```

### Virtual Mode

When `virtual_mode=True`, all absolute paths are treated as relative to the workspace:

```python
fs = LocalFilesystem(workspace="/workspace", virtual_mode=True)

# Both resolve to /workspace/config.json
fs.read("config.json")
fs.read("/config.json")  # Virtual absolute path
```

When `virtual_mode=False`, absolute paths outside workspace are blocked:

```python
fs = LocalFilesystem(workspace="/workspace", virtual_mode=False)

fs.read("/workspace/config.json")  # OK - within workspace
fs.read("/etc/passwd")              # Blocked - outside workspace
```

### Invalid Path Detection

```python
# These will raise InvalidPathError:
fs.read("file\x00.txt")     # Null bytes
fs.read("~/.bashrc")         # Home directory reference
fs.read("")                  # Empty path
```

## Error Handling

All methods raise typed exceptions:

```python
from soothe.foundation.filesystem import (
    PathNotFoundError,
    PermissionDeniedError,
    PathTraversalError,
    InvalidPathError,
    FilesystemError,
)

try:
    content = fs.read("sensitive.txt")
except PathNotFoundError:
    print("File not found")
except PermissionDeniedError:
    print("Access denied")
except PathTraversalError:
    print("Security violation detected")
except FilesystemError as e:
    print(f"Filesystem error: {e}")
```

## Async Support

All operations have async variants:

```python
async def process_files():
    content = await fs.aread("file.txt")
    await fs.awrite("output.txt", content)
    entries = await fs.als(".")
```

## Backup Support

Destructive operations support automatic backups:

```python
# Creates backup in .backups/ directory
result = fs.write("important.txt", "new content", backup=True)
print(f"Backup created: {result.backup_path}")

result = fs.delete("important.txt", backup=True)
print(f"Backup at: {result.backup_path}")
```

## Implementing Custom Backends

```python
from soothe.foundation.filesystem import UnifiedFilesystem
from soothe.foundation.filesystem.protocol import ReadResult, WriteResult

class S3Filesystem(UnifiedFilesystem):
    """S3-backed filesystem implementation."""

    def __init__(self, bucket: str, **kwargs):
        super().__init__(workspace="/", **kwargs)
        self.bucket = bucket
        # Initialize S3 client...

    def read(self, path: str, **kwargs) -> ReadResult:
        # Implement S3 read
        pass

    def write(self, path: str, content: str | bytes, **kwargs) -> WriteResult:
        # Implement S3 write
        pass

    # ... implement other methods
```

## Protocol Types

### FileInfo

```python
from soothe.foundation.filesystem import FileInfo

info: FileInfo = fs.info("file.txt")
print(f"Size: {info.size}")
print(f"Modified: {info.modified_at}")
print(f"Permissions: {info.permissions}")
```

### ReadResult

```python
from soothe.foundation.filesystem import ReadResult

result: ReadResult = fs.read("file.txt")
print(f"Content: {result.content}")
print(f"Is binary: {result.is_binary}")
print(f"Truncated: {result.truncated}")
```

### GlobResult

```python
from soothe.foundation.filesystem import GlobResult

result: GlobResult = fs.glob("**/*.py")
for match in result.matches:
    print(match)
if result.truncated:
    print("Results were truncated")
```

## Configuration

```python
fs = LocalFilesystem(
    workspace="/workspace",
    virtual_mode=True,          # Enable sandboxing
    max_file_size_mb=10,        # Max file size
    backup_dir=".backups",      # Backup directory
)
```

## Integration with Security Layer

The UnifiedFilesystem can be combined with the security layer:

```python
from soothe.foundation.security import SecurityEnforcer
from soothe.foundation.filesystem import LocalFilesystem

# Create filesystem
fs = LocalFilesystem(workspace="/workspace")

# Wrap with security enforcer
enforcer = SecurityEnforcer(
    workspace="/workspace",
    policy=STRICT_POLICY,
)

# Validate before operations
if enforcer.check_access("config.json", "read"):
    content = fs.read("config.json")
```
