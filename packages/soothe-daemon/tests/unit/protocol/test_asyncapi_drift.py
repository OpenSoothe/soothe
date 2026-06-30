"""Tests for the AsyncAPI spec drift checker (RFC-450 §11.3).

The drift checker lives at ``scripts/check_asyncapi_drift.py``. It validates
that the committed AsyncAPI spec (``docs/specs/asyncapi.yaml``) stays in sync
with the daemon's ``PARAMS_REGISTRY`` and the SDK's client-side params models.

These tests run the checker against the real spec to catch drift regressions
before CI does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check_asyncapi_drift.py"
_SPEC_PATH = _REPO_ROOT / "docs" / "specs" / "asyncapi.yaml"


def _load_drift_checker():
    """Import the drift checker script as a module (it's not on the path)."""
    spec = importlib.util.spec_from_file_location("check_asyncapi_drift", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_asyncapi_drift"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def drift_checker():
    """Load the drift checker module once per test module."""
    return _load_drift_checker()


class TestAsyncAPIStructure:
    """The committed AsyncAPI spec must be structurally valid."""

    def test_spec_exists(self) -> None:
        assert _SPEC_PATH.exists(), f"AsyncAPI spec missing at {_SPEC_PATH}"

    def test_spec_loads_as_yaml(self, drift_checker) -> None:
        doc = drift_checker.load_asyncapi(_SPEC_PATH)
        assert isinstance(doc, dict)

    def test_spec_passes_structural_validation(self, drift_checker) -> None:
        doc = drift_checker.load_asyncapi(_SPEC_PATH)
        errors = drift_checker.validate_structure(doc)
        assert not errors, f"Structural errors: {errors}"

    def test_spec_has_params_schemas(self, drift_checker) -> None:
        doc = drift_checker.load_asyncapi(_SPEC_PATH)
        params = drift_checker.extract_params_schemas(doc)
        # RFC-450 §6.2 registry has many methods; the spec should cover the
        # majority of them.
        assert len(params) >= 20, f"Only {len(params)} params schemas found"

    def test_spec_has_method_specific_messages(self, drift_checker) -> None:
        doc = drift_checker.load_asyncapi(_SPEC_PATH)
        methods = drift_checker.extract_message_methods(doc)
        # Should cover loop_*, job_*, daemon_*, skills_*, models_*, etc.
        assert len(methods) >= 20, f"Only {len(methods)} method messages found"


class TestDaemonRegistrySync:
    """AsyncAPI methods must match the daemon's PARAMS_REGISTRY."""

    def test_no_methods_missing_from_registry(self, drift_checker) -> None:
        doc = drift_checker.load_asyncapi(_SPEC_PATH)
        methods = drift_checker.extract_message_methods(doc)
        registry, import_ok = drift_checker.load_daemon_registry()
        assert import_ok, "Daemon PARAMS_REGISTRY not importable"
        missing_in_registry, _missing_in_asyncapi = drift_checker.cross_reference_registry(
            methods, registry
        )
        assert not missing_in_registry, (
            "Methods in AsyncAPI missing from PARAMS_REGISTRY:\n" + "\n".join(missing_in_registry)
        )


class TestSDKParamsSync:
    """AsyncAPI params schemas must have matching SDK client models."""

    def test_no_schemas_missing_from_sdk(self, drift_checker) -> None:
        doc = drift_checker.load_asyncapi(_SPEC_PATH)
        params = drift_checker.extract_params_schemas(doc)
        sdk_module, import_ok = drift_checker.load_sdk_params_module()
        assert import_ok, "SDK params module not importable"
        assert sdk_module is not None, "SDK params module not importable"
        drift = drift_checker.cross_reference_sdk_params(params, sdk_module)
        assert not drift, "AsyncAPI params schemas missing from SDK:\n" + "\n".join(drift)


class TestSchemaNameConversion:
    """snake_case AsyncAPI schema names convert to PascalCase SDK class names."""

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("loopGetParams", "LoopGetParams"),
            ("loopInputParams", "LoopInputParams"),
            ("subscribeParams", "SubscribeParams"),
            ("connectionInitParams", "ConnectionInitParams"),
            ("jobCreateParams", "JobCreateParams"),
            ("slashCommandParams", "SlashCommandParams"),
        ],
    )
    def test_camel_to_pascal(self, drift_checker, input_name: str, expected: str) -> None:
        assert drift_checker.schema_to_camel(input_name) == expected


class TestFullCheckPasses:
    """The end-to-end drift check must pass on the committed spec."""

    def test_main_returns_zero(self, drift_checker, capsys) -> None:
        exit_code = drift_checker.main(["--spec", str(_SPEC_PATH)])
        captured = capsys.readouterr()
        assert exit_code == 0, (
            f"Drift check failed (exit {exit_code}):\n{captured.out}\n{captured.err}"
        )
