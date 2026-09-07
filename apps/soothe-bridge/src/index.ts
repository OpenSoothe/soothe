/**
 * Sobo Bridge — Hono server that implements the Rakazo oRPC wire format
 * and translates each call to the Soothe daemon's WebSocket protocol.
 *
 * Architecture:
 *
 *   Electron (sobo) → loads Web UI (soothe-web)
 *      │  HTTP/SSE over /rpc/*
 *      ▼
 *   Bridge (this server, Hono, port 3100)
 *      │  WebSocket JSON envelope {proto, type, method, params, id}
 *      ▼
 *   Soothe Daemon (Python, FastAPI+Uvicorn, port 8765)
 *
 * The bridge maintains a pool of Soothe WS clients, maps Rakazo domain
 * concepts (bots, threads, messages, runs) to Soothe domain concepts
 * (loops, messages, events), and translates the event stream from
 * Soothe's WebSocket `next` frames into SSE for the web client.
 */

import { serve } from "@hono/node-server";
import { existsSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { Hono } from "hono";
import { SoothePool } from "./soothe-pool.js";
import { createRouter } from "./router.js";

const port = Number(process.env.SOOTHE_BRIDGE_PORT ?? 3100);
const daemonUrl = process.env.SOOTHE_DAEMON_URL ?? "ws://127.0.0.1:8765";

// Web UI static assets — built by @soothe/web, served by the bridge.
const WEB_ROOT = process.env.SOOTHE_WEB_ROOT ??
  path.resolve(import.meta.dirname, "..", "..", "soothe-web", "dist");

const pool = new SoothePool(daemonUrl);
const app = new Hono();

// CORS
app.use("*", async (c, next) => {
  c.header("Access-Control-Allow-Origin", "*");
  c.header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  c.header("Access-Control-Allow-Headers", "Content-Type, x-sobo-space-id");
  c.header("Access-Control-Allow-Credentials", "true");
  if (c.req.method === "OPTIONS") return c.body(null, 204);
  await next();
});

// --- Health probe ---
app.post("/rpc/health", async (c) => {
  const connected = await pool.isConnectedAsync();
  return c.json({ json: { ok: true, version: "0.0.1", daemon: connected } });
});
app.get("/rpc/health", async (c) => {
  const connected = await pool.isConnectedAsync();
  return c.json({ json: { ok: true, version: "0.0.1", daemon: connected } });
});

// --- RPC router ---
const router = createRouter(pool);
app.route("/rpc", router);

// --- Static web UI assets ---
const CONTENT_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

if (existsSync(WEB_ROOT)) {
  app.get("*", async (c) => {
    let pathname = c.req.path;
    if (pathname === "/" || pathname === "") pathname = "/index.html";
    const filePath = path.join(WEB_ROOT, pathname);
    try {
      const content = await readFile(filePath);
      const ext = path.extname(filePath).toLowerCase();
      return new Response(content, {
        headers: { "content-type": CONTENT_TYPES[ext] ?? "application/octet-stream" },
      });
    } catch {
      // SPA fallback
      try {
        const index = await readFile(path.join(WEB_ROOT, "index.html"));
        return new Response(index, {
          headers: { "content-type": "text/html; charset=utf-8" },
        });
      } catch {
        return c.text("Not found", 404);
      }
    }
  });
  console.log(`[sobo-bridge] serving web UI from ${WEB_ROOT}`);
} else {
  console.warn(`[sobo-bridge] web UI not found at ${WEB_ROOT} — run pnpm --filter @soothe/web build`);
}

// --- Start ---
console.log(`[sobo-bridge] listening on http://127.0.0.1:${port}`);
console.log(`[sobo-bridge] soothe daemon: ${daemonUrl}`);

serve({ fetch: app.fetch, port, hostname: "127.0.0.1" }, (info) => {
  console.log(`[sobo-bridge] ready on http://127.0.0.1:${info.port}`);
});
