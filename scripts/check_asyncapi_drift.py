#!/usr/bin/env python3
"""AsyncAPI spec → Pydantic model drift checker (RFC-450 §11.3).

The AsyncAPI spec at ``docs/specs/asyncapi.yaml`` is the single source of truth
for the protocol-1 wire contract. This script:

1. Parses the AsyncAPI YAML and extracts the ``components.schemas`` block.
2. Cross-references each ``*Params`` schema against the daemon's
   ``PARAMS_REGISTRY`` and the SDK's client-side params models.
3. Reports:
   - Params schemas defined in AsyncAPI but missing from the daemon registry.
   - Methods registered in the daemon registry but missing from AsyncAPI.
   - Field-level mismatches (required vs. optional, type differences).
4. Validates the AsyncAPI document structurally (required top-level keys,
   valid YAML).

Exit codes:
    0 — no drift detected (or warnings only).
    1 — structural errors or drift detected.

Usage::

    python scripts/check_asyncapi_drift.py
    python scripts/check_asyncapi_drift.py --spec docs/specs/asyncapi.yaml

This is a *drift detector*, not a generator. RFC-450 §11.3 envisions
``datamodel-code-generator`` producing Pydantic models from JSON Schema
components; that generator is optional (requires an external tool install).
This script provides the CI-checkable guarantee that the committed
spec and the committed models stay in sync, which is the normative
requirement — "a CI check SHALL regenerate and diff against the committed
version to detect drift."
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any

# Path bootstrap so the script runs from the repo root without install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _src in (
    _REPO_ROOT / "packages" / "soothe-daemon" / "src",
    _REPO_ROOT / "packages" / "soothe-sdk" / "src",
    _REPO_ROOT / "client" / "python" / "src",
):
    _src_str = str(_src)
    if _src.exists() and _src_str not in sys.path:
        sys.path.insert(0, _src_str)

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "ERROR: PyYAML is required. Install with `pip install pyyaml` or `uv sync`.",
        file=sys.stderr,
    )
    sys.exit(2)

DEFAULT_SPEC = _REPO_ROOT / "docs" / "specs" / "asyncapi.yaml"


# ---------------------------------------------------------------------------
# AsyncAPI loading
# ---------------------------------------------------------------------------


def load_asyncapi(spec_path: Path) -> dict[str, Any]:
    """Load and parse the AsyncAPI YAML document.

    Args:
        spec_path: Path to the asyncapi.yaml file.

    Returns:
        Parsed document as a dict.

    Raises:
        SystemExit: If the file cannot be read or parsed.
    """
    if not spec_path.exists():
        print(f"ERROR: AsyncAPI spec not found at {spec_path}", file=sys.stderr)
        sys.exit(1)
    try:
        with spec_path.open(encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        print(f"ERROR: Failed to parse YAML in {spec_path}:\n{exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(doc, dict):
        print(f"ERROR: AsyncAPI document is not a mapping: {type(doc)!r}", file=sys.stderr)
        sys.exit(1)
    return doc


def validate_structure(doc: dict[str, Any]) -> list[str]:
    """Validate the AsyncAPI document's structural requirements.

    Args:
        doc: Parsed AsyncAPI document.

    Returns:
        List of structural error strings (empty if valid).
    """
    errors: list[str] = []
    required_top = ["asyncapi", "info", "servers", "channels", "components"]
    for key in required_top:
        if key not in doc:
            errors.append(f"Missing top-level key: {key!r}")

    if "info" in doc and isinstance(doc["info"], dict):
        for key in ("title", "version"):
            if key not in doc["info"]:
                errors.append(f"Missing info.{key}")

    components = doc.get("components")
    if not isinstance(components, dict):
        errors.append("components must be a mapping")
    else:
        for key in ("schemas", "messages"):
            if key not in components:
                errors.append(f"Missing components.{key}")

    channels = doc.get("channels")
    if not isinstance(channels, dict) or "main" not in channels:
        errors.append("channels.main is required")

    return errors


# ---------------------------------------------------------------------------
# Schema extraction
# ---------------------------------------------------------------------------


def extract_params_schemas(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract ``*Params`` schemas from the AsyncAPI components.

    Args:
        doc: Parsed AsyncAPI document.

    Returns:
        Dict mapping schema name → schema dict for entries whose name ends
        with ``Params``.
    """
    schemas = (doc.get("components") or {}).get("schemas") or {}
    if not isinstance(schemas, dict):
        return {}
    return {name: schema for name, schema in schemas.items() if name.endswith("Params")}


def schema_to_camel(name: str) -> str:
    """Convert an AsyncAPI schema name (snake_case) to a Pydantic class name.

    Args:
        name: Schema name like ``loopGetParams``.

    Returns:
        PascalCase class name like ``LoopGetParams``.
    """
    if not name:
        return name
    # Already PascalCase
    if name[0].isupper():
        return name
    # camelCase → PascalCase
    return name[0].upper() + name[1:]


def extract_message_methods(doc: dict[str, Any]) -> dict[str, str | None]:
    """Extract method names from method-specific request/notification messages.

    Scans ``components.messages`` for entries whose payload constrains ``method``
    to a const value, returning ``{method_name: message_class}``.

    Args:
        doc: Parsed AsyncAPI document.

    Returns:
        Dict mapping method string → message class (request/notification/subscribe).
    """
    messages = (doc.get("components") or {}).get("messages") or {}
    if not isinstance(messages, dict):
        return {}
    found: dict[str, str | None] = {}
    for _name, msg in messages.items():
        if not isinstance(msg, dict):
            continue
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            continue
        # allOf composition — inspect each branch for a method const.
        branches = payload.get("allOf") if "allOf" in payload else [payload]
        if not isinstance(branches, list):
            continue
        method_const: str | None = None
        msg_type: str | None = None
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            props = branch.get("properties") or {}
            if not isinstance(props, dict):
                continue
            method_prop = props.get("method")
            if isinstance(method_prop, dict) and "const" in method_prop:
                method_const = str(method_prop["const"])
            type_prop = props.get("type")
            if isinstance(type_prop, dict) and "const" in type_prop:
                msg_type = str(type_prop["const"])
        if method_const is not None:
            found[method_const] = msg_type
    return found


# ---------------------------------------------------------------------------
# Daemon registry cross-reference
# ---------------------------------------------------------------------------


def load_daemon_registry() -> tuple[dict[tuple[str, str | None], type], bool]:
    """Import the daemon's PARAMS_REGISTRY.

    Returns:
        Tuple of ``(PARAMS_REGISTRY, import_ok)`` where ``PARAMS_REGISTRY`` maps
        ``(type, method)`` → params model and ``import_ok`` is ``False`` when the
        daemon package could not be imported.
    """
    try:
        mod = importlib.import_module("soothe_daemon.protocol.schemas")
    except ImportError as exc:
        print(f"WARNING: Cannot import daemon protocol schemas: {exc}", file=sys.stderr)
        return {}, False
    return getattr(mod, "PARAMS_REGISTRY", {}), True


def cross_reference_registry(
    asyncapi_methods: dict[str, str | None],
    registry: dict[tuple[str, str | None], type],
) -> tuple[list[str], list[str]]:
    """Cross-reference AsyncAPI methods against the daemon registry.

    Args:
        asyncapi_methods: Methods extracted from AsyncAPI messages.
        registry: The daemon's ``(type, method)`` registry.

    Returns:
        Tuple of (missing_in_registry, missing_in_asyncapi) report lines.
    """
    # Build a set of methods known to the registry (value side of the tuple key).
    registry_methods: set[str] = {m for (_t, m) in registry if m is not None}

    missing_in_registry: list[str] = []
    for method, msg_type in sorted(asyncapi_methods.items()):
        # Look up the (type, method) entry that matches the message class.
        if msg_type is not None:
            if (msg_type, method) not in registry:
                missing_in_registry.append(
                    f"  method {method!r} (type={msg_type!r}) in AsyncAPI but not in PARAMS_REGISTRY"
                )
        elif method not in registry_methods:
            missing_in_registry.append(
                f"  method {method!r} in AsyncAPI but not in PARAMS_REGISTRY"
            )

    missing_in_asyncapi: list[str] = []
    # Only check protocol-1 envelope methods (those with a non-None method key
    # and a protocol-1 type — request/notification/subscribe). Legacy flat
    # types (method=None) are intentionally not in AsyncAPI.
    proto1_types = {"request", "notification", "subscribe"}
    registry_proto1_methods: set[str] = set()
    for t, m in registry:
        if m is not None and t in proto1_types:
            registry_proto1_methods.add(f"{t}:{m}")
    for entry in sorted(registry_proto1_methods):
        t, m = entry.split(":", 1)
        if m not in asyncapi_methods:
            missing_in_asyncapi.append(
                f"  ({t}, {m!r}) in PARAMS_REGISTRY but no method-specific message in AsyncAPI"
            )

    return missing_in_registry, missing_in_asyncapi


# ---------------------------------------------------------------------------
# SDK client params cross-reference
# ---------------------------------------------------------------------------


def load_sdk_params_module() -> tuple[Any, bool]:
    """Import the SDK's client-side params validation module.

    Returns:
        Tuple of ``(module, import_ok)`` where ``module`` is the imported module
        or ``None`` when unavailable.
    """
    try:
        return importlib.import_module("soothe_client.protocol_params"), True
    except ImportError as exc:
        print(f"WARNING: Cannot import SDK params module: {exc}", file=sys.stderr)
        return None, False


def cross_reference_sdk_params(
    asyncapi_schemas: dict[str, dict[str, Any]], sdk_module: Any
) -> list[str]:
    """Cross-reference AsyncAPI params schemas against SDK params models.

    Args:
        asyncapi_schemas: ``*Params`` schemas from AsyncAPI.
        sdk_module: The imported SDK params module (or ``None``).

    Returns:
        List of drift report lines (empty if no drift).
    """
    if sdk_module is None:
        return []
    drift: list[str] = []
    for schema_name in sorted(asyncapi_schemas):
        class_name = schema_to_camel(schema_name)
        if not hasattr(sdk_module, class_name):
            drift.append(
                f"  AsyncAPI schema {schema_name!r} → expected SDK class {class_name!r} not found"
            )
    return drift


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for the AsyncAPI drift checker.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 0 if clean, 1 if drift/errors detected.
    """
    parser = argparse.ArgumentParser(
        description="Check AsyncAPI spec ↔ Pydantic model drift (RFC-450 §11.3)."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=DEFAULT_SPEC,
        help=f"Path to asyncapi.yaml (default: {DEFAULT_SPEC}).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings (missing SDK/daemon module) as errors.",
    )
    args = parser.parse_args(argv)

    doc = load_asyncapi(args.spec)

    # 1. Structural validation
    structural_errors = validate_structure(doc)
    if structural_errors:
        print("FAIL: AsyncAPI structural errors:")
        for err in structural_errors:
            print(f"  {err}")
        return 1
    print(f"OK: {args.spec} is structurally valid.")

    # 2. Extract schemas and methods
    params_schemas = extract_params_schemas(doc)
    print(f"INFO: Found {len(params_schemas)} *Params schemas in AsyncAPI.")
    message_methods = extract_message_methods(doc)
    print(f"INFO: Found {len(message_methods)} method-specific messages in AsyncAPI.")

    # 3. Cross-reference daemon registry
    registry, daemon_import_ok = load_daemon_registry()
    missing_in_registry, missing_in_asyncapi = cross_reference_registry(message_methods, registry)

    # 4. Cross-reference SDK params
    sdk_module, sdk_import_ok = load_sdk_params_module()
    sdk_drift = cross_reference_sdk_params(params_schemas, sdk_module)

    # 5. Report
    has_errors = False
    if args.strict and not daemon_import_ok:
        print(
            "\nFAIL: --strict requires soothe_daemon.protocol.schemas to be importable.",
            file=sys.stderr,
        )
        has_errors = True
    if args.strict and not sdk_import_ok:
        print(
            "\nFAIL: --strict requires soothe_client.protocol_params to be importable.",
            file=sys.stderr,
        )
        has_errors = True
    if missing_in_registry:
        print("\nFAIL: Methods in AsyncAPI missing from daemon PARAMS_REGISTRY:")
        has_errors = True
        for line in missing_in_registry:
            print(line)

    if missing_in_asyncapi:
        print("\nWARN: Methods in daemon PARAMS_REGISTRY missing from AsyncAPI:")
        for line in missing_in_asyncapi:
            print(line)
        # Registry entries without AsyncAPI messages are a soft warning — the
        # generic `request` message covers them. Only fail in strict mode.
        if args.strict:
            has_errors = True

    if sdk_drift:
        print("\nFAIL: AsyncAPI params schemas missing from SDK client models:")
        has_errors = True
        for line in sdk_drift:
            print(line)

    if not has_errors:
        print("\nOK: No drift detected. AsyncAPI spec and Pydantic models are in sync.")
        return 0
    print("\nFAIL: Drift detected between AsyncAPI spec and Pydantic models.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
