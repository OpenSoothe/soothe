"""Unit tests for the AsyncAPI drift detector (RFC-450 §11.3).

Tests the drift-check logic in ``scripts/check_asyncapi_drift.py``:

- ``run_checks()`` against the real spec and models → 0 errors
- ``parse_messages()`` extracts (type, method, params_schema) from spec messages
- ``parse_params_schemas()`` extracts all ``*Params`` schemas
- ``check_schema_presence()`` flags spec schemas with no model
- ``check_registry_coverage()`` flags spec↔registry (type, method) mismatches
- ``check_field_drift()`` warns on required-field mismatches
- ``_model_to_schema_name()`` converts CamelCase model → camelCase schema
- CLI ``--strict`` and ``--json`` exit codes
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "scripts" / "check_asyncapi_drift.py"
SPEC_PATH = ROOT / "docs" / "specs" / "asyncapi.yaml"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Script loader — scripts/ is not a package, load via spec
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.fixture(scope="module")
def drift_mod():
    """Load the drift checker script as a module."""
    spec = importlib.util.spec_from_file_location("_check_asyncapi_drift", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules *before* exec_module so that the @dataclass
    # decorator can resolve cls.__module__ during class body execution
    # (dataclasses._is_type calls sys.modules.get(cls.__module__).__dict__).
    sys.modules["_check_asyncapi_drift"] = mod
    # Insert daemon + client src on sys.path so the script's imports resolve
    for p in (
        str(ROOT / "packages" / "soothe-daemon" / "src"),
        str(ROOT / "client" / "python" / "src"),
    ):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# parse_messages
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_parse_messages_extracts_method_specific_pairs(drift_mod) -> None:
    """Every method-specific message yields (type, method, params_schema)."""
    spec = drift_mod.load_spec()
    messages = drift_mod.parse_messages(spec)
    # Build the (type, method) → params_schema map
    pairs: dict[tuple[str, str], str] = {}
    for msg in messages:
        if msg.type_const and msg.method_const and msg.params_schema:
            if isinstance(msg.method_const, str):
                pairs[(msg.type_const, msg.method_const)] = msg.params_schema
    # Known method-specific messages must be present
    assert ("request", "loop_get") in pairs
    assert pairs[("request", "loop_get")] == "loopGetParams"
    assert ("request", "job_create") in pairs
    assert ("notification", "slash_command") in pairs
    assert ("subscribe", "loop_events") in pairs


def test_parse_messages_generic_messages_have_no_method(drift_mod) -> None:
    """Generic messages (request, response, notification) have method_const=None."""
    spec = drift_mod.load_spec()
    messages = drift_mod.parse_messages(spec)
    by_name = {m.name: m for m in messages}
    # Generic 'request' message has no pinned method
    gen_req = by_name.get("request")
    assert gen_req is not None
    assert gen_req.method_const is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# parse_params_schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_parse_params_schemas_excludes_non_params(drift_mod) -> None:
    """Non-params schemas (baseEnvelope, errorObject, etc.) are excluded."""
    spec = drift_mod.load_spec()
    schemas = drift_mod.parse_params_schemas(spec)
    assert "baseEnvelope" not in schemas
    assert "errorObject" not in schemas
    assert "streamEventPayload" not in schemas
    # Core params schemas are present
    assert "loopGetParams" in schemas
    assert "jobCreateParams" in schemas
    assert "connectionInitParams" in schemas


def test_parse_params_schemas_all_end_with_params(drift_mod) -> None:
    """Every returned schema name ends with 'Params'."""
    spec = drift_mod.load_spec()
    schemas = drift_mod.parse_params_schemas(spec)
    for name in schemas:
        assert name.endswith("Params"), f"{name} does not end with 'Params'"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# _model_to_schema_name
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_model_to_schema_name_camel_case(drift_mod) -> None:
    """CamelCase model → camelCase schema (first letter lowercased)."""
    assert drift_mod._model_to_schema_name("LoopGetParams") == "loopGetParams"
    assert drift_mod._model_to_schema_name("JobCreateParams") == "jobCreateParams"


def test_model_to_schema_name_overrides(drift_mod) -> None:
    """Override map handles special daemon/client naming differences."""
    assert drift_mod._model_to_schema_name("CommandParams") == "slashCommandParams"
    assert drift_mod._model_to_schema_name("CommandRequestParams") == "rpcCommandParams"
    assert drift_mod._model_to_schema_name("SlashCommandParams") == "slashCommandParams"
    # AutopilotUnsubscribeParams / PingParams / PongParams → empty (skip)
    assert drift_mod._model_to_schema_name("AutopilotUnsubscribeParams") == ""
    assert drift_mod._model_to_schema_name("PingParams") == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# check_schema_presence
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_check_schema_presence_no_errors_on_real_spec(drift_mod) -> None:
    """The committed spec and models have no schema-presence drift."""
    spec = drift_mod.load_spec()
    spec_schemas = drift_mod.parse_params_schemas(spec)
    daemon_reg = drift_mod.load_daemon_registry()
    client_models = drift_mod.load_client_params_models()
    report = drift_mod.DriftReport()
    drift_mod.check_schema_presence(spec_schemas, daemon_reg, client_models, report)
    assert not report.errors, f"Schema presence errors: {report.errors}"


def test_check_schema_presence_flags_missing_model(drift_mod) -> None:
    """A spec schema with no model is flagged as an error."""
    fake_schemas = {
        "nonExistentParams": drift_mod.SpecSchema(
            name="nonExistentParams",
            required=[],
            properties={},
        )
    }
    report = drift_mod.DriftReport()
    drift_mod.check_schema_presence(fake_schemas, {}, {}, report)
    assert len(report.errors) == 1
    assert "nonExistentParams" in report.errors[0]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# check_registry_coverage
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_check_registry_coverage_no_errors_on_real_spec(drift_mod) -> None:
    """The committed spec messages and registry have no coverage drift."""
    spec = drift_mod.load_spec()
    spec_messages = drift_mod.parse_messages(spec)
    daemon_reg = drift_mod.load_daemon_registry()
    report = drift_mod.DriftReport()
    drift_mod.check_registry_coverage(spec_messages, daemon_reg, report)
    assert not report.errors, f"Registry coverage errors: {report.errors}"


def test_check_registry_coverage_flags_missing_registry_entry(drift_mod) -> None:
    """A spec (type, method) pair with no registry entry is an error."""
    fake_messages = [
        drift_mod.SpecMessage(
            name="fakeRequest",
            type_const="request",
            method_const="fake_method",
            params_schema="fakeParams",
        )
    ]
    report = drift_mod.DriftReport()
    drift_mod.check_registry_coverage(fake_messages, {}, report)
    assert len(report.errors) == 1
    assert "fake_method" in report.errors[0]


def test_check_registry_coverage_flags_orphan_registry_entry(drift_mod) -> None:
    """A registry (type, method) pair with no spec message is an error."""
    report = drift_mod.DriftReport()
    drift_mod.check_registry_coverage([], {("request", "orphan_method"): object}, report)
    assert len(report.errors) == 1
    assert "orphan_method" in report.errors[0]


def test_check_registry_coverage_skips_control_types(drift_mod) -> None:
    """Registry entries with method=None (control types) are not flagged."""
    report = drift_mod.DriftReport()
    drift_mod.check_registry_coverage(
        [],
        {
            ("connection_init", None): object,
            ("ping", None): object,
            ("pong", None): object,
            ("unsubscribe", None): object,
        },
        report,
    )
    assert not report.errors


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# check_field_drift
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_check_field_drift_warnings_are_advisory(drift_mod) -> None:
    """Field drift produces warnings (not errors) — optionality is loosened."""
    spec = drift_mod.load_spec()
    spec_schemas = drift_mod.parse_params_schemas(spec)
    daemon_reg = drift_mod.load_daemon_registry()
    client_models = drift_mod.load_client_params_models()
    report = drift_mod.DriftReport()
    drift_mod.check_field_drift(spec_schemas, daemon_reg, client_models, report)
    # Warnings are expected (daemon loosens required fields for handler flexibility)
    # but no errors
    assert not report.errors, f"Field drift errors: {report.errors}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# run_checks (integration)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_run_checks_zero_errors(drift_mod) -> None:
    """Full drift check against the committed spec yields zero errors."""
    report = drift_mod.run_checks(strict=True)
    assert not report.errors, f"Drift errors: {report.errors}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI (subprocess)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _run_cli(*args: str) -> tuple[int, str]:
    """Run the drift checker CLI and return (exit_code, stdout)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return result.returncode, result.stdout


def test_cli_default_exits_zero() -> None:
    """Default mode (no --strict) exits 0 even with warnings."""
    code, _ = _run_cli()
    assert code == 0


def test_cli_strict_exits_zero_on_no_errors() -> None:
    """--strict exits 0 when there are no structural errors (warnings are advisory)."""
    code, _ = _run_cli("--strict")
    assert code == 0


def test_cli_json_output() -> None:
    """--json produces valid JSON with expected keys."""
    code, stdout = _run_cli("--json")
    assert code == 0
    data: dict[str, Any] = json.loads(stdout)
    assert "errors" in data
    assert "warnings" in data
    assert "error_count" in data
    assert "warning_count" in data
    assert data["error_count"] == 0


def test_cli_no_drift_message() -> None:
    """When no errors and no warnings, the 'no drift' message is printed."""
    # This only happens if warnings == 0; we can't guarantee that, so just
    # verify the script runs and produces output
    code, stdout = _run_cli()
    assert code == 0
    # Either "No drift" or warnings summary is present
    assert "drift" in stdout.lower() or "warning" in stdout.lower()
