# Image Understanding Example

Demonstrates how to send images to the Soothe daemon for analysis using the WebSocket client from `soothe-sdk`.

## Overview

This example shows the complete image processing pipeline:

1. **Client-side**: Load image file → base64 encode → attachment format
2. **WebSocket protocol**: Send input message with `attachments` field
3. **Daemon processing**:
   - Protocol validation (MIME type, size limits)
   - Vision preflight (IG-327): Extract visual context using image-role model
   - Main agent processing with enriched text
4. **Response streaming**: Display events including vision summary

## Architecture Flow

```
┌─ Client (Python) ──────────────────────────┐
│ 1. Load image: test_image.jpg              │
│ 2. Encode: base64                          │
│ 3. Format: {"mime_type": "...", "data":...}│
└────────────────────────────────────────────┘
                    ↓
┌─ WebSocket Protocol ───────────────────────┐
│ {                                          │
│   "type": "input",                         │
│   "text": "Describe this image...",        │
│   "attachments": [{"mime_type": ..., ...}] │
│ }                                          │
└────────────────────────────────────────────┘
                    ↓
┌─ Daemon Validation ────────────────────────┐
│ ✓ MIME type check (jpeg/png/gif/webp/bmp)  │
│ ✓ Size limit (≤20 MB)                      │
│ ✓ Base64 validation                        │
│ ✓ Count limit (≤8 images)                  │
└────────────────────────────────────────────┘
                    ↓
┌─ Vision Preflight (IG-327) ────────────────┐
│ model = config.create_chat_model("image")  │
│ msg = HumanMessage([vision prompt, image]) │
│ response = await model.ainvoke([msg])      │
│ summary = response.content                 │
└────────────────────────────────────────────┘
                    ↓
┌─ Text Enrichment ──────────────────────────┐
│ "Describe this image..."                   │
│                                            │
│ --- Vision summary ---                     │
│ [Vision model output describing image]     │
│ ---                                        │
└────────────────────────────────────────────┘
                    ↓
┌─ Agent Processing ─────────────────────────┐
│ Enriched text → AgentLoop                  │
│ Tools → analyze_image (optional re-process)│
│ Final response → Stream events             │
└────────────────────────────────────────────┘
```

## Usage

### Prerequisites

1. **Daemon running**:
```bash
soothe daemon start
```

2. **Test image**: Place `test_image.jpg` in project root or modify `IMAGE_PATH` in script

3. **Dependencies**: Python environment with soothe packages installed

### Run Example

```bash
# From project root:
uv run python examples/image_understanding_example.py
```

### Expected Output

```
============================================================
Soothe Image Understanding Example (Daemon WebSocket API)
============================================================

[Config] Loaded configuration
[Image] Loaded: test_image.jpg
[Image] Size: 0.15 MB
[Image] MIME: image/jpeg
[Image] Base64 length: 20480 chars

[Daemon] WebSocket URL: ws://127.0.0.1:8765

[Client] Connecting to daemon...
[Client] Connected successfully

[Session] Bootstrapping thread...
[Session] Thread created: <thread_id>

[Input] Sending query with image attachment...
[Input] Query: Describe this image in detail. What do you see?
[Input] Attachment: 1 image

[Daemon] Streaming response events...
============================================================

[1] Status: processing (thread: <thread_id>)
[2] Event: soothe.foundation.ai.message
  AI Response: <vision summary>
[3] Event: soothe.foundation.ai.message
  AI Response: <final analysis>
[4] Status: idle (thread: <thread_id>)

[Complete] Daemon returned to idle state
============================================================
[Stats] Total events received: <count>

[Client] Closing connection...
[Client] Connection closed

============================================================
Example complete!
============================================================
```

## Image Requirements

- **Formats**: JPEG, PNG, GIF, WebP, BMP
- **Size**: ≤20 MB per image
- **Count**: ≤8 images per message
- **Encoding**: Valid base64

## Code Structure

### Key Components

```python
# Load image as daemon attachment
attachment = load_image_as_attachment(IMAGE_PATH)
# Returns: {"mime_type": "image/jpeg", "data": "base64..."}

# Connect to daemon via WebSocket
client = WebSocketClient(url=ws_url)
await connect_websocket_with_retries(client)

# Bootstrap thread session
status_event = await bootstrap_thread_session(
    client,
    resume_thread_id=None,
    verbosity="detailed",
)

# Send input with attachment
input_message = {
    "type": "input",
    "text": "Describe this image...",
    "attachments": [attachment],
    "autonomous": False,
}
await client.send(input_message)

# Stream response events
await stream_response_events(client)
```

### Event Types

- `status`: Daemon state transitions (processing → idle)
- `event`: Structured events (ai_message, error, tool output)
- `output`: Tool execution results

## Vision Preflight Details

The daemon's vision preflight (IG-327) automatically:

1. Detects attachments in input message
2. Creates image-role model from `ModelRouter.image` config
3. Sends multimodal HumanMessage to vision model:
   ```
   "Describe the attached image(s) concisely for another assistant
   that will handle the user's request. Focus on visible objects,
   text, charts, and intent."
   ```
4. Merges vision summary into user text:
   ```
   [user text]

   --- Vision summary ---
   [vision model output]
   ---
   ```
5. Passes enriched text to main agent loop

## Configuration

### Model Router

Configure vision model in `config.yml`:

```yaml
models:
  router:
    default: "openai:gpt-4o-mini"
    image: "openai:gpt-4o"  # Vision-capable model
```

If `image` role not configured, falls back to `default`.

### Example Config Loading

```python
from examples._config_helper import load_example_config

config = load_example_config()
# Loads from SOOTHE_HOME or config/config.dev.yml
```

## Troubleshooting

### Connection Errors

```
[Error] Failed to connect: Connection refused
[Solution] Ensure daemon is running: soothe daemon start
```

### Image Errors

```
[Error] Image too large: 25.3 MB (max 20 MB)
[Solution] Resize or compress image before sending
```

```
[Error] Unsupported image format: .tif
[Solution] Use JPEG, PNG, GIF, WebP, or BMP
```

### Vision Model Errors

```
[ERROR] BadRequestError: Invalid image format
[Solution] Ensure image is valid and not corrupted
```

## Related Documentation

- **Architecture**: `docs/specs/RFC-000-system-conceptual-design.md`
- **Vision Preflight**: `docs/impl/IG-327-*` (implementation guide)
- **Image Processing**: See analysis in this directory
- **Daemon Protocol**: `packages/soothe/src/soothe/daemon/protocol_v2.py`
- **Vision Implementation**: `packages/soothe/src/soothe/daemon/image_understanding.py`

## Advanced Usage

### Multiple Images

```python
attachments = [
    load_image_as_attachment("image1.jpg"),
    load_image_as_attachment("image2.png"),
]
input_message = {
    "type": "input",
    "text": "Compare these two images",
    "attachments": attachments,
}
```

### Tool-Based Analysis

The agent can also use `analyze_image` tool for re-processing:

```python
# Agent receives enriched text with vision summary
# Can call analyze_image tool for detailed analysis
# Tools: packages/soothe/src/soothe/toolkits/image.py
```

### Autonomous Mode

```python
input_message = {
    "type": "input",
    "text": "Analyze image and create a report",
    "attachments": [attachment],
    "autonomous": True,  # Enable autonomous goal execution
}
```

## SDK Reference

- `WebSocketClient`: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`
- `bootstrap_thread_session`: `packages/soothe-sdk/src/soothe_sdk/client/session.py`
- `VerbosityLevel`: `packages/soothe-sdk/src/soothe_sdk/core/types.py`

## See Also

- `examples/batch_tasks_example.py`: Headless CLI batch processing
- [`soothe-community`](https://github.com/OpenSoothe/soothe-community): optional delegates and runnable examples
- `packages/soothe-cli/src/soothe_cli/tui/media_utils.py`: TUI image handling