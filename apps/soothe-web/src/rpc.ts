/**
 * Minimal oRPC client — talks to the Soothe Bridge at /rpc.
 * The bridge implements the same oRPC contract shape as Rakazo's appContract.
 */

const RPC_URL = "/rpc";

type RpcResult<T> = { json: T } | { error: { message: string } };

export async function rpc<T = unknown>(
  method: string,
  params?: Record<string, unknown>,
): Promise<T> {
  const response = await fetch(RPC_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ method, params: params ?? {} }),
  });

  if (!response.ok) {
    throw new Error(`RPC ${method} failed: HTTP ${response.status}`);
  }

  const body = (await response.json()) as RpcResult<T>;

  if ("error" in body) {
    throw new Error(body.error.message);
  }

  return body.json;
}

/**
 * Subscribe to thread events via SSE.
 * Returns an async iterator of events.
 */
export async function* subscribeThreadEvents(
  botId: string,
  cursor: number,
): AsyncGenerator<unknown> {
  const params = new URLSearchParams({ botId, cursor: String(cursor) });
  const response = await fetch(`${RPC_URL}/threads/subscribe?${params}`, {
    headers: { accept: "text/event-stream" },
    credentials: "include",
  });

  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {
          // Skip malformed SSE lines
        }
      }
    }
  }
}
