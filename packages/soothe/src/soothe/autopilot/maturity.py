"""Job-level maturity assessment (RFC-230 / IG-692).

Host-side (Autopilot + CE): structural probes first; latch ``acceptance_met``.
StrangeLoop must not own job maturity.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from soothe.autopilot.evidence_grounding import workspace_pytest_probe

logger = logging.getLogger(__name__)

MaturityLevel = Literal[
    "scaffold",
    "wave_partial",
    "wave_integrated",
    "acceptance_candidate",
    "accepted",
    "blocked",
]
CriterionStatus = Literal["pass", "fail", "unknown", "skipped"]
RailSignal = Literal["needs_feedback", "ready_for_next_wave", "job_complete", "none"]


@dataclass
class MaturityCriterion:
    """One acceptance criterion with probe evidence."""

    id: str
    description: str
    status: CriterionStatus
    evidence: str = ""


@dataclass
class JobMaturitySnapshot:
    """Durable job maturity result stored on the CE job root."""

    assessed_at: datetime
    level: MaturityLevel
    acceptance_met: bool
    criteria: list[MaturityCriterion] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    suggested_rail_signal: RailSignal = "none"
    probe_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for ``GoalNode.maturity``."""
        return {
            "assessed_at": self.assessed_at.isoformat(),
            "level": self.level,
            "acceptance_met": self.acceptance_met,
            "criteria": [
                {
                    "id": c.id,
                    "description": c.description,
                    "status": c.status,
                    "evidence": c.evidence,
                }
                for c in self.criteria
            ],
            "blockers": list(self.blockers),
            "suggested_rail_signal": self.suggested_rail_signal,
            "probe_summary": self.probe_summary,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> JobMaturitySnapshot | None:
        """Parse a stored maturity dict."""
        if not isinstance(raw, dict):
            return None
        criteria: list[MaturityCriterion] = []
        for item in raw.get("criteria") or []:
            if not isinstance(item, dict):
                continue
            criteria.append(
                MaturityCriterion(
                    id=str(item.get("id") or ""),
                    description=str(item.get("description") or ""),
                    status=item.get("status") or "unknown",  # type: ignore[arg-type]
                    evidence=str(item.get("evidence") or ""),
                )
            )
        assessed_raw = raw.get("assessed_at")
        try:
            assessed_at = (
                datetime.fromisoformat(str(assessed_raw)) if assessed_raw else datetime.now(UTC)
            )
        except ValueError:
            assessed_at = datetime.now(UTC)
        if assessed_at.tzinfo is None:
            assessed_at = assessed_at.replace(tzinfo=UTC)
        return cls(
            assessed_at=assessed_at,
            level=raw.get("level") or "scaffold",  # type: ignore[arg-type]
            acceptance_met=bool(raw.get("acceptance_met")),
            criteria=criteria,
            blockers=[str(b) for b in (raw.get("blockers") or [])],
            suggested_rail_signal=raw.get("suggested_rail_signal") or "none",  # type: ignore[arg-type]
            probe_summary=str(raw.get("probe_summary") or ""),
        )


def maturity_wire_fields(maturity: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact maturity fields for job_status / autopilot_top (RFC-230)."""
    snap = JobMaturitySnapshot.from_dict(maturity)
    if snap is None:
        return None
    return {
        "level": snap.level,
        "acceptance_met": snap.acceptance_met,
        "blockers": list(snap.blockers[:8]),
        "suggested_rail_signal": snap.suggested_rail_signal,
        "probe_summary": snap.probe_summary[:500],
        "assessed_at": snap.assessed_at.isoformat(),
    }


def load_goal_md_excerpt(workspace: str | Path | None, *, max_chars: int = 800) -> str:
    """Read workspace GOAL.md body excerpt, or empty string."""
    if not workspace or not str(workspace).strip():
        return ""
    path = Path(workspace).expanduser() / "GOAL.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")[:max_chars].strip()
    except OSError:
        return ""


def acceptance_contract_brief(
    *,
    verification_rules: str | None = None,
    workspace: str | Path | None = None,
    maturity: dict[str, Any] | None = None,
    max_chars: int = 600,
) -> str:
    """Build a short acceptance contract blurb for QA / verify goal descriptions."""
    parts: list[str] = []
    if verification_rules and verification_rules.strip():
        parts.append(f"verification_rules: {verification_rules.strip()[:400]}")
    goal_excerpt = load_goal_md_excerpt(workspace, max_chars=400)
    if goal_excerpt:
        parts.append(f"GOAL.md:\n{goal_excerpt}")
    wire = maturity_wire_fields(maturity)
    if wire and wire.get("blockers"):
        blockers = "; ".join(str(b) for b in wire["blockers"][:5])
        parts.append(f"Current maturity blockers: {blockers}")
    if not parts:
        return (
            "Verify workspace acceptance: build/tests pass and GOAL demos "
            "(e.g. return-N / printf) succeed when applicable."
        )
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def is_verify_class_goal(*, rail_tags: list[str] | None, role: str | None) -> bool:
    """True when a completed goal should trigger job maturity assessment."""
    tags = {t.lower() for t in (rail_tags or [])}
    role_l = (role or "").lower()
    if "qa" in tags or role_l == "qa":
        return True
    if "verify" in tags and "feedback" in tags:
        return True
    return False


def _run_cmd(
    argv: list[str],
    *,
    cwd: Path,
    timeout_s: float,
) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"probe error: {exc}"
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()
    summary = tail[-1] if tail else f"exit={proc.returncode}"
    return proc.returncode, summary[:500]


def _probe_cargo(workspace: Path, *, timeout_s: float = 120.0) -> list[MaturityCriterion]:
    """Cargo build + test probes when ``Cargo.toml`` exists."""
    if not (workspace / "Cargo.toml").is_file():
        return []
    criteria: list[MaturityCriterion] = []
    code, summary = _run_cmd(
        ["cargo", "build", "--workspace"],
        cwd=workspace,
        timeout_s=timeout_s,
    )
    criteria.append(
        MaturityCriterion(
            id="cargo_build",
            description="cargo build --workspace",
            status="pass" if code == 0 else "fail",
            evidence=summary,
        )
    )
    code, summary = _run_cmd(
        ["cargo", "test", "--workspace", "--", "--test-threads=1"],
        cwd=workspace,
        timeout_s=timeout_s,
    )
    criteria.append(
        MaturityCriterion(
            id="cargo_test",
            description="cargo test --workspace",
            status="pass" if code == 0 else "fail",
            evidence=summary,
        )
    )
    # GOAL-style fixture: compile simple_return if ccc binary exists after build.
    ccc = workspace / "target" / "debug" / "ccc"
    fixture = workspace / "tests" / "fixtures" / "simple_return.c"
    if ccc.is_file() and fixture.is_file():
        out = workspace / "target" / "debug" / "_maturity_simple_return"
        code, summary = _run_cmd(
            [str(ccc), str(fixture), "-o", str(out)],
            cwd=workspace,
            timeout_s=min(60.0, timeout_s),
        )
        status: CriterionStatus
        evidence = summary
        if code != 0:
            status = "fail"
        elif out.is_file() and out.stat().st_size <= 128:
            # Header-only / stub ELF — not a real GOAL acceptance.
            status = "fail"
            evidence = f"object too small ({out.stat().st_size}B); likely stub ELF"
        else:
            # Try execute; relocatable stubs fail exec — treat as fail.
            run_code, run_summary = _run_cmd(
                [str(out)],
                cwd=workspace,
                timeout_s=10.0,
            )
            if run_code == 0:
                status = "pass"
                evidence = f"compiled+ran ok ({out.stat().st_size}B)"
            else:
                status = "fail"
                evidence = f"compiled but not executable: {run_summary}"
        criteria.append(
            MaturityCriterion(
                id="goal_simple_return",
                description="Compile and run tests/fixtures/simple_return.c via ccc",
                status=status,
                evidence=evidence,
            )
        )
    return criteria


def _probe_python(workspace: Path) -> list[MaturityCriterion]:
    line = workspace_pytest_probe(str(workspace))
    if not line:
        return []
    status: CriterionStatus = "pass" if "PASS" in line else "fail"
    if "PASS" not in line and "FAIL" not in line:
        status = "unknown"
    return [
        MaturityCriterion(
            id="pytest",
            description="python -m pytest -q",
            status=status,
            evidence=line,
        )
    ]


def _derive_level(*, acceptance_met: bool, criteria: list[MaturityCriterion]) -> MaturityLevel:
    """Coarse level for P0/P1; richer wave-aware levels land in P2."""
    if acceptance_met:
        return "accepted"
    if criteria:
        return "acceptance_candidate"
    return "scaffold"


def _suggested_signal(*, acceptance_met: bool) -> RailSignal:
    if acceptance_met:
        return "job_complete"
    return "needs_feedback"


def latch_acceptance_met(
    *,
    rail_acceptance_met: bool = False,
    maturity: dict[str, Any] | None = None,
) -> bool:
    """Resolve acceptance latch preferring CE maturity over rail_state."""
    if rail_acceptance_met:
        return True
    if isinstance(maturity, dict) and maturity.get("acceptance_met"):
        return True
    return False


class JobMaturityAssessor:
    """Assess job root maturity from workspace probes + optional contract text."""

    def __init__(self, *, cargo_timeout_s: float = 120.0) -> None:
        self._cargo_timeout_s = cargo_timeout_s

    def assess_workspace(
        self,
        workspace: str | Path | None,
        *,
        verification_rules: str | None = None,
        goal_md: str | None = None,
    ) -> JobMaturitySnapshot:
        """Run structural probes under ``workspace`` and build a snapshot.

        Args:
            workspace: Job workspace path.
            verification_rules: Optional RFC-228 rules (recorded as criteria text).
            goal_md: Optional GOAL.md body (recorded; not NL-executed in P0).

        Returns:
            Fresh ``JobMaturitySnapshot``.
        """
        criteria: list[MaturityCriterion] = []
        root: Path | None = None
        if workspace and str(workspace).strip():
            root = Path(workspace).expanduser()
            if root.is_dir():
                criteria.extend(_probe_cargo(root, timeout_s=self._cargo_timeout_s))
                if not any(c.id.startswith("cargo_") for c in criteria):
                    criteria.extend(_probe_python(root))

        # Contract sources are informational (unknown); probes alone latch acceptance.
        if verification_rules and verification_rules.strip():
            criteria.append(
                MaturityCriterion(
                    id="verification_rules",
                    description="Operator verification_rules present",
                    status="unknown",
                    evidence=verification_rules.strip()[:300],
                )
            )
        goal_text = (goal_md or "").strip() or load_goal_md_excerpt(root, max_chars=300)
        if goal_text:
            criteria.append(
                MaturityCriterion(
                    id="goal_md",
                    description="GOAL.md present",
                    status="unknown",
                    evidence=goal_text[:300],
                )
            )

        required = [c for c in criteria if c.id != "verification_rules" and c.id != "goal_md"]
        # Latch only when there is at least one required probe and all pass.
        if not required:
            acceptance_met = False
            blockers = ["no structural probes available for workspace"]
        else:
            fails = [c for c in required if c.status == "fail"]
            unknowns = [c for c in required if c.status in {"unknown", "skipped"}]
            acceptance_met = (
                not fails and not unknowns and all(c.status == "pass" for c in required)
            )
            blockers = [f"{c.id}: {c.evidence or c.status}" for c in fails + unknowns]

        level = _derive_level(acceptance_met=acceptance_met, criteria=criteria)
        signal = _suggested_signal(acceptance_met=acceptance_met)
        summary = "; ".join(f"{c.id}={c.status}" for c in criteria) or "no probes"
        return JobMaturitySnapshot(
            assessed_at=datetime.now(UTC),
            level=level,
            acceptance_met=acceptance_met,
            criteria=criteria,
            blockers=blockers,
            suggested_rail_signal=signal,
            probe_summary=summary,
        )
