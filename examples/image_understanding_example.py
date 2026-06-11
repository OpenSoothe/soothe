"""Image understanding example -- demonstrates vision processing via daemon API.

This example shows how to send an image to the Soothe daemon for analysis
using the WebSocket client from soothe-sdk. The daemon performs vision
preflight (IG-327) to extract visual information before main processing.

Usage:
    # From project root:
    uv run python examples/image_understanding_example.py

    # Ensure daemon is running:
    soothe daemon start

    # Provide test_image.jpg in the project root or modify IMAGE_PATH below

The example:
1. Loads an image file and converts to base64 attachment format
2. Connects to the daemon via WebSocket (soothe-sdk client)
3. Sends input message with text + image attachment
4. Streams response events and displays vision preflight results
"""

import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _config_helper import load_example_config
from soothe_sdk.client import (
    WebSocketClient,
    bootstrap_thread_session,
    connect_websocket_with_retries,
    websocket_url_from_config,
)

# Image path configuration
IMAGE_PATH = Path(__file__).parent.parent / "test_image.jpg"
MAX_IMAGE_SIZE_MB = 20  # Daemon limit


def load_image_as_attachment(image_path: Path) -> dict[str, str]:
    """Load an image file and convert to daemon attachment format.

    Args:
        image_path: Path to the image file.

    Returns:
        Attachment dict with mime_type and base64 data.

    Raises:
        FileNotFoundError: If image file doesn't exist.
        ValueError: If image exceeds size limit or unsupported format.
    """
    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Check file size
    file_size_mb = image_path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_IMAGE_SIZE_MB:
        raise ValueError(f"Image too large: {file_size_mb:.2f} MB (max {MAX_IMAGE_SIZE_MB} MB)")

    # Detect MIME type from extension
    suffix = image_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime_type = mime_map.get(suffix)
    if not mime_type:
        raise ValueError(
            f"Unsupported image format: {suffix}. Supported: {', '.join(mime_map.keys())}"
        )

    # Load and encode to base64
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    base64_data = base64.b64encode(image_bytes).decode("utf-8")

    print(f"[Image] Loaded: {image_path.name}")
    print(f"[Image] Size: {file_size_mb:.2f} MB")
    print(f"[Image] MIME: {mime_type}")
    print(f"[Image] Base64 length: {len(base64_data)} chars")

    return {"mime_type": mime_type, "data": base64_data}


async def stream_response_events(client: WebSocketClient) -> None:
    """Stream and display daemon response events.

    Args:
        client: Connected WebSocketClient instance.
    """
    print("\n[Daemon] Streaming response events...")
    print("=" * 60)

    event_count = 0
    while True:
        try:
            event = await asyncio.wait_for(client.read_event(), timeout=30.0)
            if not event:
                continue

            event_count += 1
            event_type = event.get("type")

            # Display different event types
            if event_type == "status":
                state = event.get("state")
                thread_id = event.get("thread_id", "?")
                print(f"\n[{event_count}] Status: {state} (thread: {thread_id})")

                # Exit when daemon goes idle
                if state == "idle":
                    print("\n[Complete] Daemon returned to idle state")
                    break

            elif event_type == "event":
                namespace = event.get("namespace", [])
                mode = event.get("mode", "?")
                data = event.get("data")

                # Handle data as dict or list
                if isinstance(data, dict):
                    event_name = data.get("type", "unknown")
                    print(f"\n[{event_count}] Event: {event_name}")
                    print(f"  Namespace: {'.'.join(namespace) if namespace else '(root)'}")
                    print(f"  Mode: {mode}")

                    # Special handling for vision-related events
                    if "vision" in event_name.lower() or "image" in event_name.lower():
                        print("  [Vision Event]")

                    # Display content for message events
                    if event_name == "ai_message":
                        content = data.get("content", "")
                        if isinstance(content, str):
                            # Show preview of AI response
                            preview = content[:200] if len(content) > 200 else content
                            print(f"  AI Response: {preview}...")
                        elif isinstance(content, list):
                            # Multimodal response
                            print(f"  AI Response: multimodal ({len(content)} blocks)")
                            for block in content[:3]:  # Show first 3 blocks
                                if isinstance(block, dict):
                                    block_type = block.get("type", "?")
                                    print(f"    - {block_type}")

                    # Display errors
                    elif event_name == "error" or "error" in data:
                        error_msg = data.get("error", "Unknown error")
                        print(f"  [ERROR] {error_msg}")

                    # Generic event data preview
                    else:
                        data_preview = str(data)[:150]
                        print(f"  Data: {data_preview}")

                elif isinstance(data, list):
                    # List of messages (state update)
                    print(f"\n[{event_count}] Event: message_list")
                    print(f"  Namespace: {'.'.join(namespace) if namespace else '(root)'}")
                    print(f"  Messages: {len(data)} messages in state")

                    # Display message contents
                    for i, msg in enumerate(data[:3]):  # Show first 3 messages
                        if not isinstance(msg, dict):
                            continue

                        msg_type = msg.get("type", "?")
                        content = msg.get("content", "")

                        # Human message
                        if msg_type in ("human", "user"):
                            if isinstance(content, str):
                                preview = content[:100] if len(content) > 100 else content
                                print(f"  [{i}] Human: {preview}")
                            elif isinstance(content, list):
                                # Multimodal content (text + images)
                                text_parts = [
                                    b.get("text", "")
                                    for b in content
                                    if isinstance(b, dict) and b.get("type") == "text"
                                ]
                                if text_parts:
                                    preview = text_parts[0][:100]
                                    print(f"  [{i}] Human: {preview}...")

                        # AI message
                        elif msg_type in ("ai", "assistant"):
                            print(f"  [{i}] AI Response:")
                            if isinstance(content, str):
                                # Show full response for vision analysis
                                if len(content) > 500:
                                    print(f"      {content[:500]}...")
                                    print(f"      [truncated, full length: {len(content)} chars]")
                                else:
                                    print(f"      {content}")
                            elif isinstance(content, list):
                                # Multimodal AI response
                                text_parts = [
                                    b.get("text", "")
                                    for b in content
                                    if isinstance(b, dict) and b.get("type") == "text"
                                ]
                                for part in text_parts:
                                    if part:
                                        preview = part[:300] if len(part) > 300 else part
                                        print(f"      {preview}")

            elif event_type == "output":
                # Tool output or other structured output
                output_type = event.get("output_type", "?")
                content = event.get("content", "")
                preview = content[:100] if len(content) > 100 else content
                print(f"\n[{event_count}] Output ({output_type}): {preview}")

            else:
                # Unknown event type - show raw structure
                print(f"\n[{event_count}] Event type: {event_type}")
                keys = list(event.keys())
                print(f"  Keys: {keys}")

        except TimeoutError:
            print("\n[Timeout] No events received for 30 seconds, assuming completion")
            break
        except Exception as e:
            print(f"\n[Error] Exception while streaming: {e}")
            import traceback

            traceback.print_exc()
            break

    print("=" * 60)
    print(f"[Stats] Total events received: {event_count}")


async def main() -> None:
    """Run image understanding example via daemon WebSocket API."""
    print("=" * 60)
    print("Soothe Image Understanding Example (Daemon WebSocket API)")
    print("=" * 60)

    # Load config
    config = load_example_config()
    print("\n[Config] Loaded configuration")

    # Load image
    try:
        attachment = load_image_as_attachment(IMAGE_PATH)
    except FileNotFoundError as e:
        print(f"\n[Error] {e}")
        print("\n[Solution] Please provide a test image:")
        print(f"  1. Place an image at: {IMAGE_PATH}")
        print("  2. Or modify IMAGE_PATH in this script")
        print("\n[Supported formats] JPG, PNG, GIF, WebP, BMP")
        print("[Size limit] 20 MB max")
        sys.exit(1)
    except ValueError as e:
        print(f"\n[Error] {e}")
        sys.exit(1)

    # Get daemon WebSocket URL
    ws_url = websocket_url_from_config(config)
    print(f"\n[Daemon] WebSocket URL: {ws_url}")

    # Create WebSocket client
    client = WebSocketClient(url=ws_url)

    # Connect with retries (for cold-start races)
    print("\n[Client] Connecting to daemon...")
    try:
        await connect_websocket_with_retries(client)
        print("[Client] Connected successfully")
    except ConnectionError as e:
        print(f"\n[Error] Failed to connect: {e}")
        print("\n[Solution] Ensure daemon is running:")
        print("  soothe daemon start")
        sys.exit(1)

    try:
        # Bootstrap thread session (handshake + new thread)
        print("\n[Session] Bootstrapping thread...")
        status_event = await bootstrap_thread_session(
            client,
            resume_thread_id=None,  # Create new thread
            verbosity="detailed",  # High verbosity for detailed output
        )
        thread_id = status_event.get("thread_id")
        print(f"[Session] Thread created: {thread_id}")

        # Send input with image attachment
        print("\n[Input] Sending query with image attachment...")
        query_text = "Describe this image in detail. What do you see?"

        input_message = {
            "type": "input",
            "text": query_text,
            "attachments": [attachment],  # Image attachment
            "autonomous": False,  # Single query mode
        }

        await client.send(input_message)
        print(f"[Input] Query: {query_text}")
        print("[Input] Attachment: 1 image")

        # Stream response events
        await stream_response_events(client)

    finally:
        # Close connection
        print("\n[Client] Closing connection...")
        await client.close()
        print("[Client] Connection closed")

    print("\n" + "=" * 60)
    print("Example complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
