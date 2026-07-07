# Local OMLX Model & Go Client Test Report

**Date:** 2026-06-30
**Environment:** macOS Darwin 25.2.0, Python 3.12.13, Go 1.26.4
**OMLX server:** `http://100.75.70.86:9642/v1` (healthy, 7 models registered, 4 loaded)
**Daemon:** `soothed` ws://127.0.0.1:8765 (PID 75413, core 0.6.17 / daemon 0.6.12)
**Config:** `config/develop/config.yml` — router `local-omlx` trio:
- Code LLM: `gemma-4-12b-coder-fable5-composer2.5`
- CV vision: `GLM-4.6V-Flash-8bit`
- Embedding: `nomicai-modernbert-embed-base-bf16` (768 dims)

---

## 1. Executive Summary

Restarted the ground daemon service and validated the locally-deployed OMLX
models end-to-end: OMLX API surface (Python suite) plus the Go WebSocket
client's unit, integration, and stress suites against the live daemon.

**All suites green after two bug fixes in the LLM wrapper layer.**

| Suite | Result | Count |
|-------|--------|-------|
| OMLX OpenAI-API comprehensive suite | ✅ PASS | 64/64 |
| Go unit (short) | ✅ PASS | all (2 packages) |
| Go integration (live daemon) | ✅ PASS | 52/52 |
| Go stress (live daemon) | ✅ PASS | 11/11 |

Two real defects were found in `packages/soothe/src/soothe/utils/llm/wrappers.py`
that broke the daemon's `intent_hint=direct_llm` path against local OMLX models.
Both are fixed with regression tests.

---

## 2. Bugs Found & Fixed

### Bug A — `_astream` returned a coroutine, not an async iterator

**Symptom:** `TestIntegration_IntentHintDirectLLM`, `...ImageToText`, and
`...DirectLLMStructured` each timed out at 90 s. Daemon log:
```
TypeError: 'async for' requires an object with __aiter__ method, got coroutine
  async for chunk in self._model._astream(...)
```

**Root cause:** `OpenAICompatModelWrapper._astream` was declared
`async def` with `return await self._model._astream(...)`. In langchain's
`BaseChatModel` contract, `_astream` is an **async generator** (it `yield`s
chunks); the public `astream` iterates it via `async for chunk in
self._astream(...)` *without* awaiting. Returning a value made `_astream` a
coroutine, which has no `__aiter__`, so every streaming direct-LLM turn
crashed.

**Fix:** rewrite `_astream` as an async generator that proxies each chunk:
```python
async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
    async for chunk in self._model._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
        yield chunk
```

**Regression test:** `tests/unit/utils/llm/test_wrapper_astream_contract.py`
(3 tests — asserts `_astream(...)` is an async iterator, not a coroutine;
yields each chunk; iterable with `async for`).

### Bug B — Structured JSON output wrapped in markdown fences was not parsed

**Symptom:** `TestIntegration_IntentHintDirectLLMStructured` failed with
`StructuredOutputError: Expecting value: line 2 column 1 (char 1)`.

**Root cause:** gemma on oMLX returns `json_schema` output wrapped in a
markdown fence even when `response_format={"type":"json_schema",...}` is set:
```
content='\n```json\n{\n  "word": "GOJSON"\n}\n```'
```
`_extract_json_str_from_response` returned this raw, so `json.loads` choked.
Direct calls to OMLX with the same `response_format` succeed, confirming the
model is fine — the daemon-side parser was too strict.

**Fix:** added `_strip_json_text` (regex fence strip + slice to outermost
`{`) and routed both `content` and `reasoning_content` through it. Reuses the
same fence pattern already used by `subagents/deep_research/json_util.py`.

**Regression test:** `tests/unit/utils/llm/test_wrapper_json_extraction.py`
(8 tests — fenced json, bare fence, prose prefix, leading-newline fence,
empty-content raises, reasoning_content fallback).

### Verification of fixes

After restarting `soothed`, the three direct-LLM tests pass:
```
TestIntegration_IntentHintDirectLLM            --- PASS (5.72s)  assistant: "OK"
TestIntegration_IntentHintImageToText          --- PASS (7.25s)  assistant: "Escape from the Cyclops's cave"
TestIntegration_IntentHintDirectLLMStructured  --- PASS (5.74s)  assistant: {"word": "GOJSON"}
```

---

## 3. OMLX Local Model Validation (Python suite)

`scripts/omlx/test_llm.py` — 64/64 passed, covering the full OpenAI-compatible
API surface of the local deployment.

| Section | Result |
|---------|--------|
| Health & Status | 2/2 |
| Models (list/status/load-unload) | 3/3 |
| Chat Basic | 4/4 |
| Chat Sampling (temp/top_p/top_k/penalties/min_p/seed) | 8/8 |
| Chat Stop (string/list) | 2/2 |
| Chat Streaming (basic/usage/finish) | 3/3 |
| Chat Structured Output (json_object/json_schema/regex/choice/grammar) | 5/5 |
| Chat Tools (basic/none/required/response) | 4/4 |
| Text Completion (basic/batch/stream/stop) | 4/4 |
| Embeddings (single/batch/base64/dims/items) | 5/5 |
| VLM (text/image-url/image-base64/detail) | 4/4 |
| Anthropic Messages API (basic/system/stream/tokens) | 4/4 |
| Responses API (basic/instructions/stream/store/previous) | 5/5 |
| Rerank | 1/1 |
| Error Handling (invalid model/auth/empty msgs/empty prompt/tool/zero tokens) | 6/6 |
| Special Features (reasoning/prefill/thinking_budget/template_kwargs) | 4/4 |

**Conclusion:** local OMLX deployment is fully functional across chat, vision,
embeddings, structured output, tool calling, streaming, and the Anthropic /
Responses / Rerank compatibility APIs.

---

## 4. Go Client Test Results

`client/go/` (module `github.com/mirasoth/soothe-client-go`, Go 1.26.4).
`go vet` and `go build` clean.

- **Unit (short):** ✅ PASS — `soothe-client-go` + `examples` packages.
- **Integration:** ✅ 52/52 PASS, 0 FAIL, 0 SKIP (live daemon at ws://127.0.0.1:8765).
  Covers connect/close, daemon-ready handshake, loop lifecycle (new/list/get/
  tree/prune/delete/reattach/subscribe/detach/input), job APIs (create/status/
  pause/resume/cancel/dag/guidance), autopilot subscribe, loop messages/state/
  cards, MCP status, daemon status/shutdown, config get, skills catalog,
  models list, image understanding (single/multiple/payload), and all
  `intent_hint direct_llm` / `image_to_text` / structured-output turns.
- **Stress:** ✅ 11/11 PASS.

---

## 5. Reproduction / Commands

```bash
# OMLX model validation
NO_PROXY=localhost,127.0.0.1,100.75.70.86 uv run python scripts/omlx/test_llm.py

# Restart ground daemon
soothed restart

# Go client tests (daemon must be running on 8765)
cd client/go
SOOTHE_DAEMON_URL=ws://127.0.0.1:8765 go test -short ./...
SOOTHE_DAEMON_URL=ws://127.0.0.1:8765 go test -count=1 -run "Integration" .
SOOTHE_DAEMON_URL=ws://127.0.0.1:8765 go test -count=1 -run "Stress" .

# Python regression tests for the fixes
uv run pytest packages/soothe/tests/unit/utils/llm/ -q
```

---

## 6. Files Changed

**Source fix:**
- `packages/soothe/src/soothe/utils/llm/wrappers.py` —
  (1) `_astream` now async-generator; (2) added `_strip_json_text` +
  `_JSON_FENCE_RE`, routed `_extract_json_str_from_response` through it.

**Regression tests (new):**
- `packages/soothe/tests/unit/utils/llm/test_wrapper_astream_contract.py`
- `packages/soothe/tests/unit/utils/llm/test_wrapper_json_extraction.py`

No test expectations were modified to force a pass — both fixes correct the
implementation, per project rule "DO NOT Cheat Tests".
