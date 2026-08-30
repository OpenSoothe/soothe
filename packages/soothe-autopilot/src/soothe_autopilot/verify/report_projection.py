"""Project CE GoalNode.report into Autopilot judge input.

StrangeLoop ledger → CE `commit_goal_report` is the evidence SoT. Autopilot
does not rebuild a parallel workspace narrative for per-goal judgment.
"""

from __future__ import annotations

from typing import Any


def build_goal_report(
    *,
    outcome: str,
    summary: str = "",
    findings: list[Any] | None = None,
    effects: list[Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable CE goal report from loop-end fields.

    Always produces at least `outcome` + `summary` so report-commit can fire
    even on thin/crash terminals.
    """
    finding_texts: list[str] = []
    for item in findings or []:
        text = getattr(item, "summary", None) or str(item)
        text = str(text).strip()
        if text:
            finding_texts.append(text[:2000])

    effect_rows: list[dict[str, Any]] = []
    for item in effects or []:
        if isinstance(item, dict):
            effect_rows.append(dict(item))
            continue
        row: dict[str, Any] = {}
        for key in ("kind", "ref", "statement", "digest", "confidence"):
            val = getattr(item, key, None)
            if val is not None:
                row[key] = val
        if row:
            effect_rows.append(row)

    report: dict[str, Any] = {
        "outcome": (outcome or "unknown").strip() or "unknown",
        "summary": (summary or "").strip(),
        "findings": finding_texts[:40],
        "effects": effect_rows[:40],
    }
    if extra:
        for key, val in extra.items():
            if key not in report and val is not None:
                report[key] = val
    if not report["summary"]:
        # Minimal report required on every loop end.
        report["summary"] = f"Loop ended with outcome={report['outcome']}"
    return report


def project_goal_report_for_judge(report: dict[str, Any] | None) -> str:
    """Flatten a CE goal report into judge prompt text.

    Prefers summary, then findings, then effects. Empty report → empty string
    (caller must not invoke LLM without a commit).
    """
    if not report:
        return ""
    parts: list[str] = []
    summary = str(report.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    findings = report.get("findings") or []
    if isinstance(findings, list) and findings:
        lines = [f"- {str(f).strip()}" for f in findings[:20] if str(f).strip()]
        if lines:
            parts.append("Findings:\n" + "\n".join(lines))
    effects = report.get("effects") or []
    if isinstance(effects, list) and effects:
        elines: list[str] = []
        for eff in effects[:15]:
            if isinstance(eff, dict):
                stmt = str(eff.get("statement") or eff.get("ref") or "").strip()
                kind = str(eff.get("kind") or "").strip()
                bit = f"{kind}: {stmt}" if kind and stmt else (stmt or kind)
            else:
                bit = str(eff).strip()
            if bit:
                elines.append(f"- {bit}")
        if elines:
            parts.append("Effects:\n" + "\n".join(elines))
    return "\n\n".join(parts).strip()
