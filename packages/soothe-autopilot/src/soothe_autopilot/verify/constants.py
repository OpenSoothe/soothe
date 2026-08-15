"""Job-maturity and workspace-inventory evidence caps (RFC-230).

These thresholds bound each evidence slice the autopilot maturity assessor
feeds to the LLM (verification_rules, GOAL.md, DAG summary, QA response) so
the assessor sees full contract context without unbounded growth; each
defaults to the full inventory budget. They were moved here from
``soothe.config.constants`` — they are autopilot-owned, not host config.
"""

from __future__ import annotations

_WORKSPACE_INVENTORY_MAX_CHARS: int = 25_000

_MATURITY_GOAL_MD_MAX_CHARS: int = 25_000
_MATURITY_VERIFICATION_RULES_MAX_CHARS: int = 25_000
_MATURITY_DAG_DESC_MAX_CHARS: int = 25_000
_MATURITY_PROBE_SUMMARY_MAX_CHARS: int = 25_000
