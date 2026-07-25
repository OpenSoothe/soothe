"""Host-owned feature diagnose checks (cron, skillify, autopilot, loop)."""

from __future__ import annotations

from typing import Any

from soothe.diagnose.models import (
    CategoryResult,
    CheckResult,
    CheckStatus,
    aggregate_status,
)


def _check_import(module_path: str, name: str) -> CheckResult:
    """Check if a host module can be imported."""
    try:
        __import__(module_path)
        return CheckResult(
            name=name,
            status=CheckStatus.OK,
            message=f"{name} import successful",
            details={"module": module_path},
        )
    except ImportError as e:
        return CheckResult(
            name=name,
            status=CheckStatus.ERROR,
            message=f"{name} import failed: {e}",
            details={
                "module": module_path,
                "remediation": f"Ensure soothe is installed correctly ({module_path})",
            },
        )


def _check_autopilot(config: Any | None) -> CheckResult:
    """Check autopilot config presence and module import."""
    import_result = _check_import("soothe.autopilot", "autopilot_module")
    if import_result.status != CheckStatus.OK:
        return CheckResult(
            name="autopilot",
            status=import_result.status,
            message=import_result.message,
            details=import_result.details,
        )

    if config is None:
        return CheckResult(
            name="autopilot",
            status=CheckStatus.SKIPPED,
            message="Autopilot: no config loaded (module OK)",
            details={"module": "soothe.autopilot"},
        )

    agent = getattr(config, "agent", None)
    autopilot = getattr(agent, "autopilot", None) if agent is not None else None
    if autopilot is None:
        return CheckResult(
            name="autopilot",
            status=CheckStatus.WARNING,
            message="agent.autopilot config missing",
            details={"remediation": "Add agent.autopilot in soothe.yml"},
        )

    enabled = bool(getattr(autopilot, "enabled", False))
    return CheckResult(
        name="autopilot",
        status=CheckStatus.OK,
        message=f"Autopilot config present (enabled={enabled})",
        details={"enabled": enabled, "module": "soothe.autopilot"},
    )


def _check_loop(config: Any | None) -> CheckResult:
    """Check StrangeLoop config presence and module import."""
    import_result = _check_import("soothe.sloop", "sloop_module")
    if import_result.status != CheckStatus.OK:
        return CheckResult(
            name="loop",
            status=import_result.status,
            message=import_result.message,
            details=import_result.details,
        )

    if config is None:
        return CheckResult(
            name="loop",
            status=CheckStatus.SKIPPED,
            message="StrangeLoop: no config loaded (module OK)",
            details={"module": "soothe.sloop"},
        )

    agent = getattr(config, "agent", None)
    loop = getattr(agent, "loop", None) if agent is not None else None
    if loop is None:
        return CheckResult(
            name="loop",
            status=CheckStatus.WARNING,
            message="agent.loop config missing",
            details={"remediation": "Add agent.loop in soothe.yml"},
        )

    return CheckResult(
        name="loop",
        status=CheckStatus.OK,
        message="StrangeLoop (agent.loop) config present",
        details={"module": "soothe.sloop"},
    )


def _check_cron(config: Any | None) -> CheckResult:
    """Check cron config presence and module import."""
    import_result = _check_import("soothe.cron", "cron_module")
    if import_result.status != CheckStatus.OK:
        return CheckResult(
            name="cron",
            status=import_result.status,
            message=import_result.message,
            details=import_result.details,
        )

    if config is None:
        return CheckResult(
            name="cron",
            status=CheckStatus.SKIPPED,
            message="Cron: no config loaded (module OK)",
            details={"module": "soothe.cron"},
        )

    cron = getattr(config, "cron", None)
    if cron is None:
        return CheckResult(
            name="cron",
            status=CheckStatus.WARNING,
            message="cron config missing",
            details={"remediation": "Add cron in soothe.yml"},
        )

    max_jobs = getattr(cron, "max_jobs", None)
    return CheckResult(
        name="cron",
        status=CheckStatus.OK,
        message=f"Cron config present (max_jobs={max_jobs})",
        details={"module": "soothe.cron", "max_jobs": max_jobs},
    )


def _check_skillify(config: Any | None) -> CheckResult:
    """Check skillify config and SDK import when enabled."""
    if config is None:
        return CheckResult(
            name="skillify",
            status=CheckStatus.SKIPPED,
            message="Skillify: no config loaded",
        )

    skillify = getattr(config, "skillify", None)
    if skillify is None:
        return CheckResult(
            name="skillify",
            status=CheckStatus.WARNING,
            message="skillify config missing",
            details={"remediation": "Add skillify in soothe.yml"},
        )

    enabled = bool(getattr(skillify, "enabled", False))
    if not enabled:
        return CheckResult(
            name="skillify",
            status=CheckStatus.SKIPPED,
            message="Skillify disabled (skillify.enabled=false)",
            details={"enabled": False},
        )

    import_result = _check_import("soothe_sdk.skillify", "skillify_module")
    if import_result.status != CheckStatus.OK:
        return CheckResult(
            name="skillify",
            status=CheckStatus.ERROR,
            message=import_result.message,
            details={
                **import_result.details,
                "enabled": True,
                "remediation": "Install soothe-sdk with skillify support",
            },
        )

    return CheckResult(
        name="skillify",
        status=CheckStatus.OK,
        message="Skillify enabled and SDK importable",
        details={
            "enabled": True,
            "model_role": getattr(skillify, "model_role", None),
            "module": "soothe_sdk.skillify",
        },
    )


async def check_host(config: Any | None = None) -> CategoryResult:
    """Check host-owned orchestration features."""
    checks = [
        _check_autopilot(config),
        _check_loop(config),
        _check_cron(config),
        _check_skillify(config),
    ]
    return CategoryResult(
        category="host",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
    )
