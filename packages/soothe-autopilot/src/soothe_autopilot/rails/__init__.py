"""LoopRail: job-scoped workflow-pattern catalog + runtime.

This package merges the former split:

- `soothe.rails`  — static catalog, path tiers, selector, L0 schema,
  verb defaults, and bundled builtin rail YAML.
- `soothe_autopilot.rails` — runtime: interpreter, rail exec, guards,
  wave plan, trace store, recipes, worktree ops.

Both now live here as one one-level subpackage under `soothe_autopilot`.
The static/catalog layer (`catalog`, `builtins`,
`selector`, `l0_schema`, `verb_defaults`, `builtin_rails/`) is the
lower tier; the runtime layer (`interpreter`, `builtins_exec`,
`guards`, `wave_plan`, `recipe_exec`, `trace_store`, ...) imports
from it, never the reverse.

AutopilotService binds `LoopRailInterpreter` on job submit when a
`rail_id` is resolved.
"""

from __future__ import annotations

# --- runtime layer (was soothe_autopilot.rails) ---
from soothe_autopilot.rails.autoresearch_exec import (
    AUTORESEARCH_RAIL_ID,
    AutoresearchExec,
)

# --- static / catalog layer (was soothe.rails) ---
from soothe_autopilot.rails.builtins import get_builtin_rails_dir, get_rails_paths
from soothe_autopilot.rails.builtins_exec import (
    BuiltinResult,
    GoalAnnotation,
    RailBuiltinExecutor,
    RailJobState,
)
from soothe_autopilot.rails.catalog import (
    BUILTIN_RAIL_IDS,
    CE_RAIL_BUILTINS,
    LoopRailCatalog,
    RailCatalogError,
    RailDefinition,
    compute_rail_hash,
    load_rail_file,
)
from soothe_autopilot.rails.guards import (
    AlwaysMatchGuardEvaluator,
    GuardContext,
    GuardEvaluator,
    LLMGuardEvaluator,
    ScriptedGuardEvaluator,
)
from soothe_autopilot.rails.interpreter import LoopRailInterpreter, RailEvent
from soothe_autopilot.rails.l0_schema import L0_OPS, normalize_do_steps
from soothe_autopilot.rails.recipe_exec import RecipeRunner
from soothe_autopilot.rails.selector import (
    RailAutoPicker,
    RailPickResult,
    resolve_rail_for_job,
    resolve_rail_id,
)
from soothe_autopilot.rails.trace_store import (
    GuardResult,
    JsonlRailTraceStore,
    MemoryRailTraceStore,
    RailTraceStore,
    RuleFireRecord,
    export_trace_evaluation,
)
from soothe_autopilot.rails.verb_defaults import (
    DEFAULT_VERB_BRIEFS,
    DEFAULT_VERB_ROLES,
    DEFAULT_VERB_TAGS,
    interpolate_brief,
    resolve_verb_brief,
)
from soothe_autopilot.rails.wave_plan import (
    WavePlan,
    resolve_fanout_slices,
)

__all__ = [
    "AUTORESEARCH_RAIL_ID",
    "AlwaysMatchGuardEvaluator",
    "AutoresearchExec",
    "BUILTIN_RAIL_IDS",
    "BuiltinResult",
    "CE_RAIL_BUILTINS",
    "DEFAULT_VERB_BRIEFS",
    "DEFAULT_VERB_ROLES",
    "DEFAULT_VERB_TAGS",
    "GoalAnnotation",
    "GuardContext",
    "GuardEvaluator",
    "GuardResult",
    "JsonlRailTraceStore",
    "L0_OPS",
    "LLMGuardEvaluator",
    "LoopRailCatalog",
    "LoopRailInterpreter",
    "MemoryRailTraceStore",
    "RailAutoPicker",
    "RailBuiltinExecutor",
    "RailCatalogError",
    "RailDefinition",
    "RailEvent",
    "RailJobState",
    "RailPickResult",
    "RailTraceStore",
    "RecipeRunner",
    "RuleFireRecord",
    "ScriptedGuardEvaluator",
    "WavePlan",
    "compute_rail_hash",
    "export_trace_evaluation",
    "get_builtin_rails_dir",
    "get_rails_paths",
    "interpolate_brief",
    "load_rail_file",
    "normalize_do_steps",
    "resolve_fanout_slices",
    "resolve_rail_for_job",
    "resolve_rail_id",
    "resolve_verb_brief",
]
