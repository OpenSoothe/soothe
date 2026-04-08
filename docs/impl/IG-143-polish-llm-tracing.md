# IG-143: Polish LLM Tracing for Complete Coverage

**Status**: Draft
**Created**: 2026-04-08
**Priority**: Medium
**Dependencies**: IG-139, IG-140, IG-142 (RFC-207)

---

## Overview

Polish LLM tracing middleware to ensure comprehensive coverage of all LLM requests and responses throughout the Soothe system. Current implementation (IG-139, IG-140) traces CoreAgent loop calls, but several LLM invocation paths bypass the middleware stack. This guide addresses coverage gaps, RFC-207 message type awareness, and trace context enrichment.

---

## Current State Analysis

### What's Working (IG-139, IG-140)

✅ **CoreAgent loop tracing**: SimplePlanner, ClaudePlanner Reason/Plan calls
✅ **Middleware pattern**: Correct use of `awrap_model_call()` hook
✅ **Auto-configuration**: Logger level auto-set to DEBUG when tracing enabled
✅ **Request details**: Message count, character length, system prompt preview
✅ **Response details**: Token usage, latency, response preview, tool calls
✅ **Correlation**: Unique trace IDs linking request to response

### Coverage Gaps (What's Missing)

❌ **Classifier calls**: `unified_classifier.py:291` - LLM-based routing classification
❌ **Consensus calls**: `consensus.py:51` - Multi-vote consensus validation
❌ **Criticality calls**: `criticality.py:107` - Goal criticality assessment
❌ **Reflection calls**: `_shared.py:224` - Heuristic reflection after loop completion
❌ **Image tool calls**: `tools/image/implementation.py:97,148` - Vision model invocations
❌ **Browser agent calls**: `subagents/browser/implementation.py:81` - Browser agent initialization
❌ **Health check calls**: `daemon/health/checks/providers_check.py:61` - Provider connectivity test
❌ **Goal directive calls**: `runner/_runner_goal_directives.py:73` - Goal alignment check

These components call `model.ainvoke()` directly without going through the middleware-wrapped CoreAgent chain.

### Message Type Awareness Gaps (RFC-207)

⚠️ **Generic counting**: Current logs show "system=1, human=1, ai=1" without RFC-207 context
⚠️ **No purpose tag**: Missing indication of call purpose (reason, plan, classify, reflect, etc.)
⚠️ **No component tag**: Missing which module made the call (planner, classifier, consensus, etc.)

---

## Implementation Plan

### Phase 1: Add Context Tags to Model Calls

#### 1.1 Extend ModelRequest Metadata

Langchain's `ModelRequest` accepts metadata in the `config` parameter. Add purpose/component tags:

**Pattern**:
```python
# Current
response = await model.ainvoke(messages)

# Enhanced
response = await model.ainvoke(
    messages,
    config={
        "metadata": {
            "soothe_call_purpose": "reason",  # reason, plan, classify, reflect, etc.
            "soothe_call_component": "planner.simple",  # module path
            "soothe_call_phase": "layer2",  # layer1, layer2, pre-stream, etc.
        }
    }
)
```

Middleware can extract these tags for enriched logging.

#### 1.2 Add Helper Function

Create utility to standardize metadata injection:

**File**: `src/soothe/core/middleware/_utils.py` (new file)

```python
"""Middleware utility functions."""

from typing import Any


def create_llm_call_metadata(
    purpose: str,
    component: str,
    phase: str = "unknown",
    **extra: Any,
) -> dict[str, Any]:
    """Create standardized metadata for LLM calls.

    Args:
        purpose: Call purpose (reason, plan, classify, reflect, etc.)
        component: Component making the call (planner.simple, classifier, etc.)
        phase: Execution phase (layer1, layer2, pre-stream, etc.)
        **extra: Additional metadata fields

    Returns:
        Metadata dict for config["metadata"]
    """
    metadata = {
        "soothe_call_purpose": purpose,
        "soothe_call_component": component,
        "soothe_call_phase": phase,
    }
    metadata.update(extra)
    return metadata
```

#### 1.3 Update All Invocation Sites

Add metadata to each `.ainvoke()` call in the gap list:

**Example - Classifier**:

**File**: `src/soothe/core/unified_classifier.py`

**Before** (line 291):
```python
result = await self._routing_model.ainvoke(prompt)
```

**After**:
```python
from soothe.core.middleware._utils import create_llm_call_metadata

result = await self._routing_model.ainvoke(
    prompt,
    config={
        "metadata": create_llm_call_metadata(
            purpose="classify",
            component="classifier.unified",
            phase="pre-stream",
        )
    }
)
```

**Example - Consensus**:

**File**: `src/soothe/cognition/consensus.py`

**Before** (line 51):
```python
response = await model.ainvoke(prompt)
```

**After**:
```python
from soothe.core.middleware._utils import create_llm_call_metadata

response = await model.ainvoke(
    prompt,
    config={
        "metadata": create_llm_call_metadata(
            purpose="consensus_vote",
            component="cognition.consensus",
            phase="layer2",
        )
    }
)
```

Apply pattern to all 8 gap sites.

---

### Phase 2: Enhance LLMTracingMiddleware

#### 2.1 Extract Metadata from Request

**File**: `src/soothe/core/middleware/llm_tracing.py`

Add metadata extraction in `_log_request()`:

```python
def _log_request(self, trace_id: int, request: ModelRequest[ContextT]) -> None:
    """Log comprehensive request details."""
    messages = request.messages

    # Existing: count messages, log preview...

    # NEW: Extract metadata tags
    if hasattr(request, "config") and request.config:
        metadata = request.config.get("metadata", {})

        purpose = metadata.get("soothe_call_purpose", "unknown")
        component = metadata.get("soothe_call_component", "unknown")
        phase = metadata.get("soothe_call_phase", "unknown")

        if purpose != "unknown":
            logger.debug(
                "[LLM Trace #%d] Purpose: %s (component=%s, phase=%s)",
                trace_id,
                purpose,
                component,
                phase,
            )
```

#### 2.2 Add RFC-207 Message Type Context

Enhance message type logging with RFC-207 awareness:

```python
# Current
if system_count > 0 or human_count > 0 or ai_count > 0:
    logger.debug(
        "[LLM Trace #%d] Messages: system=%d, human=%d, ai=%d",
        trace_id,
        system_count,
        human_count,
        ai_count,
    )

# Enhanced with RFC-207 context
if system_count > 0 or human_count > 0 or ai_count > 0:
    # Detect RFC-207 pattern (SystemMessage + HumanMessage)
    rfc207_pattern = system_count == 1 and human_count == 1 and ai_count == 0

    logger.debug(
        "[LLM Trace #%d] Messages: system=%d, human=%d, ai=%d%s",
        trace_id,
        system_count,
        human_count,
        ai_count,
        " (RFC-207 separation)" if rfc207_pattern else "",
    )
```

#### 2.3 Add Purpose-Specific Previews

Different purposes benefit from different preview focus:

```python
# For "plan" purpose: show goal excerpt
# For "reason" purpose: show goal + evidence excerpt
# For "classify" purpose: show user query excerpt

purpose = metadata.get("soothe_call_purpose", "unknown")

if purpose == "plan":
    # Find goal in HumanMessage and show longer preview
    for msg in messages:
        if isinstance(msg, HumanMessage):
            goal_preview = self._preview(msg.content, max_length=400)
            logger.debug(
                "[LLM Trace #%d] Goal (preview): %s",
                trace_id,
                goal_preview,
            )
            break

elif purpose == "classify":
    # Show user query (usually short)
    for msg in messages:
        if isinstance(msg, HumanMessage):
            logger.debug(
                "[LLM Trace #%d] Query: %s",
                trace_id,
                msg.content[:200],  # Usually short
            )
            break
```

---

### Phase 3: Add Middleware Wrapper for Non-CoreAgent Calls

#### 3.1 Create LLMTracingWrapper

Components that call LLMs outside CoreAgent chain need middleware wrapping:

**File**: `src/soothe/core/middleware/_wrapper.py` (new file)

```python
"""LLM tracing wrapper for direct model calls outside CoreAgent."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel


class LLMTracingWrapper:
    """Wraps BaseChatModel to add tracing for non-CoreAgent calls.

    Use this when calling model.ainvoke() directly outside the
    CoreAgent middleware chain (e.g., in classifier, consensus, etc.).

    Example:
        wrapped_model = LLMTracingWrapper(model)
        response = await wrapped_model.ainvoke(messages, metadata={...})
    """

    def __init__(self, model: BaseChatModel) -> None:
        """Initialize wrapper with underlying model."""
        self._model = model

    async def ainvoke(
        self,
        messages: Any,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Invoke model with automatic tracing.

        Args:
            messages: Messages to send to model
            config: Config dict (metadata added here if missing)
            **kwargs: Additional arguments

        Returns:
            Model response
        """
        import logging
        import time

        logger = logging.getLogger("soothe.core.middleware.llm_tracing")

        # Generate trace ID
        trace_id = id(self)  # Simple unique ID

        # Log request
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        msg_count = len(messages) if hasattr(messages, "__len__") else 1
        total_chars = sum(
            len(m.content) if hasattr(m, "content") and isinstance(m.content, str)
            else len(str(m.content)) if hasattr(m, "content")
            else len(str(m))
            for m in messages
        ) if hasattr(messages, "__iter__") else len(str(messages))

        logger.debug(
            "[LLM Trace #%d] Request: %d messages (%s chars)",
            trace_id,
            msg_count,
            self._format_size(total_chars),
        )

        # Extract metadata
        metadata = (config or {}).get("metadata", {})
        purpose = metadata.get("soothe_call_purpose", "unknown")
        component = metadata.get("soothe_call_component", "unknown")

        if purpose != "unknown":
            logger.debug(
                "[LLM Trace #%d] Purpose: %s (component=%s)",
                trace_id,
                purpose,
                component,
            )

        # Measure time
        start_time = time.perf_counter()

        try:
            response = await self._model.ainvoke(messages, config=config, **kwargs)

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Log response
            if hasattr(response, "content"):
                preview = str(response.content)[:200]
                logger.debug(
                    "[LLM Trace #%d] Response: %dms, preview: %s",
                    trace_id,
                    duration_ms,
                    preview,
                )

                # Log token usage if available
                if hasattr(response, "response_metadata"):
                    token_usage = response.response_metadata.get("token_usage", {})
                    if token_usage:
                        logger.debug(
                            "[LLM Trace #%d] Token usage: prompt=%d, completion=%d, total=%d",
                            trace_id,
                            token_usage.get("prompt_tokens", 0),
                            token_usage.get("completion_tokens", 0),
                            token_usage.get("total_tokens", 0),
                        )

            return response

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "[LLM Trace #%d] Error after %dms: %s: %s",
                trace_id,
                duration_ms,
                type(e).__name__,
                str(e)[:200],
            )
            raise

    def _format_size(self, char_count: int) -> str:
        """Format character count as human-readable size."""
        if char_count < 1000:
            return str(char_count)
        if char_count < 1_000_000:
            return f"{char_count / 1000:.1f}K"
        return f"{char_count / 1_000_000:.1f}M"
```

#### 3.2 Apply Wrapper to Gap Sites

Update components to use wrapper:

**File**: `src/soothe/core/unified_classifier.py`

**Before**:
```python
class UnifiedClassifier:
    def __init__(self, model: BaseChatModel, ...):
        self._routing_model = model
```

**After**:
```python
from soothe.core.middleware._wrapper import LLMTracingWrapper

class UnifiedClassifier:
    def __init__(self, model: BaseChatModel, config: SootheConfig, ...):
        # Wrap model if tracing enabled
        if config.llm_tracing.enabled:
            self._routing_model = LLMTracingWrapper(model)
        else:
            self._routing_model = model
```

Apply to all 8 gap sites.

---

### Phase 4: Config File Alignment

#### 4.1 Verify Config Parity

Both `config/config.yml` and `config.dev.yml` must have matching `llm_tracing` sections:

**config/config.yml** (template):
```yaml
llm_tracing:
  enabled: false  # Default off for production
  log_preview_length: 200  # Default preview length
```

**config.dev.yml** (dev defaults):
```yaml
llm_tracing:
  enabled: true  # Default on for development
  log_preview_length: 1000  # Longer previews for debugging
```

#### 4.2 Add to Settings Schema

**File**: `src/soothe/config/settings.py`

Add LLM tracing config class:

```python
class LLMTracingConfig(BaseModel):
    """LLM tracing middleware configuration."""

    enabled: bool = False
    log_preview_length: int = 200

    @field_validator("log_preview_length")
    @classmethod
    def validate_preview_length(cls, v: int) -> int:
        """Ensure preview length is reasonable."""
        if v < 50:
            raise ValueError("log_preview_length must be at least 50")
        if v > 1000:
            raise ValueError("log_preview_length must not exceed 1000")
        return v


class SootheConfig(BaseSettings):
    # Existing fields...

    llm_tracing: LLMTracingConfig = Field(default_factory=LLMTracingConfig)
```

---

### Phase 5: Test Updates

#### 5.1 Add Metadata Injection Tests

**File**: `tests/unit/core/middleware/test_llm_tracing.py` (new file)

```python
"""Tests for LLM tracing metadata injection."""

from unittest.mock import AsyncMock, MagicMock

from soothe.core.middleware._utils import create_llm_call_metadata
from soothe.core.middleware.llm_tracing import LLMTracingMiddleware


async def test_metadata_extraction_in_tracing():
    """Test middleware extracts metadata from request."""
    middleware = LLMTracingMiddleware()

    # Create mock request with metadata
    request = MagicMock()
    request.messages = [MagicMock(content="test")]
    request.config = {
        "metadata": create_llm_call_metadata(
            purpose="classify",
            component="classifier",
            phase="pre-stream",
        )
    }

    # Log request (capture logs)
    middleware._log_request(1, request)

    # Verify metadata logged
    # (Use logging capture or assert logger.debug called)


async def test_wrapper_applies_tracing():
    """Test wrapper adds tracing to direct calls."""
    from soothe.core.middleware._wrapper import LLMTracingWrapper

    mock_model = AsyncMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content="response"))

    wrapper = LLMTracingWrapper(mock_model)

    messages = [MagicMock(content="test")]
    config = {"metadata": create_llm_call_metadata(purpose="test", component="test")}

    response = await wrapper.ainvoke(messages, config=config)

    assert response is not None
    mock_model.ainvoke.assert_called_once()
```

#### 5.2 Add Integration Test

**File**: `tests/integration/test_llm_tracing_coverage.py` (new file)

```python
"""Test LLM tracing covers all invocation paths."""

import logging
import pytest


@pytest.mark.asyncio
async def test_classifier_tracing_enabled():
    """Test classifier calls are traced."""
    # Enable tracing
    # Run classifier
    # Verify logs contain "[LLM Trace" with purpose="classify"


@pytest.mark.asyncio
async def test_consensus_tracing_enabled():
    """Test consensus calls are traced."""
    # Enable tracing
    # Run consensus
    # Verify logs contain "[LLM Trace" with purpose="consensus_vote"


@pytest.mark.asyncio
async def test_rfc207_message_type_logged():
    """Test RFC-207 message structure is logged."""
    # Run planner with RFC-207 messages
    # Verify logs show "(RFC-207 separation)"
```

---

### Phase 6: Documentation Updates

#### 6.1 Update IG-139

**File**: `docs/impl/IG-139-llm-tracing.md`

Add section on metadata injection:

```markdown
## Metadata Injection (IG-143)

All LLM calls should include standardized metadata for enriched tracing:

```python
from soothe.core.middleware._utils import create_llm_call_metadata

response = await model.ainvoke(
    messages,
    config={
        "metadata": create_llm_call_metadata(
            purpose="classify",
            component="classifier",
            phase="pre-stream",
        )
    }
)
```

This enables the middleware to log:
- Call purpose (classify, reason, plan, reflect, etc.)
- Component making the call (classifier, planner, etc.)
- Execution phase (layer1, layer2, pre-stream, etc.)
```

#### 6.2 Add IG-143 to CLAUDE.md

**File**: `CLAUDE.md`

Add in Recent Changes:

```markdown
### IG-143: LLM Tracing Polish
- Added metadata injection for all LLM calls (purpose, component, phase)
- Added LLMTracingWrapper for non-CoreAgent calls
- Enhanced logging with RFC-207 message type awareness
- Covered all LLM invocation paths (classifier, consensus, criticality, etc.)
- All tests passing ✅
```

---

## Files Modified

### New Files

1. `src/soothe/core/middleware/_utils.py` - Metadata creation helper
2. `src/soothe/core/middleware/_wrapper.py` - Wrapper for direct calls
3. `tests/unit/core/middleware/test_llm_tracing.py` - Metadata tests
4. `tests/integration/test_llm_tracing_coverage.py` - Coverage tests

### Modified Files

5. `src/soothe/core/middleware/llm_tracing.py`:
   - Add metadata extraction
   - Add RFC-207 message type context
   - Add purpose-specific previews

6. `src/soothe/core/unified_classifier.py`:
   - Add metadata to `ainvoke()` call
   - Wrap model with LLMTracingWrapper

7. `src/soothe/cognition/consensus.py`:
   - Add metadata to `ainvoke()` call
   - Wrap model

8. `src/soothe/cognition/criticality.py`:
   - Add metadata to `ainvoke()` call
   - Wrap model

9. `src/soothe/backends/planning/_shared.py`:
   - Add metadata to reflection calls
   - Wrap model

10. `src/soothe/tools/image/implementation.py`:
    - Add metadata to vision calls
    - Wrap model

11. `src/soothe/subagents/browser/implementation.py`:
    - Add metadata to browser agent calls
    - Wrap model

12. `src/soothe/daemon/health/checks/providers_check.py`:
    - Add metadata to health check calls
    - Wrap model

13. `src/soothe/core/runner/_runner_goal_directives.py`:
    - Add metadata to goal alignment calls
    - Wrap model

14. `src/soothe/config/settings.py`:
    - Add `LLMTracingConfig` class
    - Add validation for `log_preview_length`

15. `config/config.yml`:
    - Update llm_tracing section

16. `config.dev.yml`:
    - Update llm_tracing section (verify parity)

### Documentation

17. `docs/impl/IG-139-llm-tracing.md`:
    - Add metadata injection section

18. `CLAUDE.md`:
    - Add IG-143 in Recent Changes

---

## Verification Checklist

- [ ] All 8 gap sites wrapped with LLMTracingWrapper
- [ ] All calls include metadata (purpose, component, phase)
- [ ] Middleware extracts and logs metadata
- [ ] RFC-207 message structure logged correctly
- [ ] Purpose-specific previews working
- [ ] Config files aligned (config.yml and config.dev.yml)
- [ ] Settings schema includes LLMTracingConfig
- [ ] Unit tests for metadata injection
- [ ] Integration tests for coverage
- [ ] All 900+ tests pass
- [ ] Zero linting errors
- [ ] Documentation updated

---

## Testing Plan

### Manual Testing

```bash
# Enable tracing
export SOOTHE_LOG_LEVEL=DEBUG

# Run various paths
soothe "hello"  # Classifier
soothe "/research test"  # Research agent
soothe "analyze this"  # Planner
soothe --checkhealth  # Health checks

# Verify all calls logged
tail -f ~/.soothe/logs/soothe.log | grep "LLM Trace"

# Expected: See traces for classifier, planner, etc. with purpose tags
```

### Verification

```bash
./scripts/verify_finally.sh
```

---

## Success Metrics

1. **Coverage**: All LLM invocation paths traced (no gaps)
2. **Context**: Each trace shows purpose, component, phase
3. **RFC-207**: Message type structure logged correctly
4. **Config**: Both config files aligned
5. **Tests**: All tests passing, coverage tests added
6. **Quality**: Zero linting errors, well-documented

---

## Rollback Plan

If issues arise:

1. Remove LLMTracingWrapper usage (revert to direct calls)
2. Remove metadata injection (revert calls to simple form)
3. Both changes are localized and reversible
4. Middleware remains unchanged (backward compatible)

---

## Dependencies

- **IG-139**: Original LLM tracing implementation
- **IG-140**: Auto-configuration for logging
- **IG-142**: RFC-207 message type separation
- **RFC-207**: SystemMessage/HumanMessage separation spec

---

## Estimated Impact

**Code Changes**:
- 4 new files (utils, wrapper, 2 test files)
- 15 modified files (9 components, middleware, config, docs)

**Test Coverage**:
- Unit tests for metadata injection
- Integration tests for coverage verification
- All existing tests continue to pass

**Performance**:
- Minimal overhead (metadata dict creation)
- Wrapper adds negligible latency
- Tracing only active when enabled

---

## Changelog

**2026-04-08 (created)**:
- Initial IG-143 created
- Coverage gaps identified (8 sites)
- Implementation plan defined
- Metadata injection pattern designed
- Wrapper pattern designed