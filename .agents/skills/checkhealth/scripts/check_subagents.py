#!/usr/bin/env python3
"""Check subagent system health.

Validates:
- Subagent configuration in config.yml
- Subagent imports and definitions
- Runtime directory setup
- Subagent-specific dependencies
- Subagent initialization status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


def check_subagent_config() -> dict[str, Any]:
    """Check subagent configuration in config file."""
    try:
        from soothe.config import SootheConfig

        config_path = Path.home() / ".soothe" / "config" / "config.yml"
        config = SootheConfig.from_yaml_file(str(config_path))

        # Check configured subagents
        subagents = config.subagents
        if not subagents:
            return {
                "name": "subagent_config",
                "status": "warning",
                "message": "No subagents configured",
                "details": {"subagents": []},
            }

        # Get status of each subagent
        subagent_status = {}
        for name, subagent_config in subagents.items():
            subagent_status[name] = {
                "enabled": subagent_config.enabled,
                "model": subagent_config.model,
                "transport": subagent_config.transport,
                "has_url": subagent_config.url is not None,
                "runtime_dir": subagent_config.runtime_dir or "default",
            }

        enabled_count = sum(1 for s in subagent_status.values() if s["enabled"])

        return {
            "name": "subagent_config",
            "status": "ok",
            "message": f"{enabled_count}/{len(subagents)} subagents configured and enabled",
            "details": {
                "total": len(subagents),
                "enabled": enabled_count,
                "subagents": subagent_status,
            },
        }

    except Exception as e:
        return {
            "name": "subagent_config",
            "status": "error",
            "message": f"Failed to check subagent config: {e}",
        }


def check_subagent_imports() -> dict[str, Any]:
    """Check if subagent modules can be imported."""
    subagent_modules = {
        "scout": "soothe.subagents.scout",
        "research": "soothe.subagents.research",
        "browser": "soothe.subagents.browser",
        "claude": "soothe.subagents.claude",
        "skillify": "soothe.subagents.skillify",
        "weaver": "soothe.subagents.weaver",
    }

    results = {}
    for name, module_path in subagent_modules.items():
        try:
            __import__(module_path)
            results[name] = {"status": "ok", "imported": True}
        except ImportError as e:
            results[name] = {"status": "error", "imported": False, "error": str(e)}
        except Exception as e:
            results[name] = {"status": "warning", "imported": True, "warning": str(e)}

    # Count results
    imported = sum(1 for r in results.values() if r.get("imported"))
    errors = sum(1 for r in results.values() if r["status"] == "error")

    if errors > 0:
        return {
            "name": "subagent_imports",
            "status": "warning",
            "message": f"{imported}/{len(subagent_modules)} subagents imported ({errors} errors)",
            "details": {
                "imported": imported,
                "total": len(subagent_modules),
                "results": results,
            },
        }

    return {
        "name": "subagent_imports",
        "status": "ok",
        "message": f"All {imported} subagent modules imported successfully",
        "details": {
            "imported": imported,
            "total": len(subagent_modules),
            "results": results,
        },
    }


def check_subagent_dependencies() -> dict[str, Any]:
    """Check subagent-specific optional dependencies."""
    optional_deps = {
        "browser": ["browser_use"],
        "research": ["tavily", "wizsearch"],
        "claude": ["claude_agent_sdk"],
        "skillify": [],  # Uses standard deps
        "weaver": [],  # Uses standard deps
        "scout": [],  # Uses standard deps
    }

    results = {}
    for subagent, deps in optional_deps.items():
        if not deps:
            results[subagent] = {"status": "ok", "optional_deps": "none required"}
            continue

        missing = []
        for dep in deps:
            try:
                __import__(dep)
            except ImportError:
                missing.append(dep)

        if missing:
            results[subagent] = {
                "status": "warning",
                "optional_deps": f"missing: {', '.join(missing)}",
                "missing": missing,
            }
        else:
            results[subagent] = {
                "status": "ok",
                "optional_deps": "all installed",
                "installed": deps,
            }

    warnings = sum(1 for r in results.values() if r["status"] == "warning")

    if warnings > 0:
        return {
            "name": "subagent_dependencies",
            "status": "warning",
            "message": f"{len(results) - warnings}/{len(results)} subagents have all dependencies",
            "details": {"results": results},
        }

    return {
        "name": "subagent_dependencies",
        "status": "ok",
        "message": "All subagent dependencies satisfied",
        "details": {"results": results},
    }


def check_runtime_directories() -> dict[str, Any]:
    """Check if runtime directories exist for enabled subagents."""
    try:
        from soothe.config import SOOTHE_HOME, SootheConfig

        config_path = Path.home() / ".soothe" / "config" / "config.yml"
        config = SootheConfig.from_yaml_file(str(config_path))

        results = {}
        for name, subagent_config in config.subagents.items():
            if not subagent_config.enabled:
                results[name] = {"status": "disabled", "dir": "N/A"}
                continue

            # Determine runtime directory
            if subagent_config.runtime_dir:
                runtime_dir = Path(subagent_config.runtime_dir).expanduser()
            else:
                runtime_dir = Path(SOOTHE_HOME) / "agents" / name

            # Check if directory exists
            exists = runtime_dir.exists()
            if exists:
                results[name] = {"status": "ok", "dir": str(runtime_dir), "exists": True}
            else:
                # Not an error - will be created on first use
                results[name] = {
                    "status": "info",
                    "dir": str(runtime_dir),
                    "exists": False,
                    "note": "will be created on first use",
                }

        # Count by status
        ok_count = sum(1 for r in results.values() if r["status"] == "ok")
        info_count = sum(1 for r in results.values() if r["status"] == "info")
        disabled_count = sum(1 for r in results.values() if r["status"] == "disabled")

        return {
            "name": "runtime_directories",
            "status": "ok",
            "message": f"{ok_count} subagents with runtime dirs, {info_count} will create on use",
            "details": {
                "results": results,
                "ok": ok_count,
                "info": info_count,
                "disabled": disabled_count,
            },
        }

    except Exception as e:
        return {
            "name": "runtime_directories",
            "status": "error",
            "message": f"Failed to check runtime directories: {e}",
        }


def check_subagent_initialization() -> dict[str, Any]:
    """Check if subagents can be initialized."""
    try:
        from soothe.config import SootheConfig

        config_path = Path.home() / ".soothe" / "config" / "config.yml"
        config = SootheConfig.from_yaml_file(str(config_path))

        results = {}
        for name, subagent_config in config.subagents.items():
            if not subagent_config.enabled:
                results[name] = {"status": "disabled", "initialized": False}
                continue

            # Check if model can be resolved
            try:
                if subagent_config.model:
                    # Try to resolve the model string
                    model_str = config.resolve_model(subagent_config.model)
                    results[name] = {
                        "status": "ok",
                        "initialized": True,
                        "model": model_str,
                    }
                else:
                    # Uses default model
                    default_model = config.resolve_model("default")
                    results[name] = {
                        "status": "ok",
                        "initialized": True,
                        "model": default_model,
                    }
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "initialized": False,
                    "error": str(e),
                }

        # Count results
        ok_count = sum(1 for r in results.values() if r["status"] == "ok")
        error_count = sum(1 for r in results.values() if r["status"] == "error")

        if error_count > 0:
            return {
                "name": "subagent_initialization",
                "status": "warning",
                "message": f"{ok_count}/{len(results)} subagents can initialize",
                "details": {"results": results},
            }

        return {
            "name": "subagent_initialization",
            "status": "ok",
            "message": f"All {ok_count} enabled subagents can initialize",
            "details": {"results": results},
        }

    except Exception as e:
        return {
            "name": "subagent_initialization",
            "status": "error",
            "message": f"Failed to check subagent initialization: {e}",
        }


def check_subagent_transport() -> dict[str, Any]:
    """Check subagent transport configuration."""
    try:
        from soothe.config import SootheConfig

        config_path = Path.home() / ".soothe" / "config" / "config.yml"
        config = SootheConfig.from_yaml_file(str(config_path))

        results = {}
        for name, subagent_config in config.subagents.items():
            transport = subagent_config.transport

            # Validate transport configuration
            if transport == "local":
                results[name] = {"status": "ok", "transport": "local"}
            elif transport in ("acp", "a2a", "langgraph"):
                if subagent_config.url:
                    results[name] = {"status": "ok", "transport": transport, "url": subagent_config.url}
                else:
                    results[name] = {
                        "status": "error",
                        "transport": transport,
                        "error": f"{transport} transport requires URL",
                    }
            else:
                results[name] = {"status": "error", "transport": transport, "error": "unknown transport"}

        errors = sum(1 for r in results.values() if r["status"] == "error")

        if errors > 0:
            return {
                "name": "subagent_transport",
                "status": "warning",
                "message": f"{len(results) - errors}/{len(results)} subagents have valid transport config",
                "details": {"results": results},
            }

        return {
            "name": "subagent_transport",
            "status": "ok",
            "message": "All subagent transports configured correctly",
            "details": {"results": results},
        }

    except Exception as e:
        return {
            "name": "subagent_transport",
            "status": "error",
            "message": f"Failed to check subagent transport: {e}",
        }


def main() -> int:
    """Run all subagent health checks."""
    checks = [
        check_subagent_config(),
        check_subagent_imports(),
        check_subagent_dependencies(),
        check_runtime_directories(),
        check_subagent_initialization(),
        check_subagent_transport(),
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
        "category": "subagents",
        "status": overall,
        "checks": checks,
    }

    print(json.dumps(result, indent=2))

    # Return exit code
    if errors > 0:
        return 2
    elif warnings > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
