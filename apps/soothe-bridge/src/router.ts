/**
 * Sobo Bridge Router
 *
 * Maps Rakazo's oRPC contract surface to Soothe daemon WebSocket calls.
 * Each Hono route returns `{ json: <payload> }` — the shape the Rakazo
 * oRPC client expects from oRPC over HTTP responses.
 *
 * Concept mapping:
 *   Rakazo bot       ↔ Soothe loop (1:1, created on first message)
 *   Rakazo thread    ↔ Soothe loop message history
 *   Rakazo message   ↔ Soothe loop_input (user) / assistant output (daemon)
 *   Rakazo run       ↔ Soothe StrangeLoop execution (one per loop_input)
 *   Rakazo computer  ↔ (not yet mapped — Phase 2)
 *   Rakazo memory    ↔ Soothe loop_state (Phase 2)
 *   Rakazo routine   ↔ Soothe cron (Phase 2)
 */

import { Hono, type Context } from "hono";
import type { SoothePool } from "./soothe-pool.js";
import type { BotRecord, BridgeStore } from "./store.js";

/** Message shape consumed by the Sobo web UI. */
export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  seq: number;
  createdAt?: string;
}

/**
 * Project Soothe `loop_messages` rows (ThreadMessage:
 * {timestamp, kind, role: "user"|"assistant"|"system", content, metadata})
 * onto the UI shape. System rows are dropped; id is derived from timestamp+
 * role+content so it stays stable across refetches.
 */
export function mapSootheMessages(rows: unknown[]): UiMessage[] {
  return rows.flatMap((row, i) => {
    const r = row as Record<string, unknown>;
    if (r.role !== "user" && r.role !== "assistant") return [];
    const text = String(r.content ?? "");
    return [
      {
        id: `msg_${String(r.timestamp ?? i)}_${r.role}_${text.length}`,
        role: r.role,
        text,
        seq: i,
        createdAt: r.timestamp === undefined ? undefined : String(r.timestamp),
      },
    ];
  });
}

export function createRouter(pool: SoothePool, store: BridgeStore): Hono {
  const app = new Hono();

  // In-memory mirror of the persisted bots table (fast sync reads).
  const bots = new Map<string, BotRecord>();
  for (const rec of store.loadBots()) {
    bots.set(rec.id, rec);
  }

  // Assistant replies captured from live `soothe.card.*` frames, per loop.
  // ThreadLogger rows only record user turns; the daemon's conversation
  // record for assistant output is the display-card stream, which is not
  // queryable after the loop completes — so we capture it live.
  const chatLog = new Map<string, UiMessage[]>();
  const CHAT_LOG_MAX = 500;

  interface CardFrame {
    op: string;
    cardId: string;
    kind: string;
    content: string;
    timestamp?: number;
  }

  /** Extract a card mutation from a daemon envelope, if present. */
  function extractCard(f: Record<string, unknown>): CardFrame | null {
    const CARD_OPS = new Set([
      "soothe.card.created",
      "soothe.card.updated",
      "soothe.card.finalized",
    ]);
    // Live path: {mode:"event", data:{type:"event", mode:"custom", data:<card>}}
    // Replay path: {mode:"soothe.card.created", data:{...card fields...}}
    const candidates = [f, f.data, (f.data as Record<string, unknown>)?.data];
    for (const c of candidates) {
      const rec = c as Record<string, unknown> | undefined;
      if (!rec || typeof rec !== "object") continue;
      const op = rec.type;
      if (typeof op !== "string" || !CARD_OPS.has(op)) continue;
      const payload = rec.data as Record<string, unknown> | undefined;
      const kind = typeof rec.kind === "string" ? rec.kind : undefined;
      if (!payload || (kind !== "assistant" && kind !== "user")) return null;
      return {
        op,
        cardId: String(rec.card_id ?? payload.id ?? ""),
        kind,
        content: String(payload.content ?? ""),
        timestamp: typeof payload.timestamp === "number" ? payload.timestamp : undefined,
      };
    }
    return null;
  }

  /** Upsert an assistant card into the loop's captured chat log. */
  function captureCard(loopId: string, card: CardFrame): void {
    if (card.kind !== "assistant" || !card.content) return;
    const log = chatLog.get(loopId) ?? [];
    // Card timestamps are epoch seconds; ThreadLogger rows use ms ISO strings.
    const ms =
      card.timestamp !== undefined
        ? card.timestamp < 1e11
          ? card.timestamp * 1000
          : card.timestamp
        : Date.now();
    const msg: UiMessage = {
      id: `card_${card.cardId}`,
      role: "assistant",
      text: card.content,
      seq: log.length,
      createdAt: new Date(ms).toISOString(),
    };
    const existing = log.findIndex(m => m.id === msg.id);
    if (existing >= 0) log[existing] = msg;
    else log.push(msg);
    chatLog.set(loopId, log.slice(-CHAT_LOG_MAX));
  }

  /** Expand `event_batch` envelopes into individual protocol-1 frames. */
  function* expandFrame(frame: Record<string, unknown>): Generator<Record<string, unknown>> {
    if (frame.type === "event_batch" && Array.isArray(frame.events)) {
      for (const env of frame.events as Record<string, unknown>[]) {
        if (env.type === "next" && env.payload) {
          yield env.payload as Record<string, unknown>;
        } else {
          yield env;
        }
      }
      return;
    }
    yield frame;
  }

  /**
   * Handle one daemon frame: capture assistant cards, translate the rest to
   * UI stream events (activity/done triggers for the debounced refetch).
   */
  function handleEnvelope(f: Record<string, unknown>): unknown | null {
    if (f.event === "subscribed") return null;
    if (f.type === "status") return null;
    if (f.type === "complete") return { type: "done" };

    const card = extractCard(f);
    if (card) return { type: "activity" };

    // Cognition progress: live path nests it at f.data.data.type.
    const deep = f.data as Record<string, unknown> | undefined;
    const deeper = deep?.data as Record<string, unknown> | undefined;
    const evtType = deeper?.type ?? deep?.type;
    const label =
      typeof evtType === "string" && evtType.startsWith("soothe.cognition.")
        ? "Thinking…"
        : undefined;
    return { type: "activity", label };
  }

  /** ThreadLogger rows + captured assistant cards, time-ordered and deduped.
   * Some turns (task-intent) never get a ThreadLogger assistant row; those
   * come only from captured cards. Cards duplicating a ThreadLogger row are
   * dropped (same text within a 2-minute window). */
  async function getMergedMessages(loopId: string): Promise<UiMessage[]> {
    let userMsgs: UiMessage[] = [];
    if (pool.isConnected()) {
      try {
        const resp = await pool.request("loop_messages", { loop_id: loopId });
        userMsgs = mapSootheMessages(resp.messages ?? []);
      } catch {
        // Fall through with captured cards only
      }
    }
    const captured = (chatLog.get(loopId) ?? []).filter(
      card =>
        !userMsgs.some(
          m =>
            m.role === "assistant" &&
            m.text === card.text &&
            Math.abs(
              new Date(m.createdAt ?? 0).getTime() - new Date(card.createdAt ?? 0).getTime(),
            ) < 120_000,
        ),
    );
    return [...userMsgs, ...captured].sort((a, b) =>
      (a.createdAt ?? "").localeCompare(b.createdAt ?? ""),
    );
  }

  const toWireBot = (b: BotRecord) => ({
    id: b.id,
    name: b.name,
    avatar: b.avatar,
    color: b.color,
    createdAt: b.createdAt,
    archived: false,
    order: 0,
    computerMode: "team",
  });

  type WireBot = ReturnType<typeof toWireBot> & { preview: string | undefined };

  // Last conversation snippet for the contact list preview.
  async function botPreview(botId: string): Promise<string | undefined> {
    const loopId = bots.get(botId)?.loopId;
    if (!loopId) return undefined;
    try {
      const msgs = await getMergedMessages(loopId);
      const last = msgs[msgs.length - 1];
      if (!last) return undefined;
      return last.role === "user" ? `你: ${last.text}` : last.text;
    } catch {
      return undefined;
    }
  }

  async function wireBotsWithPreview(): Promise<WireBot[]> {
    return Promise.all(
      Array.from(bots.values()).map(async b => ({
        ...toWireBot(b),
        preview: await botPreview(b.id),
      })),
    );
  }

  // --- oRPC wire format helper ---
  // oRPC over HTTP expects POST with { method, params } and returns { json: <data> }
  const handleRpc = async (
    c: Context,
    handler: (params: Record<string, unknown>) => Promise<unknown>,
  ) => {
    try {
      let params: Record<string, unknown> = {};
      if (c.req.method === "POST") {
        const body = await c.req.json().catch(() => ({}));
        params = body.params ?? body;
      } else {
        params = c.req.query();
      }
      const result = await handler(params);
      return c.json({ json: result });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("[bridge] RPC error:", message);
      return c.json({ error: { message } }, 400);
    }
  };

  // ================================================================
  // health
  // ================================================================
  app.post("/health", async c => {
    return c.json({ json: { ok: true, version: "0.0.1", daemon: pool.isConnected() } });
  });

  // ================================================================
  // me — current user (single-user MVP)
  // ================================================================
  app.post("/me", async c =>
    handleRpc(c, async () => ({
      id: "sobo-user",
      email: "user@sobo.local",
      name: "Sobo User",
    })),
  );

  app.get("/me", async c =>
    c.json({
      json: {
        id: "sobo-user",
        email: "user@sobo.local",
        name: "Sobo User",
      },
    }),
  );

  // ================================================================
  // bootstrap — returns me + bots list + current thread
  // ================================================================
  app.post("/bootstrap", async c =>
    handleRpc(c, async params => {
      const botId = params.botId as string | undefined;
      const wireBots = await wireBotsWithPreview();
      const active = wireBots.find(b => b.id === botId) ?? wireBots[0];
      let thread = null;

      if (active) {
        const loopId = bots.get(active.id)?.loopId;
        if (loopId) {
          try {
            const messages = await getMergedMessages(loopId);
            thread = { botId: active.id, messages, cursor: messages.length };
          } catch {
            thread = { botId: active.id, messages: [], cursor: 0 };
          }
        } else {
          thread = { botId: active.id, messages: [], cursor: 0 };
        }
      }

      return {
        me: { id: "sobo-user", email: "user@sobo.local", name: "Sobo User" },
        spaces: [
          {
            id: "default",
            name: "Default",
            isDefault: true,
            bots: wireBots,
            groups: [],
            botSections: [],
            externalConversations: [],
          },
        ],
        currentSpaceId: "default",
        thread,
        routines: [],
        deployment: {
          signupsEnabled: true,
          signupAllowlist: [],
          computerHost: null,
        },
      };
    }),
  );

  app.get("/bootstrap", async c => {
    return c.json({
      json: {
        me: { id: "sobo-user", email: "user@sobo.local", name: "Sobo User" },
        spaces: [
          {
            id: "default",
            name: "Default",
            isDefault: true,
            bots: Array.from(bots.values()).map(toWireBot),
            groups: [],
            botSections: [],
            externalConversations: [],
          },
        ],
        currentSpaceId: "default",
        thread: null,
        routines: [],
        deployment: { signupsEnabled: true, signupAllowlist: [], computerHost: null },
      },
    });
  });

  // ================================================================
  // bots — list, create, get, update, remove
  // ================================================================
  app.post("/bots/list", async c =>
    handleRpc(c, async () => {
      return wireBotsWithPreview();
    }),
  );
  app.get("/bots/list", async c => {
    return c.json({ json: await wireBotsWithPreview() });
  });

  app.post("/bots/create", async c =>
    handleRpc(c, async params => {
      const bot: BotRecord = {
        id: `bot_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
        name: (params.name as string) || "New Bot",
        avatar: params.avatar as string | undefined,
        color: params.color as string | undefined,
        createdAt: new Date().toISOString(),
      };
      bots.set(bot.id, bot);
      store.upsertBot(bot);
      return toWireBot(bot);
    }),
  );

  app.post("/bots/get", async c =>
    handleRpc(c, async params => {
      const bot = bots.get(params.botId as string);
      if (!bot) throw new Error("Bot not found");
      return toWireBot(bot);
    }),
  );

  app.post("/bots/update", async c =>
    handleRpc(c, async params => {
      const id = params.botId as string;
      const existing = bots.get(id);
      if (!existing) throw new Error("Bot not found");
      const updated: BotRecord = {
        ...existing,
        name: (params.name as string) ?? existing.name,
        avatar: (params.avatar as string) ?? existing.avatar,
        color: (params.color as string) ?? existing.color,
      };
      bots.set(id, updated);
      store.upsertBot(updated);
      return toWireBot(updated);
    }),
  );

  app.post("/bots/remove", async c =>
    handleRpc(c, async params => {
      const id = params.botId as string;
      const loopId = bots.get(id)?.loopId;
      if (loopId && pool.isConnected()) {
        try {
          await pool.request("loop_delete", { loop_id: loopId });
        } catch {
          // Best-effort cleanup — loop may already be gone.
        }
      }
      bots.delete(id);
      store.deleteBot(id);
      const removedLoop = loopId;
      if (removedLoop) chatLog.delete(removedLoop);
      return { ok: true as const };
    }),
  );

  // ================================================================
  // threads — messages, send, subscribe (SSE)
  // ================================================================
  app.post("/threads/messages", async c =>
    handleRpc(c, async params => {
      const botId = params.botId as string;
      const loopId = bots.get(botId)?.loopId;
      if (!loopId) return { messages: [], cursor: -1 };
      const messages = await getMergedMessages(loopId);
      return { messages, cursor: messages.length };
    }),
  );

  app.post("/threads/send", async c =>
    handleRpc(c, async params => {
      const botId = params.botId as string;
      const text = params.text as string;

      // Ensure a loop exists for this bot
      let loopId = bots.get(botId)?.loopId;
      if (!loopId) {
        // Create the bot if it doesn't exist yet (auto-create on first message)
        let record = bots.get(botId);
        if (!record) {
          record = {
            id: botId,
            name: "Bot",
            createdAt: new Date().toISOString(),
          };
          bots.set(botId, record);
          store.upsertBot(record);
        }
        // Create a new Soothe loop
        const resp = await pool.request("loop_new", {
          client_workspace: botId,
        });
        loopId = resp.loop_id;
        if (!loopId) throw new Error("loop_new did not return loop_id");
        record.loopId = loopId;
        store.setBotLoop(botId, loopId);
        // Soothe daemon requires a subscription before loop_input
        await pool.subscribeLoop(loopId);
      }

      // Send the user message to the daemon
      await pool.request("loop_input", {
        loop_id: loopId,
        content: text,
      });

      return {
        taskId: `task_${Date.now().toString(36)}`,
        runId: `run_${Date.now().toString(36)}`,
        seq: Date.now(),
      };
    }),
  );

  app.post("/threads/stop", async c =>
    handleRpc(c, async () => {
      // Soothe doesn't have a direct "stop" — we'd cancel the job.
      // For MVP, return ok.
      return { ok: true as const };
    }),
  );

  // ================================================================
  // threads/subscribe — SSE event stream
  // Translates Soothe loop_events → activity triggers for the web UI.
  // The UI refetches thread history on each activity event, so events only
  // need to signal "something happened", not carry message content.
  // ================================================================
  app.get("/threads/subscribe", async c => {
    const botId = c.req.query("botId") ?? "";
    const signal = c.req.raw.signal;

    c.header("content-type", "text/event-stream");
    c.header("cache-control", "no-store");
    c.header("connection", "keep-alive");

    const stream = new ReadableStream({
      async start(controller) {
        const keepAlive = setInterval(() => {
          try {
            controller.enqueue(`: keep-alive\n\n`);
          } catch {
            clearInterval(keepAlive);
          }
        }, 15_000);

        try {
          // The loop may not exist yet (bot created but no message sent).
          // Poll until it appears, then attach to its event stream.
          let loopId = bots.get(botId)?.loopId;
          while (!loopId && !signal.aborted) {
            await new Promise(resolve => setTimeout(resolve, 500));
            loopId = bots.get(botId)?.loopId;
          }

          if (loopId && !signal.aborted) {
            for await (const frame of pool.consumeLoopEvents(loopId, signal)) {
              for (const envelope of expandFrame(frame)) {
                const card = extractCard(envelope);
                if (card) captureCard(loopId, card);
                const event = handleEnvelope(envelope);
                if (event) {
                  controller.enqueue(`data: ${JSON.stringify(event)}\n\n`);
                }
              }
            }
          }
        } catch (error) {
          console.error("[bridge] SSE stream error:", error);
        } finally {
          clearInterval(keepAlive);
          try {
            controller.close();
          } catch {
            // Already closed
          }
        }
      },
    });

    return c.body(stream);
  });

  // ================================================================
  // models — list available models from daemon
  // ================================================================
  app.post("/models/list", async c =>
    handleRpc(c, async () => {
      try {
        const resp = await pool.request("models_list", {});
        const respRecord = resp as Record<string, unknown>;
        const models = (respRecord.models ?? resp) as unknown[];
        if (Array.isArray(models)) {
          return models.map(m => {
            const r = m as Record<string, unknown>;
            return {
              provider: r.provider ?? "soothe",
              id: r.id ?? r.name ?? "default",
              label: r.label ?? r.name ?? "Default",
              billing: r.billing ?? "byom",
            };
          });
        }
        return [];
      } catch (error) {
        console.error("[bridge] models_list error:", error);
        return [];
      }
    }),
  );
  app.get("/models/list", async c => {
    try {
      const resp = await pool.request("models_list", {});
      const respRecord = resp as Record<string, unknown>;
      const models = (respRecord.models ?? resp) as unknown[];
      if (Array.isArray(models)) {
        return c.json({
          json: models.map(m => {
            const r = m as Record<string, unknown>;
            return {
              provider: r.provider ?? "soothe",
              id: r.id ?? r.name ?? "default",
              label: r.label ?? r.name ?? "Default",
              billing: r.billing ?? "byom",
            };
          }),
        });
      }
      return c.json({ json: [] });
    } catch (error) {
      console.error("[bridge] models_list error:", error);
      return c.json({ json: [] });
    }
  });

  app.post("/models/credentials", async c => handleRpc(c, async () => []));

  // ================================================================
  // computer — stub (Phase 2)
  // ================================================================
  app.post("/computer/status", async c =>
    handleRpc(c, async () => ({
      status: "stopped",
      provider: "none",
    })),
  );

  // ================================================================
  // memory — stub (Phase 2)
  // ================================================================
  app.post("/memory/list", async c => handleRpc(c, async () => []));

  // ================================================================
  // routines — stub (Phase 2)
  // ================================================================
  app.post("/routines/list", async c => handleRpc(c, async () => []));

  // ================================================================
  // Catch-all: return empty for unimplemented endpoints
  // ================================================================
  app.all("*", async c => {
    console.log(`[bridge] unimplemented: ${c.req.method} ${c.req.path}`);
    return c.json({ json: null }, 200);
  });

  return app;
}
