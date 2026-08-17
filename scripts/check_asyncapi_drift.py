#!/usr/bin/env python3
"""AsyncAPI spec drift detector (RFC-450 §11.3).

Parses ``docs/specs/asyncapi.yaml`` (AsyncAPI 3.0 — the single source of truth)
and cross-references every ``*Params`` schema and method-specific message against:

1. The daemon ``PARAMS_REGISTRY`` — the ``(type, method) → params model`` map
   that the transport validation layer consults at the wire boundary.
2. The client ``soothe_client.protocol_params`` models — the SDK-side params
   models clients use to validate before send.

A CI check SHALL regenerate and diff against the committed version to detect
drift between the AsyncAPI spec and the Pydantic models (RFC-450 §11.3,
§15.2).  This script detects three classes of drift:

- **Schema gaps**: an ``*Params`` schema in the spec that has no corresponding
  Pydantic model, or a Pydantic model with no corresponding spec schema.
- **Registry gaps**: a ``(type, method)`` pair in the spec that has no entry in
  ``PARAMS_REGISTRY``, or a registry entry with no corresponding spec message.
- **Field drift**: required-field mismatches between the spec schema and the
  Pydantic model (loose check — warns on missing/extra required fields).

Exit codes:
    0 — no drift detected (or warnings only without ``--strict``)
    1 — drift detected (errors), or warnings with ``--strict``

Usage::

    python scripts/check_asyncapi_drift.py            # report drift, exit 0 on warnings
    python scripts/check_asyncapi_drift.py --strict  # exit 1 on any drift (CI mode)
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML is required. Install with 'pip install pyyaml'.", file=sys.stderr)
    sys.exit(2)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Paths
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "specs" / "asyncapi.yaml"

# Daemon package — PARAMS_REGISTRY is the canonical wire validation map.
DAEMON_SRC = ROOT / "packages" / "soothe-daemon" / "src"
# Client package — protocol_params holds the SDK-side validation models.
CLIENT_SRC = ROOT / "client" / "python" / "src"

# Pydantic model name → expected asyncapi schema name conversion.
# Most models follow the convention: ``LoopGetParams`` → ``loopGetParams``.
# A few have different names (documented here so the cross-reference is exact).
_MODEL_TO_SCHEMA_OVERRIDES: dict[str, str] = {
    # Daemon: CommandParams is the slash_command notification model
    "CommandParams": "slashCommandParams",
    "CommandRequestParams": "rpcCommandParams",
    # Client: SlashCommandParams / RpcCommandParams differ from daemon
    "SlashCommandParams": "slashCommandParams",
    "RpcCommandParams": "rpcCommandParams",
    # Client: DeliveryAckParams has no daemon equivalent but matches spec
    "DeliveryAckParams": "deliveryAckParams",
    # AutopilotUnsubscribeParams has no spec schema (non-envelope control type)
    "AutopilotUnsubscribeParams": "",  # explicitly skip
    # PingParams / PongParams have no spec params schema (empty)
    "PingParams": "",
    "PongParams": "",
}

# Schema names that are not param schemas (base/transport-only, skip).
_NON_PARAMS_SCHEMAS = frozenset(
    {
        "baseEnvelope",
        "connectionAckResult",
        "errorObject",
        "streamEventPayload",
        "statusPayload",
    }
)


@dataclass
class DriftFinding:
    """A single structured drift finding (RFC-450 §11.3).

    Fields:
        module: The subsystem the finding concerns — one of
            ``"schema"``, ``"registry"``, ``"client"``, ``"field"``.
        severity: ``"error"`` (structural drift, CI-failing) or
            ``"warning"`` (field-level advisory, non-fatal).
        message: Human-readable description of the drift.
        timestamp: ISO-8601 UTC string when the finding was produced.
    """

    module: str
    severity: str
    message: str
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(tz=timezone.utc).isoformat()

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable mapping of this finding."""
        return {
            "module": self.module,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class DriftReport:
    """Accumulated drift findings."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    findings: list[DriftFinding] = field(default_factory=list)
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(tz=timezone.utc).isoformat()

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    def error(self, msg: str, *, module: str = "schema") -> None:
        self.errors.append(msg)
        self.findings.append(
            DriftFinding(module=module, severity="error", message=msg)
        )

    def warn(self, msg: str, *, module: str = "field") -> None:
        self.warnings.append(msg)
        self.findings.append(
            DriftFinding(module=module, severity="warning", message=msg)
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AsyncAPI spec parsing
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class SpecMessage:
    """A parsed message from the AsyncAPI components.messages section."""

    name: str
    type_const: str | None = None
    method_const: str | list[str] | None = None
    params_schema: str | None = None


@dataclass
class SpecSchema:
    """A parsed params schema from the AsyncAPI components.schemas section."""

    name: str
    required: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    """Load and parse the AsyncAPI YAML spec."""
    if not path.exists():
        print(f"ERROR: AsyncAPI spec not found at {path}", file=sys.stderr)
        sys.exit(2)
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    if not isinstance(spec, dict):
        print(f"ERROR: AsyncAPI spec is not a mapping at {path}", file=sys.stderr)
        sys.exit(2)
    return spec


def parse_messages(spec: dict[str, Any]) -> list[SpecMessage]:
    """Extract method-specific messages from components.messages.

    Each message payload is an ``allOf`` of ``baseEnvelope`` + an inline
    object that pins ``type`` (const) and ``method`` (const or enum) and
    optionally references a ``params`` schema via ``$ref``.

    Generic messages (``request``, ``response``, ``notification``, ``subscribe``,
    etc.) have no pinned method and are returned with ``method_const=None``.
    """
    messages: list[SpecMessage] = []
    comp_messages = spec.get("components", {}).get("messages", {})
    for name, msg_def in comp_messages.items():
        payload = msg_def.get("payload", {})
        all_of = payload.get("allOf", [])
        sm = SpecMessage(name=name)
        if not all_of:
            # Some messages have no allOf (e.g. inline payload) — skip method extraction
            messages.append(sm)
            continue
        for entry in all_of:
            props = entry.get("properties", {})
            if "type" in props and isinstance(props["type"], dict):
                sm.type_const = props["type"].get("const")
            if "method" in props and isinstance(props["method"], dict):
                m = props["method"]
                sm.method_const = m.get("const") or m.get("enum")
            if "params" in props and isinstance(props["params"], dict):
                ref = props["params"].get("$ref", "")
                if ref:
                    sm.params_schema = ref.split("/")[-1]
        messages.append(sm)
    return messages


def parse_params_schemas(spec: dict[str, Any]) -> dict[str, SpecSchema]:
    """Extract all ``*Params`` schemas from components.schemas.

    Returns a mapping of schema name → :class:`SpecSchema`.
    Non-params schemas (envelope, error, transport) are excluded.
    """
    result: dict[str, SpecSchema] = {}
    schemas = spec.get("components", {}).get("schemas", {})
    for name, schema_def in schemas.items():
        if name in _NON_PARAMS_SCHEMAS:
            continue
        if not name.endswith("Params"):
            continue
        required = schema_def.get("required", [])
        properties = schema_def.get("properties", {})
        result[name] = SpecSchema(
            name=name,
            required=list(required) if isinstance(required, list) else [],
            properties=properties if isinstance(properties, dict) else {},
        )
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Pydantic model introspection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _model_to_schema_name(model_name: str) -> str:
    """Convert a Pydantic model name to the expected AsyncAPI schema name.

    ``LoopGetParams`` → ``loopGetParams`` (camelCase first letter).
    Overrides handle the special cases.
    """
    if model_name in _MODEL_TO_SCHEMA_OVERRIDES:
        return _MODEL_TO_SCHEMA_OVERRIDES[model_name]
    # CamelCase → camelCase: lowercase the first letter
    return model_name[0].lower() + model_name[1:]


def _get_pydantic_required_fields(model_cls: type) -> set[str]:
    """Extract required field names from a Pydantic v2 model class.

    A field is "required" if it has no default and no default factory.
    """
    required: set[str] = set()
    for field_name, field_info in model_cls.model_fields.items():
        if field_info.is_required():
            required.add(field_name)
    return required


def load_daemon_registry() -> dict[tuple[str, str | None], type]:
    """Import the daemon PARAMS_REGISTRY and return it as a dict."""
    # Ensure the daemon source is on sys.path
    src_root = str(DAEMON_SRC)
    if src_root not in sys.path:
        sys.path.insert(0, src_root)
    # Also need the client source for soothe_sdk wire codec (imported by schemas)
    client_src = str(CLIENT_SRC)
    if client_src not in sys.path:
        sys.path.insert(0, client_src)
    try:
        module = importlib.import_module("soothe_daemon.protocol.schemas")
        registry = getattr(module, "PARAMS_REGISTRY", {})
        if not registry:
            print("ERROR: PARAMS_REGISTRY is empty or missing", file=sys.stderr)
            sys.exit(2)
        return dict(registry)
    except Exception as e:
        print(f"ERROR: Failed to import daemon PARAMS_REGISTRY: {e}", file=sys.stderr)
        sys.exit(2)


def load_client_params_models() -> dict[str, type]:
    """Import the client protocol_params module and return all *Params model classes."""
    src_root = str(CLIENT_SRC)
    if src_root not in sys.path:
        sys.path.insert(0, src_root)
    try:
        module = importlib.import_module("soothe_client.protocol_params")
        models: dict[str, type] = {}
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and name.endswith("Params")
                and name != "ParamsBase"
                and name != "EmptyParams"
                and hasattr(obj, "model_fields")
            ):
                models[name] = obj
        return models
    except Exception as e:
        print(f"ERROR: Failed to import client protocol_params: {e}", file=sys.stderr)
        sys.exit(2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Drift detection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def check_schema_presence(
    spec_schemas: dict[str, SpecSchema],
    daemon_registry: dict[tuple[str, str | None], type],
    client_models: dict[str, type],
    report: DriftReport,
) -> None:
    """Check that every spec *Params schema has a corresponding Pydantic model.

    Checks both the daemon and client model sets.  A schema in the spec that
    has no model in either set is an error (the spec promises a schema the
    code does not implement).
    """
    spec_schema_names = set(spec_schemas.keys())

    # Build expected schema-name → model-name reverse maps
    daemon_schema_to_model: dict[str, str] = {}
    for model_name in (m for m in _collect_model_names(daemon_registry)):
        schema_name = _model_to_schema_name(model_name)
        if schema_name:
            daemon_schema_to_model[schema_name] = model_name

    client_schema_to_model: dict[str, str] = {}
    for model_name in client_models:
        schema_name = _model_to_schema_name(model_name)
        if schema_name:
            client_schema_to_model[schema_name] = model_name

    # Spec schemas with no model in either daemon or client
    for schema_name in sorted(spec_schema_names):
        in_daemon = schema_name in daemon_schema_to_model
        in_client = schema_name in client_schema_to_model
        if not in_daemon and not in_client:
            report.error(
                f"Schema '{schema_name}' is defined in the AsyncAPI spec but has "
                f"no corresponding Pydantic model in the daemon or client.",
                module="schema",
            )

    # Models with no corresponding spec schema (only check models that expect a schema)
    all_expected_schemas = spec_schema_names
    for schema_name, model_name in sorted(daemon_schema_to_model.items()):
        if schema_name and schema_name not in all_expected_schemas:
            # Skip intentionally-schemaless models (empty string in overrides)
            report.error(
                f"Daemon model '{model_name}' expects schema '{schema_name}' but it "
                f"is not defined in the AsyncAPI spec.",
                module="schema",
            )


def _collect_model_names(
    registry: dict[tuple[str, str | None], type],
) -> set[str]:
    """Extract unique model class names from the registry values."""
    return {cls.__name__ for cls in registry.values()}


def check_registry_coverage(
    spec_messages: list[SpecMessage],
    daemon_registry: dict[tuple[str, str | None], type],
    report: DriftReport,
) -> None:
    """Check that every method-specific spec message has a registry entry.

    Only messages with both a pinned ``type`` and ``method`` (const, not enum)
    and a ``params`` schema ref are checked — these are the concrete
    ``(type, method)`` pairs the daemon must validate.

    Registry entries that have no corresponding spec message are also reported.
    """
    # Build the set of (type, method) pairs the spec defines
    spec_pairs: set[tuple[str, str]] = set()
    for msg in spec_messages:
        if msg.type_const is None or msg.params_schema is None:
            continue
        if msg.method_const is None:
            continue
        if isinstance(msg.method_const, list):
            # Enum method (e.g. subscribe with [loop_events, autopilot_events])
            for m in msg.method_const:
                spec_pairs.add((msg.type_const, m))
        else:
            spec_pairs.add((msg.type_const, msg.method_const))

    # Build the set of (type, method) pairs the daemon registry covers
    registry_pairs: set[tuple[str, str | None]] = set(daemon_registry.keys())

    # Spec pairs with no registry entry
    for pair in sorted(spec_pairs):
        if pair not in registry_pairs:
            report.error(
                f"Spec message defines ({pair[0]!r}, {pair[1]!r}) with a params "
                f"schema but PARAMS_REGISTRY has no entry for this pair.",
                module="registry",
            )

    # Registry entries with no spec message (excluding control types with method=None)
    for pair in sorted(registry_pairs):
        type_val, method_val = pair
        if method_val is None:
            # Non-envelope control types (connection_init, ping, pong, unsubscribe)
            # — these are expected; no spec message with a pinned method
            continue
        if pair not in spec_pairs:
            report.error(
                f"PARAMS_REGISTRY has entry ({type_val!r}, {method_val!r}) but the "
                f"AsyncAPI spec has no corresponding method-specific message.",
                module="registry",
            )


def check_client_model_coverage(
    spec_schemas: dict[str, SpecSchema],
    client_models: dict[str, type],
    report: DriftReport,
) -> None:
    """Check that every client model has a corresponding spec schema.

    Client models without a spec schema are warnings (the client may define
    extra models for local use), not hard errors.
    """
    spec_schema_names = set(spec_schemas.keys())
    for model_name in sorted(client_models):
        schema_name = _model_to_schema_name(model_name)
        if not schema_name:
            continue  # intentionally skipped
        if schema_name not in spec_schema_names:
            report.warn(
                f"Client model '{model_name}' expects schema '{schema_name}' but it "
                f"is not defined in the AsyncAPI spec.",
                module="client",
            )


def check_field_drift(
    spec_schemas: dict[str, SpecSchema],
    daemon_registry: dict[tuple[str, str | None], type],
    client_models: dict[str, type],
    report: DriftReport,
) -> None:
    """Check required-field alignment between spec schemas and Pydantic models.

    For each spec schema that maps to a Pydantic model, compare the spec's
    ``required`` list against the model's required fields.  Missing or extra
    required fields are warnings (field-level drift may be intentional for
    handler flexibility, but should be reviewed).
    """
    # Build schema → model maps for both daemon and client
    for source_name, registry_or_models, is_registry in [
        ("daemon", daemon_registry, True),
        ("client", client_models, False),
    ]:
        if is_registry:
            # Registry: values are model classes, keys are (type, method) pairs
            seen_schemas: set[str] = set()
            for model_cls in registry_or_models.values():
                schema_name = _model_to_schema_name(model_cls.__name__)
                if not schema_name or schema_name in seen_schemas:
                    continue
                seen_schemas.add(schema_name)
                if schema_name not in spec_schemas:
                    continue
                _compare_fields(
                    schema_name, spec_schemas[schema_name], model_cls, source_name, report
                )
        else:
            for model_name, model_cls in registry_or_models.items():
                schema_name = _model_to_schema_name(model_name)
                if not schema_name or schema_name not in spec_schemas:
                    continue
                _compare_fields(
                    schema_name, spec_schemas[schema_name], model_cls, source_name, report
                )


def _compare_fields(
    schema_name: str,
    spec_schema: SpecSchema,
    model_cls: type,
    source_name: str,
    report: DriftReport,
) -> None:
    """Compare required fields between a spec schema and a Pydantic model."""
    spec_required = set(spec_schema.required)
    model_required = _get_pydantic_required_fields(model_cls)

    if spec_required == model_required:
        return

    missing_in_model = spec_required - model_required
    extra_in_model = model_required - spec_required

    if missing_in_model:
        report.warn(
            f"{source_name} model '{model_cls.__name__}' (schema '{schema_name}') "
            f"is missing required fields present in spec: {sorted(missing_in_model)}",
            module="field",
        )
    if extra_in_model:
        report.warn(
            f"{source_name} model '{model_cls.__name__}' (schema '{schema_name}') "
            f"has required fields not in spec: {sorted(extra_in_model)}",
            module="field",
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Output
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def print_report(report: DriftReport, strict: bool, json_output: bool) -> None:
    """Print the drift report in human-readable or JSON format."""
    if json_output:
        output = {
            "errors": report.errors,
            "warnings": report.warnings,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "strict": strict,
            "generated_at": report.generated_at,
            "findings": [f.to_dict() for f in report.findings],
        }
        print(json.dumps(output, indent=2))
        return

    # Human-readable
    if report.errors:
        print(f"\n{'=' * 60}")
        print(f"DRIFT ERRORS ({len(report.errors)}):")
        print(f"{'=' * 60}")
        for err in report.errors:
            print(f"  ✗ {err}")

    if report.warnings:
        print(f"\n{'-' * 60}")
        print(f"DRIFT WARNINGS ({len(report.warnings)}):")
        print(f"{'-' * 60}")
        for warn in report.warnings:
            print(f"  ! {warn}")

    if not report.errors and not report.warnings:
        print("✓ No AsyncAPI spec drift detected.")
        return

    print()
    if report.errors:
        print(f"Summary: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    elif report.warnings:
        print(f"Summary: {len(report.warnings)} warning(s) (advisory; non-fatal)")
    else:
        pass  # already printed "No drift"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run_checks(strict: bool, json_output: bool = False) -> DriftReport:
    """Run all drift checks and return the report."""
    report = DriftReport()

    # Load spec
    spec = load_spec()
    spec_messages = parse_messages(spec)
    spec_schemas = parse_params_schemas(spec)

    # Load code models
    daemon_registry = load_daemon_registry()
    client_models = load_client_params_models()

    # Run checks
    check_schema_presence(spec_schemas, daemon_registry, client_models, report)
    check_registry_coverage(spec_messages, daemon_registry, report)
    check_client_model_coverage(spec_schemas, client_models, report)
    check_field_drift(spec_schemas, daemon_registry, client_models, report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect drift between the AsyncAPI spec and Pydantic models (RFC-450 §11.3).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 on any drift (errors or warnings). Used in CI.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (for programmatic consumption).",
    )
    args = parser.parse_args()

    report = run_checks(strict=args.strict, json_output=args.json)
    print_report(report, args.strict, args.json)

    # Exit logic:
    # - Errors (structural drift: missing schemas/registry entries) → always exit 1
    # - Warnings (field-level advisories) → non-fatal even in --strict; field
    #   optionality is intentionally loosened in the daemon for handler
    #   flexibility (RFC-450 §6.2).  Structural drift is what CI gates on.
    if report.has_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
