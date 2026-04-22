#!/usr/bin/env python3
"""Automated import path updates for soothe daemon package (IG-185 Phase 3)."""

from pathlib import Path

# Same import mapping as CLI (from RFC-610)
IMPORT_MAPPING = {
    "from soothe_sdk import plugin": "from soothe_sdk.plugin import plugin",
    "from soothe_sdk import tool": "from soothe_sdk.plugin import tool",
    "from soothe_sdk import subagent": "from soothe_sdk.plugin import subagent",
    "from soothe_sdk import Manifest": "from soothe_sdk.plugin import Manifest",
    "from soothe_sdk import PluginManifest": "from soothe_sdk.plugin import Manifest",
    "from soothe_sdk import PluginContext": "from soothe_sdk.plugin import Context",
    "from soothe_sdk import PluginHealth": "from soothe_sdk.plugin import Health",
    "from soothe_sdk import register_event": "from soothe_sdk.plugin import register_event",
    "from soothe_sdk import emit_progress": "from soothe_sdk.plugin import emit_progress",
    "from soothe_sdk import WebSocketClient": "from soothe_sdk.client import WebSocketClient",
    "from soothe_sdk import VerbosityLevel": "from soothe_sdk.client import VerbosityLevel",
    "from soothe_sdk import bootstrap_thread_session": "from soothe_sdk.client import bootstrap_thread_session",
    "from soothe_sdk import connect_websocket_with_retries": "from soothe_sdk.client import connect_websocket_with_retries",
    "from soothe_sdk import encode": "from soothe_sdk.client.protocol import encode",
    "from soothe_sdk import decode": "from soothe_sdk.client.protocol import decode",
    "from soothe_sdk import Plan": "from soothe_sdk.client.schemas import Plan",
    "from soothe_sdk import PlanStep": "from soothe_sdk.client.schemas import PlanStep",
    "from soothe_sdk import ToolOutput": "from soothe_sdk.client.schemas import ToolOutput",
    "from soothe_sdk import SOOTHE_HOME": "from soothe_sdk.client.config import SOOTHE_HOME",
    "from soothe_sdk import DEFAULT_EXECUTE_TIMEOUT": "from soothe_sdk.client.config import DEFAULT_EXECUTE_TIMEOUT",
    "from soothe_sdk import setup_logging": "from soothe_sdk.utils import setup_logging",
    "from soothe_sdk import GlobalInputHistory": "from soothe_sdk.utils import GlobalInputHistory",
    "from soothe_sdk import VERBOSITY_TO_LOG_LEVEL": "from soothe_sdk.utils import VERBOSITY_TO_LOG_LEVEL",
    "from soothe_sdk import format_cli_error": "from soothe_sdk.utils import format_cli_error",
    "from soothe_sdk import log_preview": "from soothe_sdk.utils import log_preview",
    "from soothe_sdk import convert_and_abbreviate_path": "from soothe_sdk.utils import convert_and_abbreviate_path",
    "from soothe_sdk import parse_autopilot_goals": "from soothe_sdk.utils import parse_autopilot_goals",
    "from soothe_sdk import get_tool_display_name": "from soothe_sdk.utils import get_tool_display_name",
    "from soothe_sdk import _TASK_NAME_RE": "from soothe_sdk.utils import _TASK_NAME_RE",
    "from soothe_sdk import resolve_provider_env": "from soothe_sdk.utils import resolve_provider_env",
    "from soothe_sdk import INVALID_WORKSPACE_DIRS": "from soothe_sdk.utils import INVALID_WORKSPACE_DIRS",
    "from soothe_sdk import ESSENTIAL_EVENT_TYPES": "from soothe_sdk.ux import ESSENTIAL_EVENT_TYPES",
    "from soothe_sdk import strip_internal_tags": "from soothe_sdk.ux import strip_internal_tags",
    "from soothe_sdk import INTERNAL_JSON_KEYS": "from soothe_sdk.ux import INTERNAL_JSON_KEYS",
    # Core imports
    "from soothe_sdk import SootheEvent": "from soothe_sdk.events import SootheEvent",
    "from soothe_sdk import LifecycleEvent": "from soothe_sdk.events import LifecycleEvent",
    "from soothe_sdk import ProtocolEvent": "from soothe_sdk.events import ProtocolEvent",
    "from soothe_sdk import SubagentEvent": "from soothe_sdk.events import SubagentEvent",
    "from soothe_sdk import OutputEvent": "from soothe_sdk.events import OutputEvent",
    "from soothe_sdk import ErrorEvent": "from soothe_sdk.events import ErrorEvent",
    "from soothe_sdk import PluginError": "from soothe_sdk.exceptions import PluginError",
    "from soothe_sdk import ValidationError": "from soothe_sdk.exceptions import ValidationError",
    "from soothe_sdk import DependencyError": "from soothe_sdk.exceptions import DependencyError",
    "from soothe_sdk import VerbosityTier": "from soothe_sdk.verbosity import VerbosityTier",
    "from soothe_sdk import should_show": "from soothe_sdk.verbosity import should_show",
    "from soothe_sdk import classify_event_to_tier": "from soothe_sdk.ux import classify_event_to_tier",
    "from soothe_sdk import ProgressCategory": "from soothe_sdk.verbosity import VerbosityTier",
    "from soothe_sdk import PersistStore": "from soothe_sdk.protocols import PersistStore",
    "from soothe_sdk import VectorRecord": "from soothe_sdk.protocols import VectorRecord",
    "from soothe_sdk import VectorStoreProtocol": "from soothe_sdk.protocols import VectorStoreProtocol",
    "from soothe_sdk import Permission": "from soothe_sdk.protocols import Permission",
    "from soothe_sdk import PermissionSet": "from soothe_sdk.protocols import PermissionSet",
    "from soothe_sdk import ActionRequest": "from soothe_sdk.protocols import ActionRequest",
    "from soothe_sdk import PolicyContext": "from soothe_sdk.protocols import PolicyContext",
    "from soothe_sdk import PolicyDecision": "from soothe_sdk.protocols import PolicyDecision",
    "from soothe_sdk import PolicyProfile": "from soothe_sdk.protocols import PolicyProfile",
    "from soothe_sdk import PolicyProtocol": "from soothe_sdk.protocols import PolicyProtocol",
}

def update_file(file_path: Path):
    """Update import statements in a file."""
    content = file_path.read_text()
    original = content
    updated_imports = []

    for old_import, new_import in IMPORT_MAPPING.items():
        if old_import in content:
            content = content.replace(old_import, new_import)
            updated_imports.append(old_import.split()[-1])

    if content != original:
        file_path.write_text(content)
        return updated_imports
    return None

# Process all daemon files
daemon_root = Path("packages/soothe/src/soothe")
updated_files = []

print("=== Phase 3: Updating daemon imports ===\n")

for py_file in daemon_root.rglob("*.py"):
    if "__pycache__" in str(py_file):
        continue

    updated_imports = update_file(py_file)
    if updated_imports:
        rel_path = py_file.relative_to(daemon_root.parent)
        updated_files.append((str(rel_path), updated_imports))
        print(f"✓ {rel_path}")
        for imp in updated_imports[:3]:  # Show first 3
            print(f"    - {imp}")
        if len(updated_imports) > 3:
            print(f"    ... and {len(updated_imports) - 3} more")

print(f"\n✓ Updated {len(updated_files)} files in soothe daemon")
print(f"Total import changes: {sum(len(imports) for _, imports in updated_files)}")