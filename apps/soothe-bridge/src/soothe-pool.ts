/**
 * Soothe Daemon connection pool.
 *
 * Maintains a single long-lived WebSocket connection to the Soothe daemon,
 * with automatic reconnect. The bridge uses this to send RPC requests
 * (loop_new, loop_input, loop_list, etc.) and subscribe to event streams
 * (loop_events → SSE for the web client).
 *
 * Wire protocol: {proto: "1", type, method, params, id}
 *   - Client → server: connection_init, request, subscribe, unsubscribe, ping, disconnect
 *   - Server → client: connection_ack, response, next, error, complete, status, pong
 *
 * The daemon enforces at most one loop subscription per client; a new
 * subscribe replaces the prior one. We track the active subscription id so
 * unsubscribe targets the right stream.
 */

import { Client } from "@mirasoth/soothe-client";
import type { MethodName } from "@mirasoth/soothe-client";

export interface SootheResponse {
  loop_id?: string;
  messages?: unknown[];
  status?: string;
  state?: string;
  workspace?: string;
  [key: string]: unknown;
}

export class SoothePool {
  private client: Client | null = null;
  private connecting: Promise<void> | null = null;
  private url: string;
  private subId: string | null = null;
  private subLoopId: string | null = null;

  constructor(url: string) {
    this.url = url;
  }

  async ensureConnected(): Promise<Client> {
    if (this.client?.isConnected()) return this.client;
    if (this.connecting) await this.connecting;
    if (this.client?.isConnected()) return this.client;

    this.connecting = this.connect();
    try {
      await this.connecting;
    } finally {
      this.connecting = null;
    }
    if (!this.client) throw new Error("Failed to connect to Soothe daemon");
    return this.client;
  }

  private async connect(): Promise<void> {
    const client = new Client(this.url);
    client.on("disconnected", () => {
      console.warn("[soothe-pool] disconnected from daemon, will retry on next request");
    });
    client.on("close", () => {
      if (this.client === client) {
        this.client = null;
        this.subId = null;
        this.subLoopId = null;
      }
    });
    await client.connect();
    this.client = client;
    console.log("[soothe-pool] connected to daemon at", this.url);
  }

  isConnected(): boolean {
    return this.client?.isConnected() ?? false;
  }

  /** Eagerly attempt connection and return status (for health checks). */
  async isConnectedAsync(): Promise<boolean> {
    if (this.client?.isConnected()) return true;
    try {
      await this.ensureConnected();
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Send an RPC request and wait for the response.
   * Returns the `result` field from the response envelope.
   */
  async request(method: string, params: Record<string, unknown>): Promise<SootheResponse> {
    const client = await this.ensureConnected();
    const result = await client.requestResponse(method as MethodName, params, method, 30_000);
    return (result ?? {}) as SootheResponse;
  }

  /**
   * Ensure the pool client is subscribed to the loop's event stream.
   * The daemon replaces any prior loop subscription, so re-subscribing to a
   * different loop is always safe; re-subscribing to the same loop is skipped
   * to avoid a redundant reattach replay.
   */
  async subscribeLoop(loopId: string): Promise<void> {
    if (this.subLoopId === loopId && this.subId !== null) return;
    const client = await this.ensureConnected();
    this.subId = await client.subscribe("loop_events", { loop_id: loopId }, 10_000);
    this.subLoopId = loopId;
  }

  /**
   * Consume loop event frames for the currently subscribed loop.
   * `client.next()` unwraps `next` frames to their payload and returns full
   * envelopes for `complete`/`error`. Yields until the stream ends or the
   * signal aborts.
   */
  async *consumeLoopEvents(
    loopId: string,
    signal?: AbortSignal,
  ): AsyncGenerator<Record<string, unknown>> {
    const client = await this.ensureConnected();
    await this.subscribeLoop(loopId);
    try {
      while (!signal?.aborted) {
        const event = await client.next();
        if (event === null) break;
        yield event;
      }
    } finally {
      if (this.subId !== null) {
        try {
          await client.unsubscribe(this.subId);
        } catch {
          // Best-effort cleanup
        }
        this.subId = null;
        this.subLoopId = null;
      }
    }
  }

  async close(): Promise<void> {
    this.client?.close();
    this.client = null;
    this.subId = null;
    this.subLoopId = null;
  }
}
