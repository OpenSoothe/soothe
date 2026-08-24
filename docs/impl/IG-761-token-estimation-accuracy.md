# IG-761: Unified Model-Aware Token Estimation

**Created**: 2026-08-24
**Status**: In Progress
**Related**: RFC-224 (context window management), IG-151 (historical token tracking), IG-439 (context window mgmt)

## Problem

Token estimation across Soothe is inaccurate and inconsistent:

1. **Hardcoded single tokenizer** — `count_tokens` in
   `packages/soothe-nano/src/soothe_nano/utils/token_counting.py` always uses
   `tiktoken.get_encoding("cl100k_base")` regardless of the model in use.
   `cl100k_base` is the GPT-4 encoding; it is only an approximation for Claude,
   Gemini, and local models, and the code never documents that caveat.

2. **Output-only fallback** — the executor fallback at
   `packages/soothe/src/soothe/sloop/engine/execute/executor.py:1131-1136`
   calls `count_tokens(output)` counting **only the response**. When a provider
   omits `usage_metadata`, input (prompt) tokens are silently dropped from
   `total_tokens_used`, so the context-window percentage can be off by an
   order of magnitude on long prompts.

3. **Scattered ad-hoc counting** — estimation logic is duplicated across
   `count_tokens`, `extract_token_usage_from_messages`,
   `extract_token_counts_from_llm_result`, and the CLI's
   `extract_stream_message_token_usage`. Each has its own assumptions; they
   drift.

4. **Context-window manager skips non-text blocks** —
   `estimate_checkpoint_tokens_sync` at
   `packages/soothe/src/soothe/sloop/engine/execute/context_window_manager.py:190`
   silently skips non-text blocks and ignores tool-call / role-tag structural
   overhead, under-counting real token usage.

5. **Undeclared dependency** — `tiktoken` is not in
   `packages/soothe-nano/pyproject.toml` dependencies. It is only present
   transitively (via `langchain-openai` and `litellm`). If those ever drop or
   narrow it, the mechanism silently degrades to `len // 4` with no warning.

## Goal

Provide a strong mechanism to estimate **all** LLM token consumption — both
input (prompt) and output (response) tokens — across all model providers, with
actual usage when available and accurate model-aware estimation when absent.

## Design

### Principles

- **Accuracy over convenience**: model/provider-aware tokenizer selection
  replaces a one-size-fits-all hardcoded encoding.
- **Actual-first, estimate-on-demand**: prefer real `usage_metadata` from
  provider responses; fall back to structural estimation only when absent.
- **Single source of truth**: one `estimate_token_usage` API consumed by
  executor, context-window manager, and CLI — no scattered ad-hoc counting.
- **Both directions counted**: input AND output tokens always estimated,
  never output alone.
- **Declared, not optional**: `tiktoken` is a real runtime dependency, not a
  silent fallback.

### Unified API surface

A new `estimate_token_usage` function in
`packages/soothe-nano/src/soothe_nano/utils/token_usage.py`:

```python
def estimate_token_usage(
    messages: list[BaseMessage],
    *,
    model: str | None = None,
) -> dict[str, int]:
    """Return {input_tokens, output_tokens, total_tokens}.

    1. If any AI message carries usage_metadata, sum actual usage across all
       AI turns and return it (actual-first).
    2. Otherwise, estimate:
       - input_tokens  = count_tokens(prompt messages, model=model)
       - output_tokens = count_tokens(response content, model=model)
       - total_tokens  = input + output + structural overhead
    """
```

The structural-overhead term accounts for per-message role tags and tool-call
formatting that contribute real tokens but are not in `.content`. It is a
small per-message constant (3 tokens) summed across messages — a documented
approximation, not a magic number (see Config below).

### Model-aware tokenizer selection

`count_tokens` in `token_counting.py` gains an optional `model` parameter:

```python
def count_tokens(text: str, *, model: str | None = None, use_tiktoken: bool = True) -> int:
```

Selection order:

1. If `model` is provided and `tiktoken.encoding_for_model(model)` succeeds
   → use that encoding (OpenAI family: `gpt-4*`, `gpt-3.5-turbo`, `o1*`, etc.).
2. If `model` matches a Claude / Gemini / local prefix → fall back to
   `cl100k_base` with a **documented accuracy caveat** (their native
   tokenizers are not available via tiktoken; `cl100k_base` is the
   best-available approximation).
3. If no `model` hint → `cl100k_base` (preserves current default behavior).
4. If `tiktoken` import fails → `len(text) // 4` (genuine emergency only).

Encoding instances are cached in a module-level `lru_cache` so the
context-window manager (called frequently) does not re-instantiate encoders.

### Merge strategy: actual vs estimated

`estimate_token_usage` checks for `usage_metadata` on `AIMessage` /
`AIMessageChunk` first (reusing the existing
`extract_token_usage_from_messages` path). When present, it returns the
**actual** counts and does NOT add estimated counts — no double-counting.
When absent, it estimates input + output + structural overhead.

### Executor integration

The executor fallback at `executor.py:1131-1136` is rewired:

```python
elif output:
    from soothe_nano.utils.token_usage import estimate_token_usage
    usage = estimate_token_usage(messages=messages, model=model_hint)
    state.total_tokens_used += usage["total_tokens"]
```

The `model_hint` is threaded from the executor's configured model name (best
effort; `None` is acceptable and preserves current behavior). When actual
usage IS present, the unified API returns it and the executor adds only the
actual total — the existing `if token_usage` branch already handles that; the
new `else` branch only fires when actual usage is absent.

### Context-window manager integration

`estimate_checkpoint_tokens_sync` consumes `estimate_token_usage` over the
checkpoint messages, replacing the ad-hoc loop that skipped non-text blocks.
The unified API's structural-overhead term accounts for tool-call / role-tag
tokens. Non-text blocks (images, etc.) are still skipped at the content level
but their message-level structural overhead is now counted.

### Dependency declaration

`tiktoken>=0.7.0` is added to `packages/soothe-nano/pyproject.toml`
`[project.dependencies]`. The current lock already resolves `tiktoken 0.13.0`
transitively, so this declaration makes an existing reality explicit without
narrowing resolution.

## Changes

1. **IG-761** (this document) — design traceability.
2. **`packages/soothe-nano/pyproject.toml`** — add `tiktoken>=0.7.0` to
   runtime dependencies.
3. **`packages/soothe-nano/src/soothe_nano/utils/token_counting.py`** —
   model-aware `count_tokens` with cached encoding selection.
4. **`packages/soothe-nano/src/soothe_nano/utils/token_usage.py`** —
   `estimate_token_usage` unified API.
5. **`packages/soothe/src/soothe/sloop/engine/execute/executor.py`** —
   fallback calls `estimate_token_usage` (input + output).
6. **`packages/soothe/src/soothe/sloop/engine/execute/context_window_manager.py`**
   — `estimate_checkpoint_tokens_sync` consumes unified API.
7. **Tests** — model-aware selection, actual-vs-estimated paths, executor
   fallback, context-window structural accounting.

## Risks & assumptions

- **Backward compatibility**: existing `count_tokens` callers pass no
  `model` hint; the default signature remains callable. The default
  encoding stays `cl100k_base`.
- **Provider tokenizer availability**: Claude/Gemini native tokenizers are
  not in tiktoken. The design documents `cl100k_base` as a best-available
  approximation rather than claiming false precision.
- **Performance**: the context-window manager calls estimation frequently;
  encoding instances are cached via `lru_cache` to avoid re-instantiation.
- **No double-counting**: when actual `usage_metadata` is present, the
  unified API returns actual counts only; the executor's `if token_usage`
  branch handles that case and the `else` (estimate) branch only fires when
  actual usage is absent.
- **Structural token overhead**: the per-message constant (3 tokens) is a
  documented approximation for role-tag + separator overhead. It is not a
  magic number pulled from inline code; it lives in the unified API with a
  clear comment.

## Open questions (resolved)

- **Claude/Gemini encoding**: use `cl100k_base` as a documented approximation.
  No provider SDK-based counter is wired in tiktoken for these families;
  claiming one would be false precision.
