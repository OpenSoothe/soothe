# IG-447: Progressive Skill Loading

**RFC**: RFC-105
**Status**: Draft
**Created**: 2026-05-29
**Depends on**: RFC-100 (CoreAgent), RFC-104 (Dynamic System Context), RFC-214 (Cache volatility), RFC-218 (Checkpoint tree), RFC-600 (Plugins)

---

## Goal

Replace deepagents' always-emit-all skill listing with a three-stage progressive disclosure pipeline:

1. **Stage 1** — budgeted, delta-only `<AVAILABLE_SKILLS>` block injected by `SystemPromptOptimizationMiddleware` on every turn.
2. **Stage 2** — path-driven conditional activation via new `SkillActivationMiddleware` triggered on file-op tool calls.
3. **Stage 3** — lazy `<SKILL_CONTEXT>` body injection (slash expansion stays unchanged; subsequent turns re-emit via `_compose_skills_block`).

Deepagents' `SkillsMiddleware` is suppressed at construction by passing `skills=None`. Per-thread activation state lives on the langgraph agent state at `state["skill_activation"]` and is snapshotted to `LoopState` at iteration boundaries for durability.

---

## Files to Touch

| File | Action |
|------|--------|
| `packages/soothe/pyproject.toml` | ADD `pathspec` runtime dep |
| `packages/soothe/src/soothe/skills/index.py:23` | EXTEND `SkillIndexEntry` with `paths: tuple[str, ...] \| None` and `when_to_use: str \| None`; update `_parse_skill_dir` to populate them; update `wire_entries()` and `_make_wire_entry` to surface them; tolerate old cache rows (skip on `TypeError`) |
| `packages/soothe/src/soothe/skills/catalog.py:28` | EXTEND `_parse_frontmatter` to parse YAML-style `paths:` lists (string or list) and multi-line `when_to_use:` (`\|`-style); EXTEND `_parse_skill_directory` to expose both fields; EXTEND `_wire_entries_*` paths to carry them in the wire dict (optional fields) |
| `packages/soothe/src/soothe/config/models.py` | ADD `ProgressiveSkillsConfig` near other config blocks (after `OutputStreamingConfig` ~line 854 is fine) |
| `packages/soothe/src/soothe/config/settings.py:271` | ADD `progressive_skills: ProgressiveSkillsConfig = Field(default_factory=ProgressiveSkillsConfig)` on `SootheConfig`, near `skills:` |
| `config/config.template.yml`, `config/config.dev.yml` | MIRROR `progressive_skills:` block (CLAUDE.md Rule #2) |
| **NEW** `packages/soothe/src/soothe/skills/budget.py` | `format_skills_within_budget(entries, *, budget_chars, per_entry_cap_chars, min_per_entry_chars) -> (str, BudgetTelemetry)` |
| **NEW** `packages/soothe/src/soothe/skills/registry.py` | `ProgressiveSkillRegistry` (stateless helpers operating on `activation_state` dict); `init_activation_state()` static |
| **NEW** `packages/soothe/src/soothe/skills/events.py` | Model defs `SkillActivatedEvent`, `SkillBodyLoadedEvent`, `InternalSkillActivatedEvent`; `register_event(...)` calls so models are registered at import time |
| `packages/soothe/src/soothe/core/events/catalog.py` | ADD `from soothe.skills.events import *  # noqa: F401, F403` near other module-self-registration imports so the registration is triggered (per IG-052 pattern) |
| `packages/soothe/src/soothe/core/loop/state/schemas.py:769` (`LoopState`) | ADD four snapshot fields (`sent_skill_names`, `activated_skill_names`, `invoked_skill_names`, `invoked_skill_bodies`) with default factories |
| `packages/soothe/src/soothe/core/loop/engine/agent_loop.py` | Add a helper `_snapshot_skill_activation(state_dict, loop_state)` and call it at the end of each plan/execute iteration (one place: after `state_manager.persist(...)` in the iteration body) |
| **NEW** `packages/soothe/src/soothe/middleware/skill_activation.py` | `SkillActivationMiddleware(AgentMiddleware)` with `abefore_agent` (rehydrate/init), `awrap_tool_call` (file-op intercept with `asyncio.Lock` per `(thread_id, skill_name)`) |
| `packages/soothe/src/soothe/middleware/_builder.py:59` | INSERT `SkillActivationMiddleware` between `SoothePolicyMiddleware` and `ToolConcurrencyMiddleware` |
| `packages/soothe/src/soothe/middleware/system_prompt_optimization.py:286-465` | ADD `_compose_skills_block(state)` private helper; call it inside `_get_prompt_for_complexity` — append `<AVAILABLE_SKILLS>` to `static_sections`, append `<SKILL_CONTEXT>` blocks (per invoked skill, excluding `just_invoked`) to `semi_static_sections`; mark sent names back into state |
| `packages/soothe/src/soothe/core/agent/_builder.py:199-211` | REPLACE the `all_skills = … skills=all_skills or None` block with `skills=None` and a comment pointing to RFC-105 |
| `packages/soothe/src/soothe/skills/catalog.py:try_expand_slash_skill_user_line` (~line 455) | When called from `AgentLoop.run_with_progress` and a skill is expanded, mark `skill_name` into `state["skill_activation"]["invoked"]`, `["invoked_bodies"][skill_name]`, and `["just_invoked"]` so `_compose_skills_block` doesn't double-print this turn. Since `catalog.try_expand_slash_skill_user_line` doesn't have access to `state`, this is done from `AgentLoop.run_with_progress` after `skill_env` is built (lines 158-172) — see Step 8 below |
| **Tests** | See "Tests" section |

---

## Implementation Steps

### Step 1 — Dependency

Add `pathspec>=0.12` to `packages/soothe/pyproject.toml` `[project] dependencies`. Verify with `uv sync` (or whatever the project uses).

### Step 2 — `ProgressiveSkillsConfig`

In `packages/soothe/src/soothe/config/models.py`:

```python
class ProgressiveSkillsConfig(BaseModel):
    """RFC-105: Tunables for the progressive skill listing budget."""

    budget_pct: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of AgentLoopConfig.context_window_limit (chars, not tokens) "
            "available for the <AVAILABLE_SKILLS> listing per turn."
        ),
    )
    max_listing_chars_per_entry: int = Field(
        default=250,
        ge=0,
        description="Hard per-entry character cap for description in the listing.",
    )
    min_listing_chars_per_entry: int = Field(
        default=20,
        ge=0,
        description="Below this, non-builtin entries fall back to names-only mode.",
    )
```

In `packages/soothe/src/soothe/config/settings.py` near `skills:` (line 271):

```python
from soothe.config.models import ProgressiveSkillsConfig  # at top

progressive_skills: ProgressiveSkillsConfig = Field(default_factory=ProgressiveSkillsConfig)
"""RFC-105: Progressive skill listing budget and per-entry caps."""
```

Mirror in `config/config.template.yml` and `config/config.dev.yml`:

```yaml
progressive_skills:
  budget_pct: 0.01
  max_listing_chars_per_entry: 250
  min_listing_chars_per_entry: 20
```

### Step 3 — Extend `SkillIndexEntry` and frontmatter parser

`skills/index.py:23`:

```python
@dataclass(frozen=True, slots=True)
class SkillIndexEntry:
    name: str
    description: str
    tags: str
    source: str
    path: str
    mtime: float
    paths: tuple[str, ...] | None = None       # RFC-105
    when_to_use: str | None = None             # RFC-105
```

Update `_parse_skill_dir` to populate from frontmatter (parsed list of patterns or None; `when_to_use` from frontmatter or None). Update `wire_entries()` and `_make_wire_entry` to include the new fields **only when non-empty** (keeps wire shape small for skills without them).

Cache compatibility: in `_load_cache`, the existing `SkillIndexEntry(**raw)` will fail for new fields on old caches → except clause already skips on `TypeError`. Verify this path or add explicit fallback.

`skills/catalog.py:28` `_parse_frontmatter`:

The current parser is single-line only (`_FM_LINE_RE`). Extend to:
- Recognize a `paths:` followed by indented `- pattern` lines, collecting into a list.
- Recognize `when_to_use: |` followed by indented lines, collecting into a string.

Keep parser simple — no yaml dep. Implementation:

```python
def _parse_frontmatter(text: str) -> dict[str, Any]:
    m = _FM_RE.match(text)
    if not m:
        return {}
    result: dict[str, Any] = {}
    lines = m.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Block-list: "key:" followed by "  - item"
        if stripped.endswith(":"):
            key = stripped[:-1].strip()
            items: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].startswith((" ", "\t")) and lines[j].strip().startswith("-"):
                item = lines[j].strip().lstrip("-").strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                items.append(item)
                j += 1
            if items:
                result[key] = items
                i = j
                continue
        # Block-scalar: "key: |" followed by indented lines
        lm = _FM_LINE_RE.match(stripped)
        if lm and lm.group(2).strip() in ("|", ">"):
            key = lm.group(1)
            block_lines: list[str] = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith(("  ", "\t")) or not lines[j].strip()):
                block_lines.append(lines[j].lstrip()[2:] if lines[j].startswith("  ") else lines[j].lstrip())
                j += 1
            result[key] = "\n".join(b for b in block_lines if b is not None).rstrip()
            i = j
            continue
        # Scalar
        if lm:
            key, val = lm.group(1), lm.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            result[key] = val
        i += 1
    return result
```

Update `_parse_skill_directory` to add `paths` and `when_to_use` to its return dict (passing through whatever `_parse_frontmatter` produced).

### Step 4 — Skill events (`skills/events.py`)

```python
"""RFC-105: Progressive skill loading events (self-registered per IG-052)."""

from __future__ import annotations

from soothe.core.events.catalog import register_event
from soothe.core.events.base_events import SootheEvent


class SkillActivatedEvent(SootheEvent):
    type: str = "soothe.skill.activated"
    skill_name: str
    matched_path: str
    pattern: str
    thread_id: str


class SkillBodyLoadedEvent(SootheEvent):
    type: str = "soothe.skill.body.loaded"
    skill_name: str
    body_chars: int
    thread_id: str


register_event(SkillActivatedEvent, summary_template="Skill activated: {skill_name} (matched {matched_path})")
register_event(SkillBodyLoadedEvent, summary_template="Skill body loaded: {skill_name} ({body_chars} chars)")


# Internal-only (not registered; used over InternalEventBus)
from pydantic import BaseModel


class InternalSkillActivatedEvent(BaseModel):
    skill_name: str
    matched_path: str
    pattern: str
    thread_id: str
```

Trigger import in `core/events/catalog.py` near other module imports (find similar lines for plugin/tool events):

```python
from soothe.skills import events as _skill_events  # noqa: F401
```

If `SootheEvent` and `register_event` live at different paths in this tree, adjust imports. (`SootheEvent` may be in `soothe.core.events.base_events` per RFC-401.)

### Step 5 — `ProgressiveSkillRegistry`

`packages/soothe/src/soothe/skills/registry.py`:

```python
"""RFC-105: Stateless helpers for progressive skill disclosure."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import pathspec

from soothe.skills.index import SkillIndexEntry


def _normalize_patterns(patterns: Sequence[str]) -> list[str]:
    """Strip trailing /** and collapse all-** to a no-op marker."""
    out: list[str] = []
    for p in patterns:
        p = p.strip()
        if not p:
            continue
        if p in ("**", "**/*"):
            return []  # all-** treated as unconditional → empty pattern list
        if p.endswith("/**"):
            p = p[:-3]
        out.append(p)
    return out


def _is_unconditional(entry: SkillIndexEntry) -> bool:
    if entry.paths is None:
        return True
    normalized = _normalize_patterns(entry.paths)
    return not normalized


class ProgressiveSkillRegistry:
    """Stateless façade. All state lives in caller-owned activation_state dict."""

    @staticmethod
    def init_activation_state() -> dict:
        return {
            "sent": set(),
            "activated": set(),
            "invoked": set(),
            "invoked_bodies": {},
            "just_invoked": set(),
        }

    def partition(
        self, entries: Sequence[SkillIndexEntry]
    ) -> tuple[list[SkillIndexEntry], list[SkillIndexEntry]]:
        unconditional, conditional = [], []
        for e in entries:
            (unconditional if _is_unconditional(e) else conditional).append(e)
        return unconditional, conditional

    def new_for_thread(
        self,
        activation_state: dict,
        candidates: Sequence[SkillIndexEntry],
    ) -> list[SkillIndexEntry]:
        sent = activation_state.get("sent", set())
        names_in_catalog = {e.name for e in candidates}
        # Prune dangling names (skill removed since last sent)
        activation_state["sent"] = {n for n in sent if n in names_in_catalog}
        sent = activation_state["sent"]
        return [e for e in candidates if e.name not in sent]

    def match_paths(
        self,
        activation_state: dict,
        workspace: Path,
        file_paths: Sequence[str],
        conditional_skills: Sequence[SkillIndexEntry],
    ) -> list[tuple[str, str, str]]:
        """Return [(skill_name, matched_path, pattern), ...] for newly-activated skills."""
        activated = activation_state.setdefault("activated", set())
        newly: list[tuple[str, str, str]] = []
        rel_paths: list[str] = []
        for p in file_paths:
            path = Path(p)
            if not path.is_absolute():
                rel_paths.append(str(path))
            else:
                try:
                    rel_paths.append(str(path.resolve().relative_to(workspace.resolve())))
                except ValueError:
                    continue  # path outside workspace → reject

        for skill in conditional_skills:
            if skill.name in activated:
                continue
            patterns = _normalize_patterns(skill.paths or ())
            if not patterns:
                continue
            spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
            for rp in rel_paths:
                if spec.match_file(rp):
                    newly.append((skill.name, rp, patterns[0]))
                    break
        return newly

    def mark_sent(self, activation_state: dict, names: Iterable[str]) -> None:
        activation_state.setdefault("sent", set()).update(names)

    def mark_activated(self, activation_state: dict, names: Iterable[str]) -> None:
        activation_state.setdefault("activated", set()).update(names)

    def mark_invoked(self, activation_state: dict, name: str, body: str) -> None:
        activation_state.setdefault("invoked", set()).add(name)
        activation_state.setdefault("invoked_bodies", {})[name] = body
        activation_state.setdefault("just_invoked", set()).add(name)

    def cache_body(self, activation_state: dict, name: str, body: str) -> None:
        activation_state.setdefault("invoked_bodies", {})[name] = body
```

### Step 6 — `format_skills_within_budget`

`packages/soothe/src/soothe/skills/budget.py`:

```python
"""RFC-105: Budgeted skill-listing formatter (Claude Code parity)."""

from __future__ import annotations

from typing import Sequence, TypedDict

from soothe.skills.index import SkillIndexEntry


class BudgetTelemetry(TypedDict):
    included_count: int
    truncated_count: int
    mode: str  # "full" | "truncated" | "names_only"
    budget_chars: int
    actual_chars: int


def _is_builtin(e: SkillIndexEntry) -> bool:
    return e.source == "builtin"


def _format_entry(e: SkillIndexEntry, *, cap: int | None) -> str:
    name = e.name
    desc = e.description or ""
    if cap is not None and len(desc) > cap:
        desc = desc[: max(0, cap - 1)].rstrip() + "…"
    wt = (e.when_to_use or "").strip()
    if wt and cap is not None:
        # add when_to_use only if room remains
        remaining = max(0, cap - len(desc))
        if remaining > 10:
            wt_trim = wt[:remaining]
            return f"- {name}: {desc}\n  When to use: {wt_trim}"
    if wt and cap is None:
        return f"- {name}: {desc}\n  When to use: {wt}"
    return f"- {name}: {desc}"


def format_skills_within_budget(
    entries: Sequence[SkillIndexEntry],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, BudgetTelemetry]:
    if not entries:
        return "", BudgetTelemetry(
            included_count=0, truncated_count=0, mode="full",
            budget_chars=budget_chars, actual_chars=0,
        )

    full_rendered = [_format_entry(e, cap=None) for e in entries]
    total_full = sum(len(r) + 1 for r in full_rendered)
    if total_full <= budget_chars:
        text = "\n".join(full_rendered)
        return text, BudgetTelemetry(
            included_count=len(entries), truncated_count=0, mode="full",
            budget_chars=budget_chars, actual_chars=len(text),
        )

    # Over budget: built-ins keep full description; share remaining among non-builtins.
    builtins = [e for e in entries if _is_builtin(e)]
    others = [e for e in entries if not _is_builtin(e)]
    builtin_text = "\n".join(_format_entry(e, cap=None) for e in builtins)
    used = len(builtin_text) + 1
    remaining = max(0, budget_chars - used)
    quota = max(min_per_entry_chars, (remaining // max(1, len(others)))) if others else 0
    quota = min(quota, per_entry_cap_chars)

    if quota < min_per_entry_chars and others:
        # names-only mode for non-builtins
        names = "\n".join(f"- {e.name}" for e in others)
        text = (builtin_text + "\n" + names) if builtin_text else names
        return text, BudgetTelemetry(
            included_count=len(entries), truncated_count=len(others), mode="names_only",
            budget_chars=budget_chars, actual_chars=len(text),
        )

    others_text = "\n".join(_format_entry(e, cap=quota) for e in others)
    text = (builtin_text + ("\n" + others_text if others_text else "")) if builtin_text else others_text
    return text, BudgetTelemetry(
        included_count=len(entries),
        truncated_count=sum(1 for e in others if len(e.description) > quota),
        mode="truncated",
        budget_chars=budget_chars,
        actual_chars=len(text),
    )
```

### Step 7 — `SkillActivationMiddleware`

`packages/soothe/src/soothe/middleware/skill_activation.py`:

```python
"""RFC-105: File-op-triggered conditional skill activation."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Sequence

from langchain.agents.middleware.types import AgentMiddleware

from soothe.config import SootheConfig
from soothe.core.events.internal_bus import InternalEventBus
from soothe.skills.events import InternalSkillActivatedEvent, SkillActivatedEvent
from soothe.skills.index import SkillIndexEntry
from soothe.skills.registry import ProgressiveSkillRegistry

logger = logging.getLogger(__name__)


FILE_OP_TOOLS: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "glob", "grep",
    "delete_file", "insert_lines", "apply_diff", "file_info",
})
_PATH_KEYS: tuple[str, ...] = ("file_path", "path", "filepath", "file")


class SkillActivationMiddleware(AgentMiddleware):
    """Intercepts file-op tool calls; activates conditional skills on path match."""

    def __init__(
        self,
        registry: ProgressiveSkillRegistry,
        catalog_provider: Callable[[], Sequence[SkillIndexEntry]],
        config: SootheConfig,
        internal_bus: InternalEventBus | None,
    ) -> None:
        self._registry = registry
        self._catalog_provider = catalog_provider
        self._config = config
        self._bus = internal_bus
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def abefore_agent(self, state, runtime) -> dict | None:
        if "skill_activation" not in state:
            return {"skill_activation": ProgressiveSkillRegistry.init_activation_state()}
        return None

    async def awrap_tool_call(self, request, handler, runtime):
        tool_name = getattr(request, "tool_name", None) or getattr(request, "name", "")
        if tool_name not in FILE_OP_TOOLS:
            return await handler(request)

        # Extract paths
        args = getattr(request, "args", None) or getattr(request, "tool_input", {}) or {}
        if not isinstance(args, dict):
            return await handler(request)
        file_paths: list[str] = []
        for key in _PATH_KEYS:
            v = args.get(key)
            if isinstance(v, str):
                file_paths.append(v)
            elif isinstance(v, list):
                file_paths.extend(p for p in v if isinstance(p, str))
        if not file_paths:
            return await handler(request)

        # Reach state via request (request.state is the langgraph dict)
        state = getattr(request, "state", None) or {}
        activation_state = state.get("skill_activation") or ProgressiveSkillRegistry.init_activation_state()

        # Workspace
        workspace_raw = state.get("workspace")
        if not workspace_raw:
            return await handler(request)
        workspace = Path(str(workspace_raw))

        # Partition catalog into conditional skills
        all_entries = list(self._catalog_provider())
        _, conditional = self._registry.partition(all_entries)
        if not conditional:
            return await handler(request)

        newly = self._registry.match_paths(activation_state, workspace, file_paths, conditional)
        if not newly:
            return await handler(request)

        thread_id = str(state.get("thread_id") or state.get("loop_id") or "")
        for skill_name, matched_path, pattern in newly:
            key = (thread_id, skill_name)
            async with await self._lock_for(key):
                if skill_name in activation_state["activated"]:
                    continue
                activation_state["activated"].add(skill_name)
                try:
                    from soothe.skills.workspace_sync import sync_specific_skill_to_workspace
                    sync_specific_skill_to_workspace(self._config, workspace, skill_name)
                except Exception:  # noqa: BLE001
                    logger.exception("[Skill] sync failed for %s", skill_name)
                if self._bus is not None:
                    try:
                        await self._bus.emit(InternalSkillActivatedEvent(
                            skill_name=skill_name, matched_path=matched_path,
                            pattern=pattern, thread_id=thread_id,
                        ))
                    except Exception:  # noqa: BLE001
                        logger.debug("[Skill] internal bus emit failed", exc_info=True)

        # Update state dict in-place; langgraph picks it up on next merge
        state["skill_activation"] = activation_state
        return await handler(request)

    async def _lock_for(self, key: tuple[str, str]) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock
```

**Note**: deepagents' middleware base-class may use different hook names (e.g., `awrap_tool_call` vs `wrap_tool_call_async`). Verify by reading `.venv/lib/python3.11/site-packages/langchain/agents/middleware/types.py` before finalizing — adjust if needed.

### Step 8 — `_compose_skills_block` in `SystemPromptOptimizationMiddleware`

In `system_prompt_optimization.py`, add to the class:

```python
def _compose_skills_block(self, state: dict | None) -> tuple[str | None, list[str]]:
    """RFC-105: Compose <AVAILABLE_SKILLS> static block + <SKILL_CONTEXT> semi-static blocks.

    Returns:
        (available_skills_block_or_None, list_of_skill_context_blocks)
    """
    if not state:
        return None, []
    activation = state.get("skill_activation") or {}
    sent = activation.setdefault("sent", set()) if isinstance(activation, dict) else set()
    activated = activation.get("activated", set()) if isinstance(activation, dict) else set()
    invoked = activation.get("invoked", set()) if isinstance(activation, dict) else set()
    just_invoked = activation.get("just_invoked", set()) if isinstance(activation, dict) else set()
    bodies = activation.get("invoked_bodies", {}) if isinstance(activation, dict) else {}

    # Resolve catalog lazily (avoid SkillIndex import cycles)
    from soothe.skills.catalog import wire_entries_for_agent_config  # noqa: WPS433
    from soothe.skills.index import SkillIndexEntry, SkillIndex
    # Use a SkillIndex-backed entry list if available — but registry needs SkillIndexEntry
    # objects, not wire dicts. Build entries via the index.
    skill_index = SkillIndex()  # cheap; mtime-cached
    entries = skill_index.rebuild_if_stale()
    # Add workspace skills via wire entries + adapt — simplest: union by name preferring index
    # (TODO: integrate workspace skills via a richer catalog API; for v1 use SkillIndex only.)

    from soothe.skills.registry import ProgressiveSkillRegistry
    registry = ProgressiveSkillRegistry()
    unconditional, _ = registry.partition(entries)
    activated_entries = [e for e in entries if e.name in activated]
    candidates = sorted({e.name: e for e in (unconditional + activated_entries)}.values(),
                        key=lambda e: e.name.lower())
    new_entries = registry.new_for_thread(activation, candidates)

    available_block: str | None = None
    if new_entries:
        ctx_limit = int(self._config.agent.loop.context_window_limit)
        budget_pct = float(self._config.progressive_skills.budget_pct)
        budget_chars = max(0, int(ctx_limit * budget_pct))
        per_entry_cap = int(self._config.progressive_skills.max_listing_chars_per_entry)
        min_per_entry = int(self._config.progressive_skills.min_listing_chars_per_entry)
        from soothe.skills.budget import format_skills_within_budget
        text, _telemetry = format_skills_within_budget(
            new_entries,
            budget_chars=budget_chars,
            per_entry_cap_chars=per_entry_cap,
            min_per_entry_chars=min_per_entry,
        )
        if text:
            available_block = f"<AVAILABLE_SKILLS>\n{text}\n</AVAILABLE_SKILLS>"
            registry.mark_sent(activation, [e.name for e in new_entries])

    skill_context_blocks: list[str] = []
    for name in sorted(invoked - just_invoked):
        body = bodies.get(name)
        if not body:
            continue
        skill_context_blocks.append(
            f"<SKILL_CONTEXT name=\"{name}\">\n{body}\n</SKILL_CONTEXT>"
        )

    # Clear transient just_invoked at end of compose
    if isinstance(activation, dict):
        activation["just_invoked"] = set()
        state["skill_activation"] = activation

    return available_block, skill_context_blocks
```

Then in `_get_prompt_for_complexity`, after the existing static_sections accumulation:

```python
# RFC-105: Progressive skill loading
avail_block, skill_ctx_blocks = self._compose_skills_block(state)
if avail_block:
    static_sections.append(avail_block)
semi_static_sections.extend(skill_ctx_blocks)
```

**Catalog scope caveat**: v1 uses `SkillIndex` only (global user skills). Workspace-local skills are NOT yet wired through `_compose_skills_block` because they don't carry `paths:`/`when_to_use` in their wire entries. Either (a) extend `wire_entries_for_agent_config` to return real `SkillIndexEntry` rows, or (b) ship v1 with global skills only and follow up. **Recommend (a)** — small, mechanical, keeps parity with RFC scope.

### Step 9 — Slash-skill invocation marks state

In `AgentLoop.run_with_progress` (after line 166, where `skill_context` is set), record the invocation in the agent state we will pass through. Since the langgraph state isn't constructed in `AgentLoop`, the invocation is recorded into `LoopState.invoked_skill_names` / `invoked_skill_bodies` directly, AND the snapshot-bridge code (Step 11) propagates back into `state["skill_activation"]`.

```python
# After skill_env resolved:
if skill_env is not None and skill_env.skill_context:
    # RFC-105: pre-seed invocation state so <SKILL_CONTEXT> re-emits on next turns
    initial_invoked = {skill_env.skill_name} if hasattr(skill_env, "skill_name") else set()
    initial_invoked_bodies = (
        {skill_env.skill_name: skill_env.skill_context} if initial_invoked else {}
    )
```

Pass `initial_invoked` / `initial_invoked_bodies` into `LoopState(...)` construction (line ~338) via the new fields, and set `just_invoked` on the agent state when injecting it (Step 11).

If `skill_env` doesn't expose `skill_name`, derive it from `parsed_skill[0]`.

### Step 10 — Extend `LoopState`

Add to `core/loop/state/schemas.py:769` (`LoopState`):

```python
# RFC-105: Progressive skill loading durability snapshot
sent_skill_names: set[str] = Field(default_factory=set)
activated_skill_names: set[str] = Field(default_factory=set)
invoked_skill_names: set[str] = Field(default_factory=set)
invoked_skill_bodies: dict[str, str] = Field(default_factory=dict)
```

### Step 11 — AgentLoop snapshot bridge

In `core/loop/engine/agent_loop.py`, factor out two small helpers near the iteration body:

```python
def _seed_state_from_loop(loop_state: LoopState) -> dict:
    """Rehydrate state['skill_activation'] from LoopState snapshot (RFC-105)."""
    return {
        "sent": set(loop_state.sent_skill_names),
        "activated": set(loop_state.activated_skill_names),
        "invoked": set(loop_state.invoked_skill_names),
        "invoked_bodies": dict(loop_state.invoked_skill_bodies),
        # just_invoked is transient: True only when slash expansion happened this turn
        "just_invoked": set(loop_state.invoked_skill_names) if loop_state.iteration == 0 else set(),
    }


def _snapshot_skill_activation(state_dict: dict, loop_state: LoopState) -> None:
    """Copy state['skill_activation'] back into LoopState fields (RFC-105)."""
    activation = state_dict.get("skill_activation") or {}
    if not isinstance(activation, dict):
        return
    loop_state.sent_skill_names = set(activation.get("sent", ()))
    loop_state.activated_skill_names = set(activation.get("activated", ()))
    loop_state.invoked_skill_names = set(activation.get("invoked", ()))
    loop_state.invoked_skill_bodies = dict(activation.get("invoked_bodies", {}))
```

Locate the iteration body in `run_with_progress` (search for `iteration += 1` or the state persistence call) and:

1. Just before invoking the inner agent for that iteration, populate the langgraph input with `"skill_activation": _seed_state_from_loop(loop_state)`.
2. Just after the iteration completes (and before checkpoint persist), call `_snapshot_skill_activation(final_state, loop_state)`.

If the agent input dict isn't easily reachable, an alternative: extend `state_manager.persist(...)` to take `loop_state.skill_*` fields and mutate them from a callback. Pick whichever fits the existing flow with minimum invasion — IG-447 author should choose based on what they find.

### Step 12 — Wire `SkillActivationMiddleware` into the stack

In `middleware/_builder.py`, after the `SoothePolicyMiddleware` block (line 126) and before `ToolConcurrencyMiddleware` (line 129):

```python
from .skill_activation import SkillActivationMiddleware
from soothe.skills.registry import ProgressiveSkillRegistry
from soothe.skills.index import SkillIndex
from soothe.core.events.internal_bus import get_internal_event_bus  # or similar

skill_index = SkillIndex()
stack.append(
    SkillActivationMiddleware(
        registry=ProgressiveSkillRegistry(),
        catalog_provider=lambda: skill_index.rebuild_if_stale(),
        config=config,
        internal_bus=get_internal_event_bus() if "get_internal_event_bus" in dir() else None,
    )
)
logger.info("[Middleware] Skill activation (RFC-105) enabled")
```

Verify the actual internal-bus accessor name in `core/events/internal_bus.py`.

### Step 13 — Suppress deepagents' `SkillsMiddleware`

In `core/agent/_builder.py` lines 199-211, replace:

```python
# Merge built-in skills with user-provided skills
all_skills = get_built_in_skills_paths()
if self._config.skills:
    all_skills.extend(self._config.skills)
```

with:

```python
# RFC-105: Skill emission is owned by SystemPromptOptimizationMiddleware via
# ProgressiveSkillRegistry. Deepagents' SkillsMiddleware must not also emit.
all_skills: list[str] = []
```

And later, change `skills=all_skills or None` to `skills=None`. Drop the unused `get_built_in_skills_paths` import if it has no other call sites.

---

## Tests

| Test file | What it covers |
|---|---|
| `packages/soothe/tests/unit/skills/test_registry_partition.py` | `paths:` presence partitions correctly; trailing `/**` stripped; all-`**` patterns demote to unconditional. |
| `packages/soothe/tests/unit/skills/test_registry_delta.py` | `new_for_thread` returns only un-sent skills; subsequent call returns `[]`; deleted skills are pruned from `sent`. |
| `packages/soothe/tests/unit/skills/test_path_matching.py` | gitignore positive/negative, `**`, anchored paths, paths outside workspace rejected. |
| `packages/soothe/tests/unit/skills/test_budget_formatter.py` | under-budget keeps full descs; over-budget truncates non-builtins; extreme case → names-only; built-ins always full; empty input. |
| `packages/soothe/tests/unit/skills/test_frontmatter_paths.py` | `_parse_frontmatter` parses `paths:` list and `when_to_use: \|` block scalar; legacy scalar fields still parse. |
| `packages/soothe/tests/unit/middleware/test_skill_activation_middleware.py` | file-op tool with matching path activates skill; non-file-op tool doesn't; non-matching path doesn't; idempotent on re-call; concurrent calls race-safe (asyncio.gather); workspace-outside path rejected. |
| `packages/soothe/tests/unit/middleware/test_system_prompt_skills_block.py` | deepagents stock listing absent; `<AVAILABLE_SKILLS>` respects budget; `just_invoked` dedupes vs slash expansion; `<SKILL_CONTEXT>` re-emits from `invoked_bodies` cache. |
| `packages/soothe/tests/integration/skills/test_progressive_skill_flow.py` | End-to-end fixture: create skill with `paths: ["src/**/*.py"]`, start agent, `read_file("src/main.py")`, assert next turn's system prompt contains it; invoke via `/skill:name`, assert body present; assert `LoopState` snapshot has all three sets populated. |

Use `pytest-asyncio` for the middleware/integration tests (the repo already uses it).

---

## Verification

```bash
cd /Users/xiamingchen/Workspace/mirasurf/soothe
./scripts/verify_finally.sh   # format + lint + 900+ unit tests
```

Manual smoke (per RFC §10):

```bash
soothe daemon start --workspace /tmp/soothe-skill-test
# Create /tmp/soothe-skill-test/.soothe/skills/python-helper/SKILL.md with:
#   ---
#   name: python-helper
#   description: Tips for editing Python files.
#   paths:
#     - "**/*.py"
#   ---
soothe -p "list files in this directory"
# Trace via Langfuse:
#   - turn-0 system prompt does NOT contain python-helper
#   - after glob/read_file hits a .py path, next turn DOES contain it
#   - <AVAILABLE_SKILLS> char count ≤ 1% of context_window_limit
#   - soothe.skill.activated event in event stream
```

---

## Risks & Open Decisions

- **Catalog provider scope (Step 8)**: v1 routes everything through `SkillIndex` which only sees `~/.soothe/skills`. Workspace-local skills are not yet first-class. Recommendation: extend `catalog.wire_entries_for_agent_config` to return real `SkillIndexEntry` objects (not wire dicts) and use that here. Defer if the change ripples too far; document the gap in the next IG.
- **Frontmatter parser**: current parser is single-line. The new block-list and block-scalar code is small but tested only via new unit tests. If we hit edge cases, switch to `PyYAML`/`ruamel.yaml` — bigger dep but battle-tested.
- **Middleware hook names**: `awrap_tool_call` / `abefore_agent` are the names per CLAUDE.md and existing middlewares; verify the deepagents/langchain base class spelling before finalizing.
- **AgentLoop snapshot location**: Step 11 leaves the exact snapshot point to the implementer. The right spot is the natural seam where `state_manager.persist(...)` is called; if the agent invocation returns the full final state, snapshot there.
- **Internal bus accessor**: Step 12 references `get_internal_event_bus()` defensively; replace with the actual API in `core/events/internal_bus.py`.
- **`skill_env.skill_name`**: If `skill_env` doesn't expose `skill_name`, derive from `parsed_skill[0]`. Either way, Step 9 needs the field actually defined.
- **Cache compatibility**: extending `SkillIndexEntry` requires the existing `~/.soothe/cache/skill_index.json` to gracefully fail to load (the existing `except TypeError` already covers this — confirm with a focused test).
