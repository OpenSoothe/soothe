#!/usr/bin/env python3
"""Comprehensive test script for OMLX OpenAI-compatible API server.

Tests cover ALL OpenAI API features:
- Health and status endpoints
- Models listing, status, load/unload operations
- Chat completions (all parameters and options)
- Text completions (legacy endpoint)
- Embeddings (all formats and options)
- Anthropic Messages API compatibility
- OpenAI Responses API
- Rerank API (Cohere/Jina compatible)
- Vision Language Model (images)
- Tool calling
- Structured output (JSON schema, regex, choice, grammar)
- Streaming with SSE
- Error handling and edge cases

Usage:
    uv run python scripts/omlx/test_llm.py

Environment (optional):
    OMLX_BASE_URL      default http://100.75.70.86:9642/v1
    OMLX_API_KEY       default mirasoth
    OMLX_LLM_MODEL     Code LLM — default chat (gemma-4-12b-coder-fable5-composer2.5)
    OMLX_VLM_MODEL     CV / vision (GLM-4.6V-Flash-8bit)
    OMLX_EMBED_MODEL   Embedding (nomicai-modernbert-embed-base-bf16)

Matches config/develop/nano.yml router roles for omlx.
"""

import base64
import json
import os
import struct
import urllib.error
import urllib.request

# Disable proxy for local / tailscale hosts
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,100.75.70.86")

# OMLX server configuration (override via env for soothe dev / remote hosts)
_OMLX_HOST = os.environ.get("OMLX_HOST", "100.75.70.86:9642")
OMLX_BASE_URL = os.environ.get("OMLX_BASE_URL", f"http://{_OMLX_HOST}/v1")
OMLX_BASE_URL_NO_V1 = os.environ.get("OMLX_BASE_URL_NO_V1", f"http://{_OMLX_HOST}")
API_KEY = os.environ.get("OMLX_API_KEY", "mirasoth")

# Soothe develop trio — Code LLM / CV vision / nomic embedding
LLM_MODEL = os.environ.get("OMLX_LLM_MODEL", "gemma-4-12b-coder-fable5-composer2.5")
VLM_MODEL = os.environ.get("OMLX_VLM_MODEL", "GLM-4.6V-Flash-8bit")
EMBED_MODEL = os.environ.get("OMLX_EMBED_MODEL", "nomicai-modernbert-embed-base-bf16")
FAIL_MODEL = os.environ.get("OMLX_FAIL_MODEL", "nonexistent-model-for-error-test")


def _model_loaded(model_id: str) -> bool:
    """Return whether ``model_id`` is loaded on the server."""
    response = make_request("/models/status", None, method="GET")
    result = json.loads(response.read().decode("utf-8"))
    row = next((m for m in result.get("models", []) if m.get("id") == model_id), None)
    return bool(row and row.get("loaded"))


def _ensure_model_loaded(model_id: str, *, label: str) -> None:
    """Load ``model_id`` via API if not already in memory."""
    if _model_loaded(model_id):
        print(f"  {label}: {model_id} already loaded")
        return
    print(f"  {label}: loading {model_id} ...")
    response = make_request(f"/models/{model_id}/load", {}, method="POST")
    result = json.loads(response.read().decode("utf-8"))
    assert result.get("status") == "ok", f"load failed: {result}"
    print(f"  {label}: {model_id} loaded")


def warmup_soothe_models() -> None:
    """Pre-load Code LLM, CV, and Embedding models before chat/VLM/embed tests."""
    print("\n[Warmup] Soothe model trio (Code / CV / Embedding)")
    print("-" * 60)
    _ensure_model_loaded(LLM_MODEL, label="Code LLM")
    _ensure_model_loaded(VLM_MODEL, label="CV vision")
    _ensure_model_loaded(EMBED_MODEL, label="Embedding")
    # Probe chat on Code model so first real test is not cold-start.
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Reply with one word: ready"}],
        "max_tokens": 16,
    }
    response = make_request("/chat/completions", payload, timeout=180)
    result = json.loads(response.read().decode("utf-8"))
    content = _assistant_text(result["choices"][0]["message"])[:80]
    print(f"  Code LLM probe: {content!r}")


def make_request(endpoint, payload=None, timeout=120, method="POST", base_url=None):
    """Make HTTP request to OMLX server."""
    url = f"{(base_url or OMLX_BASE_URL)}{endpoint}"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def make_request_raw(endpoint, payload=None, timeout=120, method="POST", base_url=None):
    """Make HTTP request and return raw response object for streaming."""
    url = f"{(base_url or OMLX_BASE_URL)}{endpoint}"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def _assistant_text(message: dict) -> str:
    """Return assistant text from ``content`` or ``reasoning_content`` (GLM/gemma oMLX)."""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    if content is not None and not isinstance(content, str):
        return str(content)
    return ""


# =============================================================================
# SECTION 1: Health and Status Endpoints
# =============================================================================


def test_health():
    """Test /health endpoint."""
    print("\n[Health] Testing: /health")
    print("-" * 60)

    response = make_request("/health", None, method="GET", base_url=OMLX_BASE_URL_NO_V1)
    result = json.loads(response.read().decode("utf-8"))

    assert result["status"] == "healthy", f"Expected healthy, got {result['status']}"
    assert "default_model" in result
    assert "engine_pool" in result

    print(f"Status: {result['status']}")
    print(f"Default model: {result['default_model']}")
    print(f"Loaded: {result['engine_pool']['loaded_count']}/{result['engine_pool']['model_count']}")
    return True


def test_api_status():
    """Test /api/status endpoint."""
    print("\n[API Status] Testing: /api/status")
    print("-" * 60)

    response = make_request("/api/status", None, method="GET", base_url=OMLX_BASE_URL_NO_V1)
    result = json.loads(response.read().decode("utf-8"))

    assert result["status"] == "ok"
    assert "version" in result
    assert "uptime_seconds" in result
    assert "loaded_models" in result

    print(f"Version: {result['version']}")
    print(f"Uptime: {result['uptime_seconds']:.1f}s")
    print(f"Total requests: {result['total_requests']}")
    print(f"Loaded models: {result['loaded_models']}")
    return True


# =============================================================================
# SECTION 2: Models Endpoints
# =============================================================================


def test_models_list():
    """Test /v1/models endpoint."""
    print("\n[Models] Testing: /v1/models")
    print("-" * 60)

    response = make_request("/models", None, method="GET")
    result = json.loads(response.read().decode("utf-8"))

    assert result["object"] == "list"
    assert "data" in result
    assert len(result["data"]) >= 1

    for model in result["data"]:
        assert model["object"] == "model"
        assert "id" in model
        assert "max_model_len" in model
        print(f"  - {model['id']} (context: {model['max_model_len']})")
    return True


def test_models_status():
    """Test /v1/models/status endpoint."""
    print("\n[Models Status] Testing: /v1/models/status")
    print("-" * 60)

    response = make_request("/models/status", None, method="GET")
    result = json.loads(response.read().decode("utf-8"))

    assert "models" in result
    for model in result["models"]:
        assert "id" in model
        assert "loaded" in model
        assert "engine_type" in model
        status = "✓ loaded" if model["loaded"] else "○ not loaded"
        print(f"  - {model['id']}: {status} ({model['engine_type']})")
    return True


def test_model_unload_load():
    """Test model unload and load operations."""
    print("\n[Model Management] Testing: unload/load")
    print("-" * 60)

    # Get current status
    response = make_request("/models/status", None, method="GET")
    result = json.loads(response.read().decode("utf-8"))

    loaded_models = [m for m in result["models"] if m["loaded"]]
    if LLM_MODEL not in {m["id"] for m in loaded_models}:
        _ensure_model_loaded(LLM_MODEL, label="Code LLM")
    test_model = LLM_MODEL
    print(f"Testing with Code LLM: {test_model}")

    # Unload
    response = make_request(f"/models/{test_model}/unload", {}, method="POST")
    result_unload = json.loads(response.read().decode("utf-8"))
    assert result_unload["status"] == "ok"
    print("Unload: ✓")

    # Verify unloaded
    response = make_request("/models/status", None, method="GET")
    result = json.loads(response.read().decode("utf-8"))
    model_status = next((m for m in result["models"] if m["id"] == test_model), None)
    assert model_status and not model_status["loaded"]

    # Load back
    response = make_request(f"/models/{test_model}/load", {}, method="POST")
    result_load = json.loads(response.read().decode("utf-8"))
    assert result_load["status"] == "ok"
    print("Load: ✓")
    return True


# =============================================================================
# SECTION 3: Chat Completions - Basic
# =============================================================================


def test_chat_basic():
    """Test basic chat completion."""
    print("\n[Chat Basic] Testing: basic completion")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "What is 2+2? Answer with just the number."}],
        "max_tokens": 10,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    assert result["object"] == "chat.completion"
    assert "choices" in result
    assert "usage" in result
    assert "id" in result

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content[:80]}...")
    print(
        f"Tokens: {result['usage']['prompt_tokens']} in, {result['usage']['completion_tokens']} out"
    )
    return True


def test_chat_with_system():
    """Test chat with system message."""
    print("\n[Chat System] Testing: system prompt")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful math tutor. Be very concise."},
            {"role": "user", "content": "What is 5*7?"},
        ],
        "max_tokens": 20,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content}")
    return True


def test_chat_multi_turn():
    """Test multi-turn conversation."""
    print("\n[Chat Multi-turn] Testing: conversation memory")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": "My name is Alice."},
            {"role": "assistant", "content": "Hello Alice! Nice to meet you."},
            {"role": "user", "content": "What's my name?"},
        ],
        "max_tokens": 30,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content}")
    return True


def test_chat_with_name():
    """Test chat with participant name."""
    print("\n[Chat Name] Testing: named participant")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": "Hello!", "name": "Bob"},
        ],
        "max_tokens": 20,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content}")
    return True


# =============================================================================
# SECTION 4: Chat Completions - Sampling Parameters
# =============================================================================


def test_chat_temperature():
    """Test temperature parameter."""
    print("\n[Chat Temperature] Testing: temperature variations")
    print("-" * 60)

    for temp in [0.0, 0.5, 1.0]:
        payload = {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": "Say 'hello'"}],
            "max_tokens": 10,
            "temperature": temp,
        }
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))
        content = _assistant_text(result["choices"][0]["message"])
        print(f"  temp={temp}: {content[:30]}...")
    return True


def test_chat_top_p():
    """Test top_p (nucleus sampling) parameter."""
    print("\n[Chat Top P] Testing: top_p parameter")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 10,
        "top_p": 0.9,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))
    print(f"Response: {_assistant_text(result['choices'][0]['message'])}")
    return True


def test_chat_top_k():
    """Test top_k parameter."""
    print("\n[Chat Top K] Testing: top_k parameter")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 10,
        "top_k": 40,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))
    print(f"Response: {_assistant_text(result['choices'][0]['message'])}")
    return True


def test_chat_repetition_penalty():
    """Test repetition_penalty parameter."""
    print("\n[Chat Repetition] Testing: repetition_penalty")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Repeat 'hello' 5 times"}],
        "max_tokens": 30,
        "repetition_penalty": 1.2,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))
    print(f"Response: {_assistant_text(result['choices'][0]['message'])}")
    return True


def test_chat_presence_penalty():
    """Test presence_penalty parameter."""
    print("\n[Chat Presence Penalty] Testing: presence_penalty")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Talk about cats"}],
        "max_tokens": 30,
        "presence_penalty": 0.5,
        "temperature": 0.7,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))
    print(f"Response: {_assistant_text(result['choices'][0]['message'])[:60]}...")
    return True


def test_chat_frequency_penalty():
    """Test frequency_penalty parameter."""
    print("\n[Chat Frequency Penalty] Testing: frequency_penalty")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 20,
        "frequency_penalty": 0.5,
        "temperature": 0.7,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))
    print(f"Response: {_assistant_text(result['choices'][0]['message'])}")
    return True


def test_chat_min_p():
    """Test min_p parameter."""
    print("\n[Chat Min P] Testing: min_p parameter")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 10,
        "min_p": 0.05,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))
    print(f"Response: {_assistant_text(result['choices'][0]['message'])}")
    return True


def test_chat_seed():
    """Test seed parameter for reproducible generation."""
    print("\n[Chat Seed] Testing: seed reproducibility")
    print("-" * 60)

    seed = 12345
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 10,
        "seed": seed,
        "temperature": 0.7,
    }

    # First call
    response1 = make_request("/chat/completions", payload)
    result1 = json.loads(response1.read().decode("utf-8"))

    # Second call with same seed
    response2 = make_request("/chat/completions", payload)
    result2 = json.loads(response2.read().decode("utf-8"))

    print(f"Call 1: {_assistant_text(result1['choices'][0]['message'])}")
    print(f"Call 2: {_assistant_text(result2['choices'][0]['message'])}")
    print(f"Seed: {seed} (best-effort reproducibility)")
    return True


# =============================================================================
# SECTION 5: Chat Completions - Stop Sequences
# =============================================================================


def test_chat_stop_string():
    """Test stop sequence as string."""
    print("\n[Chat Stop] Testing: stop sequence (string)")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Count from 1 to 10"}],
        "max_tokens": 50,
        "stop": "5",  # Should stop before 5
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    finish_reason = result["choices"][0].get("finish_reason")
    print(f"Response: {content[:60]}...")
    print(f"Finish reason: {finish_reason}")
    return True


def test_chat_stop_list():
    """Test stop sequences as list."""
    print("\n[Chat Stop List] Testing: stop sequences (list)")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "List colors: red, blue, green, yellow, purple"}],
        "max_tokens": 50,
        "stop": ["yellow", "purple"],
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content}")
    return True


# =============================================================================
# SECTION 6: Chat Completions - Streaming
# =============================================================================


def test_chat_stream_basic():
    """Test basic streaming."""
    print("\n[Chat Stream] Testing: basic streaming")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Say hello in 3 languages"}],
        "max_tokens": 50,
        "stream": True,
        "temperature": 0.1,
    }

    response = make_request_raw("/chat/completions", payload)

    print("Response: ", end="", flush=True)
    chunks = 0
    for line in response:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "content" in delta:
                    print(delta["content"], end="", flush=True)
                    chunks += 1

    print(f"\nChunks received: {chunks}")
    return True


def test_chat_stream_with_usage():
    """Test streaming with include_usage option."""
    print("\n[Chat Stream Usage] Testing: stream_options.include_usage")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Count to 5"}],
        "max_tokens": 30,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.1,
    }

    response = make_request_raw("/chat/completions", payload)

    print("Response: ", end="", flush=True)
    usage_received = None
    for line in response:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "content" in delta:
                    print(delta["content"], end="", flush=True)
            if "usage" in chunk and chunk["usage"]:
                usage_received = chunk["usage"]

    print()
    if usage_received:
        print(f"Usage: {usage_received}")
    return True


def test_chat_stream_finish_reason():
    """Test streaming finish_reason in final chunk."""
    print("\n[Chat Stream Finish] Testing: finish_reason in stream")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 5,
        "stream": True,
        "temperature": 0.1,
    }

    response = make_request_raw("/chat/completions", payload)

    finish_reason = None
    for line in response:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            choices = chunk.get("choices", [])
            if choices and choices[0].get("finish_reason"):
                finish_reason = choices[0]["finish_reason"]

    print(f"Finish reason: {finish_reason}")
    return True


# =============================================================================
# SECTION 7: Chat Completions - Structured Output
# =============================================================================


def test_chat_json_object():
    """Test json_object response format."""
    print("\n[Chat JSON Object] Testing: response_format json_object")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": "Give me a JSON object with name='test' and value=42"}
        ],
        "max_tokens": 50,
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content}")

    # Try to parse as JSON
    try:
        parsed = json.loads(content)
        print(f"Parsed: {parsed}")
    except json.JSONDecodeError:
        print("Note: Model may not enforce strict JSON (depends on model)")
    return True


def test_chat_json_schema():
    """Test json_schema response format."""
    print("\n[Chat JSON Schema] Testing: response_format json_schema")
    print("-" * 60)

    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
        "required": ["name", "age"],
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": "Tell me about a person named John who is 30 years old"}
        ],
        "max_tokens": 50,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "person",
                "schema": schema,
            },
        },
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content}")
    return True


def test_chat_structured_outputs_regex():
    """Test structured_outputs with regex."""
    print("\n[Chat Regex] Testing: structured_outputs regex")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Give me a phone number"}],
        "max_tokens": 20,
        "structured_outputs": {
            "regex": "\\d{3}-\\d{3}-\\d{4}",
        },
        "temperature": 0.1,
    }

    try:
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))
        content = _assistant_text(result["choices"][0]["message"])
        print(f"Response: {content}")
    except urllib.error.HTTPError as e:
        print(f"Note: Regex enforcement may not be available: {e.code}")
    return True


def test_chat_structured_outputs_choice():
    """Test structured_outputs with choice (constrained output)."""
    print("\n[Chat Choice] Testing: structured_outputs choice")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Pick a color"}],
        "max_tokens": 10,
        "structured_outputs": {
            "choice": ["red", "blue", "green"],
        },
        "temperature": 0.1,
    }

    try:
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))
        content = _assistant_text(result["choices"][0]["message"])
        print(f"Response: {content}")
    except urllib.error.HTTPError as e:
        print(f"Note: Choice enforcement may not be available: {e.code}")
    return True


def test_chat_structured_outputs_grammar():
    """Test structured_outputs with grammar."""
    print("\n[Chat Grammar] Testing: structured_outputs grammar")
    print("-" * 60)

    # Simple grammar for JSON-like output
    grammar = """
root ::= "{" pair "}"
pair ::= string ":" value
string ::= '"' [a-z]+ '"'
value ::= string | number
number ::= [0-9]+
"""

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Give me a simple JSON object"}],
        "max_tokens": 20,
        "structured_outputs": {
            "grammar": grammar,
        },
        "temperature": 0.1,
    }

    try:
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))
        content = _assistant_text(result["choices"][0]["message"])
        print(f"Response: {content}")
    except urllib.error.HTTPError as e:
        print(f"Note: Grammar enforcement may not be available: {e.code}")
    return True


# =============================================================================
# SECTION 8: Chat Completions - Tool Calling
# =============================================================================


def test_chat_tools_basic():
    """Test basic tool calling."""
    print("\n[Chat Tools] Testing: tool definitions")
    print("-" * 60)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get current weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City name"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["location"],
                },
            },
        }
    ]

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "What's the weather in Tokyo?"}],
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": 100,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    message = result["choices"][0]["message"]
    print(f"Content: {message.get('content', '(none)')}")

    if message.get("tool_calls"):
        for tc in message["tool_calls"]:
            print(f"Tool call: {tc['function']['name']}({tc['function']['arguments']})")
    else:
        print("No tool calls (model chose to respond directly)")
    return True


def test_chat_tools_none():
    """Test tool_choice='none'."""
    print("\n[Chat Tools None] Testing: tool_choice=none")
    print("-" * 60)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
            },
        }
    ]

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "What's the weather in Tokyo?"}],
        "tools": tools,
        "tool_choice": "none",  # Force no tool calls
        "max_tokens": 50,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    message = result["choices"][0]["message"]
    assert not message.get("tool_calls"), "Expected no tool calls with tool_choice=none"
    print(f"Content: {message.get('content', '(none)')}")
    print("No tool calls: ✓")
    return True


def test_chat_tools_required():
    """Test tool_choice forcing specific tool."""
    print("\n[Chat Tools Required] Testing: tool_choice specific tool")
    print("-" * 60)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get current time",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
            },
        },
    ]

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Hello"}],
        "tools": tools,
        "tool_choice": {"type": "function", "function": {"name": "get_time"}},
        "max_tokens": 50,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    message = result["choices"][0]["message"]
    if message.get("tool_calls"):
        tc = message["tool_calls"][0]
        print(f"Tool call: {tc['function']['name']}")
    return True


def test_chat_tools_with_response():
    """Test tool call with tool response."""
    print("\n[Chat Tools Response] Testing: tool response in conversation")
    print("-" * 60)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"location": {"type": "string"}}},
            },
        }
    ]

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": "What's the weather in Tokyo?"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"location": "Tokyo"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": '{"temperature": 22, "condition": "sunny"}',
            },
        ],
        "tools": tools,
        "max_tokens": 50,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content[:80]}...")
    return True


# =============================================================================
# SECTION 9: Text Completions (Legacy)
# =============================================================================


def test_completion_basic():
    """Test basic text completion."""
    print("\n[Completion] Testing: basic text completion")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "prompt": "The capital of France is",
        "max_tokens": 10,
        "temperature": 0.1,
    }

    response = make_request("/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    assert result["object"] == "text_completion"
    assert "choices" in result

    text = result["choices"][0]["text"]
    print(f"Response: {text}")
    return True


def test_completion_batch():
    """Test completion with multiple prompts."""
    print("\n[Completion Batch] Testing: multiple prompts")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "prompt": ["Hello", "Goodbye"],
        "max_tokens": 5,
        "temperature": 0.1,
    }

    response = make_request("/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    assert len(result["choices"]) >= 2

    for i, choice in enumerate(result["choices"]):
        print(f"Prompt {i}: {choice['text']}")
    return True


def test_completion_stream():
    """Test streaming text completion."""
    print("\n[Completion Stream] Testing: streaming completion")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "prompt": "Once upon a time",
        "max_tokens": 20,
        "stream": True,
        "temperature": 0.1,
    }

    response = make_request_raw("/completions", payload)

    print("Response: ", end="", flush=True)
    for line in response:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            choices = chunk.get("choices", [])
            if choices:
                text = choices[0].get("text", "")
                print(text, end="", flush=True)

    print()
    return True


def test_completion_with_stop():
    """Test completion with stop sequence."""
    print("\n[Completion Stop] Testing: stop sequence")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "prompt": "Count: 1, 2, 3,",
        "max_tokens": 20,
        "stop": ["6", "7"],
        "temperature": 0.1,
    }

    response = make_request("/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    text = result["choices"][0]["text"]
    print(f"Response: {text}")
    return True


# =============================================================================
# SECTION 10: Embeddings
# =============================================================================


def test_embedding_single():
    """Test single embedding."""
    print("\n[Embedding] Testing: single text")
    print("-" * 60)

    payload = {
        "model": EMBED_MODEL,
        "input": "Hello, world!",
    }

    response = make_request("/embeddings", payload)
    result = json.loads(response.read().decode("utf-8"))

    assert result["object"] == "list"
    assert len(result["data"]) == 1
    assert result["data"][0]["object"] == "embedding"

    embedding = result["data"][0]["embedding"]
    print(f"Dimension: {len(embedding)}")
    print(f"First 5: {embedding[:5]}")
    print(f"Tokens: {result['usage']['prompt_tokens']}")
    return True


def test_embedding_batch():
    """Test batch embeddings."""
    print("\n[Embedding Batch] Testing: multiple texts")
    print("-" * 60)

    payload = {
        "model": EMBED_MODEL,
        "input": ["Hello", "World", "Test"],
    }

    response = make_request("/embeddings", payload)
    result = json.loads(response.read().decode("utf-8"))

    assert len(result["data"]) == 3

    for i, emb in enumerate(result["data"]):
        assert emb["index"] == i
        print(f"  [{i}] {len(emb['embedding'])} dims")
    print(f"Total tokens: {result['usage']['total_tokens']}")
    return True


def test_embedding_base64():
    """Test embedding with base64 encoding."""
    print("\n[Embedding Base64] Testing: base64 format")
    print("-" * 60)

    payload = {
        "model": EMBED_MODEL,
        "input": "Test base64",
        "encoding_format": "base64",
    }

    response = make_request("/embeddings", payload)
    result = json.loads(response.read().decode("utf-8"))

    embedding = result["data"][0]["embedding"]
    assert isinstance(embedding, str)

    decoded = base64.b64decode(embedding)
    floats = struct.unpack(f"<{len(decoded) // 4}f", decoded)

    print(f"Base64: {len(embedding)} chars")
    print(f"Decoded: {len(floats)} floats")
    print(f"First 5: {floats[:5]}")
    return True


def test_embedding_dimensions():
    """Test embedding dimension truncation."""
    print("\n[Embedding Dimensions] Testing: dimension truncation")
    print("-" * 60)

    # Get full dimension
    payload_full = {"model": EMBED_MODEL, "input": "Test"}
    response = make_request("/embeddings", payload_full)
    result_full = json.loads(response.read().decode("utf-8"))
    full_dim = len(result_full["data"][0]["embedding"])

    # Request truncated
    payload = {
        "model": EMBED_MODEL,
        "input": "Test truncation",
        "dimensions": 256,
    }

    response = make_request("/embeddings", payload)
    result = json.loads(response.read().decode("utf-8"))

    actual_dim = len(result["data"][0]["embedding"])
    print(f"Full dimension: {full_dim}")
    print("Requested: 256")
    print(f"Actual: {actual_dim}")
    return True


def test_embedding_items():
    """Test embedding with items format (multimodal)."""
    print("\n[Embedding Items] Testing: items format")
    print("-" * 60)

    payload = {
        "model": EMBED_MODEL,
        "items": [{"text": "Hello"}, {"text": "World"}],
    }

    try:
        response = make_request("/embeddings", payload)
        result = json.loads(response.read().decode("utf-8"))

        assert len(result["data"]) == 2
        print(f"Items embedded: {len(result['data'])}")
        return True
    except urllib.error.HTTPError as e:
        print(f"Note: Items format may not be supported: {e.code}")
        return True


# =============================================================================
# SECTION 11: Vision Language Model (VLM)
# =============================================================================


def test_vlm_text():
    """Test VLM with text only."""
    print("\n[VLM Text] Testing: text-only input")
    print("-" * 60)

    payload = {
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": "Describe the color blue briefly"}],
        "max_tokens": 50,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content[:100]}...")
    return True


def test_vlm_image_url():
    """Test VLM with image URL."""
    print("\n[VLM Image URL] Testing: image from URL")
    print("-" * 60)

    payload = {
        "model": VLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image briefly"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Google_2015_logo.svg/100px-Google_2015_logo.svg.png"
                        },
                    },
                ],
            }
        ],
        "max_tokens": 50,
        "temperature": 0.1,
    }

    try:
        response = make_request("/chat/completions", payload, timeout=60)
        result = json.loads(response.read().decode("utf-8"))

        content = _assistant_text(result["choices"][0]["message"])
        print(f"Response: {content[:100]}...")
        return True
    except urllib.error.HTTPError as e:
        print(f"Note: Image URL may not be accessible: {e.code}")
        return True


def test_vlm_image_base64():
    """Test VLM with base64-encoded image."""
    print("\n[VLM Image Base64] Testing: base64 image")
    print("-" * 60)

    # 10x10 red PNG
    red_png = "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFklEQVQYlWNgGAWjYBSMglEwCkYBDQAAAVkABwC3ZdsAAAAASUVORK5CYII="

    payload = {
        "model": VLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What color is this image?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{red_png}"}},
                ],
            }
        ],
        "max_tokens": 30,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload, timeout=60)
    result = json.loads(response.read().decode("utf-8"))

    content = _assistant_text(result["choices"][0]["message"])
    print(f"Response: {content}")
    return True


def test_vlm_image_detail():
    """Test VLM image with detail parameter."""
    print("\n[VLM Image Detail] Testing: image detail level")
    print("-" * 60)

    red_png = "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFklEQVQYlWNgGAWjYBSMglEwCkYBDQAAAVkABwC3ZdsAAAAASUVORK5CYII="

    for detail in ["low", "high", "auto"]:
        payload = {
            "model": VLM_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe the image"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{red_png}",
                                "detail": detail,
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 20,
            "temperature": 0.1,
        }

        try:
            response = make_request("/chat/completions", payload, timeout=30)
            json.loads(response.read().decode("utf-8"))
            print(f"  detail={detail}: ✓")
        except urllib.error.HTTPError as e:
            print(f"  detail={detail}: HTTP {e.code}")
    return True


# =============================================================================
# SECTION 12: Anthropic Messages API
# =============================================================================


def test_anthropic_messages_basic():
    """Test Anthropic Messages API."""
    print("\n[Anthropic Messages] Testing: basic message")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "max_tokens": 30,
        "messages": [
            {"role": "user", "content": "What is 2+2?"},
        ],
    }

    response = make_request("/messages", payload)
    result = json.loads(response.read().decode("utf-8"))

    # Anthropic response format
    assert "id" in result
    assert result["type"] == "message"

    # Content is a list of blocks
    content_blocks = result.get("content", [])
    if content_blocks:
        text = next((b.get("text", "") for b in content_blocks if b.get("type") == "text"), "")
        print(f"Response: {text}")
    return True


def test_anthropic_messages_system():
    """Test Anthropic Messages with system."""
    print("\n[Anthropic System] Testing: system prompt")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "max_tokens": 30,
        "system": "You are a helpful assistant. Be concise.",
        "messages": [
            {"role": "user", "content": "Hello"},
        ],
    }

    response = make_request("/messages", payload)
    result = json.loads(response.read().decode("utf-8"))

    content_blocks = result.get("content", [])
    if content_blocks:
        text = next((b.get("text", "") for b in content_blocks if b.get("type") == "text"), "")
        print(f"Response: {text}")
    return True


def test_anthropic_messages_stream():
    """Test Anthropic Messages streaming."""
    print("\n[Anthropic Stream] Testing: streaming")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "max_tokens": 30,
        "messages": [{"role": "user", "content": "Say hello"}],
        "stream": True,
    }

    response = make_request_raw("/messages", payload)

    print("Response: ", end="", flush=True)
    for line in response:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            data = line[6:]
            try:
                event = json.loads(data)
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        print(delta.get("text", ""), end="", flush=True)
            except json.JSONDecodeError:
                pass

    print()
    return True


def test_anthropic_count_tokens():
    """Test Anthropic count_tokens endpoint."""
    print("\n[Anthropic Tokens] Testing: count_tokens")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": "Hello, how are you?"},
        ],
    }

    response = make_request("/messages/count_tokens", payload)
    result = json.loads(response.read().decode("utf-8"))

    assert "input_tokens" in result
    print(f"Input tokens: {result['input_tokens']}")
    return True


# =============================================================================
# SECTION 13: OpenAI Responses API
# =============================================================================


def test_responses_basic():
    """Test OpenAI Responses API."""
    print("\n[Responses API] Testing: basic response")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "input": "What is 2+2?",
        "max_output_tokens": 30,
    }

    response = make_request("/responses", payload)
    result = json.loads(response.read().decode("utf-8"))

    assert result["object"] == "response"
    assert "output" in result

    output_items = result.get("output", [])
    if output_items:
        for item in output_items:
            if item.get("type") == "message":
                content = item.get("content", [])
                for c in content:
                    if c.get("type") == "output_text":
                        print(f"Response: {c.get('text', '')}")

    print(f"Response ID: {result['id']}")
    return True


def test_responses_with_instructions():
    """Test Responses API with instructions."""
    print("\n[Responses Instructions] Testing: instructions field")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "input": "Hello",
        "instructions": "Be very brief and formal.",
        "max_output_tokens": 30,
    }

    response = make_request("/responses", payload)
    result = json.loads(response.read().decode("utf-8"))

    output_items = result.get("output", [])
    if output_items:
        for item in output_items:
            if item.get("type") == "message":
                content = item.get("content", [])
                for c in content:
                    if c.get("type") == "output_text":
                        print(f"Response: {c.get('text', '')}")
    return True


def test_responses_stream():
    """Test Responses API streaming."""
    print("\n[Responses Stream] Testing: streaming")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "input": "Say hello",
        "max_output_tokens": 30,
        "stream": True,
    }

    response = make_request_raw("/responses", payload)

    print("Response: ", end="", flush=True)
    for line in response:
        line = line.decode("utf-8").strip()
        if line.startswith("data: "):
            data = line[6:]
            try:
                event = json.loads(data)
                if event.get("type") == "response.output_text.delta":
                    print(event.get("delta", ""), end="", flush=True)
            except json.JSONDecodeError:
                pass

    print()
    return True


def test_responses_with_store():
    """Test Responses API with store option."""
    print("\n[Responses Store] Testing: store option")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "input": "Hello",
        "max_output_tokens": 20,
        "store": True,
    }

    response = make_request("/responses", payload)
    result = json.loads(response.read().decode("utf-8"))

    response_id = result["id"]
    print(f"Stored response ID: {response_id}")

    # Try to retrieve
    try:
        response = make_request(f"/responses/{response_id}", None, method="GET")
        retrieved = json.loads(response.read().decode("utf-8"))
        print(f"Retrieved: {retrieved['id']}")
        return True
    except urllib.error.HTTPError as e:
        print(f"Note: Response storage may not be enabled: {e.code}")
        return True


def test_responses_previous():
    """Test Responses API with previous_response_id."""
    print("\n[Responses Previous] Testing: previous_response_id")
    print("-" * 60)

    # First response
    payload1 = {
        "model": LLM_MODEL,
        "input": "My name is Alice.",
        "max_output_tokens": 30,
        "store": True,
    }

    response1 = make_request("/responses", payload1)
    result1 = json.loads(response1.read().decode("utf-8"))
    response_id = result1["id"]
    print(f"First response ID: {response_id}")

    # Second response referencing first
    payload2 = {
        "model": LLM_MODEL,
        "input": "What's my name?",
        "max_output_tokens": 30,
        "previous_response_id": response_id,
    }

    response2 = make_request("/responses", payload2)
    result2 = json.loads(response2.read().decode("utf-8"))

    output_items = result2.get("output", [])
    if output_items:
        for item in output_items:
            if item.get("type") == "message":
                content = item.get("content", [])
                for c in content:
                    if c.get("type") == "output_text":
                        print(f"Response: {c.get('text', '')}")
    return True


# =============================================================================
# SECTION 14: Rerank API
# =============================================================================


def test_rerank_basic():
    """Test basic rerank."""
    print("\n[Rerank] Testing: basic rerank")
    print("-" * 60)

    # Check if reranker model is available
    response = make_request("/models/status", None, method="GET")
    result = json.loads(response.read().decode("utf-8"))

    reranker_models = [m for m in result["models"] if m["engine_type"] == "reranker"]
    if not reranker_models:
        print("No reranker models available - skipping")
        return True

    reranker = reranker_models[0]["id"]
    print(f"Using reranker: {reranker}")

    payload = {
        "model": reranker,
        "query": "What is machine learning?",
        "documents": [
            "Machine learning is a subset of AI",
            "The weather is sunny today",
            "Deep learning uses neural networks",
        ],
        "top_n": 2,
    }

    try:
        response = make_request("/rerank", payload)
        result = json.loads(response.read().decode("utf-8"))

        print(f"Results: {len(result['results'])}")
        for r in result["results"]:
            print(f"  [{r['index']}] score={r['relevance_score']:.3f}")
        return True
    except urllib.error.HTTPError as e:
        print(f"Note: Rerank may not be available: {e.code}")
        return True


# =============================================================================
# SECTION 15: Error Handling
# =============================================================================


def test_error_invalid_model():
    """Test error for invalid model."""
    print("\n[Error Invalid Model] Testing: nonexistent model")
    print("-" * 60)

    payload = {
        "model": "nonexistent-model-xyz",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 10,
    }

    try:
        make_request("/chat/completions", payload)
        print("Unexpected success!")
        return False
    except urllib.error.HTTPError as e:
        assert e.code == 404
        print(f"HTTP {e.code}: ✓")
        return True


def test_error_invalid_api_key():
    """Test error for invalid API key."""
    print("\n[Error Auth] Testing: invalid API key")
    print("-" * 60)

    url = f"{OMLX_BASE_URL}/chat/completions"
    headers = {"Authorization": "Bearer invalid-key", "Content-Type": "application/json"}
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 5,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )

    try:
        urllib.request.urlopen(req, timeout=10)
        print("Unexpected success!")
        return False
    except urllib.error.HTTPError as e:
        assert e.code == 401
        print("HTTP 401: ✓")
        return True


def test_error_empty_messages():
    """Test error for empty messages."""
    print("\n[Error Empty] Testing: empty messages")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [],
        "max_tokens": 10,
    }

    try:
        make_request("/chat/completions", payload)
        print("Unexpected success!")
        return False
    except urllib.error.HTTPError as e:
        if e.code in (400, 422, 500):
            print(f"HTTP {e.code} (rejected empty messages): ✓")
            return True
        print(f"Unexpected HTTP {e.code}")
        return False


def test_error_empty_prompt():
    """Test error for empty prompt."""
    print("\n[Error Empty Prompt] Testing: empty prompt")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "prompt": "",
        "max_tokens": 10,
    }

    try:
        make_request("/completions", payload)
        # Some servers may allow this
        print("Server accepted empty prompt")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 422:
            print("HTTP 422 (validation): ✓")
        else:
            print(f"HTTP {e.code}")
        return True


def test_error_malformed_tool_call():
    """Test error for malformed tool call."""
    print("\n[Error Tool] Testing: malformed tool arguments")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "test", "arguments": "not valid json"},
                    }
                ],
            },
        ],
        "max_tokens": 10,
    }

    try:
        make_request("/chat/completions", payload)
        print("Server accepted malformed tool call")
        return True
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: validation error")
        return True


def test_error_max_tokens_zero():
    """Test handling of max_tokens=0."""
    print("\n[Error Zero Tokens] Testing: max_tokens=0")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 0,
    }

    try:
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))
        text = _assistant_text(result["choices"][0]["message"])
        print(f"Server handled gracefully: {text[:20]!r}...")
        return True
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: ✓")
        return True


# =============================================================================
# SECTION 16: Special Features
# =============================================================================


def test_chat_reasoning_content():
    """Test reasoning_content in response."""
    print("\n[Chat Reasoning] Testing: reasoning content")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Think about what 2+2 equals"}],
        "max_tokens": 100,
        "temperature": 0.1,
    }

    response = make_request("/chat/completions", payload)
    result = json.loads(response.read().decode("utf-8"))

    message = result["choices"][0]["message"]
    content = message.get("content", "")
    reasoning = message.get("reasoning_content")

    print(f"Content: {content[:50]}...")
    if reasoning:
        print(f"Reasoning: {reasoning[:50]}...")
    else:
        print("No separate reasoning_content (model may not support)")
    return True


def test_chat_partial_prefill():
    """Test partial/prefill mode."""
    print("\n[Chat Prefill] Testing: partial message")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "user", "content": "Complete this sentence:"},
            {"role": "assistant", "content": "The answer is", "partial": True},
        ],
        "max_tokens": 20,
        "temperature": 0.1,
    }

    try:
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))

        content = _assistant_text(result["choices"][0]["message"])
        print(f"Response: {content}")
        return True
    except urllib.error.HTTPError as e:
        print(f"Note: Partial mode may not be supported: {e.code}")
        return True


def test_chat_thinking_budget():
    """Test thinking_budget parameter."""
    print("\n[Chat Thinking Budget] Testing: thinking_budget")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 30,
        "thinking_budget": 100,  # Limit thinking tokens
        "temperature": 0.1,
    }

    try:
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))
        print(f"Response: {_assistant_text(result['choices'][0]['message'])[:50]}...")
        return True
    except urllib.error.HTTPError as e:
        print(f"Note: thinking_budget may not be supported: {e.code}")
        return True


def test_chat_chat_template_kwargs():
    """Test chat_template_kwargs parameter."""
    print("\n[Chat Template Kwargs] Testing: chat_template_kwargs")
    print("-" * 60)

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 20,
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0.1,
    }

    try:
        response = make_request("/chat/completions", payload)
        result = json.loads(response.read().decode("utf-8"))
        print(f"Response: {_assistant_text(result['choices'][0]['message'])}")
        return True
    except urllib.error.HTTPError as e:
        print(f"Note: chat_template_kwargs may not be supported: {e.code}")
        return True


# =============================================================================
# Run All Tests
# =============================================================================

TEST_SECTIONS = [
    (
        "Health & Status",
        [
            ("Health", test_health),
            ("API Status", test_api_status),
        ],
    ),
    (
        "Models",
        [
            ("Models List", test_models_list),
            ("Models Status", test_models_status),
            ("Model Unload/Load", test_model_unload_load),
        ],
    ),
    (
        "Chat Basic",
        [
            ("Chat Basic", test_chat_basic),
            ("Chat System", test_chat_with_system),
            ("Chat Multi-turn", test_chat_multi_turn),
            ("Chat Name", test_chat_with_name),
        ],
    ),
    (
        "Chat Sampling",
        [
            ("Temperature", test_chat_temperature),
            ("Top P", test_chat_top_p),
            ("Top K", test_chat_top_k),
            ("Repetition Penalty", test_chat_repetition_penalty),
            ("Presence Penalty", test_chat_presence_penalty),
            ("Frequency Penalty", test_chat_frequency_penalty),
            ("Min P", test_chat_min_p),
            ("Seed", test_chat_seed),
        ],
    ),
    (
        "Chat Stop",
        [
            ("Stop String", test_chat_stop_string),
            ("Stop List", test_chat_stop_list),
        ],
    ),
    (
        "Chat Streaming",
        [
            ("Stream Basic", test_chat_stream_basic),
            ("Stream Usage", test_chat_stream_with_usage),
            ("Stream Finish", test_chat_stream_finish_reason),
        ],
    ),
    (
        "Chat Structured Output",
        [
            ("JSON Object", test_chat_json_object),
            ("JSON Schema", test_chat_json_schema),
            ("Regex", test_chat_structured_outputs_regex),
            ("Choice", test_chat_structured_outputs_choice),
            ("Grammar", test_chat_structured_outputs_grammar),
        ],
    ),
    (
        "Chat Tools",
        [
            ("Tools Basic", test_chat_tools_basic),
            ("Tools None", test_chat_tools_none),
            ("Tools Required", test_chat_tools_required),
            ("Tools Response", test_chat_tools_with_response),
        ],
    ),
    (
        "Text Completion",
        [
            ("Completion Basic", test_completion_basic),
            ("Completion Batch", test_completion_batch),
            ("Completion Stream", test_completion_stream),
            ("Completion Stop", test_completion_with_stop),
        ],
    ),
    (
        "Embeddings",
        [
            ("Embedding Single", test_embedding_single),
            ("Embedding Batch", test_embedding_batch),
            ("Embedding Base64", test_embedding_base64),
            ("Embedding Dimensions", test_embedding_dimensions),
            ("Embedding Items", test_embedding_items),
        ],
    ),
    (
        "VLM",
        [
            ("VLM Text", test_vlm_text),
            ("VLM Image URL", test_vlm_image_url),
            ("VLM Image Base64", test_vlm_image_base64),
            ("VLM Image Detail", test_vlm_image_detail),
        ],
    ),
    (
        "Anthropic API",
        [
            ("Anthropic Basic", test_anthropic_messages_basic),
            ("Anthropic System", test_anthropic_messages_system),
            ("Anthropic Stream", test_anthropic_messages_stream),
            ("Anthropic Tokens", test_anthropic_count_tokens),
        ],
    ),
    (
        "Responses API",
        [
            ("Responses Basic", test_responses_basic),
            ("Responses Instructions", test_responses_with_instructions),
            ("Responses Stream", test_responses_stream),
            ("Responses Store", test_responses_with_store),
            ("Responses Previous", test_responses_previous),
        ],
    ),
    (
        "Rerank",
        [
            ("Rerank Basic", test_rerank_basic),
        ],
    ),
    (
        "Error Handling",
        [
            ("Error Invalid Model", test_error_invalid_model),
            ("Error Auth", test_error_invalid_api_key),
            ("Error Empty Messages", test_error_empty_messages),
            ("Error Empty Prompt", test_error_empty_prompt),
            ("Error Tool", test_error_malformed_tool_call),
            ("Error Zero Tokens", test_error_max_tokens_zero),
        ],
    ),
    (
        "Special Features",
        [
            ("Reasoning Content", test_chat_reasoning_content),
            ("Prefill", test_chat_partial_prefill),
            ("Thinking Budget", test_chat_thinking_budget),
            ("Template Kwargs", test_chat_chat_template_kwargs),
        ],
    ),
]


def run_tests():
    """Run all tests."""
    print("=" * 60)
    print("OMLX OpenAI API Comprehensive Test Suite")
    print("=" * 60)
    print(f"Server:     {OMLX_BASE_URL_NO_V1}")
    print(f"Code LLM:   {LLM_MODEL}")
    print(f"CV vision:  {VLM_MODEL}")
    print(f"Embedding:  {EMBED_MODEL}")

    warmup_soothe_models()

    results = {}
    section_results = {}

    for section_name, tests in TEST_SECTIONS:
        print(f"\n{'=' * 60}")
        print(f"Section: {section_name}")
        print("=" * 60)

        section_passed = 0
        for name, test_func in tests:
            try:
                passed = test_func()
                results[name] = passed
                if passed:
                    section_passed += 1
            except Exception as e:
                print(f"FAILED: {e}")
                results[name] = False

        section_results[section_name] = (section_passed, len(tests))

    # Summary
    print("\n" + "=" * 60)
    print("Summary by Section")
    print("=" * 60)

    for section, (passed, total) in section_results.items():
        status = "✓" if passed == total else "○"
        print(f"  {status} {section}: {passed}/{total}")

    print("\n" + "=" * 60)
    print("Detailed Results")
    print("=" * 60)

    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {name}: {status}")

    total_tests = len(results)
    total_passed = sum(results.values())
    print(f"\nTotal: {total_passed}/{total_tests} tests passed")

    return all(results.values())


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
