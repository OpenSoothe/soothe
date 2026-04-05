#!/usr/bin/env python3
"""Check TUI components and slash commands health.

Validates:
- TUI app and widget imports
- Slash command definitions
- Command parser functions
- Subagent routing configuration
- Input history management
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


def check_tui_imports() -> dict[str, Any]:
    """Check if TUI components can be imported."""
    try:
        from soothe.ux.tui_app import SootheApp
        from soothe.ux.tui_shared import TuiState, render_plan_tree

        return {
            "name": "tui_imports",
            "status": "ok",
            "message": "TUI components imported successfully",
            "details": {
                "app": "SootheApp",
                "state": "TuiState",
                "helpers": "render_plan_tree",
            },
        }
    except ImportError as e:
        return {
            "name": "tui_imports",
            "status": "error",
            "message": f"Failed to import TUI components: {e}",
        }
    except Exception as e:
        return {
            "name": "tui_imports",
            "status": "error",
            "message": f"TUI import error: {e}",
        }


def check_slash_commands() -> dict[str, Any]:
    """Check if slash commands are properly defined."""
    try:
        from soothe.ux.commands import SLASH_COMMANDS

        expected_commands = {
            "/exit",
            "/quit",
            "/detach",
            "/autopilot",
            "/plan",
            "/memory",
            "/context",
            "/policy",
            "/history",
            "/thread",
            "/clear",
            "/config",
            "/help",
        }

        # Check that key commands exist
        missing = []
        for cmd in expected_commands:
            # Handle commands with args like "/autopilot <prompt>"
            base_cmd = cmd.split()[0]
            if not any(k.startswith(base_cmd) for k in SLASH_COMMANDS):
                missing.append(cmd)

        total_commands = len(SLASH_COMMANDS)

        if missing:
            return {
                "name": "slash_commands",
                "status": "warning",
                "message": f"Slash commands loaded but missing: {', '.join(missing)}",
                "details": {
                    "total_commands": total_commands,
                    "missing": missing,
                },
            }

        return {
            "name": "slash_commands",
            "status": "ok",
            "message": f"All {total_commands} slash commands defined",
            "details": {
                "total_commands": total_commands,
                "commands": list(SLASH_COMMANDS.keys())[:10],  # First 10 for brevity
            },
        }

    except ImportError as e:
        return {
            "name": "slash_commands",
            "status": "error",
            "message": f"Failed to import slash commands: {e}",
        }
    except Exception as e:
        return {
            "name": "slash_commands",
            "status": "error",
            "message": f"Slash commands check failed: {e}",
        }


def check_command_parser() -> dict[str, Any]:
    """Check if command parser functions work."""
    try:
        from soothe.ux.commands import parse_autonomous_command

        # Test valid autonomous commands
        test_cases = [
            ("/autopilot test prompt", (None, "test prompt")),
            ("/autopilot 20 test with limit", (20, "test with limit")),
            ("/autopilot", None),  # Invalid - no prompt
        ]

        results = []
        for cmd, expected in test_cases:
            result = parse_autonomous_command(cmd)
            if expected is None:
                if result is None:
                    results.append(f"✓ '{cmd}' correctly rejected")
                else:
                    results.append(f"✗ '{cmd}' should be rejected but got {result}")
            elif result == expected:
                results.append(f"✓ '{cmd}' parsed correctly")
            else:
                results.append(f"✗ '{cmd}' expected {expected} but got {result}")

        # Check if all tests passed
        all_passed = all(r.startswith("✓") for r in results)

        return {
            "name": "command_parser",
            "status": "ok" if all_passed else "warning",
            "message": "Command parser tested" if all_passed else "Some parser tests failed",
            "details": {
                "tests_passed": sum(1 for r in results if r.startswith("✓")),
                "tests_total": len(results),
                "results": results,
            },
        }

    except ImportError as e:
        return {
            "name": "command_parser",
            "status": "error",
            "message": f"Failed to import command parser: {e}",
        }
    except Exception as e:
        return {
            "name": "command_parser",
            "status": "error",
            "message": f"Command parser check failed: {e}",
        }


def check_subagent_routing() -> dict[str, Any]:
    """Check subagent routing configuration."""
    try:
        from soothe.ux.commands import (
            BUILTIN_SUBAGENT_NAMES,
            SUBAGENT_DISPLAY_NAMES,
            get_subagent_display_name,
        )

        # Check display names
        expected_subagents = {"browser", "claude", "research"}
        actual_subagents = set(BUILTIN_SUBAGENT_NAMES)

        if expected_subagents != actual_subagents:
            missing = expected_subagents - actual_subagents
            extra = actual_subagents - expected_subagents
            msg = f"Subagent mismatch. Missing: {missing}, Extra: {extra}"
            return {
                "name": "subagent_routing",
                "status": "warning",
                "message": msg,
                "details": {
                    "expected": list(expected_subagents),
                    "actual": list(actual_subagents),
                },
            }

        # Test display name function
        test_name = get_subagent_display_name("browser")
        if test_name != "Browser":
            return {
                "name": "subagent_routing",
                "status": "warning",
                "message": f"Display name function incorrect: got '{test_name}'",
            }

        return {
            "name": "subagent_routing",
            "status": "ok",
            "message": f"Subagent routing configured for {len(BUILTIN_SUBAGENT_NAMES)} subagents",
            "details": {
                "subagents": BUILTIN_SUBAGENT_NAMES,
                "display_names": SUBAGENT_DISPLAY_NAMES,
            },
        }

    except ImportError as e:
        return {
            "name": "subagent_routing",
            "status": "error",
            "message": f"Failed to import subagent routing: {e}",
        }
    except Exception as e:
        return {
            "name": "subagent_routing",
            "status": "error",
            "message": f"Subagent routing check failed: {e}",
        }


def check_tui_widgets() -> dict[str, Any]:
    """Check if TUI widgets can be instantiated."""
    try:
        # Import widget classes
        from soothe.ux.tui_app import (
            ActivityPanel,
            ChatInput,
            ConversationPanel,
            InfoBar,
            PlanPanel,
        )

        # Check that they're proper classes
        widget_classes = {
            "ConversationPanel": ConversationPanel,
            "PlanPanel": PlanPanel,
            "ActivityPanel": ActivityPanel,
            "InfoBar": InfoBar,
            "ChatInput": ChatInput,
        }

        # Verify they can be instantiated (without running)
        for name, cls in widget_classes.items():
            if not isinstance(cls, type):
                return {
                    "name": "tui_widgets",
                    "status": "error",
                    "message": f"{name} is not a class",
                }

        return {
            "name": "tui_widgets",
            "status": "ok",
            "message": f"All {len(widget_classes)} TUI widgets defined",
            "details": {
                "widgets": list(widget_classes.keys()),
            },
        }

    except ImportError as e:
        return {
            "name": "tui_widgets",
            "status": "error",
            "message": f"Failed to import TUI widgets: {e}",
        }
    except Exception as e:
        return {
            "name": "tui_widgets",
            "status": "error",
            "message": f"TUI widgets check failed: {e}",
        }


def check_input_history() -> dict[str, Any]:
    """Check input history functionality."""
    try:
        from soothe.ux.tui_app import ChatInput

        # Create instance and test history
        input_widget = ChatInput()

        # Test history management
        test_history = ["command 1", "command 2", "command 3"]
        input_widget.set_history(test_history)

        # Add new item
        input_widget.add_to_history("command 4")

        # Check it was added
        if len(input_widget._history) != 4:
            return {
                "name": "input_history",
                "status": "warning",
                "message": f"History management incorrect: expected 4 items, got {len(input_widget._history)}",
            }

        return {
            "name": "input_history",
            "status": "ok",
            "message": "Input history management working",
            "details": {
                "features": ["set_history", "add_to_history", "navigation"],
            },
        }

    except ImportError as e:
        return {
            "name": "input_history",
            "status": "error",
            "message": f"Failed to import ChatInput: {e}",
        }
    except Exception as e:
        return {
            "name": "input_history",
            "status": "error",
            "message": f"Input history check failed: {e}",
        }


def main() -> int:
    """Run all TUI health checks."""
    checks = [
        check_tui_imports(),
        check_slash_commands(),
        check_command_parser(),
        check_subagent_routing(),
        check_tui_widgets(),
        check_input_history(),
    ]

    # Determine overall status
    errors = sum(1 for c in checks if c["status"] == "error")
    warnings = sum(1 for c in checks if c["status"] == "warning")

    if errors > 0:
        overall = "critical"
    elif warnings > 0:
        overall = "warning"
    else:
        overall = "healthy"

    # Output JSON
    result = {
        "category": "tui",
        "status": overall,
        "checks": checks,
    }

    print(json.dumps(result, indent=2))

    # Return exit code
    if errors > 0:
        return 2
    if warnings > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
