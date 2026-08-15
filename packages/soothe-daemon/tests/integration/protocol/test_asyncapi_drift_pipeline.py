"""Integration tests for the drift → alert → issue pipeline (RFC-450 §11.3).

These tests exercise the full three-stage tooling pipeline described in
RFC-450 §11.3 "Tooling Pipeline" and §15.2 "Generated Pydantic model
management":

1. **Drift detection** — ``scripts/check_asyncapi_drift.py`` parses
   ``docs/specs/asyncapi.yaml`` (the single source of truth) and
   cross-references every ``*Params`` schema and method-specific message
   against the daemon ``PARAMS_REGISTRY`` and client
   ``soothe_client.protocol_params`` models.

2. **Alert generation** — the ``--json`` mode emits a structured alert
   object (``errors``, ``warnings``, ``error_count``, ``warning_count``)
   that downstream consumers (verify_finally.sh ``record_failure_log``,
   CI dashboards) can parse to surface actionable diagnostics.

3. **Issue synthesis** — the structured alert carries enough detail
   (schema names, ``(type, method)`` pairs, field-level deltas) for an
   operator or automated system to file a tracking issue describing the
   exact drift — the "issue" stage of the pipeline.

The tests validate the entire pipeline end-to-end:

- The committed spec produces zero structural errors (the baseline invariant).
- ``--json`` output is well-formed and parseable by downstream consumers.
- Injected drift (missing schema, orphan registry entry) flows through the
  full pipeline: detection → structured alert → synthesised issue body
  containing the drift detail.
- The ``verify_finally.sh`` integration contract (``record_check_outcome``
  pass/fail/skip transitions) is honoured.
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
VERIFY_SCRIPT = ROOT / "scripts" / "verify_finally.sh"


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
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _run_cli(*args: str) -> tuple[int, str, str]:
    """Run the drift checker CLI and return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return result.returncode, result.stdout, result.stderr


def _run_cli_json(*args: str) -> tuple[int, dict[str, Any]]:
    """Run the drift checker CLI with --json and return (exit_code, parsed_json)."""
    code, stdout, _ = _run_cli("--json", *args)
    data: dict[str, Any] = json.loads(stdout)
    return code, data


def _synthesise_issue_body(alert: dict[str, Any]) -> str:
    """Synthesise a GitHub-issue-style body from a structured drift alert.

    This mirrors what an operator or automated issue-filer would produce
    from the ``--json`` output: a human-readable summary of each drift
    finding, grouped by severity.
    """
    lines: list[str] = []
    lines.append(
        f"# AsyncAPI Spec Drift — {alert['error_count']} error(s), "
        f"{alert['warning_count']} warning(s)"
    )
    lines.append("")
    lines.append("Detected by `scripts/check_asyncapi_drift.py --strict` (RFC-450 §11.3).")
    lines.append("")
    if alert["errors"]:
        lines.append("## Errors (structural drift)")
        for err in alert["errors"]:
            lines.append(f"- {err}")
        lines.append("")
    if alert["warnings"]:
        lines.append("## Warnings (field-level advisories)")
        for warn in alert["warnings"]:
            lines.append(f"- {warn}")
        lines.append("")
    lines.append("## Remediation")
    lines.append("1. Review the schemas/models listed above.")
    lines.append("2. Update `docs/specs/asyncapi.yaml` or the Pydantic models to resolve drift.")
    lines.append(
        "3. Re-run `python scripts/check_asyncapi_drift.py --strict` to confirm zero errors."
    )
    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 1: Drift detection — baseline invariant
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDriftDetection:
    """Stage 1: the drift detector correctly identifies (or absents) drift."""

    def test_committed_spec_has_zero_structural_errors(self, drift_mod) -> None:
        """The committed spec and models have no structural drift.

        This is the baseline CI invariant: ``--strict`` must exit 0.  If
        this test fails, someone changed the spec or models without
        updating the other side.
        """
        report = drift_mod.run_checks(strict=True)
        assert not report.errors, f"Structural drift detected in committed spec: {report.errors}"

    def test_drift_detector_loads_real_spec(self, drift_mod) -> None:
        """The detector can load and parse the real asyncapi.yaml."""
        spec = drift_mod.load_spec()
        assert isinstance(spec, dict)
        assert "components" in spec
        # The spec must define both schemas and messages
        assert "schemas" in spec["components"]
        assert "messages" in spec["components"]

    def test_drift_detector_loads_daemon_registry(self, drift_mod) -> None:
        """The detector can import the daemon PARAMS_REGISTRY."""
        registry = drift_mod.load_daemon_registry()
        assert isinstance(registry, dict)
        assert len(registry) > 0, "PARAMS_REGISTRY is empty"
        # Every key is a (type, method?) tuple
        for key in registry:
            assert isinstance(key, tuple)
            assert len(key) == 2

    def test_drift_detector_loads_client_models(self, drift_mod) -> None:
        """The detector can import the client protocol_params models."""
        models = drift_mod.load_client_params_models()
        assert isinstance(models, dict)
        assert len(models) > 0, "No client params models found"
        # Every value is a Pydantic model class
        for model_cls in models.values():
            assert hasattr(model_cls, "model_fields"), f"{model_cls} is not a Pydantic model"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 2: Alert generation — structured --json output
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAlertGeneration:
    """Stage 2: ``--json`` produces a structured alert for downstream consumers."""

    def test_json_alert_has_required_keys(self) -> None:
        """The JSON alert contains all keys a downstream consumer needs."""
        code, alert = _run_cli_json()
        assert code == 0, f"Drift checker exited {code} with errors: {alert.get('errors')}"
        for key in ("errors", "warnings", "error_count", "warning_count", "strict"):
            assert key in alert, f"Missing key '{key}' in JSON alert"
        assert isinstance(alert["errors"], list)
        assert isinstance(alert["warnings"], list)
        assert isinstance(alert["error_count"], int)
        assert isinstance(alert["warning_count"], int)
        assert isinstance(alert["strict"], bool)

    def test_json_alert_error_count_matches_list_length(self) -> None:
        """``error_count`` must equal ``len(errors)``."""
        _, alert = _run_cli_json()
        assert alert["error_count"] == len(alert["errors"])

    def test_json_alert_warning_count_matches_list_length(self) -> None:
        """``warning_count`` must equal ``len(warnings)``."""
        _, alert = _run_cli_json()
        assert alert["warning_count"] == len(alert["warnings"])

    def test_json_alert_baseline_has_zero_errors(self) -> None:
        """The committed spec produces zero errors in the JSON alert."""
        _, alert = _run_cli_json()
        assert alert["error_count"] == 0, (
            f"Expected 0 errors, got {alert['error_count']}: {alert['errors']}"
        )

    def test_json_alert_strict_flag_reflected(self) -> None:
        """The ``strict`` field in the JSON output reflects the --strict flag."""
        _, alert = _run_cli_json("--strict")
        assert alert["strict"] is True

    def test_json_alert_no_strict_flag_reflected(self) -> None:
        """Without --strict, the ``strict`` field is False."""
        _, alert = _run_cli_json()
        assert alert["strict"] is False

    def test_human_readable_output_contains_drift_summary(self) -> None:
        """Human-readable output (no --json) contains drift-related text."""
        code, stdout, _ = _run_cli()
        assert code == 0
        lower = stdout.lower()
        # Either "no drift" or a summary with "warning" / "error"
        assert "drift" in lower or "warning" in lower


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Stage 3: Issue synthesis — structured alert → issue body
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestIssueSynthesis:
    """Stage 3: the structured alert carries enough detail to file an issue."""

    def test_synthesised_issue_body_has_title(self) -> None:
        """The issue body starts with a markdown H1 title."""
        _, alert = _run_cli_json()
        body = _synthesise_issue_body(alert)
        assert body.startswith("# AsyncAPI Spec Drift")

    def test_synthesised_issue_body_has_remediation_section(self) -> None:
        """The issue body includes a remediation section."""
        _, alert = _run_cli_json()
        body = _synthesise_issue_body(alert)
        assert "## Remediation" in body
        assert "check_asyncapi_drift.py" in body

    def test_synthesised_issue_body_lists_errors_when_present(self, drift_mod) -> None:
        """When drift is injected, the issue body lists each error."""
        # Inject a missing schema to produce a structural error
        fake_schemas = {
            "nonExistentParams": drift_mod.SpecSchema(
                name="nonExistentParams",
                required=[],
                properties={},
            )
        }
        report = drift_mod.DriftReport()
        drift_mod.check_schema_presence(fake_schemas, {}, {}, report)
        assert report.has_errors

        alert = {
            "errors": report.errors,
            "warnings": report.warnings,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "strict": True,
        }
        body = _synthesise_issue_body(alert)
        assert "## Errors (structural drift)" in body
        assert "nonExistentParams" in body

    def test_synthesised_issue_body_lists_warnings_when_present(self, drift_mod) -> None:
        """When field-level drift exists, the issue body lists warnings."""
        report = drift_mod.DriftReport()
        report.warn("Test warning: field 'foo' missing from model 'BarParams'")
        alert = {
            "errors": report.errors,
            "warnings": report.warnings,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "strict": True,
        }
        body = _synthesise_issue_body(alert)
        assert "## Warnings (field-level advisories)" in body
        assert "foo" in body
        assert "BarParams" in body

    def test_synthesised_issue_body_omits_empty_sections(self) -> None:
        """When there are no errors, the errors section is omitted."""
        alert = {
            "errors": [],
            "warnings": [],
            "error_count": 0,
            "warning_count": 0,
            "strict": True,
        }
        body = _synthesise_issue_body(alert)
        assert "## Errors" not in body
        assert "## Warnings" not in body


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# End-to-end pipeline: drift → alert → issue (injected drift)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDriftAlertIssuePipeline:
    """End-to-end: injected drift flows through detection → alert → issue."""

    def test_missing_schema_drift_flows_through_pipeline(self, drift_mod) -> None:
        """A spec schema with no model is detected, alerted, and synthesised.

        Pipeline:
        1. Inject a fake schema → ``check_schema_presence`` detects the error.
        2. Build a structured alert from the report.
        3. Synthesise an issue body and verify it contains the schema name.
        """
        # Stage 1: detection
        fake_schemas = {
            "missingSchemaParams": drift_mod.SpecSchema(
                name="missingSchemaParams",
                required=["loop_id"],
                properties={"loop_id": {"type": "string"}},
            )
        }
        report = drift_mod.DriftReport()
        drift_mod.check_schema_presence(fake_schemas, {}, {}, report)
        assert report.has_errors
        assert any("missingSchemaParams" in e for e in report.errors)

        # Stage 2: alert
        alert = {
            "errors": report.errors,
            "warnings": report.warnings,
            "error_count": len(report.errors),
            "warning_count": len(report.warnings),
            "strict": True,
        }
        assert alert["error_count"] >= 1

        # Stage 3: issue
        body = _synthesise_issue_body(alert)
        assert "missingSchemaParams" in body
        assert "## Errors (structural drift)" in body

    def test_orphan_registry_entry_flows_through_pipeline(self, drift_mod) -> None:
        """A registry entry with no spec message flows through the pipeline."""
        # Stage 1: detection
        fake_registry = {("request", "orphan_method"): type("FakeParams", (), {})}
        report = drift_mod.DriftReport()
        drift_mod.check_registry_coverage([], fake_registry, report)
        assert report.has_errors
        assert any("orphan_method" in e for e in report.errors)

        # Stage 2: alert
        alert = {
            "errors": report.errors,
            "warnings": [],
            "error_count": len(report.errors),
            "warning_count": 0,
            "strict": True,
        }

        # Stage 3: issue
        body = _synthesise_issue_body(alert)
        assert "orphan_method" in body

    def test_missing_registry_entry_flows_through_pipeline(self, drift_mod) -> None:
        """A spec (type, method) with no registry entry flows through."""
        # Stage 1: detection
        fake_messages = [
            drift_mod.SpecMessage(
                name="fakeRequest",
                type_const="request",
                method_const="unknown_method",
                params_schema="unknownParams",
            )
        ]
        report = drift_mod.DriftReport()
        drift_mod.check_registry_coverage(fake_messages, {}, report)
        assert report.has_errors
        assert any("unknown_method" in e for e in report.errors)

        # Stage 2 → Stage 3
        alert = {
            "errors": report.errors,
            "warnings": [],
            "error_count": len(report.errors),
            "warning_count": 0,
            "strict": True,
        }
        body = _synthesise_issue_body(alert)
        assert "unknown_method" in body

    def test_clean_spec_produces_empty_issue(self) -> None:
        """When there is no drift, the issue body has no error/warning sections."""
        _, alert = _run_cli_json()
        body = _synthesise_issue_body(alert)
        # No errors section (baseline has 0 errors)
        assert "## Errors" not in body
        # The body still has the title and remediation
        assert "# AsyncAPI Spec Drift" in body
        assert "## Remediation" in body


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# verify_finally.sh integration contract
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestVerifyFinallyIntegration:
    """The verify_finally.sh contract: pass/fail/skip outcome transitions."""

    def test_verify_finally_has_asyncapi_drift_check(self) -> None:
        """verify_finally.sh defines and calls check_asyncapi_drift."""
        content = VERIFY_SCRIPT.read_text(encoding="utf-8")
        # Function is defined
        assert "check_asyncapi_drift()" in content
        # Function is called in the execution block
        # (appears in both the main block and the --fast path)
        assert content.count("check_asyncapi_drift") >= 3, (
            "check_asyncapi_drift should be defined and called"
        )

    def test_verify_finally_uses_strict_flag(self) -> None:
        """verify_finally.sh runs the drift checker with --strict (CI mode)."""
        content = VERIFY_SCRIPT.read_text(encoding="utf-8")
        assert "--strict" in content, (
            "verify_finally.sh must run drift checker with --strict for CI gating"
        )

    def test_verify_finally_records_outcome(self) -> None:
        """verify_finally.sh records pass/fail/skip outcomes for the drift check."""
        content = VERIFY_SCRIPT.read_text(encoding="utf-8")
        # The function records outcomes via record_check_outcome
        assert 'record_check_outcome "asyncapi"' in content
        # All three states should be present
        assert '"pass"' in content or '"pass"' in content
        assert '"fail"' in content
        assert '"skip"' in content

    def test_verify_finally_records_failure_log(self) -> None:
        """verify_finally.sh records failure details for end-of-run summary."""
        content = VERIFY_SCRIPT.read_text(encoding="utf-8")
        assert "record_failure_log" in content
        assert "AsyncAPI drift" in content

    def test_ci_workflow_runs_drift_check(self) -> None:
        """The CI workflow runs the drift checker with --strict."""
        ci_path = ROOT / ".github" / "workflows" / "ci.yml"
        content = ci_path.read_text(encoding="utf-8")
        assert "check_asyncapi_drift.py" in content
        assert "--strict" in content
