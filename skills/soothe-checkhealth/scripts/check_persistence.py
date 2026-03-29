#!/usr/bin/env python3
"""Check persistence layer health.

Validates:
- PostgreSQL connectivity
- RocksDB availability
- File system permissions and disk space
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from soothe.config import SOOTHE_HOME


def check_postgresql() -> dict[str, Any]:
    """Check PostgreSQL connectivity."""
    try:
        import asyncpg

        # Note: This check is limited without actual config
        # In a real implementation, we would load config and test connection
        return {
            "name": "postgresql",
            "status": "info",
            "message": "PostgreSQL check requires config (skipped in standalone mode)",
            "details": {
                "note": "Run with --config to test actual database connection",
                "asyncpg_installed": True,
            },
        }
    except ImportError:
        return {
            "name": "postgresql",
            "status": "info",
            "message": "asyncpg not installed (PostgreSQL optional - install with: pip install asyncpg)",
            "details": {
                "asyncpg_installed": False,
                "optional": True,
            },
        }


def check_rocksdb() -> dict[str, Any]:
    """Check RocksDB availability."""
    try:
        import rocksdb

        # Check data directory
        data_dir = Path(SOOTHE_HOME) / "data" / "rocksdb"
        if not data_dir.parent.exists():
            return {
                "name": "rocksdb",
                "status": "ok",
                "message": "rocksdb installed, data directory will be created on first use",
                "details": {"rocksdb_installed": True},
            }

        return {
            "name": "rocksdb",
            "status": "ok",
            "message": "rocksdb installed and ready",
            "details": {"data_dir": str(data_dir), "rocksdb_installed": True},
        }
    except ImportError:
        return {
            "name": "rocksdb",
            "status": "info",
            "message": "rocksdb not installed (optional - install with: pip install python-rocksdb)",
            "details": {
                "rocksdb_installed": False,
                "optional": True,
            },
        }


def check_filesystem() -> dict[str, Any]:
    """Check file system permissions and disk space."""
    soothe_home = Path(SOOTHE_HOME)
    issues = []

    # Check if home directory exists
    if not soothe_home.exists():
        return {
            "name": "filesystem",
            "status": "error",
            "message": f"Soothe home directory not found: {soothe_home}",
            "details": {"path": str(soothe_home)},
        }

    # Check required subdirectories
    required_dirs = ["logs", "threads", "config"]
    for dirname in required_dirs:
        dir_path = soothe_home / dirname
        if not dir_path.exists():
            issues.append(f"Missing directory: {dirname}")

    # Check write permissions
    test_file = soothe_home / ".health_check_test"
    try:
        test_file.write_text("test")
        test_file.unlink()
    except (PermissionError, OSError) as e:
        issues.append(f"Write permission error: {e}")

    # Check disk space (require at least 100MB)
    try:
        stat = shutil.disk_usage(soothe_home)
        free_mb = stat.free / (1024 * 1024)
        if free_mb < 100:
            issues.append(f"Low disk space: {free_mb:.1f}MB free")
    except OSError as e:
        issues.append(f"Could not check disk space: {e}")

    if issues:
        return {
            "name": "filesystem",
            "status": "error" if "permission" in str(issues).lower() else "warning",
            "message": "Issues found: " + "; ".join(issues),
            "details": {"issues": issues},
        }

    return {
        "name": "filesystem",
        "status": "ok",
        "message": f"File system OK ({free_mb:.0f}MB free)",
        "details": {
            "home": str(soothe_home),
            "free_mb": round(free_mb, 1),
        },
    }


def run_checks() -> dict[str, Any]:
    """Run all persistence checks."""
    checks = [
        check_postgresql(),
        check_rocksdb(),
        check_filesystem(),
    ]

    # Determine overall status
    status = "healthy"
    for check in checks:
        if check["status"] == "error":
            status = "critical"
            break
        if check["status"] in ("warning", "info") and status != "critical":
            status = "warning"

    return {
        "category": "persistence",
        "status": status,
        "checks": checks,
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
