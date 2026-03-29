#!/usr/bin/env python3
"""Template for AI-driven interactive health checks.

This script provides a starting point for AI agents to write custom diagnostic code.
Modify and run with: uv run python scripts/interactive_check_template.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


def check_import(module_path: str, class_name: str) -> None:
    """Test if a module and class can be imported and instantiated."""
    try:
        module = __import__(module_path, fromlist=[class_name])
        cls = getattr(module, class_name)
        print(f"✓ Successfully imported {module_path}.{class_name}")
    except ImportError as e:
        print(f"✗ Import failed: {e}")
    except Exception as e:
        print(f"✗ Import succeeded but error occurred: {e}")


def check_backend_functionality(backend_type: str) -> None:
    """Test backend instantiation."""
    from soothe.config import SootheConfig

    try:
        config_path = Path.home() / ".soothe" / "config" / "config.yml"
        config = SootheConfig.from_yaml_file(str(config_path))

        # Import the appropriate backend based on type
        if backend_type == "json":
            from soothe.backends.durability.json import JsonDurability

            persist_dir = config.protocols.durability.persist_dir or str(Path.home() / ".soothe" / "threads")
            backend = JsonDurability(persist_dir)
            print(f"✓ {backend_type} backend instantiated at {persist_dir}")
        elif backend_type == "postgresql":
            from soothe.backends.durability.postgresql import PostgreSQLDurability

            backend = PostgreSQLDurability(config.persistence.soothe_postgres_dsn)
            print(f"✓ {backend_type} backend instantiated")
        elif backend_type == "rocksdb":
            from soothe.backends.durability.rocksdb import RocksDBDurability

            persist_dir = config.protocols.durability.persist_dir or str(Path.home() / ".soothe" / "threads")
            backend = RocksDBDurability(persist_dir)
            print(f"✓ {backend_type} backend instantiated at {persist_dir}")
        else:
            print(f"✗ Unknown backend type: {backend_type}")

    except Exception as e:
        print(f"✗ {backend_type} backend check failed: {e}")


def check_configuration() -> None:
    """Validate configuration file in detail."""
    import yaml

    from soothe.config import SootheConfig

    config_path = Path.home() / ".soothe" / "config" / "config.yml"

    # Check YAML structure
    try:
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        print("✓ YAML syntax valid")
    except Exception as e:
        print(f"✗ YAML parsing failed: {e}")
        return

    # Display key configuration
    print("\nConfiguration Summary:")
    if "model" in raw_config:
        print(f"  Model providers: {list(raw_config['model'].get('providers', {}).keys())}")
    if "durability" in raw_config:
        print(f"  Durability backends: {list(raw_config['durability'].keys())}")

    # Validate with Pydantic
    try:
        config = SootheConfig.from_yaml_file(config_path)
        print("✓ Configuration validates with Pydantic schema")
    except Exception as e:
        print(f"✗ Pydantic validation failed: {e}")


def check_daemon_socket() -> None:
    """Test daemon socket communication."""
    import json
    import socket

    from soothe.daemon import socket_path

    sock_path = socket_path()

    if not sock_path.exists():
        print(f"✗ Socket file not found at {sock_path}")
        return

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(sock_path))
        sock.settimeout(5.0)

        # Send a simple ping
        sock.send(json.dumps({"command": "ping"}).encode())

        response = sock.recv(4096)
        result = json.loads(response)

        print(f"✓ Daemon socket responsive: {result}")
        sock.close()

    except TimeoutError:
        print("✗ Daemon socket timeout (daemon may be hung)")
    except Exception as e:
        print(f"✗ Daemon socket communication failed: {e}")


def main() -> int:
    """Run interactive health checks."""
    print("=" * 60)
    print("Soothe Interactive Health Check")
    print("=" * 60)
    print()

    # Example checks - AI agents can modify these
    print("1. Testing Configuration")
    print("-" * 40)
    check_configuration()
    print()

    print("2. Testing Backend Imports")
    print("-" * 40)
    check_import("soothe.backends.durability.json", "JsonDurability")
    check_import("soothe.backends.durability.postgresql", "PostgreSQLDurability")
    check_import("soothe.backends.durability.rocksdb", "RocksDBDurability")
    print()

    print("3. Testing Backend Functionality")
    print("-" * 40)
    check_backend_functionality("json")
    # Uncomment to test other backends:
    # check_backend_functionality("postgresql")
    # check_backend_functionality("rocksdb")
    print()

    print("4. Testing Daemon Socket")
    print("-" * 40)
    check_daemon_socket()
    print()

    print("=" * 60)
    print("Interactive checks complete")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
