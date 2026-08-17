"""Job-level maturity assessment (RFC-230).

Host-side (Autopilot + CE): structured LLM judges the job acceptance contract
against DAG + workspace evidence; latch ``acceptance_met``. StrangeLoop must
not own job maturity. Domain-agnostic — coding and non-coding workspaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from soothe_autopilot.prompts import build_maturity_prompt
from soothe_autopilot.verify.constants import (
    _MATURITY_DAG_DESC_MAX_CHARS,
    _MATURITY_GOAL_MD_MAX_CHARS,
    _MATURITY_PROBE_SUMMARY_MAX_CHARS,
    _MATURITY_VERIFICATION_RULES_MAX_CHARS,
    _WORKSPACE_INVENTORY_MAX_CHARS,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from soothe.context.models import GoalNode

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
RailSignal = Literal[
    "needs_feedback",
    "slices_ready_to_spawn",
    "ready_for_next_wave",  # legacy alias; must not withhold ready slices
    "job_complete",
    "none",
]

_WORKSPACE_INVENTORY_MAX_ENTRIES = 80
_DAG_SUMMARY_MAX_CHILDREN = 40


@dataclass
class MaturityCriterion:
    """One acceptance criterion with evidence."""

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


class MaturityCriterionOut(BaseModel):
    """Structured LLM criterion row."""

    id: str = Field(description="Short stable criterion id")
    description: str = Field(default="", description="What was checked")
    status: CriterionStatus = Field(description="pass, fail, unknown, or skipped")
    evidence: str = Field(default="", description="Brief evidence for the status")


class MaturityAssessmentVerdict(BaseModel):
    """Structured job-maturity LLM outcome (RFC-630)."""

    acceptance_met: bool = Field(
        description="True only when the job acceptance contract is satisfied"
    )
    level: MaturityLevel = Field(description="Coarse maturity level derived from contract judgment")
    criteria: list[MaturityCriterionOut] = Field(
        default_factory=list,
        description="Per-criterion statuses against the acceptance contract",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Short blockers when acceptance is not met",
    )
    suggested_rail_signal: RailSignal = Field(
        description="job_complete when accepted; needs_feedback when not; else none"
    )
    reasoning: str = Field(default="", description="Brief overall reasoning")


class MaturityAssessmentError(RuntimeError):
    """Raised when job maturity assessment cannot run (missing model or LLM failure)."""


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
        "probe_summary": snap.probe_summary[:_MATURITY_PROBE_SUMMARY_MAX_CHARS],
        "assessed_at": snap.assessed_at.isoformat(),
    }


def acceptance_contract_brief(
    *,
    verification_rules: str | None = None,
    jobs_root: Path | None = None,
    job_id: str | None = None,
    maturity: dict[str, Any] | None = None,
    max_chars: int = _MATURITY_VERIFICATION_RULES_MAX_CHARS,
) -> str:
    """Build a short acceptance contract blurb for QA / verify goal descriptions.

    Reads the durable job artifact ``jobs/{job_id}/GOAL.md`` only — never a
    workspace-tree ``GOAL.md`` (IG-742).
    """
    from soothe_autopilot.intake import load_job_goal_md

    parts: list[str] = []
    if verification_rules and verification_rules.strip():
        parts.append(
            f"verification_rules: {verification_rules.strip()[:_MATURITY_VERIFICATION_RULES_MAX_CHARS]}"
        )
    goal_excerpt = load_job_goal_md(
        jobs_root=jobs_root,
        job_id=job_id,
        max_chars=_MATURITY_GOAL_MD_MAX_CHARS,
    )
    if goal_excerpt:
        parts.append(f"GOAL.md:\n{goal_excerpt}")
    wire = maturity_wire_fields(maturity)
    if wire and wire.get("blockers"):
        blockers = "; ".join(str(b) for b in wire["blockers"][:5])
        parts.append(f"Current maturity blockers: {blockers}")
    if not parts:
        return (
            "Verify the job acceptance contract: deliverables and success "
            "criteria in the job GOAL.md / verification_rules (or the job "
            "description) must be satisfied for this workspace domain."
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


def shallow_workspace_inventory(
    workspace: str | Path | None,
    *,
    max_entries: int = _WORKSPACE_INVENTORY_MAX_ENTRIES,
    max_chars: int = _WORKSPACE_INVENTORY_MAX_CHARS,
) -> str:
    """List shallow workspace paths for LLM evidence (no command execution)."""
    if not workspace or not str(workspace).strip():
        return ""
    root = Path(workspace).expanduser()
    if not root.is_dir():
        return ""
    lines: list[str] = []
    try:
        # Top-level first, then one level of nesting.
        top = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for entry in top:
            if len(lines) >= max_entries:
                break
            rel = entry.name
            if entry.is_dir():
                lines.append(f"{rel}/")
                try:
                    children = sorted(entry.iterdir(), key=lambda p: p.name.lower())
                except OSError:
                    continue
                for child in children[:12]:
                    if len(lines) >= max_entries:
                        break
                    suffix = "/" if child.is_dir() else ""
                    lines.append(f"{rel}/{child.name}{suffix}")
            else:
                lines.append(rel)
    except OSError as exc:
        return f"(inventory error: {exc})"
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def format_job_dag_summary(
    root: GoalNode | None,
    children: list[GoalNode] | None,
    *,
    max_children: int = _DAG_SUMMARY_MAX_CHILDREN,
) -> str:
    """Compact DAG summary for the maturity evidence pack."""
    parts: list[str] = []
    if root is not None:
        parts.append(
            f"root id={root.id} status={root.status} desc={(root.description or '')[:_MATURITY_DAG_DESC_MAX_CHARS]}"
        )
    for child in (children or [])[:max_children]:
        tags = ",".join(child.rail_tags or []) or "-"
        role = child.role or "-"
        parts.append(
            f"- {child.id} status={child.status} role={role} tags={tags} "
            f"desc={(child.description or '')[:_MATURITY_DAG_DESC_MAX_CHARS]}"
        )
    if children and len(children) > max_children:
        parts.append(f"... ({len(children) - max_children} more children omitted)")
    return "\n".join(parts)


def _snapshot_from_verdict(verdict: MaturityAssessmentVerdict) -> JobMaturitySnapshot:
    criteria = [
        MaturityCriterion(
            id=c.id,
            description=c.description,
            status=c.status,
            evidence=c.evidence,
        )
        for c in verdict.criteria
    ]
    level: MaturityLevel = verdict.level
    if verdict.acceptance_met:
        level = "accepted"
        signal: RailSignal = (
            verdict.suggested_rail_signal
            if verdict.suggested_rail_signal == "job_complete"
            else "job_complete"
        )
    else:
        if level == "accepted":
            level = "acceptance_candidate"
        signal = (
            verdict.suggested_rail_signal
            if verdict.suggested_rail_signal
            in {
                "needs_feedback",
                "none",
                "slices_ready_to_spawn",
                "ready_for_next_wave",
            }
            else "needs_feedback"
        )
    summary = (
        verdict.reasoning.strip()
        or "; ".join(f"{c.id}={c.status}" for c in criteria)
        or "llm assessment"
    )
    return JobMaturitySnapshot(
        assessed_at=datetime.now(UTC),
        level=level,
        acceptance_met=bool(verdict.acceptance_met),
        criteria=criteria,
        blockers=list(verdict.blockers),
        suggested_rail_signal=signal,
        probe_summary=summary[:_MATURITY_PROBE_SUMMARY_MAX_CHARS],
    )


def _fail_closed_snapshot(*, reason: str) -> JobMaturitySnapshot:
    return JobMaturitySnapshot(
        assessed_at=datetime.now(UTC),
        level="scaffold",
        acceptance_met=False,
        criteria=[],
        blockers=[reason],
        suggested_rail_signal="needs_feedback",
        probe_summary=reason,
    )


class JobMaturityAssessor:
    """Assess job root maturity via structured LLM against the acceptance contract."""

    def __init__(self, *, model: BaseChatModel | None = None) -> None:
        self._model = model

    async def assess(
        self,
        workspace: str | Path | None,
        *,
        verification_rules: str | None = None,
        goal_md: str | None = None,
        dag_summary: str | None = None,
        qa_response: str | None = None,
        root: GoalNode | None = None,
        children: list[GoalNode] | None = None,
    ) -> JobMaturitySnapshot:
        """Gather evidence and run structured LLM maturity assessment.

        Args:
            workspace: Job workspace path (shallow inventory only).
            verification_rules: Optional operator criteria from job_create.
            goal_md: Optional GOAL.md body.
            dag_summary: Optional preformatted DAG text; else built from root/children.
            qa_response: Optional latest QA/verify StrangeLoop response excerpt.
            root: Optional job root node for DAG summary.
            children: Optional job descendants for DAG summary.

        Returns:
            Fresh ``JobMaturitySnapshot``. Fail-closed (acceptance_met=false)
            when the model is missing; raises ``MaturityAssessmentError`` on
            LLM invoke failure so callers can log without latching true.
        """
        rules = (verification_rules or "").strip()
        goal_text = (goal_md or "").strip()
        dag = (dag_summary or "").strip() or format_job_dag_summary(root, children)
        inventory = shallow_workspace_inventory(workspace)
        qa = (qa_response or "").strip()

        if self._model is None:
            logger.warning("Job maturity model missing; fail-closed (no acceptance latch)")
            return _fail_closed_snapshot(reason="maturity model unavailable")

        prompt = build_maturity_prompt(
            verification_rules=rules,
            goal_md=goal_text,
            dag_summary=dag,
            workspace_inventory=inventory,
            qa_response=qa,
        )
        try:
            from langchain_core.messages import HumanMessage
            from soothe_nano.llm.invoke_policy import (
                await_with_llm_call_policy,
                llm_rate_limit_config_from,
            )
            from soothe_nano.llm.observability import create_llm_call_metadata
            from soothe_nano.llm.structured import invoke_structured_chat_typed
            from soothe_nano.utils.text_preview import preview_first

            invoke_config = {
                "metadata": create_llm_call_metadata(
                    purpose="job_maturity",
                    component="autopilot.job_maturity",
                    phase="post-verify",
                )
            }

            async def _invoke() -> MaturityAssessmentVerdict:
                return await invoke_structured_chat_typed(
                    self._model,
                    [HumanMessage(content=prompt)],
                    MaturityAssessmentVerdict,
                    config=invoke_config,
                )

            verdict = await await_with_llm_call_policy(
                _invoke,
                config=llm_rate_limit_config_from(None),
            )
            snapshot = _snapshot_from_verdict(verdict)
            logger.info(
                "Job maturity LLM: acceptance_met=%s level=%s reasoning=%s",
                snapshot.acceptance_met,
                snapshot.level,
                preview_first(verdict.reasoning or "", 200),
            )
            return snapshot
        except MaturityAssessmentError:
            raise
        except Exception as exc:
            logger.exception("Job maturity LLM assessment failed")
            msg = f"Job maturity LLM assessment failed: {exc}"
            raise MaturityAssessmentError(msg) from exc
