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

import { Hono } from "hono";
import type { SoothePool } from "./soothe-pool.js";

export function createRouter(pool: SoothePool): Hono {
  const app = new Hono();

  // In-memory bot → loop_id mapping.
  // In production this would be persisted; for MVP we keep it in-process.
  const botToLoop = new Map<string, string>();
  const botMeta = new Map<string, { id: string; name: string; avatar?: string; color?: string; createdAt: string }>();

  // --- oRPC wire format helper ---
  // oRPC over HTTP expects POST with { method, params } and returns { json: <data> }
  const handleRpc = async (c: any, handler: (params: any) => Promise<unknown>) => {
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
  app.post("/health", async (c) => {
    return c.json({ json: { ok: true, version: "0.0.1", daemon: pool.isConnected() } });
  });

  // ================================================================
  // me — current user (single-user MVP)
  // ================================================================
  app.post("/me", async (c) => handleRpc(c, async () => ({
    id: "sobo-user",
    email: "user@sobo.local",
    name: "Sobo User",
  })));

  app.get("/me", async (c) => c.json({ json: {
    id: "sobo-user",
    email: "user@sobo.local",
    name: "Sobo User",
  } }));

  // ================================================================
  // bootstrap — returns me + bots list + current thread
  // ================================================================
  app.post("/bootstrap", async (c) => handleRpc(c, async (params) => {
    const botId = params.botId as string | undefined;
    const bots = Array.from(botMeta.values()).map((b) => ({
      ...b,
      archived: false,
      order: 0,
      computerMode: "team",
    }));
    const active = bots.find((b) => b.id === botId) ?? bots[0];
    let thread = null;

    if (active) {
      const loopId = botToLoop.get(active.id);
      if (loopId && pool.isConnected()) {
        try {
          const resp = await pool.request("loop_messages", { loop_id: loopId });
          thread = {
            botId: active.id,
            messages: resp.messages ?? [],
            cursor: (resp.messages as unknown[])?.length ?? 0,
          };
        } catch {
          thread = { botId: active.id, messages: [], cursor: 0 };
        }
      } else {
        thread = { botId: active.id, messages: [], cursor: 0 };
      }
    }

    return {
      me: { id: "sobo-user", email: "user@sobo.local", name: "Sobo User" },
      spaces: [{
        id: "default",
        name: "Default",
        isDefault: true,
        bots,
        groups: [],
        botSections: [],
        externalConversations: [],
      }],
      currentSpaceId: "default",
      thread,
      routines: [],
      deployment: {
        signupsEnabled: true,
        signupAllowlist: [],
        computerHost: null,
      },
    };
  }));

  app.get("/bootstrap", async (c) => {
    const botId = c.req.query("botId");
    const bots = Array.from(botMeta.values()).map((b) => ({
      ...b,
      archived: false,
      order: 0,
      computerMode: "team",
    }));
    return c.json({ json: {
      me: { id: "sobo-user", email: "user@sobo.local", name: "Sobo User" },
      spaces: [{
        id: "default",
        name: "Default",
        isDefault: true,
        bots,
        groups: [],
        botSections: [],
        externalConversations: [],
      }],
      currentSpaceId: "default",
      thread: null,
      routines: [],
      deployment: { signupsEnabled: true, signupAllowlist: [], computerHost: null },
    } });
  });

  // ================================================================
  // bots — list, create, get, update, remove
  // ================================================================
  app.post("/bots/list", async (c) => handleRpc(c, async () => {
    return Array.from(botMeta.values()).map((b) => ({
      ...b,
      archived: false,
      order: 0,
      computerMode: "team",
    }));
  }));
  app.get("/bots/list", async (c) => {
    return c.json({ json: Array.from(botMeta.values()).map((b) => ({
      ...b, archived: false, order: 0, computerMode: "team",
    })) });
  });

  app.post("/bots/create", async (c) => handleRpc(c, async (params) => {
    const id = `bot_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    const bot = {
      id,
      name: (params.name as string) || "New Bot",
      avatar: params.avatar as string | undefined,
      color: params.color as string | undefined,
      createdAt: new Date().toISOString(),
    };
    botMeta.set(id, bot);
    return { ...bot, archived: false, order: 0, computerMode: "team" };
  }));

  app.post("/bots/get", async (c) => handleRpc(c, async (params) => {
    const bot = botMeta.get(params.botId as string);
    if (!bot) throw new Error("Bot not found");
    return { ...bot, archived: false, order: 0, computerMode: "team" };
  }));

  app.post("/bots/update", async (c) => handleRpc(c, async (params) => {
    const id = params.botId as string;
    const existing = botMeta.get(id);
    if (!existing) throw new Error("Bot not found");
    const updated = {
      ...existing,
      name: (params.name as string) ?? existing.name,
      avatar: (params.avatar as string) ?? existing.avatar,
      color: (params.color as string) ?? existing.color,
    };
    botMeta.set(id, updated);
    return { ...updated, archived: false, order: 0, computerMode: "team" };
  }));

  app.post("/bots/remove", async (c) => handleRpc(c, async (params) => {
    const id = params.botId as string;
    const loopId = botToLoop.get(id);
    if (loopId && pool.isConnected()) {
      try { await pool.request("loop_delete", { loop_id: loopId }); } catch {}
    }
    botToLoop.delete(id);
    botMeta.delete(id);
    return { ok: true as const };
  }));

  // ================================================================
  // threads — messages, send, subscribe (SSE)
  // ================================================================
  app.post("/threads/messages", async (c) => handleRpc(c, async (params) => {
    const botId = params.botId as string;
    const loopId = botToLoop.get(botId);
    if (!loopId) return { messages: [], cursor: -1 };
    if (!pool.isConnected()) return { messages: [], cursor: -1 };
    const resp = await pool.request("loop_messages", { loop_id: loopId });
    const messages = (resp.messages as unknown[]) ?? [];
    return { messages, cursor: messages.length };
  }));

  app.post("/threads/send", async (c) => handleRpc(c, async (params) => {
    const botId = params.botId as string;
    const text = params.text as string;

    // Ensure a loop exists for this bot
    let loopId = botToLoop.get(botId);
    if (!loopId) {
      // Create the bot if it doesn't exist yet (auto-create on first message)
      if (!botMeta.has(botId)) {
        botMeta.set(botId, {
          id: botId,
          name: "Bot",
          createdAt: new Date().toISOString(),
        });
      }
      // Create a new Soothe loop
      const resp = await pool.request("loop_new", {
        client_workspace: botId,
      });
      loopId = resp.loop_id;
      if (!loopId) throw new Error("loop_new did not return loop_id");
      botToLoop.set(botId, loopId);
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
  }));

  app.post("/threads/stop", async (c) => handleRpc(c, async (params) => {
    // Soothe doesn't have a direct "stop" — we'd cancel the job.
    // For MVP, return ok.
    return { ok: true as const };
  }));

  // ================================================================
  // threads/subscribe — SSE event stream
  // Translates Soothe loop_events → Rakazo ProductEvent stream
  // ================================================================
  app.get("/threads/subscribe", async (c) => {
    const botId = c.req.query("botId");
    const cursor = Number(c.req.query("cursor") ?? -1);
    const loopId = botToLoop.get(botId ?? "");

    if (!loopId) {
      // No loop yet — return an empty SSE stream that stays open
      c.header("content-type", "text/event-stream");
      c.header("cache-control", "no-store");
      c.header("connection", "keep-alive");
      return c.body(new ReadableStream({
        start(controller) {
          const keepAlive = setInterval(() => {
            controller.enqueue(`: keep-alive\n\n`);
          }, 15_000);
          // Keep open until the client disconnects
          // The controller will be closed when the client disconnects
        },
      }));
    }

    c.header("content-type", "text/event-stream");
    c.header("cache-control", "no-store");
    c.header("connection", "keep-alive");

    const stream = new ReadableStream({
      async start(controller) {
        try {
          // Subscribe to Soothe loop events and translate to Rakazo ProductEvent shape
          for await (const frame of pool.subscribeLoopEvents(loopId)) {
            const event = translateSootheEvent(frame, botId ?? "");
            if (event) {
              controller.enqueue(`data: ${JSON.stringify(event)}\n\n`);
            }
          }
        } catch (error) {
          console.error("[bridge] SSE stream error:", error);
        } finally {
          controller.close();
        }
      },
    });

    return c.body(stream);
  });

  // ================================================================
  // models — list available models from daemon
  // ================================================================
  app.post("/models/list", async (c) => handleRpc(c, async () => {
    try {
      const resp = await pool.request("models_list", {});
      const models = (resp as any).models ?? (resp as any);
      if (Array.isArray(models)) {
        return models.map((m: any) => ({
          provider: m.provider ?? "soothe",
          id: m.id ?? m.name ?? "default",
          label: m.label ?? m.name ?? "Default",
          billing: m.billing ?? "byom",
        }));
      }
      return [];
    } catch (error) {
      console.error("[bridge] models_list error:", error);
      return [];
    }
  }));
  app.get("/models/list", async (c) => {
    try {
      const resp = await pool.request("models_list", {});
      const models = (resp as any).models ?? resp;
      if (Array.isArray(models)) {
        return c.json({ json: models.map((m: any) => ({
          provider: m.provider ?? "soothe",
          id: m.id ?? m.name ?? "default",
          label: m.label ?? m.name ?? "Default",
          billing: m.billing ?? "byom",
        })) });
      }
      return c.json({ json: [] });
    } catch (error) {
      console.error("[bridge] models_list error:", error);
      return c.json({ json: [] });
    }
  });

  app.post("/models/credentials", async (c) => handleRpc(c, async () => []));

  // ================================================================
  // computer — stub (Phase 2)
  // ================================================================
  app.post("/computer/status", async (c) => handleRpc(c, async (params) => ({
    status: "stopped",
    provider: "none",
  })));

  // ================================================================
  // memory — stub (Phase 2)
  // ================================================================
  app.post("/memory/list", async (c) => handleRpc(c, async () => []));

  // ================================================================
  // routines — stub (Phase 2)
  // ================================================================
  app.post("/routines/list", async (c) => handleRpc(c, async () => []));

  // ================================================================
  // Catch-all: return empty for unimplemented endpoints
  // ================================================================
  app.all("*", async (c) => {
    console.log(`[bridge] unimplemented: ${c.req.method} ${c.req.path}`);
    return c.json({ json: null }, 200);
  });

  return app;
}

/**
 * Translate a Soothe daemon event frame into a Rakazo ProductEvent shape.
 *
 * Soothe events use namespaced strings like:
 *   soothe.protocol.message.received
 *   soothe.cognition.strange_loop.started
 *   soothe.card.created
 *   soothe.output.autonomous.final_report.reported
 *
 * Rakazo ProductEvent is a discriminated union with types like:
 *   message, progress, tool, ask, done, usage, takeover
 */
function translateSootheEvent(frame: unknown, botId: string): unknown | null {
  const f = frame as Record<string, unknown>;
  const type = f.type as string | undefined;

  // Soothe `next` frames carry event payloads
  if (type === "next") {
    const payload = (f.payload ?? f) as Record<string, unknown>;
    const eventName = (payload.event ?? payload.type ?? "") as string;

    // Assistant message → Rakazo message event
    if (eventName === "soothe.protocol.message.received" || eventName === "soothe.protocol.message.sent") {
      const content = payload.content ?? payload.text ?? "";
      return {
        type: "message",
        message: {
          id: `msg_${Date.now().toString(36)}`,
          role: "assistant",
          content: String(content),
          seq: Date.now(),
          createdAt: new Date().toISOString(),
          runId: `run_${Date.now().toString(36)}`,
          artifacts: [],
        },
      };
    }

    // Card created/updated → progress event
    if (String(eventName).startsWith("soothe.card.")) {
      return {
        type: "progress",
        progress: {
          label: String(payload.title ?? payload.summary ?? eventName),
          detail: String(payload.detail ?? ""),
        },
      };
    }

    // Tool events → progress
    if (String(eventName).startsWith("soothe.tool.")) {
      return {
        type: "progress",
        progress: {
          label: String(payload.tool ?? payload.name ?? "Tool"),
          detail: String(eventName),
        },
      };
    }

    // StrangeLoop started → progress
    if (String(eventName).startsWith("soothe.cognition.strange_loop.started")) {
      return { type: "progress", progress: { label: "Thinking…", detail: "" } };
    }

    // Final report → done event with assistant message
    if (String(eventName) === "soothe.output.autonomous.final_report.reported") {
      const content = payload.report ?? payload.content ?? "";
      return {
        type: "message",
        message: {
          id: `msg_${Date.now().toString(36)}`,
          role: "assistant",
          content: String(content),
          seq: Date.now(),
          createdAt: new Date().toISOString(),
          runId: `run_${Date.now().toString(36)}`,
          artifacts: [],
        },
      };
    }

    // Generic event → skip
    return null;
  }

  // Status frames
  if (type === "status") {
    return null;
  }

  // Complete
  if (type === "complete") {
    return { type: "done" };
  }

  return null;
}
