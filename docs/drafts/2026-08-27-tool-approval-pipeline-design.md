# Design: Multi-Stage Tool-Approval Pipeline

**Date**: 2026-08-27
**Status**: Draft
**Depends on**: RFC-622 (CoreAgent Clarification Relay), RFC-623 (Veritas Auto-Mode Robustness)
**Related**: `../claude-code/` (Claude Code permission system — pattern reference)

---

## 1. Problem

In auto clarification mode, every `tool_approval` interrupt triggers a full veritas LLM call. The `think`-class model is invoked with a ~25k-char user prompt (AGENTS.md inlined verbatim, plus recent step outputs, prior clarifications, plan summary) and structured-output enforcement with up to 2 retries.

Most tool-approval decisions are trivially safe (in-workspace `edit_file` aligned with the goal) or trivially dangerous (`rm -rf /`, editing `.git/config`). An LLM is not needed for these. The cost is both latency (one round-trip per tool call) and token spend (huge prompt × every interrupt × every goal), especially severe in autopilot runs that execute many goals headlessly.

### Guiding principle

Borrow the layered pipeline from Claude Code's permission system: **deterministic stages first, LLM classifier as the last resort**. Most tool calls are resolved by cheap rule/safety checks without an LLM round-trip. Veritas only fires for genuinely ambiguous cases — the same structural pattern as Claude Code's `classifyYoloAction` being the final stage in auto mode, after deny rules, ask rules, safety checks, the `acceptEdits` fast-path, and the safe-tool allowlist have all had a chance to resolve the decision.

---

## 2. Pipeline

The pipeline runs for the `tool_approval` clarification origin only. All other origins (`execute`, `plan_mode_review`, `rail_pause`) are untouched.

```
tool_approval interrupt
        │
        ▼
Stage 1: Deny rules          ── deterministic, instant
  (denylist command patterns, forbidden paths)
  → match ──► REJECT
        │ no match
        ▼
Stage 2: Safety checks       ── bypass-immune, instant
  (DANGEROUS_FILES, DANGEROUS_DIRECTORIES, path traversal,
   UNC paths, suspicious patterns)
  → match ──► REJECT
        │ no match
        ▼
Stage 3: Allow rules         ── deterministic, instant
  (allowlist command patterns, in-workspace writes)
  → match ──► APPROVE
        │ no match
        ▼
Stage 4: Veritas LLM         ── final guard, ambiguous cases only
  (slim prompt: tool name, args, user request, goal —
   no AGENTS.md, no step outputs, fast model)
  → APPROVE / REJECT / DEFER
```

**First stage that returns a decision wins.** Stages 1–3 are microsecond, no-LLM. Stage 4 is the existing veritas path with a slimmer prompt and `fast` model role.

### Why this order

Claude Code's `hasPermissionsToUseToolInner` established the order: deny rules → ask rules → safety checks → allow rules → LLM classifier. The deny-first ordering is a security property: a destructive command pattern (`rm -rf`) is rejected before any allow rule can fire. Safety checks are bypass-immune — they run regardless of config, like Claude Code's `checkPathSafetyForAutoEdit` which blocks `.git/` and shell configs even in `bypassPermissions` mode. Allow rules never override safety. The LLM is the final guard, not the first.

---

## 3. Config: `ToolApprovalConfig`

New sub-block under `agent.clarification` in `SootheConfig`.

### 3.1 YAML shape

```yaml
agent:
  clarification:
    tool_approval:
      enabled: true                      # master switch; false = all go to veritas
      
      # Stage 1: deny rules — match = immediate REJECT
      deny_rules:
        - tool: run_command
          pattern: "rm -rf *"
        - tool: run_command
          pattern: "sudo *"
        - tool: run_command
          pattern: "chmod 777 *"
        - tool: run_command
          pattern: "git push --force*"
        - tool: run_command
          pattern: "git push -f*"
        - tool: run_command
          pattern: "dd if=*"
        - tool: run_command
          pattern: "mkfs*"
        - tool: edit_file
          pattern: "/etc/**"
        - tool: write_file
          pattern: "/etc/**"
      
      # Stage 2: safety checks — built-in, always on when enabled.
      # Not configurable per-rule; bypass-immune (like Claude Code's
      # DANGEROUS_FILES / DANGEROUS_DIRECTORIES).
      # Dangerous files: .gitconfig, .bashrc, .zshrc, .profile, .mcp.json
      # Dangerous dirs: .git/, .vscode/, .idea/, .claude/
      # Suspicious: path traversal (..), UNC (//server), trailing dots
      
      # Stage 3: allow rules — match = immediate APPROVE
      allow_rules:
        - tool: edit_file
          pattern: "<workspace>/**"
        - tool: write_file
          pattern: "<workspace>/**"
        - tool: run_command
          pattern: "ls *"
        - tool: run_command
          pattern: "cat *"
        - tool: run_command
          pattern: "grep *"
        - tool: run_command
          pattern: "find *"
        - tool: run_command
          pattern: "pytest*"
        - tool: run_command
          pattern: "python -m pytest*"
        - tool: run_command
          pattern: "ruff *"
        - tool: run_command
          pattern: "mypy *"
        - tool: run_command
          pattern: "git status"
        - tool: run_command
          pattern: "git diff*"
        - tool: run_command
          pattern: "git log*"
      
      # Stage 4: veritas fallback
      veritas_fallback:
        enabled: true                    # false = defer ambiguous to human
        model_role: "fast"               # use fast model, not think
        max_context_steps: 0             # no recent step outputs in prompt
        inline_project_instructions: false  # no 25k AGENTS.md
      
      # Audit — every decision logged with stage + reason
      audit:
        log_decisions: true
        log_level: "info"
```

### 3.2 Python models

```python
class ToolApprovalRule(BaseModel):
    """One deny or allow rule for tool-action approval."""
    tool: Literal["edit_file", "write_file", "delete", "run_command"]
    pattern: str
    # Pattern syntax (adapted from Claude Code's shellRuleMatching):
    #   "exact"       → exact match (e.g. "git status")
    #   "prefix:*"    → prefix match (e.g. "grep:*" matches "grep -r foo")
    #   "wildcard*"   → wildcard match, * = any sequence (e.g. "pytest*")
    # Path patterns support ** (recursive) via pathspec (gitignore-style)


class VeritasFallbackConfig(BaseModel):
    """Stage 4: veritas LLM fallback for ambiguous tool approvals."""
    enabled: bool = True
    model_role: Literal["default", "fast", "think", "image", "ocr", "embedding"] = "fast"
    max_context_steps: int = Field(default=0, ge=0)
    inline_project_instructions: bool = False


class ToolApprovalAuditConfig(BaseModel):
    """Audit logging for tool-approval decisions."""
    log_decisions: bool = True
    log_level: Literal["debug", "info", "warning"] = "info"


class ToolApprovalConfig(BaseModel):
    """Multi-stage tool-approval pipeline config (RFC-622 extension)."""
    enabled: bool = True
    deny_rules: list[ToolApprovalRule] = Field(default_factory=_default_deny_rules)
    allow_rules: list[ToolApprovalRule] = Field(default_factory=_default_allow_rules)
    veritas_fallback: VeritasFallbackConfig = Field(default_factory=VeritasFallbackConfig)
    audit: ToolApprovalAuditConfig = Field(default_factory=ToolApprovalAuditConfig)
```

`_default_deny_rules` and `_default_allow_rules` return the lists shown in the YAML above so the defaults are meaningful without config.

### 3.3 Integration into `ClarificationConfig`

```python
class ClarificationConfig(BaseModel):
    # ... existing fields unchanged ...
    
    tool_approval: ToolApprovalConfig = Field(default_factory=ToolApprovalConfig)
    """Multi-stage tool-approval pipeline. When enabled, deterministic
    deny/safety/allow stages resolve most tool calls without an LLM.
    Veritas remains the final guard for ambiguous cases."""
```

---

## 4. Components

### 4.1 `ToolApprovalRule` pattern matcher
**File**: `sloop/clarification/tool_rule_matcher.py`

Adapts Claude Code's `shellRuleMatching.ts` to Python.

```python
def match_command_rule(command: str, pattern: str) -> bool:
    """Match a shell command against a permission pattern.
    
    Supports three syntaxes (mirrors Claude Code's parsePermissionRule):
    - "exact"       → exact string match
    - "prefix:*"    → prefix match (legacy syntax, e.g. "grep:*")
    - "wildcard*"   → wildcard match (* = any sequence)
    
    Matching is case-insensitive for commands.
    """

def match_path_rule(path: str, pattern: str, workspace_root: str | None) -> bool:
    """Match a file path against a permission pattern.
    
    Uses pathspec (gitignore-style) for ** recursive matching.
    Expands <workspace> token to workspace_root.
    
    Handles:
    - <workspace>/** → any path inside workspace root
    - /etc/** → absolute path patterns
    - ~/... → home directory patterns
    - relative patterns resolved against workspace root
    """
```

Uses the `pathspec` library (Python equivalent of Claude Code's `ignore` npm package) for gitignore-style path matching. Already a dependency if available; otherwise falls back to `fnmatch` with `**` expansion.

### 4.2 Safety checker
**File**: `sloop/clarification/tool_safety_check.py`

Adapts Claude Code's `filesystem.ts` dangerous-path detection. The dangerous file and directory lists are built-in constants — not configurable per-rule — because they represent bypass-immune security boundaries (the same principle as Claude Code's `DANGEROUS_FILES` / `DANGEROUS_DIRECTORIES` which cannot be overridden by allow rules).

```python
DANGEROUS_FILES: frozenset[str] = frozenset({
    ".gitconfig", ".gitmodules",
    ".bashrc", ".bash_profile",
    ".zshrc", ".zprofile", ".profile",
    ".ripgreprc",
    ".mcp.json", ".claude.json",
})

DANGEROUS_DIRECTORIES: frozenset[str] = frozenset({
    ".git", ".vscode", ".idea", ".claude",
})

DESTRUCTIVE_COMMAND_PATTERNS: tuple[str, ...] = (
    "rm -rf", "rm -r", "rm -f",
    "sudo", "chmod 777", "chmod -R",
    "git push --force", "git push -f",
    "dd if=", "mkfs",
    ">/dev/sd", "shred",
)


@dataclass(frozen=True)
class SafetyResult:
    safe: bool
    reason: str


def check_path_safety(path: str) -> SafetyResult:
    """Check if a file path is dangerous to auto-approve.
    
    Returns unsafe for:
    - Paths inside DANGEROUS_DIRECTORIES (.git/, .vscode/, etc.)
    - Paths ending in DANGEROUS_FILES (.bashrc, .gitconfig, etc.)
    - Path traversal (.. segments)
    - UNC paths (//server or \\\\server)
    - Trailing dots/spaces (Windows canonicalization bypass)
    """

def check_command_safety(command: str) -> SafetyResult:
    """Check if a shell command is destructive.
    
    Returns unsafe for DESTRUCTIVE_COMMAND_PATTERNS matches.
    """
```

### 4.3 `ToolApprovalPipeline`
**File**: `sloop/clarification/tool_approval_pipeline.py`

```python
@dataclass(frozen=True)
class ApprovalResult:
    decision: Literal["approve", "reject"]
    stage: Literal["deny_rule", "safety_check", "allow_rule"]
    reason: str = ""


class ToolApprovalPipeline:
    """Multi-stage tool-approval evaluator.
    
    Stages run cheapest-first; the first stage that returns a
    decision wins. Veritas LLM is the final stage for ambiguous
    cases — this pipeline returns None to defer to veritas.
    
    Safety property: deny rules and safety checks always run before
    allow rules. No allow rule can override a safety denial.
    """
    
    def __init__(
        self,
        config: ToolApprovalConfig,
        workspace_root: str | None,
    ) -> None:
        self._deny_rules = config.deny_rules
        self._allow_rules = config.allow_rules
        self._workspace = workspace_root
    
    def evaluate(
        self,
        action_requests: list[Mapping[str, Any]],
    ) -> ApprovalResult | None:
        """Run all stages. Returns None = defer to veritas.
        
        Evaluates per action request. If any request is rejected,
        the whole batch is rejected. If all are approved, the
        batch is approved. If any are ambiguous, defer to veritas.
        """
        any_ambiguous = False
        
        for ar in action_requests:
            name = str(ar.get("name") or "")
            args = ar.get("args") or {}
            
            # Stage 1: deny rules
            if self._matches_any_rule(name, args, self._deny_rules):
                return ApprovalResult("reject", "deny_rule",
                    f"matched deny rule for {name}")
            
            # Stage 2: safety checks (bypass-immune)
            if name in ("edit_file", "write_file", "delete"):
                path = str(args.get("file_path") or args.get("path") or "")
                safety = check_path_safety(path)
                if not safety.safe:
                    return ApprovalResult("reject", "safety_check",
                        safety.reason)
            
            if name == "run_command":
                cmd = str(args.get("command") or "")
                safety = check_command_safety(cmd)
                if not safety.safe:
                    return ApprovalResult("reject", "safety_check",
                        safety.reason)
            
            # Stage 3: allow rules
            if self._matches_any_rule(name, args, self._allow_rules):
                continue  # this action is approved, check next
            
            # No rule matched — ambiguous
            any_ambiguous = True
        
        if any_ambiguous:
            return None  # defer to veritas
        
        # All action requests matched allow rules
        return ApprovalResult("approve", "allow_rule",
            "all actions matched allow rules")
    
    def _matches_any_rule(
        self,
        tool_name: str,
        args: Mapping[str, Any],
        rules: list[ToolApprovalRule],
    ) -> bool:
        """Check if a tool action matches any rule in the list."""
        for rule in rules:
            if rule.tool != tool_name:
                continue
            if tool_name == "run_command":
                cmd = str(args.get("command") or "")
                if match_command_rule(cmd, rule.pattern):
                    return True
            elif tool_name in ("edit_file", "write_file", "delete"):
                path = str(args.get("file_path") or args.get("path") or "")
                if match_path_rule(path, rule.pattern, self._workspace):
                    return True
        return False
```

### 4.4 `ClarificationRequest.metadata` field

Add an optional metadata mapping to `ClarificationRequest` so the pipeline can inspect the raw `action_requests` payload.

```python
@dataclass(frozen=True)
class ClarificationRequest:
    questions: tuple[str, ...]
    origin_node: ClarificationOrigin
    origin_interrupt_id: str
    loop_state: LoopStateView
    metadata: Mapping[str, Any] = field(default_factory=dict)
    """Origin-specific payload. For tool_approval: {'action_requests': [...]}.
    Empty for other origins."""
```

`(de)serialization`: `metadata` is JSON-safe (plain dicts/lists), serialized alongside the existing fields in `request_to_state` / `request_from_state`. Default empty dict when absent (backward compatible).

`ClarificationDetector.from_tool_approval_interrupt` populates:

```python
return ClarificationRequest(
    questions=questions,
    origin_node=ORIGIN_TOOL_APPROVAL,
    origin_interrupt_id=interrupt_id,
    loop_state=loop_state,
    metadata={"action_requests": list(action_requests)},
)
```

### 4.5 `AutoClarificationPolicy` integration

The policy gains a `tool_approval_pipeline` attribute, built from config at construction time.

```python
class AutoClarificationPolicy:
    def __init__(
        self,
        veritas_answer: VeritasAnswerFn,
        *,
        min_confidence: float = 0.4,
        interactive_fallback: ClarificationPolicy | None = None,
        force_manual_origins: Collection[ClarificationOrigin] | None = None,
        degrade_low_confidence: bool = False,
        tool_approval_pipeline: ToolApprovalPipeline | None = None,
    ) -> None:
        # ... existing fields ...
        self._tool_approval_pipeline = tool_approval_pipeline
    
    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        # NEW: tool-approval pipeline short-circuit
        if (
            request.origin_node == "tool_approval"
            and self._tool_approval_pipeline is not None
        ):
            action_requests = request.metadata.get("action_requests", [])
            result = self._tool_approval_pipeline.evaluate(action_requests)
            if result is not None:
                logger.info(
                    "[clarification] tool_approval %s by stage=%s reason=%s",
                    result.decision, result.stage, result.reason,
                )
                return ClarificationAnswer(
                    answers=(result.decision,),
                    source="static",
                    confidence=1.0,
                    audit={
                        "stage": result.stage,
                        "reason": result.reason,
                    },
                )
            # fall through to veritas (existing path)
        
        # existing: requires_manual check, veritas call, fallback logic
        if self.requires_manual(request.origin_node):
            ...
```

### 4.6 `source` literal gains `"static"`

```python
# protocol.py
source: Literal["human", "veritas", "fallback", "static"]
```

```python
# Serialization validation
source = d.get("source")
if source not in ("human", "veritas", "fallback", "static"):
    raise ValueError(...)
```

The `prior_clarifications` context format becomes:
`"Q: {question}\nA: {answer} (source=static, conf=1.0)"` — distinguishes rule-based decisions from LLM decisions in the audit trail.

### 4.7 `build_default_clarification_policy` and `runtime_factory` wiring

`selector.py` passes the pipeline through:

```python
def build_default_clarification_policy(
    mode: ClarificationMode,
    *,
    veritas_answer: VeritasAnswerFn | None = None,
    emit: EmitFn | None = None,
    min_confidence: float = 0.4,
    interactive_fallback: ClarificationPolicy | None = None,
    force_manual_origins: tuple[str, ...] | list[str] | None = None,
    degrade_low_confidence: bool = False,
    tool_approval_pipeline: ToolApprovalPipeline | None = None,  # new
) -> ClarificationPolicy:
    ...
    return AutoClarificationPolicy(
        veritas_answer,
        min_confidence=min_confidence,
        interactive_fallback=interactive_fallback,
        force_manual_origins=force_manual_origins,
        degrade_low_confidence=degrade_low_confidence,
        tool_approval_pipeline=tool_approval_pipeline,
    )
```

`runtime_factory.py` builds the pipeline from config:

```python
def build_clarification_policy_for_runner(
    config: SootheConfig,
    *,
    mode: str | None = None,
    emit: EmitFn | None = None,
    human_attached: bool = False,
    thread_id: str | None = None,
    loop_id: str | None = None,
) -> ClarificationPolicy:
    ...
    # Build tool-approval pipeline from config
    ta_config = clar_cfg.tool_approval
    tool_approval_pipeline: ToolApprovalPipeline | None = None
    if ta_config.enabled:
        workspace_root = ...  # resolved from loop state at request time
        tool_approval_pipeline = ToolApprovalPipeline(
            config=ta_config,
            workspace_root=workspace_root,
        )
    
    return build_default_clarification_policy(
        mode="auto",
        veritas_answer=_veritas,
        emit=emit,
        min_confidence=clar_cfg.auto_min_confidence,
        interactive_fallback=interactive_fallback,
        force_manual_origins=list(clar_cfg.force_manual_origins or ()),
        degrade_low_confidence=clar_cfg.degrade_to_manual_on_low_confidence,
        tool_approval_pipeline=tool_approval_pipeline,
    )
```

**Workspace resolution**: `workspace_root` is per-request (from `LoopStateView.workspace_summary`), not per-goal. The pipeline is constructed without a workspace root; the workspace is resolved at evaluation time from the `ClarificationRequest.loop_state.workspace_summary` and passed to `match_path_rule`. This handles the case where different goals in the same runner have different workspaces.

Adjusted `ToolApprovalPipeline.evaluate` signature:

```python
def evaluate(
    self,
    action_requests: list[Mapping[str, Any]],
    *,
    workspace_root: str | None = None,  # per-request override
) -> ApprovalResult | None:
```

`AutoClarificationPolicy.answer` passes `request.loop_state.workspace_summary`:

```python
result = self._tool_approval_pipeline.evaluate(
    action_requests,
    workspace_root=request.loop_state.workspace_summary,
)
```

### 4.8 Veritas fallback prompt truncation

When a tool-approval case reaches Stage 4 (veritas), the user prompt is drastically slimmer. A new variant in `build_veritas_user_prompt` gated on origin:

```python
def build_veritas_user_prompt(
    request: ClarificationRequest,
    *,
    max_context_steps: int = 8,
    agent_instructions_max_chars: int = 25_000,
) -> str:
    if request.origin_node == "tool_approval":
        return _build_tool_approval_user_prompt(request)
    # existing intent-answerer prompt
    ...


def _build_tool_approval_user_prompt(request: ClarificationRequest) -> str:
    """Slim prompt for tool-approval fallback.
    
    Only includes what's needed for a safety judgment:
    - Tool name + full args (from metadata.action_requests)
    - User request (context for intent alignment)
    - Goal description (context for intent alignment)
    
    No AGENTS.md, no prior clarifications, no recent step outputs.
    """
    view = request.loop_state
    lines = [
        "=== Original user request ===",
        view.user_request.strip() or "(none)",
        "",
        "=== Goal description ===",
        view.goal_description.strip() or "(none)",
        "",
        "=== Pending tool actions ===",
    ]
    for i, ar in enumerate(request.metadata.get("action_requests", []), 1):
        name = ar.get("name", "?")
        args = ar.get("args", {})
        lines.append(f"{i}. {name}({dict(args)})")
    return "\n".join(lines)
```

The `VeritasFallbackConfig` settings (`model_role`, `max_context_steps`, `inline_project_instructions`) are threaded through `runtime_factory._veritas` into `veritas_answer()` as overrides when the origin is `tool_approval`:

```python
async def _veritas(request: ClarificationRequest) -> VeritasAnswerSchema:
    if request.origin_node == "tool_approval":
        return await veritas_answer(
            request,
            model=veritas_fallback_model,      # fast model
            max_context_steps=ta_config.veritas_fallback.max_context_steps,
            soothe_config=config,
            thread_id=thread_id,
            loop_id=loop_id,
            # prompt builder checks origin internally
        )
    return await veritas_answer(
        request,
        model=veritas_model,                  # think model (existing)
        max_context_steps=veritas_cfg.max_context_steps,
        soothe_config=config,
        thread_id=thread_id,
        loop_id=loop_id,
    )
```

---

## 5. Safety Properties

1. **Deny rules first.** A destructive command pattern is rejected before any allow rule can fire. This is a security property: `rm -rf /` matches the deny rule `rm -rf *` at Stage 1, never reaching Stage 3.

2. **Safety checks are bypass-immune.** `DANGEROUS_FILES` and `DANGEROUS_DIRECTORIES` are built-in constants, not configurable. They always run at Stage 2 when `tool_approval.enabled` is true, regardless of what allow rules say. An allow rule for `<workspace>/**` does not auto-approve `.git/config` because the safety check fires first. This mirrors Claude Code's `checkPathSafetyForAutoEdit` which blocks `.git/` and shell configs even in `bypassPermissions` mode.

3. **Allow rules never override safety.** The pipeline order guarantees safety checks (Stage 2) run before allow rules (Stage 3). An allow rule matching a path that also matches a safety check is dead — the safety check wins.

4. **Fail-safe on pipeline error.** Any exception in Stages 1–3 is caught and the pipeline returns `None` (defer to veritas). The pipeline never auto-approves on error. This is the same principle as Claude Code's classifier fallback: when the classifier is unavailable, it falls back to manual approval rather than auto-approving.

5. **Fail-safe on workspace unknown.** If `workspace_summary` is `None`, path-based allow rules (Stage 3) do not fire — the `<workspace>` token cannot expand. Everything reaches veritas. Path-based deny rules (Stage 1) with absolute patterns (`/etc/**`) still fire.

6. **Veritas remains the final guard.** Ambiguous cases (unknown tool, command not on any list, MCP tool) still get LLM scrutiny. The pipeline eliminates trivial decisions; it does not eliminate the LLM.

7. **`delete` is never auto-approved by allow rules.** The default allow rules include `edit_file` and `write_file` but not `delete`. Even with an in-workspace path, `delete` always reaches veritas. Operators can add a `delete` allow rule explicitly if they want auto-approve for deletions.

---

## 6. What This Eliminates

For a typical autopilot goal with 20 tool calls (mostly in-workspace `edit_file` + safe `run_command` like `pytest`):

| Stage | Calls | LLM? | Cost |
|-------|------:|------|------|
| 1. Deny rules | 0 | no | ~0 |
| 2. Safety checks | ~2 (`.git/` edits blocked) | no | ~0 |
| 3. Allow rules | ~16 (in-workspace writes, safe commands) | no | ~0 |
| 4. Veritas LLM | ~2 (ambiguous commands, non-workspace paths) | yes (fast model, ~500-token prompt) | minimal |
| **Before (all veritas)** | 20 | all yes (think model, ~25k-token prompt) | **huge** |

~90% of tool approvals become instant and free. The remaining ~10% use a fast model with a ~50× smaller prompt.

---

## 7. Data Flow

```
1. deepagents emits action_requests interrupt
   (edit_file / write_file / delete / run_command)

2. Executor captures it
   → ClarificationDetector.detect() sees "action_requests" key
   → from_tool_approval_interrupt() builds:
     ClarificationRequest(
       origin="tool_approval",
       metadata={"action_requests": [...]},
       loop_state=LoopStateView(workspace_summary="/path/to/workspace", ...)
     )

3. AutoClarificationPolicy.answer():
   a. origin == tool_approval, pipeline is not None
   b. pipeline.evaluate(action_requests, workspace_root=...)
      Stage 1: deny rules → reject?  → ClarificationAnswer(source="static")
      Stage 2: safety checks → reject? → ClarificationAnswer(source="static")
      Stage 3: allow rules → approve? → ClarificationAnswer(source="static")
      Stage 4: None → fall through
   c. (fallthrough) requires_manual? no
   d. _veritas_answer(request) with slim prompt + fast model
      → ClarificationAnswer(source="veritas")

4. build_clarification_resume_payload()
   maps "approve"/"reject" to HITL decisions shape
   (unchanged — _answer_to_decision already handles these tokens)
```

---

## 8. Testing

### 8.1 Rule matcher unit tests
- Exact match: `git status` matches rule `git status`
- Prefix match: `grep -r foo` matches rule `grep:*`
- Wildcard match: `pytest -xvs` matches rule `pytest*`
- Non-match: `rm -rf /` does not match allow rule `ls *`
- Case insensitivity for commands

### 8.2 Safety checker unit tests
- Dangerous file: `edit_file` on `.bashrc` → unsafe
- Dangerous directory: `edit_file` on `.git/config` → unsafe
- Path traversal: `edit_file` on `../../etc/passwd` → unsafe
- UNC path: `edit_file` on `//server/share` → unsafe
- Trailing dots: `edit_file` on `.git.` → unsafe
- Safe path: `edit_file` on `src/auth.py` inside workspace → safe
- Destructive command: `run_command rm -rf /` → unsafe
- Safe command: `run_command pytest` → safe (no destructive pattern)

### 8.3 Pipeline integration tests
- Deny rule match → reject, stage=deny_rule
- Safety check match → reject, stage=safety_check
- Allow rule match → approve, stage=allow_rule
- No match → None (defer to veritas)
- Mixed batch (one rejected, one approved) → reject (first rejection wins)
- Pipeline disabled (`enabled=false`) → None (all go to veritas)
- Workspace unknown → path-based allow rules don't fire
- Pipeline error → None (defer to veritas, never auto-approve on error)

### 8.4 Policy integration test
- Pipeline short-circuits before veritas for clear-cut cases (mock `_veritas_answer`, assert not called)
- Ambiguous case reaches veritas with slim prompt (assert prompt does not contain AGENTS.md)
- `source="static"` in audit trail for pipeline decisions
- `source="veritas"` for LLM decisions

### 8.5 Config test
- Default deny/allow rules loaded from `ToolApprovalConfig` defaults
- Operator can override rules in `nano.yml`
- `veritas_fallback.enabled=false` → ambiguous defers to human (interactive fallback) or hard-defers (autopilot)

### 8.6 Serialization test
- `ClarificationRequest` with `metadata={"action_requests": [...]}` survives `request_to_state` / `request_from_state` round-trip
- `ClarificationAnswer` with `source="static"` survives `answer_to_state` / `answer_from_state` round-trip
- Backward compatibility: deserializing old state without `metadata` → empty dict (no crash)

### 8.7 End-to-end test
- `tool_approval` interrupt with in-workspace `edit_file` → approved by Stage 3, no LLM call
- `tool_approval` interrupt with `rm -rf /` → rejected by Stage 1, no LLM call
- `tool_approval` interrupt with ambiguous `run_command` (e.g. `curl https://example.com`) → reaches veritas with slim prompt

---

## 9. Scope Boundaries

### In scope
- `ToolApprovalConfig`, `ToolApprovalRule`, `VeritasFallbackConfig`, `ToolApprovalAuditConfig` models
- `tool_rule_matcher.py` (command + path pattern matching)
- `tool_safety_check.py` (dangerous paths/files/commands)
- `tool_approval_pipeline.py` (multi-stage evaluator)
- `ClarificationRequest.metadata` field + detector populating it
- `AutoClarificationPolicy` short-circuit branch for `tool_approval`
- Veritas user prompt truncation for `tool_approval` origin
- `source` literal gains `"static"`
- `runtime_factory` + `selector` wiring
- Default deny/allow rule lists
- Config template (`config/config.template.yml`, `config/develop/nano.yml`) additions

### Out of scope
- Changing `interrupt_on` wiring in `builder.py` (still interrupts on all 4 mutating tools — the pipeline decides faster, the interrupt surface is unchanged)
- Applying the pipeline to non-`tool_approval` origins (intent clarifications still need LLM reasoning)
- Rule persistence / TUI "always allow" button (Claude Code's `PermissionUpdate` equivalent — future work)
- Sandboxing (Claude Code's `SandboxManager` — separate concern)
- Caching across tool calls within a goal (each call's context differs; caching is a future optimization)
- Two-stage LLM classifier (Claude Code's stage-1 + stage-2 classifier — overkill for now; the single veritas call with a slim prompt is sufficient)

---

## 10. Dependencies

- `pathspec` library for gitignore-style path matching (Python equivalent of Claude Code's `ignore` npm package). If not already a dependency, add to `soothe` package. If adding it is a blocker, fall back to `fnmatch` with `**` expansion as a stopgap — but `pathspec` is the right choice for correctness (handles edge cases like `**` matching at any depth, negation patterns, etc.).

---

## 11. File Manifest

| File | Action | Description |
|------|--------|-------------|
| `sloop/clarification/tool_rule_matcher.py` | new | Command + path pattern matcher |
| `sloop/clarification/tool_safety_check.py` | new | Dangerous path/file/command checker |
| `sloop/clarification/tool_approval_pipeline.py` | new | Multi-stage evaluator |
| `sloop/clarification/protocol.py` | edit | Add `metadata` to `ClarificationRequest`; add `"static"` to `source` literal |
| `sloop/clarification/detector.py` | edit | Populate `metadata` in `from_tool_approval_interrupt` |
| `sloop/clarification/auto.py` | edit | Add pipeline short-circuit in `answer()`; new `tool_approval_pipeline` init arg |
| `sloop/clarification/selector.py` | edit | Pass pipeline through to policy |
| `sloop/clarification/runtime_factory.py` | edit | Build pipeline from config; dual-model wiring |
| `subagents/veritas/prompts.py` | edit | Slim prompt variant for `tool_approval` origin |
| `config/models.py` | edit | Add `ToolApprovalConfig` + sub-models; add to `ClarificationConfig` |
| `sloop/clarification/__init__.py` | edit | Export new public symbols |
| `config/config.template.yml` | edit | Add `tool_approval` block |
| `config/develop/nano.yml` | edit | Add `tool_approval` block |
| `tests/.../test_tool_rule_matcher.py` | new | Rule matcher unit tests |
| `tests/.../test_tool_safety_check.py` | new | Safety checker unit tests |
| `tests/.../test_tool_approval_pipeline.py` | new | Pipeline integration tests |
| `tests/.../test_tool_approval_bridge.py` | edit | Add pipeline short-circuit tests |
| `tests/.../test_veritas_prompts.py` | edit | Slim prompt variant tests |
| `tests/.../test_clarification_auto.py` | edit | Source="static" + pipeline integration |
