#!/usr/bin/env python3
"""Check protocol backends health.

Validates:
- Context protocol backends (vector, keyword)
- Memory protocol backend (MemU)
- Planner protocol backends (direct, subagent, claude)
- Policy protocol backend (config-driven)
- Durability protocol backends (JSON, RocksDB, PostgreSQL)
- Vector store protocol backends (in-memory, pgvector, weaviate)
- Remote agent protocol backend (LangGraph)
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


def check_import(module_path: str, class_name: str) -> dict[str, Any]:
    """Check if a module and class can be imported."""
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return {
            "status": "ok",
            "message": f"Successfully imported {module_path}.{class_name}",
        }
    except ImportError as e:
        return {
            "status": "error",
            "message": f"Failed to import {module_path}.{class_name}: {e}",
        }
    except AttributeError as e:
        return {
            "status": "error",
            "message": f"Class {class_name} not found in {module_path}: {e}",
        }


def check_memory_protocols() -> dict[str, Any]:
    """Check memory protocol backend."""
    checks = []

    # Check MemU memory backend
    result = check_import("soothe.backends.memory.memu", "MemUMemory")
    checks.append(
        {
            "name": "memory_memu",
            "status": result["status"],
            "message": "MemU memory backend: " + result["message"],
        }
    )

    return {
        "name": "memory_protocols",
        "status": "ok" if all(c["status"] == "ok" for c in checks) else "warning",
        "checks": checks,
    }


def check_planning_protocols() -> dict[str, Any]:
    """Check planning protocol backends."""
    checks = []

    # Check simple planner
    result = check_import("soothe.backends.planning.simple", "SimplePlanner")
    checks.append(
        {
            "name": "planning_simple",
            "status": result["status"],
            "message": "Simple planner: " + result["message"],
        }
    )

    # Check auto planner
    result = check_import("soothe.backends.planning.router", "AutoPlanner")
    checks.append(
        {
            "name": "planning_auto",
            "status": result["status"],
            "message": "Auto planner: " + result["message"],
        }
    )

    # Check claude planner
    result = check_import("soothe.backends.planning.claude", "ClaudePlanner")
    checks.append(
        {
            "name": "planning_claude",
            "status": result["status"],
            "message": "Claude planner: " + result["message"],
        }
    )

    return {
        "name": "planning_protocols",
        "status": "ok" if all(c["status"] == "ok" for c in checks) else "error",
        "checks": checks,
    }


def check_policy_protocols() -> dict[str, Any]:
    """Check policy protocol backend."""
    result = check_import("soothe.backends.policy.config_driven", "ConfigDrivenPolicy")
    return {
        "name": "policy_protocols",
        "status": result["status"],
        "message": "Policy backend: " + result["message"],
    }


def check_durability_protocols() -> dict[str, Any]:
    """Check durability protocol backends."""
    checks = []

    # Check JSON durability
    result = check_import("soothe.backends.durability.json", "JsonDurability")
    checks.append(
        {
            "name": "durability_json",
            "status": result["status"],
            "message": "JSON durability: " + result["message"],
        }
    )

    # Check RocksDB durability
    result = check_import("soothe.backends.durability.rocksdb", "RocksDBDurability")
    checks.append(
        {
            "name": "durability_rocksdb",
            "status": result["status"],
            "message": "RocksDB durability: " + result["message"],
        }
    )

    # Check PostgreSQL durability
    result = check_import("soothe.backends.durability.postgresql", "PostgreSQLDurability")
    checks.append(
        {
            "name": "durability_postgresql",
            "status": result["status"],
            "message": "PostgreSQL durability: " + result["message"],
        }
    )

    return {
        "name": "durability_protocols",
        "status": "ok" if all(c["status"] == "ok" for c in checks) else "warning",
        "checks": checks,
    }


def check_vector_store_protocols() -> dict[str, Any]:
    """Check vector store protocol backends."""
    checks = []

    # Check in-memory vector store
    result = check_import("soothe.backends.vector_store.in_memory", "InMemoryVectorStore")
    checks.append(
        {
            "name": "vectorstore_inmemory",
            "status": result["status"],
            "message": "In-memory vector store: " + result["message"],
        }
    )

    # Check pgvector
    result = check_import("soothe.backends.vector_store.pgvector", "PGVectorStore")
    checks.append(
        {
            "name": "vectorstore_pgvector",
            "status": result["status"],
            "message": "PgVector store: " + result["message"],
        }
    )

    # Check weaviate
    result = check_import("soothe.backends.vector_store.weaviate", "WeaviateVectorStore")
    checks.append(
        {
            "name": "vectorstore_weaviate",
            "status": result["status"],
            "message": "Weaviate store: " + result["message"],
        }
    )

    return {
        "name": "vector_store_protocols",
        "status": "ok" if all(c["status"] == "ok" for c in checks) else "warning",
        "checks": checks,
    }


def check_remote_agent_protocols() -> dict[str, Any]:
    """Check remote agent protocol backend."""
    result = check_import("soothe.backends.remote.langgraph", "LangGraphRemoteAgent")
    return {
        "name": "remote_agent_protocols",
        "status": result["status"],
        "message": "Remote agent backend: " + result["message"],
    }


def run_checks() -> dict[str, Any]:
    """Run all protocol backend checks."""
    all_checks = []

    # Check each protocol category
    all_checks.append(check_memory_protocols())
    all_checks.append(check_planner_protocols())
    all_checks.append(check_policy_protocols())
    all_checks.append(check_durability_protocols())
    all_checks.append(check_vector_store_protocols())
    all_checks.append(check_remote_agent_protocols())

    # Flatten checks for status determination
    flat_checks = []
    for cat in all_checks:
        if "checks" in cat:
            flat_checks.extend(cat["checks"])
        else:
            flat_checks.append(cat)

    # Determine overall status
    status = "healthy"
    has_warning = False
    for check in flat_checks:
        if check["status"] == "error":
            status = "critical"
            break
        if check["status"] == "warning":
            has_warning = True

    if status != "critical" and has_warning:
        status = "warning"

    return {
        "category": "protocols",
        "status": status,
        "checks": all_checks,
    }


def main() -> int:
    """Run checks and output JSON."""
    result = run_checks()
    print(json.dumps(result, indent=2))

    # Return exit code
    if result["status"] == "healthy":
        return 0
    if result["status"] == "warning":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
